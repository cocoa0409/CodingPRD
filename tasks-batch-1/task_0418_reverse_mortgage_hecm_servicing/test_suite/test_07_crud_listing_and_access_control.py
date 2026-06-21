"""Resource CRUD, listing + filtering + pagination, the append-only ledger,
origination idempotency, audit recompute, and the RBAC gates.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    make_borrower_headers,
    setup_lender_with_plf,
    setup_preorigination_loan,
    setup_originated_loc_base_loan,
    setup_originated_loan,
    setup_due_and_payable_loan,
    create_borrower,
    create_loan,
)

_SO = TEST_USERS["servicer_ops_headers"]
_CO = TEST_USERS["compliance_officer_headers"]
_HUD = TEST_USERS["hud_auditor_headers"]


# ---------------------------------------------------------------------------
# entities / create_lender_returns_201_with_all_fields_and_default_clock
# ---------------------------------------------------------------------------
def test_create_lender_returns_201_with_default_clock(api):
    """PRD §3.1: "On creation the lender's simulated clock, `clock_utc`, is initialized to
    `1970-01-01T00:00:00.000Z`."

    Design: Corner/entities/create_lender_returns_201_with_all_fields_and_default_clock
    """
    data = validate_success(api.create_lender(
        {"name": "Acme Servicing", "hud_lending_limit_cents": 80000000}, _SO),
        expected_status=201)
    assert data["name"] == "Acme Servicing"
    assert data["hud_lending_limit_cents"] == 80000000
    assert data["clock_utc"] == "1970-01-01T00:00:00.000Z"
    assert isinstance(data["id"], str) and len(data["id"]) > 0


# ---------------------------------------------------------------------------
# entities / get_loan_returns_stored_entity_by_id
# ---------------------------------------------------------------------------
def test_get_loan_returns_stored_entity(api):
    """PRD §2.8: "When an endpoint names a resource by an `id` in its path, that
    identifier is resolved before the request body is considered"

    Design: Corner/entities/get_loan_returns_stored_entity_by_id
    """
    lender = setup_lender_with_plf()
    borrower = create_borrower(lender["id"])
    loan = create_loan(lender["id"], borrower["id"], appraised_value_cents=30000000,
                       expected_rate_bps=500, draw_type="LINE_OF_CREDIT")
    data = validate_success(api.get_loan(loan["id"], _SO))
    assert data["id"] == loan["id"]
    assert data["borrower_id"] == borrower["id"]
    assert data["appraised_value_cents"] == 30000000
    assert data["draw_type"] == "LINE_OF_CREDIT"


# ---------------------------------------------------------------------------
# entities / list_loans_filtered_by_lender_id_returns_array_envelope
# ---------------------------------------------------------------------------
def test_list_loans_filtered_by_lender_id(api):
    """PRD §2.8: "Loans may be filtered by `lender_id`, `borrower_id`, or
    `non_borrowing_spouse_id`"
    PRD §2.3: "The `meta` block of every list response carries the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is
    the number of records matching the filter before the limit/offset window
    is applied and `has_more` is true when records remain beyond the current
    window."

    Design: Corner/entities/list_loans_filtered_by_lender_id_returns_array_envelope
    """
    lender = setup_lender_with_plf()
    borrower = create_borrower(lender["id"])
    create_loan(lender["id"], borrower["id"], appraised_value_cents=30000000,
                expected_rate_bps=500, draw_type="LUMP_SUM")
    create_loan(lender["id"], borrower["id"], appraised_value_cents=40000000,
                expected_rate_bps=500, draw_type="LINE_OF_CREDIT")
    data, meta = validate_paginated(api.list_loans(_SO, params={"lender_id": lender["id"]}))
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(item["lender_id"] == lender["id"] for item in data)


# ---------------------------------------------------------------------------
# entities / get_loan_nonexistent_id_returns_not_found
# ---------------------------------------------------------------------------
def test_get_loan_nonexistent_id_returns_not_found(api):
    """PRD §2.8: "if any referenced resource — whether named in the path or in the body — does
    not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_loan_nonexistent_id_returns_not_found
    """
    validate_success(api.create_lender(
        {"name": "NF Servicer", "hud_lending_limit_cents": 80000000}, _SO),
        expected_status=201)
    validate_error(api.get_loan("loan_does_not_exist_0000", _SO), ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# entities / create_loan_missing_required_draw_type_returns_invalid_request
# ---------------------------------------------------------------------------
def test_create_loan_missing_draw_type_returns_invalid_request(api):
    """PRD §2.10: "fourth, request-body well-formedness — required fields present,
    enumerations valid, monetary amounts strictly greater than zero, a `TERM`
    loan carrying `tenure_term_months`, a `SHORT_SALE` resolution carrying
    `appraised_at_resolution_cents` (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_loan_missing_required_draw_type_returns_invalid_request
    """
    lender = setup_lender_with_plf()
    borrower = create_borrower(lender["id"])
    validate_error(api.create_loan(
        {"lender_id": lender["id"], "borrower_id": borrower["id"],
         "appraised_value_cents": 30000000, "expected_rate_bps": 500}, _SO),
        ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# entities / create_loan_invalid_draw_type_enum_returns_invalid_request
# ---------------------------------------------------------------------------
def test_create_loan_invalid_draw_type_enum_returns_invalid_request(api):
    """PRD §3.2: "The draw type is one of `LUMP_SUM`, `LINE_OF_CREDIT`, `TENURE`, or `TERM`"
    PRD §2.10: "fourth, request-body well-formedness — required fields present,
    enumerations valid, monetary amounts strictly greater than zero, a `TERM`
    loan carrying `tenure_term_months`, a `SHORT_SALE` resolution carrying
    `appraised_at_resolution_cents` (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_loan_invalid_draw_type_enum_returns_invalid_request
    """
    lender = setup_lender_with_plf()
    borrower = create_borrower(lender["id"])
    validate_error(api.create_loan(
        {"lender_id": lender["id"], "borrower_id": borrower["id"],
         "appraised_value_cents": 30000000, "expected_rate_bps": 500,
         "draw_type": "BALLOON"}, _SO),
        ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# entities / create_lesa_non_positive_charge_returns_invalid_request
# ---------------------------------------------------------------------------
def test_create_lesa_non_positive_charge_returns_invalid_request(api):
    """PRD §3.3: "the `annual_property_charge_cents` (estimated annual property charges
    — taxes plus insurance — used to size the set-aside, greater than zero)"
    PRD §2.10: "fourth, request-body well-formedness — required fields present,
    enumerations valid, monetary amounts strictly greater than zero".

    Design: Corner/entities/create_lesa_non_positive_charge_returns_invalid_request
    """
    lender, borrower, loan = setup_preorigination_loan()
    validate_error(api.create_lesa(
        {"loan_id": loan["id"], "funding_mode": "FULLY_FUNDED",
         "annual_property_charge_cents": 0, "life_expectancy_years": 10}, _SO),
        ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# entities / create_loan_with_nonexistent_borrower_id_returns_not_found
# ---------------------------------------------------------------------------
def test_create_loan_nonexistent_borrower_returns_not_found(api):
    """PRD §2.8: "if any referenced resource — whether named in the path or in the body — does
    not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_loan_with_nonexistent_borrower_id_returns_not_found
    """
    lender = validate_success(api.create_lender(
        {"name": "FK Servicer", "hud_lending_limit_cents": 80000000}, _SO),
        expected_status=201)
    validate_error(api.create_loan(
        {"lender_id": lender["id"], "borrower_id": "borrower_missing_0000",
         "appraised_value_cents": 30000000, "expected_rate_bps": 500,
         "draw_type": "LUMP_SUM"}, _SO),
        ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# entities / ledger_entry_immutable_no_update_or_version_field
# ---------------------------------------------------------------------------
def test_ledger_entries_are_append_only_no_version(api):
    """PRD §2.4: "The `PrincipalLimitFactor` and the `LedgerEntry` are append-only reference
    rows: each carries only an `id` and a `created_at`, and neither has an
    `updated_at` nor a `version`."

    Design: Corner/entities/ledger_entry_immutable_no_update_or_version_field
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    data, meta = validate_paginated(api.list_ledger_entries(_HUD, params={"loan_id": loan["id"]}))
    assert len(data) >= 1
    assert all("version" not in entry for entry in data)
    assert data[0]["entry_type"] == "ADVANCE"


# ---------------------------------------------------------------------------
# state_machines / new_loan_starts_active_pre_origination_initial_state
# ---------------------------------------------------------------------------
def test_new_loan_starts_active_pre_origination(api):
    """PRD §3.2: "At creation the loan's `disposition_status` is `ACTIVE` pending origination,
    its `servicing_status` is `CURRENT`, its `origination_date` is null, and
    every monetary balance is zero."

    Design: Corner/state_machines/new_loan_starts_active_pre_origination_initial_state
    """
    lender = setup_lender_with_plf()
    borrower = create_borrower(lender["id"])
    data = validate_success(api.create_loan(
        {"lender_id": lender["id"], "borrower_id": borrower["id"],
         "appraised_value_cents": 30000000, "expected_rate_bps": 500,
         "draw_type": "LINE_OF_CREDIT"}, _SO), expected_status=201)
    assert data["disposition_status"] == "ACTIVE"
    assert data["servicing_status"] == "CURRENT"
    assert data["origination_date"] is None
    assert data["principal_balance_cents"] == 0


# ---------------------------------------------------------------------------
# state_machines / originate_already_originated_loan_returns_already_originated
# ---------------------------------------------------------------------------
def test_originate_already_originated_returns_already_originated(api):
    """PRD §3.4: "It is permitted only while the loan is still in its pre-origination state —
    that is, while `origination_date` is null; attempting to originate a loan
    that already has an `origination_date` set is rejected with
    `ERR_ALREADY_ORIGINATED` (HTTP 409)."

    Design: Corner/state_machines/originate_already_originated_loan_returns_already_originated
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    validate_error(api.originate_loan(loan["id"], _SO), ApiErrorId.ERR_ALREADY_ORIGINATED.value)


# ---------------------------------------------------------------------------
# errors / recompute_reconciles_balance_to_ledger_no_inconsistency
# ---------------------------------------------------------------------------
def test_recompute_reconciles_balance_no_inconsistency(api):
    """PRD §3.12: "A HUD auditor — or a `ServicerOps` operator — may invoke an audit recompute on
    a loan, which re-derives the `principal_balance_cents` from the ledger
    stream and reconciles the derived balances, including
    `available_line_of_credit_cents`, against the stored values."

    Design: Corner/errors/recompute_reconciles_balance_to_ledger_no_inconsistency
    """
    lender, borrower, loan = setup_originated_loan(loan_overrides={"draw_type": "LUMP_SUM"})
    validate_success(api.post_accrual(loan["id"], {"number_of_months": 1}, _SO))
    bal_before = validate_success(api.get_loan(loan["id"], _SO))["principal_balance_cents"]
    data = validate_success(api.recompute_loan(loan["id"], _HUD))
    assert data["principal_balance_cents"] == bal_before


# ---------------------------------------------------------------------------
# cross_cutting / list_loans_invalid_pagination_limit_returns_400
# ---------------------------------------------------------------------------
def test_list_loans_invalid_pagination_limit_returns_400(api):
    """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, must be at least 1,
    and may not exceed 100."
    PRD §2.3: "A request whose `limit` or `offset` falls outside these bounds is
    rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/cross_cutting/list_loans_invalid_pagination_limit_returns_400
    """
    lender = validate_success(api.create_lender(
        {"name": "Page Servicer", "hud_lending_limit_cents": 80000000}, _SO),
        expected_status=201)
    validate_error(
        api.list_loans(_SO, params={"lender_id": lender["id"], "limit": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value)


# ---------------------------------------------------------------------------
# cross_cutting / list_disbursements_filter_by_status_returns_only_matching
# ---------------------------------------------------------------------------
def test_list_disbursements_filter_by_status(api):
    """PRD §2.8: "disbursements and occupancy certifications by `loan_id` and by `status`"

    Design: Corner/cross_cutting/list_disbursements_filter_by_status_returns_only_matching
    """
    lender, borrower, loan = setup_originated_loc_base_loan()
    rej = validate_success(api.create_disbursement(
        {"loan_id": loan["id"], "kind": "LINE_DRAW", "requested_amount_cents": 100000}, _SO),
        expected_status=201)
    validate_success(api.create_disbursement(
        {"loan_id": loan["id"], "kind": "LINE_DRAW", "requested_amount_cents": 200000}, _SO),
        expected_status=201)
    validate_success(api.reject_disbursement(rej["id"], _SO))
    data, meta = validate_paginated(
        api.list_disbursements(_SO, params={"loan_id": loan["id"], "status": "REJECTED"}))
    assert len(data) == 1
    assert data[0]["id"] == rej["id"]
    assert data[0]["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# rbac / missing_user_context_header_returns_400
# ---------------------------------------------------------------------------
def test_missing_user_context_header_returns_400(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other
    processing."

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    validate_error(
        api.create_lender({"name": "NoCtx Servicer", "hud_lending_limit_cents": 80000000}, {}),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ---------------------------------------------------------------------------
# rbac / borrower_cannot_create_lender_returns_forbidden
# ---------------------------------------------------------------------------
def test_borrower_cannot_create_lender_returns_forbidden(api):
    """PRD §2.1: "Once the headers are validated, the system checks that the caller's role is
    permitted to invoke the requested endpoint; a recognized role attempting
    an operation outside its grant is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/borrower_cannot_create_lender_returns_forbidden
    """
    lender = setup_lender_with_plf()
    borrower = create_borrower(lender["id"])
    validate_error(
        api.create_lender({"name": "Sneaky Servicer", "hud_lending_limit_cents": 80000000},
                          make_borrower_headers(borrower["id"])),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ---------------------------------------------------------------------------
# rbac / servicerops_cannot_open_resolution_returns_forbidden
# ---------------------------------------------------------------------------
def test_servicerops_cannot_open_resolution_returns_forbidden(api):
    """PRD §4: the POST /resolutions endpoint is authorized for ComplianceOfficer only.
    PRD §2.1: "a recognized role attempting an operation outside its grant is rejected
    with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §3.11: "A due-and-payable loan is closed out through a resolution, opened by a
    `ComplianceOfficer`."

    Design: Corner/rbac/servicerops_cannot_open_resolution_returns_forbidden
    """
    lender, borrower, loan, event = setup_due_and_payable_loan(
        draw_type="LUMP_SUM", event_type="SALE_OF_PROPERTY")
    validate_error(
        api.create_resolution({"loan_id": loan["id"], "path": "PAYOFF"}, _SO),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    loan_after = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_after["disposition_status"] == "DUE_AND_PAYABLE"


# ---------------------------------------------------------------------------
# rbac / hudauditor_cannot_post_accrual_returns_forbidden
# ---------------------------------------------------------------------------
def test_hudauditor_cannot_post_accrual_returns_forbidden(api):
    """PRD §4: the POST /loans/{loanId}/post-accrual endpoint is authorized for
    ServicerOps and System only.
    PRD §2.1: "a recognized role attempting an operation outside its grant is rejected
    with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/hudauditor_cannot_post_accrual_returns_forbidden
    """
    lender, borrower, loan = setup_originated_loan(loan_overrides={"draw_type": "LUMP_SUM"})
    validate_error(
        api.post_accrual(loan["id"], {"number_of_months": 1}, _HUD),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
