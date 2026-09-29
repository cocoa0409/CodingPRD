"""Revenue-code mapping, the department whitelist, and what a retirement does and does not gate."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_revenue_code, create_department, create_item, create_inactive_item,
    reprice_item, item_lifecycle, read_item, read_facility, set_clock,
    ADMIN, ANALYST, APPROVER, MANAGER2_USER_ID,
)

FACILITY = {
    "name": "Mercy General", "cms_certification_number": "CCN-2193-REF",
    "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
}
RC_0300 = {
    "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
    "allowed_code_types": ["CPT"], "pricing_class": "PROCEDURE", "status": "ACTIVE",
}
RC_0250 = {
    "code": "0250", "description": "Pharmacy - general", "requires_hcpcs": True,
    "allowed_code_types": ["HCPCS"], "pricing_class": "PHARMACY", "status": "ACTIVE",
}
SUPPLY_PRICING = dict(cost_basis_cents=4000, medicare_rate_cents=2000,
                      market_p75_cents=30000, effective_from="2026-09-01T00:00:00Z")
CATH_PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
                    market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")


def test_the_mapping_check_fires_before_the_whitelist_and_an_empty_whitelist_gates_nothing():
    """PRD §3.3: "The revenue-code mapping must be legal: the item's `code_type` must appear in the
    revenue code's `allowed_code_types`, and if that revenue code has `requires_hcpcs` set to true then
    the item's `code_type` must be `CPT` or `HCPCS` and its `code_value` must be non-null — otherwise
    `ERR_REVENUE_CODE_MAPPING_INVALID` (422). The owning department's `allowed_revenue_code_values`
    must be empty or must contain the mapped revenue code's `code`, otherwise
    `ERR_DEPARTMENT_REVENUE_CODE_NOT_ALLOWED` (422)."
    PRD §2.9: "23–31. Business referential integrity, in this order:
    `ERR_REVENUE_CODE_MAPPING_INVALID` (422), `ERR_DEPARTMENT_REVENUE_CODE_NOT_ALLOWED` (422),"
    PRD §3.1: "That array is a whitelist: when it is non-empty, an item in this department may only map
    to a revenue code whose `code` appears in it, and a violation is
    `ERR_DEPARTMENT_REVENUE_CODE_NOT_ALLOWED`. An empty array means unrestricted."

    Design: Corner/validations/department_revenue_code_allowlist_applies_only_when_populated_and_yields_to_the_mapping_check
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(
        facility_overrides=FACILITY,
        revenue_code_overrides=RC_0300,
        department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                              "allowed_revenue_code_values": ["0300"]},
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
    )
    facility_id = base["facility"]["id"]
    rc_250 = create_revenue_code(**RC_0250)
    dept_a = base["department"]
    dept_b = create_department(facility_id, MANAGER2_USER_ID, name="Central Supply",
                               cost_center_code="CC-200")
    assert dept_a["allowed_revenue_code_values"] == ["0300"]
    assert dept_b["allowed_revenue_code_values"] == [], "the omitted whitelist is unrestricted"

    def body(department_id, revenue_code_id, **extra):
        fields = dict(
            cdm_number="CDM-2001", description="STERILE DRESSING KIT",
            code_type="HCPCS", **SUPPLY_PRICING,
        )
        fields.update(extra)
        return factories.create_charge_item_payload(
            facility_id, department_id, revenue_code_id, **fields
        )

    validate_error(
        api_client.create_charge_item(
            body(dept_a["id"], rc_250["id"], code_type="CPT", code_value="93458"), ANALYST
        ),
        ApiErrorId.ERR_REVENUE_CODE_MAPPING_INVALID.value, 422,
    )
    validate_error(
        api_client.create_charge_item(
            body(dept_a["id"], rc_250["id"], code_value="A4550"), ANALYST
        ),
        ApiErrorId.ERR_DEPARTMENT_REVENUE_CODE_NOT_ALLOWED.value, 422,
    )

    accepted = validate_success(
        api_client.create_charge_item(
            body(dept_b["id"], rc_250["id"], code_value="A4550"), ANALYST
        ), 201,
    )
    assert accepted["department_id"] == dept_b["id"]
    assert accepted["lifecycle_status"] == "DRAFT"
    assert accepted["price_status"] == "PRICE_STALE"

    cpt = validate_success(
        api_client.create_charge_item(
            factories.create_charge_item_payload(
                facility_id, dept_a["id"], base["revenue_code"]["id"],
                cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                code_type="CPT", code_value="93458", **CATH_PRICING,
            ), ANALYST,
        ), 201,
    )
    assert cpt["gross_charge_cents"] == 0, "0300 is whitelisted, and a fresh item is unpriced"

    validate_error(
        api_client.create_charge_item(
            factories.create_charge_item_payload(
                facility_id, dept_b["id"], rc_250["id"],
                cdm_number="CDM-2002", description="IV POLE",
                code_type="CPT", code_value="93458", **SUPPLY_PRICING,
            ), ANALYST,
        ),
        ApiErrorId.ERR_REVENUE_CODE_MAPPING_INVALID.value, 422,
    )

    rows, meta = validate_paginated(
        api_client.list_charge_items(ANALYST, {"facility_id": facility_id})
    )
    assert meta["total_count"] == 2, "three refusals stored nothing"
    assert {row["cdm_number"] for row in rows} == {"CDM-2001", "CDM-1001"}


