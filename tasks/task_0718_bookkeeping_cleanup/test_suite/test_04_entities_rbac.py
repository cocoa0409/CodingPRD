"""Entity creation defaults, validation, computed fields, listing, RBAC, and
segregation of duties.
"""
from prd_bench_local_runner.testing import (
    get_success_data, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
)
from test_helpers import (
    api_client, ApiErrorId,
    make_engagement_manager_headers,
    make_bookkeeper_headers,
    make_reviewer_headers,
)
from test_helpers import fixtures as fx

EM = make_engagement_manager_headers("em-1")
BK = make_bookkeeper_headers("bk-1")
RV = make_reviewer_headers("reviewer-1")


def test_create_engagement_returns_201_with_defaults(api):
    """PRD 3.1: "A fresh engagement starts with `workflow_status` of `DRAFT`, a parallel
    `billing_status` of `UNBILLED`, and `scope_locked` set to false." PRD 3.1: "The
    manager may also declare a `complexity_tier` of `LOW`, `MEDIUM`, or `HIGH`,
    defaulting to `MEDIUM`"

    Design: Corner/entities/create_engagement_returns_201_with_defaults
    """
    client = get_success_data(api.create_client(
        {"legal_name": "C1", "entity_type": "LLC", "accounting_basis": "ACCRUAL"}, EM))
    data = validate_success(api.create_engagement(
        {"client_id": client["id"], "title": "E1", "period_start": "2025-01-01",
         "period_end": "2025-06-30"}, EM), expected_status=201)
    assert data["workflow_status"] == "DRAFT"
    assert data["billing_status"] == "UNBILLED"
    assert data["scope_locked"] is False
    assert data["complexity_tier"] == "MEDIUM"
    assert data["version"] == 1


