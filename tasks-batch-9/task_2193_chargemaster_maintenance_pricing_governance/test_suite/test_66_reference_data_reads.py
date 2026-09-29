"""Reads across the reference-data families, one-way retirement, and clock-driven term expiry."""
from test_helpers import (
    api_client, validate_success, validate_paginated,
    create_facility, create_revenue_code, create_department, create_price_rule,
    create_item, reprice_item, read_department, read_facility, create_payer_contract, set_clock,
    make_manager_headers, ADMIN, ANALYST, APPROVER, COMPLIANCE, CONTRACT,
    MANAGER_USER_ID, MANAGER2_USER_ID,
)


def test_reference_reads_expose_defaults_and_the_clock_expires_a_term_for_good():
    """PRD §3.1: "Each `RevenueCode` row carries a four-digit UB-04 `code` string that is globally unique
    (for example `'0300'`), a human-readable `description`, a boolean `requires_hcpcs`, an
    `allowed_code_types` array drawn from the four values `CPT`, `HCPCS`, `REV_ONLY` and `CDM_INTERNAL`,
    a `pricing_class` of `SUPPLY`, `PHARMACY`, `PROCEDURE` or `ROOM_AND_BOARD` that forms part of the
    scope key used when selecting a price rule, and a `status` that defaults to `ACTIVE` and may be
    `RETIRED`."
    PRD §3.1: "Revenue codes are reference data and carry only `id` and `created_at`."
    PRD §3.1: "An empty array means unrestricted. A fresh department has `capture_hold` false,
    `unresolved_finding_amount_cents`, `recovered_charge_cents` and `open_request_count` all at 0."
    PRD §3.2: "Every rule also carries `min_medicare_multiple_bp`, defaulting to 12000 basis points, and
    `market_cap_multiple_bp`, defaulting to 11000 basis points."
    PRD §3.2: "Each rule exposes `applied_item_count`, the number of charge items whose
    `applied_price_rule_id` names it."
    PRD §2.5: "Moving the clock has one business consequence: every `PayerContract` whose `status` is
    `ACTIVE` and whose `term_end_date` is earlier than the new logical now transitions to `EXPIRED`."

    Design: Corner/endpoints/reference_data_reads_retirement_and_clock_driven_contract_expiry
    """
    set_clock("2026-09-01T00:00:00Z")
    facility = create_facility(name="Mercy General",
                              cms_certification_number="CCN-2193-REFREAD",
                              rounding_mode="NEAREST_CENT")
    facility_id = facility["id"]

    rc_300 = create_revenue_code(code="0300", description="Laboratory - general",
                                requires_hcpcs=False, allowed_code_types=["CPT"],
                                pricing_class="PROCEDURE")
    assert rc_300["status"] == "ACTIVE", "the omitted status defaults to ACTIVE"
    assert "version" not in rc_300 and "updated_at" not in rc_300, (
        "reference data carries only id and created_at"
    )
    rc_250 = create_revenue_code(code="0250", description="Pharmacy - general",
                                requires_hcpcs=True, allowed_code_types=["HCPCS"],
                                pricing_class="PHARMACY")
    rc_637 = create_revenue_code(code="0637", description="Self-administrable drugs",
                                requires_hcpcs=True, allowed_code_types=["HCPCS"],
                                pricing_class="PHARMACY", status="RETIRED")
    assert rc_637["status"] == "RETIRED", "status is an input at creation time"

    department = create_department(facility_id, MANAGER_USER_ID, name="Cardiac Cath Lab",
                                  cost_center_code="CC-100",
                                  allowed_revenue_code_values=["0300"])
    radiology = create_department(facility_id, MANAGER2_USER_ID, name="Radiology",
                                  cost_center_code="CC-200")
    assert radiology["allowed_revenue_code_values"] == [], (
        "an omitted allowlist is the empty array, not null"
    )

    rule = create_price_rule(facility_id, rc_300["id"], pricing_method="COST_PLUS_MARKUP",
                            effective_from="2026-01-01T00:00:00Z")
    base = {"facility": facility, "revenue_code": rc_300, "department": department,
            "price_rule": rule, "manager_headers": make_manager_headers(MANAGER_USER_ID),
            "manager_user_id": MANAGER_USER_ID}
    item = create_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                       code_type="CPT", code_value="93458", cost_basis_cents=100000,
                       medicare_rate_cents=50000, market_p75_cents=900000,
                       effective_from="2026-09-01T00:00:00Z")
    priced = reprice_item(item["id"])
    assert priced["gross_charge_cents"] == 240000, "the omitted tier ladder is the standard one"
    assert priced["price_status"] == "PRICED_CURRENT"
    assert priced["applied_price_rule_id"] == rule["id"]

    aetna = create_payer_contract(
        facility_id, payer_code="AETNA", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-09-30T00:00:00Z",
        trailing_units=100)
    assert aetna["status"] == "ACTIVE"
    assert aetna["renegotiation_notice_days"] == 30
    bcbs = create_payer_contract(
        facility_id, payer_code="BCBS", product_line="COMMERCIAL",
        reimbursement_method="CASE_RATE", case_rate_cents=90000, percent_of_charge_bp=None,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-31T00:00:00Z",
        trailing_units=40)
    assert bcbs["percent_of_charge_bp"] is None, "CASE_RATE needs no percentage"

    read_dept = validate_success(api_client.get_department(department["id"], COMPLIANCE), 200)
    assert read_dept["allowed_revenue_code_values"] == ["0300"]
    assert read_dept["capture_hold"] is False
    assert read_dept["unresolved_finding_amount_cents"] == 0
    assert read_dept["recovered_charge_cents"] == 0
    assert read_dept["open_request_count"] == 0

    dept_rows, dept_meta = validate_paginated(api_client.list_departments(
        CONTRACT, {"facility_id": facility_id, "capture_hold": False}))
    assert dept_meta["total_count"] == 2
    assert dept_meta["has_more"] is False
    assert {row["id"] for row in dept_rows} == {department["id"], radiology["id"]}

    read_rc = validate_success(api_client.get_revenue_code(
        rc_250["id"], make_manager_headers(MANAGER_USER_ID)), 200)
    assert read_rc["requires_hcpcs"] is True
    assert read_rc["pricing_class"] == "PHARMACY"
    assert read_rc["status"] == "ACTIVE"

    retired = validate_success(api_client.retire_revenue_code(rc_250["id"], ADMIN), 200)
    assert retired["status"] == "RETIRED"

    _, retired_meta = validate_paginated(api_client.list_revenue_codes(
        ANALYST, {"status": "RETIRED", "limit": 100}))
    assert retired_meta["total_count"] == 2, "0250 was just retired and 0637 was born retired"

    proc_rows, proc_meta = validate_paginated(api_client.list_revenue_codes(
        ANALYST, {"pricing_class": "PROCEDURE"}))
    assert proc_meta["total_count"] == 1
    assert proc_rows[0]["id"] == rc_300["id"]

    read_rule = validate_success(api_client.get_price_rule(rule["id"], APPROVER), 200)
    assert read_rule["min_medicare_multiple_bp"] == 12000
    assert read_rule["market_cap_multiple_bp"] == 11000
    assert read_rule["flat_fee_cents"] is None
    assert read_rule["effective_to"] is None
    assert read_rule["status"] == "ACTIVE"
    assert read_rule["applied_item_count"] == 1
    assert read_rule["superseded_by_rule_id"] is None

    rule_rows, rule_meta = validate_paginated(api_client.list_price_rules(
        COMPLIANCE, {"facility_id": facility_id, "revenue_code_id": rc_300["id"],
                     "status": "ACTIVE"}))
    assert rule_meta["total_count"] == 1
    assert rule_rows[0]["id"] == rule["id"]

    set_clock("2026-10-01T00:00:00Z")
    assert validate_success(api_client.get_payer_contract(aetna["id"], CONTRACT), 200)["status"] \
        == "EXPIRED", "the term ended 2026-09-30, before the new logical now"

    active_rows, active_meta = validate_paginated(api_client.list_payer_contracts(
        COMPLIANCE, {"facility_id": facility_id, "status": "ACTIVE"}))
    assert active_meta["total_count"] == 1
    assert active_rows[0]["id"] == bcbs["id"]

    set_clock("2026-09-15T00:00:00Z")
    assert validate_success(api_client.get_payer_contract(aetna["id"], CONTRACT), 200)["status"] \
        == "EXPIRED", "the clock's only business consequence is ACTIVE to EXPIRED, never the reverse"

    read_back = read_facility(facility_id)
    assert read_back["active_item_count"] == 0, "the item never left DRAFT"
    assert read_back["chargemaster_posture"] == "OPEN"
    assert read_department(department["id"])["open_request_count"] == 0
