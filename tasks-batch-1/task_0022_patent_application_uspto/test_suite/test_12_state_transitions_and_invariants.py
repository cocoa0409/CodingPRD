"""Invalid state transitions, terminal-state lockdown, micro-eligibility
gating, ledger conservation across the FILING+ISSUE chain, and OA row-count
conservation across the NOA-supersede cascade.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock, run_sweep,
    create_applicant, create_application, get_application,
    setup_applicant_and_application,
    setup_application_in_awaiting_examination,
    setup_application_with_outstanding_oa,
    setup_application_in_allowed,
    setup_multi_oa_cycle,
    pay_filing_fee, docket_application, issue_office_action,
    pay_issue_fee, file_oa_response,
    create_applicant_payload, create_pay_issue_fee_payload,
    issue_fee_cents,
)

ADMIN = TEST_USERS["admin_headers"]


# =============================================================================
# Corner / state_machines / docket_application_already_awaiting_returns_invalid_state
# =============================================================================

def test_docket_already_awaiting_application_returns_invalid_state(api, examiner_headers):
    """Calling docket on an already-AWAITING_EXAMINATION application is
    rejected with ERR_INVALID_STATE.

    PRD §2.7: "Only after these gates pass does the server evaluate
    state-machine admissibility (`ERR_INVALID_STATE` if the transition is
    not defined out of the current state..."
    PRD §3.4: "Once an application's accumulated `total_fees_paid_cents` is
    at least the expected filing fee for its type-and-size, an examiner can
    docket it, transitioning the application from `FILED` to
    `AWAITING_EXAMINATION`."

    Design: Corner/state_machines/docket_application_already_awaiting_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_application_in_awaiting_examination(
        entity_size="LARGE", application_type="UTILITY",
    )
    res = api.docket_application(application["id"], examiner_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# Corner / state_machines / docket_filed_without_filing_fee_returns_invalid_state
# =============================================================================

def test_docket_filed_application_without_filing_fee_rejected(api, examiner_headers):
    """Calling docket on a FILED application that has not posted its FILING
    fee is rejected — the FILED→AWAITING_EXAMINATION precondition requires
    total_fees_paid_cents ≥ expected filing fee.

    PRD §3.4: "Once an application's accumulated `total_fees_paid_cents` is
    at least the expected filing fee for its type-and-size, an examiner can
    docket it, transitioning the application from `FILED` to
    `AWAITING_EXAMINATION`."

    Design: Corner/state_machines/docket_filed_without_filing_fee_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_applicant_and_application(
        entity_size="LARGE", application_type="UTILITY",
    )
    # No FILING fee posted yet.
    res = api.docket_application(application["id"], examiner_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# Corner / state_machines / response_after_maximum_due_date_rejected_late
# =============================================================================

def test_response_after_maximum_due_date_rejected(api):
    """A response filed when current_utc > OfficeAction.maximum_due_date
    violates the response-timeliness precondition.

    PRD §3.5: "Specifically, the response is timely only when the server's
    current UTC instant — recorded into the response as `response_filed_at`
    — is on or before the office action's `shortened_due_date` advanced by
    `extension_months_requested` months, AND that advanced datetime is
    itself on or before the office action's `maximum_due_date`."

    Design: Corner/state_machines/response_after_maximum_due_date_rejected_late
    """
    from test_helpers import create_office_action_response_payload
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    # max_due = issue_date + 6mo = 2026-07-01. Advance to 2026-08-01 (past max).
    set_clock("2026-08-01T00:00:00.000Z")
    res = api.create_office_action_response(
        create_office_action_response_payload(
            office_action_id=oa["id"],
            extension_months_requested=3, claim_amendment_count=10,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# Corner / state_machines / pay_issue_fee_on_abandoned_application_terminal_state
# =============================================================================

def test_pay_issue_fee_on_abandoned_application_returns_invalid_state(api):
    """Pay-issue-fee on an ABANDONED Application is rejected — ABANDONED is
    a terminal state from which no transition is permitted.

    PRD §2.7: "...`ERR_TERMINAL_STATE` if the source state is in the
    entity's terminal set — namely `ABANDONED`, `EXPIRED`, `CONVERTED` for
    an application, `RESPONDED`, `EXPIRED`, `WITHDRAWN` for an office
    action, and `PAID`, `LAPSED` for a maintenance fee, with the single
    exception that an `ISSUED` application is permitted to transition to
    `EXPIRED` via maintenance-fee lapse..."

    Design: Corner/state_machines/pay_issue_fee_on_abandoned_application_terminal_state
    """
    from prd_bench_local_runner.testing import validate_error_is_one_of
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    set_clock("2026-08-01T00:00:00.000Z")
    run_sweep()
    app_after = get_application(application["id"], applicant)
    assert app_after["status"] == "ABANDONED"

    res = api.pay_issue_fee(
        application["id"],
        create_pay_issue_fee_payload(
            amount_cents=120000,
            expected_application_version=app_after["version"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_INVALID_STATE.value,
        ApiErrorId.ERR_TERMINAL_STATE.value,
    ])

    # Application status must remain ABANDONED.
    after = get_application(application["id"], applicant)
    assert after["status"] == "ABANDONED"


# =============================================================================
# Corner / validations / micro_ineligible_high_income_rejected
# =============================================================================

def test_create_micro_applicant_with_high_income_rejected(api, admin_headers):
    """Creating a MICRO applicant with gross_income_prior_year_cents above
    24,600,000 returns ERR_MICRO_INELIGIBLE.

    PRD §3.1: "A micro-entity applicant is accepted only when the
    micro-entity eligibility predicate holds at applicant-creation time:
    `gross_income_prior_year_cents` must be present, must not exceed
    `MICRO_INCOME_CEILING_CENTS` of 24,600,000 cents (the illustrative
    $246,000 ceiling), `prior_applications_filed` must not exceed
    `MICRO_PRIOR_APPS_CEILING` of 4, and `micro_qualifying_year` must be
    present. If any of those four conditions fails, the create is rejected
    with `ERR_MICRO_INELIGIBLE`."

    Design: Corner/validations/micro_ineligible_high_income_rejected
    """
    set_clock("2026-01-01T00:00:00.000Z")
    res = api.create_applicant(
        create_applicant_payload(
            legal_name="HighInc Co", entity_size="MICRO",
            prior_applications_filed=0, micro_qualifying_year=2025,
            gross_income_prior_year_cents=30000000,  # > 24,600,000 ceiling
        ),
        admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_MICRO_INELIGIBLE.value)


# =============================================================================
# Corner / validations / micro_ineligible_too_many_prior_apps_rejected
# =============================================================================

def test_create_micro_applicant_with_too_many_prior_apps_rejected(api, admin_headers):
    """Creating a MICRO applicant with prior_applications_filed > 4 returns
    ERR_MICRO_INELIGIBLE.

    PRD §3.1: "A micro-entity applicant is accepted only when the
    micro-entity eligibility predicate holds at applicant-creation time:
    `gross_income_prior_year_cents` must be present, must not exceed
    `MICRO_INCOME_CEILING_CENTS` of 24,600,000 cents (the illustrative
    $246,000 ceiling), `prior_applications_filed` must not exceed
    `MICRO_PRIOR_APPS_CEILING` of 4, and `micro_qualifying_year` must be
    present. If any of those four conditions fails, the create is rejected
    with `ERR_MICRO_INELIGIBLE`."

    Design: Corner/validations/micro_ineligible_too_many_prior_apps_rejected
    """
    set_clock("2026-01-01T00:00:00.000Z")
    res = api.create_applicant(
        create_applicant_payload(
            legal_name="ManyApps Co", entity_size="MICRO",
            prior_applications_filed=5,  # > 4 ceiling
            micro_qualifying_year=2025,
            gross_income_prior_year_cents=5000000,
        ),
        admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_MICRO_INELIGIBLE.value)


# =============================================================================
# Difficulty / compensating_invariant / ledger_conservation_total_fees_equals_sum_of_payments
# =============================================================================

def test_total_fees_paid_equals_sum_of_payments_after_filing_and_issue(api):
    """After FILING (SMALL UTILITY 16000) + ISSUE (60000) = 76000 cents,
    Application.total_fees_paid_cents == 76000 AND the sum of POSTED
    FeePayments for the application also equals 76000.

    PRD §3.3: "On every successful fee payment, a new `FeePayment` row is
    created with `payment_status` set to `POSTED`, the payment is appended
    to the application's ledger, and `Application.total_fees_paid_cents` is
    recomputed as the sum of `amount_cents` across all `POSTED` payments
    for that application; `Application.version` bumps and `updated_at` is
    refreshed."

    Design: Difficulty/compensating_invariant/ledger_conservation_total_fees_equals_sum_of_payments
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_application_in_allowed(
        entity_size="SMALL", application_type="UTILITY",
    )
    issued = pay_issue_fee(applicant, application)
    assert issued["total_fees_paid_cents"] == 76000

    list_res = api.list_fee_payments(
        make_applicant_headers(applicant["id"]),
        params={"application_id": issued["id"]},
    )
    payments = validate_success(list_res, 200)
    sum_payments = sum(p["amount_cents"] for p in payments)
    assert sum_payments == 76000, (
        f"Sum of payments must equal 76000, got {sum_payments}"
    )
    assert issued["total_fees_paid_cents"] == sum_payments, (
        f"total_fees_paid_cents ({issued['total_fees_paid_cents']}) must equal "
        f"sum of POSTED payments ({sum_payments})"
    )


def test_total_fees_paid_recomputed_on_every_payment(api):
    """The ledger-conservation invariant must hold INCREMENTALLY: after the
    FILING payment alone, total_fees_paid_cents == 16000; after the ISSUE
    payment, total_fees_paid_cents == 76000.

    PRD §3.3: "On every successful fee payment, a new `FeePayment` row is
    created with `payment_status` set to `POSTED`, the payment is appended
    to the application's ledger, and `Application.total_fees_paid_cents` is
    recomputed as the sum of `amount_cents` across all `POSTED` payments
    for that application; `Application.version` bumps and `updated_at` is
    refreshed."

    Design: Difficulty/compensating_invariant/ledger_conservation_total_fees_equals_sum_of_payments
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_applicant_and_application(
        entity_size="SMALL", application_type="UTILITY",
    )
    assert application["total_fees_paid_cents"] == 0

    pay_filing_fee(applicant, application)
    app_after_filing = get_application(application["id"], applicant)
    assert app_after_filing["total_fees_paid_cents"] == 16000

    docket_application(application["id"])
    issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")
    issued = pay_issue_fee(applicant, app_after_filing)

    assert issued["total_fees_paid_cents"] == 76000


# =============================================================================
# Difficulty / compensating_invariant / oa_population_conservation_outstanding_plus_withdrawn_equals_initial
# =============================================================================

def test_oa_row_count_strictly_increases_on_noa_never_deletes(api, examiner_headers):
    """OA rows are never deleted. Across the NOA-supersede cascade: before
    NOA, count(OAs) = 3 (two RESPONDED + one OUTSTANDING); after NOA, count
    = 4 — the two RESPONDED remain RESPONDED, the previously-OUTSTANDING
    is WITHDRAWN, and the NOA itself is the OUTSTANDING fourth row.

    PRD §3.6: "A notice of allowance issued while the application is in
    `OFFICE_ACTION_OUTSTANDING` advances the application to `ALLOWED` and
    additionally sets every other `OUTSTANDING` office action on the same
    application to `WITHDRAWN` as a side effect, bumping the version of
    each office action that was withdrawn (excluding the notice itself,
    which remains the active allowance)."

    Design: Difficulty/compensating_invariant/oa_population_conservation_outstanding_plus_withdrawn_equals_initial
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, responded_oas, outstanding_oa = setup_multi_oa_cycle(
        num_responded=2, final_outstanding=True, entity_size="LARGE",
    )
    pre_count = len(responded_oas) + (1 if outstanding_oa else 0)
    assert pre_count == 3

    noa = issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")

    list_res = api.list_office_actions(
        examiner_headers, params={"application_id": application["id"]},
    )
    oas_after = validate_success(list_res, 200)
    assert len(oas_after) == 4, (
        f"Expected 4 OA rows after NOA cascade (3 pre + 1 NOA), got {len(oas_after)}"
    )

    by_id = {oa["id"]: oa for oa in oas_after}
    for r in responded_oas:
        assert by_id[r["id"]]["status"] == "RESPONDED"
    assert by_id[outstanding_oa["id"]]["status"] == "WITHDRAWN"
    assert by_id[noa["id"]]["status"] == "OUTSTANDING"


def test_application_status_allowed_after_noa_supersede_cascade(api):
    """The same cascade leaves Application in ALLOWED.

    PRD §3.6: "A notice of allowance issued while the application is in
    `OFFICE_ACTION_OUTSTANDING` advances the application to `ALLOWED` and
    additionally sets every other `OUTSTANDING` office action on the same
    application to `WITHDRAWN` as a side effect, bumping the version of
    each office action that was withdrawn (excluding the notice itself,
    which remains the active allowance)."

    Design: Difficulty/compensating_invariant/oa_population_conservation_outstanding_plus_withdrawn_equals_initial
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, responded_oas, outstanding_oa = setup_multi_oa_cycle(
        num_responded=2, final_outstanding=True, entity_size="LARGE",
    )
    issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")
    app_after = get_application(application["id"], applicant)
    assert app_after["status"] == "ALLOWED"


# =============================================================================
# Corner / endpoints / list_applications_pagination_default_limit
# =============================================================================

def test_list_applications_returns_array_envelope_with_meta(api, admin_headers):
    """GET /applications returns paginated array envelope with all created
    applications.

    PRD §2.3: "List endpoints accept two query parameters: `limit` and
    `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and
    a maximum of 100; the `offset` parameter defaults to 0 and must be
    non-negative. All list responses are sorted by `created_at` in
    ascending order. The `meta` block of every list response surfaces
    `limit`, `offset`, `total_count` (the number of records matching the
    filter before pagination), and `has_more` (true when more records
    exist beyond the current page)."

    Design: Corner/endpoints/list_applications_pagination_default_limit
    """
    from prd_bench_local_runner.testing import validate_paginated
    set_clock("2026-01-01T00:00:00.000Z")
    applicant = create_applicant(legal_name="Pag Co", entity_size="LARGE")
    create_application(applicant, application_type="UTILITY",
                       title="App1", claim_count=5, independent_claim_count=1)
    create_application(applicant, application_type="DESIGN",
                       title="App2", claim_count=5, independent_claim_count=1)
    create_application(applicant, application_type="PROVISIONAL",
                       title="App3", claim_count=5, independent_claim_count=1)

    res = api.list_applications(admin_headers,
                                params={"applicant_id": applicant["id"]})
    data, meta = validate_paginated(res)
    assert len(data) == 3
    assert meta["total_count"] == 3