def test_get_engagement_not_found_returns_404(api):
    """PRD 2.5: "the system validates them strictly left to right and rejects the
    request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an
    existing resource."

    Design: Corner/entities/get_engagement_not_found_returns_404
    """
    validate_error(api.get_engagement(NON_EXISTENT_UUID, EM), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_engagement_missing_required_field(api):
    """PRD 2.6: "Request-body well-formedness — required fields present, enum values
    valid, and `amount_cents` and `weight_bp` strictly positive (`ERR_INVALID_REQUEST`)
    — is fifth." PRD 3.1: "the cleanup window as `period_start` and `period_end`"

    Design: Corner/entities/create_engagement_missing_required_field
    """
    client = get_success_data(api.create_client(
        {"legal_name": "C2", "entity_type": "LLC", "accounting_basis": "ACCRUAL"}, EM))
    validate_error(api.create_engagement(
        {"client_id": client["id"], "title": "E2", "period_end": "2025-06-30"}, EM),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_client_default_accounting_basis_accrual(api):
    """PRD 3.1: "optionally its `accounting_basis`, which is either `CASH` or `ACCRUAL`
    and defaults to `ACCRUAL` when omitted."

    Design: Corner/entities/client_default_accounting_basis_accrual
    """
    data = validate_success(api.create_client(
        {"legal_name": "DefCli", "entity_type": "SOLE_PROP"}, EM), expected_status=201)
    assert data["accounting_basis"] == "ACCRUAL"


def test_account_normal_side_computed_from_type(api):
    """PRD 3.3: "The system derives each account's `normal_side`: accounts of type
    `ASSET` or `EXPENSE` have a `DEBIT` normal side, and all other types have a `CREDIT`
    normal side."

    Design: Corner/entities/account_normal_side_computed_from_type
    """
    client = get_success_data(api.create_client(
        {"legal_name": "NS Co", "entity_type": "LLC", "accounting_basis": "ACCRUAL"}, EM))
    eng = get_success_data(api.create_engagement(
        {"client_id": client["id"], "title": "NS", "period_start": "2025-01-01",
         "period_end": "2025-06-30"}, EM))
    data = validate_success(api.create_account(
        eng["id"], {"account_code": "5000", "name": "Exp", "account_type": "EXPENSE"}, BK),
        expected_status=201)
    assert data["normal_side"] == "DEBIT"


def test_duplicate_account_code_rejected(api):
    """PRD 3.3: "The `account_code` must be unique within the engagement among accounts
    that are not `EXCLUDED`; a collision is rejected with `ERR_DUPLICATE_ACCOUNT_CODE`."

    Design: Corner/entities/duplicate_account_code_rejected
    """
    client = get_success_data(api.create_client(
        {"legal_name": "Dup Co", "entity_type": "LLC", "accounting_basis": "ACCRUAL"}, EM))
    eng = get_success_data(api.create_engagement(
        {"client_id": client["id"], "title": "Dup", "period_start": "2025-01-01",
         "period_end": "2025-06-30"}, EM))
    get_success_data(api.create_account(
        eng["id"], {"account_code": "1000", "name": "Cash", "account_type": "ASSET"}, BK))
    validate_error(api.create_account(
        eng["id"], {"account_code": "1000", "name": "Cash 2", "account_type": "ASSET"}, BK),
        ApiErrorId.ERR_DUPLICATE_ACCOUNT_CODE.value)


def test_list_engagements_pagination_envelope(api):
    """PRD 2.3: "Every list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the envelope's `meta` object."

    Design: Corner/entities/list_engagements_pagination_envelope
    """
    client = get_success_data(api.create_client(
        {"legal_name": "List Co", "entity_type": "LLC", "accounting_basis": "ACCRUAL"}, EM))
    get_success_data(api.create_engagement(
        {"client_id": client["id"], "title": "L", "period_start": "2025-01-01",
         "period_end": "2025-06-30"}, EM))
    data, meta = validate_paginated(api.list_engagements(EM, params={"client_id": client["id"]}))
    assert "total_count" in meta
    assert "has_more" in meta
    assert isinstance(data, list)


def test_missing_user_headers_rejected(api):
    """PRD 2.1: "Every request to the API must carry two mandatory headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in which they
    act. A request missing either header, or carrying a malformed value, is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_user_headers_rejected
    """
    client = get_success_data(api.create_client(
        {"legal_name": "Auth Co", "entity_type": "LLC", "accounting_basis": "ACCRUAL"}, EM))
    validate_error(api.get_client(client["id"], headers={}),
                   ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_bookkeeper_cannot_mark_reconciled(api):
    """PRD 2.1: "When a caller presents a recognized role that is nonetheless not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`." PRD 4: the mark-reconciled endpoint authorizes only
    `Reviewer`.

    Design: Corner/rbac/bookkeeper_cannot_mark_reconciled
    """
    eng, acct, entry = fx.setup_reconciliation_with_categorized_account()
    validate_error(api.mark_reconciled(eng["id"], acct["id"], BK),
                   ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_segregation_of_duties_same_user_blocked(api):
    """PRD 2.1: "the user who marks an account as reconciled must not be the same user
    (by `X-User-ID`) who categorized that account. A reviewer who attempts to sign off
    on an account they themselves categorized is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_same_user_blocked
    """
    shared_bk = make_bookkeeper_headers("user-shared")
    shared_rv = make_reviewer_headers("user-shared")
    eng = fx.setup_reconstruction_engagement()
    acct = get_success_data(api.create_account(
        eng["id"], {"account_code": "1000", "name": "Cash", "account_type": "ASSET"}, shared_bk))
    entry = get_success_data(api.create_entry(
        eng["id"], {"account_id": acct["id"], "txn_date": "2025-02-01",
                    "side": "DEBIT", "amount_cents": 1000}, shared_bk))
    get_success_data(api.post_entry(eng["id"], entry["id"], shared_bk))
    get_success_data(api.categorize_account(eng["id"], acct["id"], shared_bk))
    get_success_data(api.advance_to_reconciliation(eng["id"], EM))
    validate_error(api.mark_reconciled(eng["id"], acct["id"], shared_rv),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