def test_a_retired_revenue_code_blocks_only_activation_and_reactivation():
    """PRD §3.1: "Retiring a revenue code is a one-way flip of `status` from `ACTIVE` to `RETIRED`;
    items already `ACTIVE` under it keep billing, but no item mapped to a retired code may thereafter
    be activated or reactivated, which surfaces as `ERR_REVENUE_CODE_RETIRED`."
    PRD §3.3: "The item's `duplicate_of_item_id` must be null — an item retired as a duplicate can
    never come back, and attempting it is `ERR_ITEM_RETIRED_AS_DUPLICATE` (409). The mapped revenue
    code's `status` must be `ACTIVE`, otherwise `ERR_REVENUE_CODE_RETIRED`. And `price_status` must be
    `PRICED_CURRENT`, otherwise `ERR_ITEM_PRICE_NOT_CURRENT`."
    PRD §3.3: "the pricing dimension must already be settled, meaning `price_status` must equal
    `PRICED_CURRENT`, otherwise `ERR_ITEM_PRICE_NOT_CURRENT` (409)"

    Design: Corner/validations/retiring_a_revenue_code_blocks_activation_but_not_review_and_price_state_check_stays_lower
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(
        facility_overrides=FACILITY,
        revenue_code_overrides=RC_0300,
        department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                              "allowed_revenue_code_values": []},
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
    )
    item_one = create_inactive_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", **CATH_PRICING,
    )
    assert item_one["lifecycle_status"] == "INACTIVE"
    assert item_one["price_status"] == "PRICED_CURRENT"
    assert item_one["gross_charge_cents"] == 240000
    assert item_one["version"] == 6

    item_two = create_item(
        base, cdm_number="CDM-1002", description="CARDIAC CATH ADD-ON",
        code_type="CPT", code_value="93459", **CATH_PRICING,
    )
    assert item_two["price_status"] == "PRICE_STALE"

    retired = validate_success(
        api_client.retire_revenue_code(base["revenue_code"]["id"], ADMIN), 200
    )
    assert retired["status"] == "RETIRED"

    validate_error(
        api_client.charge_item_lifecycle(item_one["id"], {"action": "REACTIVATE"}, APPROVER),
        ApiErrorId.ERR_REVENUE_CODE_RETIRED.value, 409,
    )
    frozen_out = read_item(item_one["id"])
    assert frozen_out["lifecycle_status"] == "INACTIVE"
    assert frozen_out["price_status"] == "PRICED_CURRENT", "the price-state check never fired"
    assert frozen_out["version"] == 6, "the refusal advanced nothing"

    submitted = item_lifecycle(item_two["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    assert submitted["lifecycle_status"] == "PENDING_REVIEW", (
        "retirement does not gate the review transition"
    )

    validate_error(
        api_client.charge_item_lifecycle(item_two["id"], {"action": "APPROVE"}, APPROVER),
        ApiErrorId.ERR_ITEM_PRICE_NOT_CURRENT.value, 409,
    )

    priced = reprice_item(item_two["id"])
    assert priced["gross_charge_cents"] == 240000, (
        "the price rule is still ACTIVE after the revenue code retired"
    )
    assert priced["price_status"] == "PRICED_CURRENT"

    approved = item_lifecycle(item_two["id"], "APPROVE", APPROVER)
    assert approved["lifecycle_status"] == "APPROVED"

    validate_error(
        api_client.charge_item_lifecycle(item_two["id"], {"action": "ACTIVATE"}, APPROVER),
        ApiErrorId.ERR_REVENUE_CODE_RETIRED.value, 409,
    )
    assert read_item(item_two["id"])["lifecycle_status"] == "APPROVED"

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 0
