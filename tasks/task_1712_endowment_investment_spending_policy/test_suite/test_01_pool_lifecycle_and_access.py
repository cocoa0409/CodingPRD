"""Pool creation defaults, auth context, role authorization, and the suspension gate."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_fund,
    api_client,
    assert_fund,
    assert_pool,
    create_donor,
    create_fund,
    create_gift,
    create_pool,
    create_pool_payload,
    create_donor_payload,
    get_success_data,
    make_board_member_headers,
    make_development_officer_headers,
    make_investment_officer_headers,
    resume_pool,
    set_target_allocations,
    suspend_pool,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_pool_creation_applies_system_defaults(api):
    """PRD §2.5: 'An `EndowmentPool` is born `ACTIVE` with `current_quarter_index`
    equal to 0 and `current_unit_price_millicents` equal to the inception price of
    100000 millicents — exactly one dollar per unit.'
    PRD §2.5: '`total_market_value_cents` is the finalized pool market value of the
    most recent `FINAL` valuation — 0 before any finalize.'

    Design: Corner/entities/pool_creation_applies_system_defaults
    """
    res = api.create_pool(create_pool_payload(pool_name="Pool NEW", inception_fiscal_year=2026),
                          TEST_USERS["admin_headers"])
    data = validate_success(res, 201)
    assert_pool(data)
    assert data["pool_status"] == "ACTIVE"
    assert data["current_quarter_index"] == 0
    assert data["current_unit_price_millicents"] == 100000
    assert data["total_units_outstanding_micro"] == 0
    assert data["total_market_value_cents"] == 0

    fetched = validate_success(api.get_pool(data["id"], TEST_USERS["admin_headers"]))
    assert fetched["pool_status"] == "ACTIVE"
    assert fetched["current_quarter_index"] == 0
    assert fetched["current_unit_price_millicents"] == 100000


def test_pool_create_missing_auth_header_returns_400(api):
    """PRD §2.1: 'A request missing either header, or carrying an empty value for
    either, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400).'

    Design: Corner/validations/pool_create_missing_auth_header_returns_400
    """
    res = api.create_pool(
        create_pool_payload(pool_name="NoAuth", inception_fiscal_year=2026),
        headers={"Content-Type": "application/json"},
    )
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER, 400)


def test_role_denied_for_other_roles_exclusive_operations(api):
    """PRD §2.1: 'A request whose role is not listed among an endpoint's authorized
    roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).'
    PRD §4: POST /endowment/pools lists only EndowmentAdmin;
    POST /endowment/valuations/{valuation_id}/finalize lists only InvestmentOfficer.

    Design: Corner/rbac/role_denied_for_other_roles_exclusive_operations
    """
    pool = create_pool(pool_name="Pool RB", inception_fiscal_year=2026)

    res1 = api.create_pool(create_pool_payload(pool_name="Nope", inception_fiscal_year=2026),
                           TEST_USERS["program_headers"])
    validate_error(res1, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    res2 = api.finalize_valuation(
        NON_EXISTENT_UUID,
        {"final_pool_market_value_cents": 0, "expected_pool_version": pool["version"]},
        TEST_USERS["dev_headers"],
    )
    validate_error(res2, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_authorization_precedes_existence_forbidden_role_on_missing_resource(api):
    """PRD §2.8: 'The order is: (1) presence of the context headers, failing as
    `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`; (2) role authorization, failing as
    `ERR_FORBIDDEN_ROLE`;'
    PRD §2.8: '(5) existence of referenced resources, validated left-to-right along
    the path and then the body, failing as `ERR_NOT_FOUND`;'
    PRD §4: POST /endowment/funds/{fund_id}/activate lists only DevelopmentOfficer.

    Design: Corner/validations/authorization_precedes_existence_forbidden_role_on_missing_resource
    """
    res = api.activate_fund(NON_EXISTENT_UUID, TEST_USERS["board_headers"])
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_fund_get_not_found_returns_404(api):
    """PRD §2.8: '(5) existence of referenced resources, validated left-to-right
    along the path and then the body, failing as `ERR_NOT_FOUND`'
    PRD §5: ERR_NOT_FOUND maps to HTTP 404.

    Design: Corner/entities/fund_get_not_found_returns_404
    """
    res = api.get_fund(NON_EXISTENT_UUID, TEST_USERS["dev_headers"])
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)


def test_create_missing_required_field_and_invalid_enum_rejected(api):
    """PRD §2.8: '(4) request body shape — required fields present, enums valid,
    integer ranges respected — failing as `ERR_INVALID_REQUEST`'
    PRD §3.1: 'a `donor_type` of `INDIVIDUAL`, `FOUNDATION`, `CORPORATION`, or `ESTATE`'

    Design: Corner/entities/create_missing_required_field_and_invalid_enum_rejected
    """
    res1 = api.create_pool({"pool_name": "No FY"}, TEST_USERS["admin_headers"])
    validate_error(res1, ApiErrorId.ERR_INVALID_REQUEST, 400)

    res2 = api.create_donor(create_donor_payload(donor_name="Bad", donor_type="ROBOT"),
                            TEST_USERS["dev_headers"])
    validate_error(res2, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_mutations_visible_in_the_same_response_immediate_consistency(api):
    """PRD §2.2: 'Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field.'
    PRD §3.1: 'On success, `activated_quarter_index` is stamped with the open quarter
    index, namely the pool's `current_quarter_index` + 1.'
    PRD §2.6: 'Suspending a pool (an `EndowmentAdmin` action moving `pool_status` from
    `ACTIVE` to `SUSPENDED`) and resuming it (`SUSPENDED` back to `ACTIVE`) each
    increment the pool's `version` by 1.'

    Design: Corner/consistency_model/mutations_visible_in_the_same_response_immediate_consistency
    """
    pool = create_pool(pool_name="Pool IC", inception_fiscal_year=2026)
    fund = create_fund(pool["id"], fund_code="FIC", fund_name="Fund IC")
    donor = create_donor(donor_name="D IC")
    create_gift(fund["id"], donor["id"], "IC1", gift_type="CORPUS", amount_cents=5_000_000)

    activate_res = api.activate_fund(fund["id"], TEST_USERS["dev_headers"])
    activated = validate_success(activate_res, 200)
    assert_fund(activated)
    assert activated["fund_status"] == "ACTIVE"
    assert activated["activated_quarter_index"] == 1

    suspend_res = api.suspend_pool(pool["id"], TEST_USERS["admin_headers"])
    suspended = validate_success(suspend_res, 200)
    assert suspended["pool_status"] == "SUSPENDED"
    assert suspended["version"] == pool["version"] + 1


def test_suspended_pool_blocks_value_operations_until_resume(api):
    """PRD §2.6: 'While a pool is `SUSPENDED`, every value-moving child operation is
    rejected with `ERR_POOL_SUSPENDED` (HTTP 409). The blocked set is exactly: gift
    receive; valuation create, finalize, and supersede; distribution create, propose,
    repropose, approve, and distribute; payout create and disburse; manager engage;
    manager-quarter-report filing; allocation bulk replacement; policy create and
    adopt; and fund activate and corpus redemption.'

    Design: Corner/validations/suspended_pool_blocks_value_operations_until_resume
    """
    pool = create_pool(pool_name="Pool SP", inception_fiscal_year=2026)
    set_target_allocations(pool["id"])
    fund = create_fund(pool["id"], fund_code="FSP", fund_name="Fund SP")
    donor = create_donor(donor_name="D SP")
    gift = create_gift(fund["id"], donor["id"], "SP1", gift_type="CORPUS", amount_cents=5_000_000)
    activate_fund(fund["id"])
    suspend_pool(pool["id"])

    res1 = api.receive_gift(gift["id"], TEST_USERS["dev_headers"])
    validate_error(res1, ApiErrorId.ERR_POOL_SUSPENDED, 409)

    res2 = api.create_valuation(
        {"pool_id": pool["id"], "estimated_pool_market_value_cents": 0},
        TEST_USERS["io_headers"],
    )
    validate_error(res2, ApiErrorId.ERR_POOL_SUSPENDED, 409)

    res3 = api.create_policy(
        {
            "pool_id": pool["id"],
            "spending_rate_bps": 500,
            "smoothing_window_quarters": 4,
            "band_floor_bps": 0,
            "band_cap_bps": 10000,
            "effective_from_fiscal_year": 2026,
        },
        TEST_USERS["io_headers"],
    )
    validate_error(res3, ApiErrorId.ERR_POOL_SUSPENDED, 409)

    resume_pool(pool["id"])
    received = validate_success(api.receive_gift(gift["id"], TEST_USERS["dev_headers"]), 200)
    assert received["gift_status"] == "RECEIVED"


def test_list_pagination_and_status_filter_interaction(api):
    """PRD §2.3: 'The `meta` block of a list response includes the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`.'
    PRD §4: GET /endowment/funds is 'filterable by `pool_id`, `fund_status`,
    `spending_posture`'.

    Design: Corner/endpoints/list_pagination_and_status_filter_interaction
    """
    pool = create_pool(pool_name="Pool PG", inception_fiscal_year=2026)
    fund_a = create_fund(pool["id"], fund_code="FA", fund_name="A")
    create_fund(pool["id"], fund_code="FB", fund_name="B")
    create_fund(pool["id"], fund_code="FC", fund_name="C")
    donor = create_donor(donor_name="D PG")
    create_gift(fund_a["id"], donor["id"], "PG1", gift_type="CORPUS", amount_cents=5_000_000)
    activate_fund(fund_a["id"])

    res1 = api.list_funds(TEST_USERS["dev_headers"],
                          params={"pool_id": pool["id"], "limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(res1)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    res2 = api.list_funds(TEST_USERS["dev_headers"],
                          params={"pool_id": pool["id"], "limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(res2)
    assert len(page2) == 1
    assert meta2["has_more"] is False

    res3 = api.list_funds(TEST_USERS["dev_headers"],
                          params={"pool_id": pool["id"], "fund_status": "ACTIVE"})
    active, meta3 = validate_paginated(res3)
    assert len(active) == 1
    assert active[0]["fund_code"] == "FA"

    body = res3.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
