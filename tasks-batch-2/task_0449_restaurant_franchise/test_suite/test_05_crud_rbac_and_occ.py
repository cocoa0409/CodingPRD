"""Entity CRUD, default/computed fields, type/required-field validation, RBAC, and
optimistic-concurrency corner instances.

Covers the entities-section, rbac-section, and cross_cutting_complexity_layers
(OCC) corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    make_franchisee_headers,
    create_sales_report_payload,
    write_off_payload,
    distribute_payload,
    setup_open_unit,
    setup_brand_franchisee_territory,
    create_territory,
    create_unit,
    create_accepted_sales_report,
    create_issued_statement,
    create_in_progress_audit,
    setup_rebate_scenario,
    get_brand_version,
    close_period,
)

FRANCHISOR = TEST_USERS["franchisor_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]
NONEXISTENT = "00000000-0000-0000-0000-000000000000"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / create_brand_returns_201_with_defaults_and_system_fields
# ═══════════════════════════════════════════════════════════════════════════
def test_create_brand_applies_defaults_and_system_fields():
    """PRD §3.1: "A brand records its name and the economic parameters ... three marginal
    royalty rates, royalty_tier_1_rate (default 0.06) ... an ad_fund_rate (default 0.02)
    ... and a late_fee_monthly_rate (default 0.015) ... On creation the brand's
    current_period_index is set to 0, its current_utc to the default instant of
    2026-01-01T00:00:00Z, and its version to 1."

    Design: Corner/entities/create_brand_returns_201_with_defaults_and_system_fields
    """
    data = validate_success(
        api_client.create_brand({"name": "FreshCo"}, FRANCHISOR), expected_status=201
    )
    assert data["royalty_tier_1_rate"] == 0.06
    assert data["ad_fund_rate"] == 0.02
    assert data["late_fee_monthly_rate"] == 0.015
    assert data["current_period_index"] == 0
    assert data["version"] == 1
    assert data["current_utc"] == "2026-01-01T00:00:00Z"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / get_brand_returns_stored_entity
# ═══════════════════════════════════════════════════════════════════════════
def test_get_brand_returns_stored_entity():
    """PRD §2.4: "Every resource the API creates carries a server-minted id formatted as
    a UUID with no type prefix."
    PRD §3.1: "A brand records its name and the economic parameters of the franchise
    relationship."

    Design: Corner/entities/get_brand_returns_stored_entity
    """
    created = get_success_data(api_client.create_brand({"name": "FreshCo"}, FRANCHISOR))
    data = validate_success(
        api_client.get_brand(created["id"], FRANCHISOR), expected_status=200
    )
    assert data["id"] == created["id"]
    assert data["name"] == "FreshCo"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / list_units_paginated_envelope
# ═══════════════════════════════════════════════════════════════════════════
def test_list_units_filtered_paginated_envelope():
    """PRD §2.3: "Each list response surfaces limit, offset, total_count (the total
    number of records matching the query before paging), and has_more (true when records
    remain beyond the current page) inside the meta object."

    Design: Corner/entities/list_units_paginated_envelope
    """
    brand, fz, terr = setup_brand_franchisee_territory(
        owner_user_id="u_lst", territory_code="LST"
    )
    create_unit(fz["id"], terr["id"])
    resp = api_client.list_units(FRANCHISOR, params={"franchisee_id": fz["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert "has_more" in meta


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / get_franchisee_not_found
# ═══════════════════════════════════════════════════════════════════════════
def test_get_nonexistent_franchisee_not_found():
    """PRD §2.7: "the first one that does not correspond to an existing record causes the
    request to fail with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_franchisee_not_found
    """
    resp = api_client.get_franchisee(NONEXISTENT, FRANCHISOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / create_territory_missing_required_code
# ═══════════════════════════════════════════════════════════════════════════
def test_create_territory_missing_code_rejected():
    """PRD §3.1: "Each territory belongs to a brand (brand_id), carries a code and a
    display name."
    PRD §2.9: "surfaces as ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_territory_missing_required_code
    """
    brand = get_success_data(api_client.create_brand({"name": "B"}, FRANCHISOR))
    resp = api_client.create_territory(
        {"brand_id": brand["id"], "name": "North"}, FRANCHISOR  # no code
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / create_franchisee_default_is_existing_operator_false
# ═══════════════════════════════════════════════════════════════════════════
def test_create_franchisee_defaults():
    """PRD §3.2: "The optional is_existing_operator flag (default false) records whether
    this party already operates other units of the brand."
    PRD §3.2: "A freshly created franchisee enters status APPLICANT with
    open_compliance_strikes set to 0."

    Design: Corner/entities/create_franchisee_default_is_existing_operator_false
    """
    brand = get_success_data(api_client.create_brand({"name": "B"}, FRANCHISOR))
    data = validate_success(
        api_client.create_franchisee(
            {"brand_id": brand["id"], "legal_name": "FZ", "owner_user_id": "u_def"},
            FRANCHISOR,
        ),
        expected_status=201,
    )
    assert data["is_existing_operator"] is False
    assert data["status"] == "APPLICANT"
    assert data["open_compliance_strikes"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / sales_report_net_sales_computed_input_ignored
# ═══════════════════════════════════════════════════════════════════════════
def test_sales_report_net_sales_computed_from_gross_minus_discounts():
    """PRD §3.8: "On ingestion the system computes net_sales_cents as the gross sales
    minus the discounts, floored at 0 so it is never negative, and the report enters
    status POLLED."

    Design: Corner/entities/sales_report_net_sales_computed_input_ignored
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_cmp", territory_code="CMP")
    data = validate_success(
        api_client.create_sales_report(
            create_sales_report_payload(unit["id"], 0, 900_000, discounts_cents=100_000),
            FRANCHISOR,
        ),
        expected_status=201,
    )
    assert data["net_sales_cents"] == 800_000  # 900000 - 100000
    assert data["status"] == "POLLED"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / invalid_enum_vendor_category_rejected
