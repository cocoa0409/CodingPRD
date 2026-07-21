"""Entity creation, computed fields, uniqueness, reads and listing (breadth corner coverage)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_client_payload, create_appeal_payload, create_assessment_payload,
    make_analyst_headers, make_client_headers, TEST_USERS,
)
from test_helpers import fixtures as fx

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST_SHARED = TEST_USERS["analyst_headers"]


def test_client_creation_returns_201_with_defaults(api):
    """PRD §3.1: "A client's `portal_enabled` flag, defaulting to true, governs whether that
    taxpayer may authenticate to the portal. Every client also carries two running ledger figures,
    `lifetime_fees_billed_cents` and `outstanding_balance_cents`, both of which begin at 0 at creation".

    Design: Corner/entities/corner_client_creation_returns_201
    """
    resp = api.create_client(create_client_payload(full_name="New Co", entity_type="BUSINESS"), FIRM_ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["entity_type"] == "BUSINESS"
    assert data["portal_enabled"] is True
    assert data["lifetime_fees_billed_cents"] == 0
    assert data["outstanding_balance_cents"] == 0


def test_client_create_is_immediately_consistent(api):
    """PRD §2.4: "The `version` begins at 1 when the resource is created and increases by exactly 1
    on every mutation that changes the resource".

    Design: Corner/consistency_model/corner_immediate_visibility_on_client_create
    """
    from test_helpers import is_valid_uuid
    resp = api.create_client(create_client_payload(full_name="Now"), FIRM_ADMIN)
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"]), "server must mint a UUID id in the same response"
    assert data["version"] == 1


def test_get_missing_assessment_returns_not_found(api):
    """PRD §2.9: "each referenced resource must exist, and the first missing reference encountered
    yields `ERR_NOT_FOUND` (HTTP 404) before any deeper reference or business rule is considered."

    Design: Corner/entities/corner_assessment_not_found_returns_404
    """
    resp = api.get_assessment(NON_EXISTENT_UUID, ANALYST_SHARED)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_appeal_missing_valuation_method_rejected(api):
    """PRD §2.9: "a request missing a required field or carrying a value of the wrong type or an
    unrecognized enum member is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/corner_appeal_missing_valuation_method_returns_invalid_request
    """
    ctx = fx.setup_base(api)
    payload = {
        "assessment_id": ctx["assessment_id"],
        "analyst_id": ctx["analyst_id"],
        "fee_agreement_id": ctx["fee_agreement_id"],
    }  # valuation_method omitted
    resp = api.create_appeal(payload, make_analyst_headers(ctx["analyst_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_evidence_adjusted_sale_value_is_computed(api):
    """PRD §3.3: "the system computes its `adjusted_sale_value_cents` as the `sale_price_cents`
    multiplied by the quantity one plus the `adjustment_pct`, rounded half up to whole cents."

    Design: Corner/entities/corner_evidence_adjusted_value_is_computed
    """
    ctx = fx.setup_base(api)
    appeal = fx.new_appeal(api, ctx["analyst_id"], ctx["assessment_id"], ctx["fee_agreement_id"],
                           "SALES_COMPARISON")
    resp = api.create_evidence(
        appeal["id"],
        {"comp_address": "z", "sale_price_cents": 20000000, "sale_date": "2025-06-01T00:00:00Z",
         "comp_assessed_value_cents": 18000000, "adjustment_pct": -0.10},
        make_analyst_headers(ctx["analyst_id"]))
    data = validate_success(resp, expected_status=201)
    assert data["adjusted_sale_value_cents"] == 18000000


def test_duplicate_assessment_year_rejected(api):
    """PRD §3.2: "the pairing of parcel and tax year must be unique, so the system supports a
    distinct assessment per year but rejects a duplicate year for the same parcel with `ERR_DUPLICATE`."

    Design: Corner/entities/corner_assessment_duplicate_year_returns_duplicate
    """
    ctx = fx.setup_base(api)  # creates a 2026 assessment on the parcel
    resp = api.create_assessment(
        create_assessment_payload(ctx["parcel_id"], tax_year=2026, original_assessed_value_cents=31000000),
        make_analyst_headers(ctx["analyst_id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_assessment_list_by_parcel_is_paginated(api):
    """PRD §2.3: "`total_count` is the number of records matching the query before the page window
    is applied and `has_more` is true exactly when records remain beyond the returned page."

    Design: Corner/entities/corner_assessment_list_by_parcel_paginated
    """
    ctx = fx.setup_base(api)
    resp = api.list_assessments(make_analyst_headers(ctx["analyst_id"]), params={"parcel_id": ctx["parcel_id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == ctx["assessment_id"]


def test_projected_annual_tax_on_create_without_exemptions(api):
    """PRD §3.2: "The `projected_annual_tax_cents` is then the effective `assessed_value_cents` less
    that approved-exemption total, multiplied by the `millage_rate` and divided by 1000, with the
    result rounded half up to whole cents".

    Design: Corner/calculations/corner_projected_annual_tax_no_exemption_on_create
    """
    ctx = fx.setup_base(api)
    resp = api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"]))
    data = validate_success(resp)
    assert data["assessed_value_cents"] == 30000000
    assert data["projected_annual_tax_cents"] == 750000  # 30000000 * 25.0 / 1000


def test_evidence_subresource_list_returns_array(api):
    """PRD §2.3: "`total_count` is the number of records matching the query before the page window
    is applied and `has_more` is true exactly when records remain beyond the returned page."

    Design: Corner/endpoints/corner_evidence_subresource_list_returns_array
    """
    ctx = fx.setup_base(api)
    appeal = fx.new_appeal(api, ctx["analyst_id"], ctx["assessment_id"], ctx["fee_agreement_id"],
                           "SALES_COMPARISON")
    fx.add_evidence(api, ctx["analyst_id"], appeal["id"], comp_address="e1", sale_price_cents=27000000,
                    comp_assessed_value_cents=27000000)
    fx.add_evidence(api, ctx["analyst_id"], appeal["id"], comp_address="e2", sale_price_cents=28000000,
                    comp_assessed_value_cents=28000000)
    resp = api.list_evidence(appeal["id"], make_analyst_headers(ctx["analyst_id"]))
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert len(data) == 2
