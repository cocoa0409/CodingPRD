"""Authentication, role authorization, participant ownership scoping,
not-found variants, and optimistic concurrency on case amendment."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    make_account,
    make_participant,
    make_participant_headers,
    make_plan,
    make_processor_headers,
    make_tax_officer_headers,
    validate_error,
    validate_success,
)

PROC1 = make_processor_headers("proc-1")
MISSING = NON_EXISTENT_UUID


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "All interactions with the API must be authenticated through a
    pair of mandatory HTTP headers. Each request must include `X-User-ID` to
    identify the acting user and `X-User-Role` to specify their operational
    capacity. The system recognizes five distinct roles: `Participant`,
    `PlanSponsorAdmin`, `RolloverProcessor`, `TaxReportingOfficer`, and
    `OperationsAgent`. A request missing either header, or presenting a role
    string outside this declared set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/case_list_missing_auth_headers_returns_401
    """
    resp = api.list_plans(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_not_found_variants_return_entity_specific_404(api):
    """PRD §2.9: "3. **Existence** — every path identifier and body reference
    must resolve, validated left-to-right as it appears in the URL hierarchy:
    plan first, then participant, account, case, and finally the leaf resource
    (document, verification, disbursement, redeposit, loan, or tax form). A
    request naming a non-existent parent is rejected with that parent's
    not-found error before the child is ever looked up: `ERR_PLAN_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_DOCUMENT_NOT_FOUND`, `ERR_VERIFICATION_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_REDEPOSIT_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, or `ERR_TAX_FORM_NOT_FOUND`."

    Design: Corner/entities/not_found_variants_return_404
    """
    foreign_participant = make_participant_headers("00000000-0000-4000-8000-000000000001")
    checks = [
        (api.get_plan(MISSING, PROC1), ApiErrorId.ERR_PLAN_NOT_FOUND),
        (api.get_account(MISSING, PROC1), ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
        (api.get_rollover_case(MISSING, PROC1), ApiErrorId.ERR_CASE_NOT_FOUND),
        (api.get_tax_form(MISSING, make_tax_officer_headers()), ApiErrorId.ERR_TAX_FORM_NOT_FOUND),
        (api.get_participant(MISSING, PROC1), ApiErrorId.ERR_PARTICIPANT_NOT_FOUND),
        (api.get_loan(MISSING, PROC1), ApiErrorId.ERR_LOAN_NOT_FOUND),
        (api.submit_document(MISSING, foreign_participant), ApiErrorId.ERR_DOCUMENT_NOT_FOUND),
        (api.issue_disbursement(MISSING, PROC1), ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND),
        (api.credit_redeposit(MISSING, PROC1), ApiErrorId.ERR_REDEPOSIT_NOT_FOUND),
        (api.complete_verification(MISSING, {"outcome": "VERIFIED"}, PROC1), ApiErrorId.ERR_VERIFICATION_NOT_FOUND),
    ]
    for resp, error_id in checks:
        validate_error(resp, error_id, expected_status=404)


def test_processor_cannot_set_clock_or_run_sweep(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the
    full role-to-endpoint mapping is given in §4."
    PRD §4: the logical-clock capability and the daily sweep endpoint are
    authorized for `OperationsAgent` only.

    Design: Corner/rbac/processor_cannot_set_clock
    """
    resp = api.set_clock("2026-06-01T00:00:00Z", make_processor_headers("proc-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    resp = api.run_daily_sweep(make_tax_officer_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_participant_cannot_read_others_case(api):
    """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id`
    of the acting `Participant` entity. Ownership checks on any resource that
    references a `Participant` compare the resource's foreign-key field to
    `X-User-ID`. A participant may only read or act on rollover cases, accounts,
    required documents, disbursements, redeposits, follow-up notices, loans, and
    tax forms whose owning account belongs to that participant; any attempt to
    reach another participant's resource is answered with `ERR_CASE_NOT_FOUND`
    or `ERR_ACCOUNT_NOT_FOUND` (HTTP 404) rather than an authorization error, so
    that the API never leaks whether the target exists at all."

    Design: Corner/rbac/participant_cannot_read_others_case
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    owner = make_participant()
    other = make_participant(
        full_name="Pat Two", date_of_birth="1965-03-10", separation_date="2026-03-01"
    )
    account = make_account(owner["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    resp = api.create_rollover_case(
        {"case_type": "DIRECT_ROLLOVER_OUT", "source_account_id": account["id"],
         "receiving_institution_name": "External IRA Trust"},
        make_participant_headers(owner["id"]),
    )
    case = validate_success(resp, expected_status=201)

    resp = api.get_rollover_case(case["id"], make_participant_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND, expected_status=404)

    owned = validate_success(api.get_rollover_case(case["id"], make_participant_headers(owner["id"])))
    assert owned["id"] == case["id"], "the owner reads the case normally"


def test_occ_case_amend_stale_version(api):
    """PRD §2.8: "**Amending a DRAFT rollover case.** A case-amendment request
    must carry `expected_rollover_case_version` matching the case's current
    `version`. If another writer has amended the case since the client last read
    it — each successful amendment legitimately replaces the prior election set
    and advances the version by 1 — the stale amendment is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.3: "While a case is `DRAFT`, the participant may amend its elections
    — `requested_amount_cents`, `receiving_plan_id`,
    `receiving_institution_name`, and `withholding_acknowledged` — subject to
    the optimistic-concurrency check of §2.8; each successful amendment advances
    the case's `version` by 1 and wholly replaces the prior election set."

    Design: Corner/complexity_layers/occ_case_amend_stale_version
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    p_headers = make_participant_headers(participant["id"])
    resp = api.create_rollover_case(
        {"case_type": "INDIRECT_ROLLOVER_OUT", "source_account_id": account["id"],
         "receiving_institution_name": "External IRA Trust", "withholding_acknowledged": True},
        p_headers,
    )
    case = validate_success(resp, expected_status=201)
    v1 = case["version"]
    assert v1 == 1

    amended = validate_success(api.amend_rollover_case(
        case["id"], {"expected_rollover_case_version": v1, "requested_amount_cents": 250000},
        p_headers,
    ))
    assert amended["version"] == 2, f"first amendment advances version 1 -> 2, got {amended['version']}"

    resp = api.amend_rollover_case(
        case["id"], {"expected_rollover_case_version": v1, "requested_amount_cents": 300000},
        p_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    amended2 = validate_success(api.amend_rollover_case(
        case["id"], {"expected_rollover_case_version": 2, "requested_amount_cents": 300000},
        p_headers,
    ))
    assert amended2["version"] == 3, f"fresh amendment advances version 2 -> 3, got {amended2['version']}"
    assert amended2["requested_amount_cents"] == 300000