# ═══════════════════════════════════════════════════════════════════════════
def test_invalid_vendor_category_rejected():
    """PRD §3.10: "a category that is one of FOOD, PACKAGING, EQUIPMENT, or SERVICES."
    PRD §2.9: "surfaces as ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/invalid_enum_vendor_category_rejected
    """
    brand = get_success_data(api_client.create_brand({"name": "B"}, FRANCHISOR))
    resp = api_client.create_vendor(
        {"brand_id": brand["id"], "name": "X", "category": "WIDGETS"}, AUDITOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: entities / unit_open_with_wrong_franchisee_parent_not_found
# ═══════════════════════════════════════════════════════════════════════════
def test_create_unit_with_nonexistent_franchisee_not_found():
    """PRD §2.7: "Foreign keys carried in request bodies — a unit_id, a vendor_id, a
    franchisee_id, and the like — are likewise required to reference existing records; a
    body that names a non-existent resource is also rejected with ERR_NOT_FOUND."

    Design: Corner/entities/unit_open_with_wrong_franchisee_parent_not_found
    """
    brand = get_success_data(api_client.create_brand({"name": "B"}, FRANCHISOR))
    terr = create_territory(brand["id"], code="PNF")
    resp = api_client.create_unit(
        {"franchisee_id": NONEXISTENT, "territory_id": terr["id"], "address": "U1"},
        FRANCHISOR,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: rbac / franchisee_cannot_create_brand
# ═══════════════════════════════════════════════════════════════════════════
def test_franchisee_cannot_create_brand():
    """PRD §2.1: "When both headers are present and valid but the caller's role is not
    authorized for the requested operation, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/franchisee_cannot_create_brand
    """
    resp = api_client.create_brand({"name": "Hijack"}, make_franchisee_headers("u_any"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: rbac / financeclerk_cannot_finalize_audit
# ═══════════════════════════════════════════════════════════════════════════
def test_financeclerk_cannot_finalize_audit():
    """PRD §2.1: "When both headers are present and valid but the caller's role is not
    authorized for the requested operation, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/financeclerk_cannot_finalize_audit
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_rbac", territory_code="RBC")
    audit = create_in_progress_audit(unit["id"])
    resp = api_client.finalize_audit(
        audit["id"],
        {
            "food_safety_score": 90,
            "cleanliness_score": 90,
            "service_score": 90,
            "brand_compliance_score": 90,
        },
        CLERK,  # ComplianceAuditor-exclusive endpoint
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: rbac / missing_auth_headers_unauthenticated
# ═══════════════════════════════════════════════════════════════════════════
def test_missing_auth_headers_unauthenticated():
    """PRD §2.1: "A request missing or malformed in either header is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api_client.get_brand(NONEXISTENT, headers={})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: cross_cutting_complexity_layers / occ_distribute_correct_version_succeeds
# ═══════════════════════════════════════════════════════════════════════════
def test_distribute_with_correct_brand_version_succeeds():
    """PRD §3.9: "Distribution (a finance-clerk action, OCC-guarded per §2.8) moves it
    OPEN → DISTRIBUTED."
    PRD §2.8: "A distribute request must carry expected_brand_version equal to the
    brand's current version."

    Design: Corner/cross_cutting_complexity_layers/occ_distribute_correct_version_succeeds
    """
    (brand, vendor, fz, terr, units, auths, account, brand_v) = setup_rebate_scenario(
        [2_000_000], rebate_pool_cents=1_000_000, min_qualifying_cents=1_000_000
    )
    data = validate_success(
        api_client.distribute_national_account(
            account["id"], distribute_payload(brand_v), CLERK
        ),
        expected_status=200,
    )
    assert data["status"] == "DISTRIBUTED"


# ═══════════════════════════════════════════════════════════════════════════
# Corner: cross_cutting_complexity_layers / occ_writeoff_stale_version_conflict
# ═══════════════════════════════════════════════════════════════════════════
def test_writeoff_with_stale_brand_version_conflicts():
    """PRD §2.8: "A write-off request must carry expected_brand_version equal to the
    brand's current version. If a period close has advanced the clock since the client
    last read the brand — changing the months-late count that feeds the compound
    late-fee formula — the write-off is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_writeoff_stale_version_conflict
    """
    brand, fz, terr, unit = setup_open_unit(owner_user_id="u_occ", territory_code="OCC")
    create_accepted_sales_report(unit["id"], 0, 1_000_000)
    statement = create_issued_statement(unit["id"], 0)
    close_period(brand["id"])
    close_period(brand["id"])  # statement now OVERDUE
    stale_v = get_brand_version(brand["id"])  # client captures version here
    close_period(brand["id"])  # a later close-period bumps Brand.version → stale_v is stale
    resp = api_client.write_off_royalty_statement(
        statement["id"], write_off_payload(stale_v), CLERK
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    refreshed = get_success_data(api_client.get_royalty_statement(statement["id"], CLERK))
    assert refreshed["status"] == "OVERDUE", "unchanged after rejected write-off"
