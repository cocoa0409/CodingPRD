"""Validation ordering, RBAC violations, SoD vs OCC priority, state vs
fiscal priority, auth / authentication, ownership.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_payment_payload, create_loan_payload,
    create_servicing_event_payload,
    advance_clock_payload, approve_discharge_payload,
    TEST_USERS,
    advance_clock, create_borrower, create_loan, fire_servicing_event,
    get_loan_version, get_loan,
    create_loan_in_repayment,
    attach_standard_10yr_plan,
    setup_loan_paid_off,
    setup_pslf_sod_violation_scenario,
    make_borrower_headers, make_pslf_adjudicator_headers,
)


# ─── Auth header missing → ERR_UNAUTHENTICATED ──────


def test_missing_x_user_role_header_returns_unauthenticated(api):
    """PRD §2.1: "Both headers are required on every endpoint except for
    `POST /v1/borrowers`, which the servicing operation may invoke without
    prior authentication context. A request that omits either header is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated
    """
    res = api.get(
        "/v1/loans",
        headers={"Content-Type": "application/json"},  # neither X-User-ID nor X-User-Role
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Borrower ownership check ───────────────────────


def test_borrower_reading_other_borrowers_loan_returns_not_resource_owner(
    api, servicer_headers,
):
    """PRD §2.1: "When `X-User-Role` is `Borrower`, `X-User-ID` is the `id`
    of the acting `Borrower` entity. Ownership checks compare `X-User-ID`
    to the `borrower_id` carried (directly or transitively through a
    `Loan`) by any resource the Borrower attempts to read or write. A
    Borrower acting on a resource whose `borrower_id` does not match
    `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/borrower_listing_other_borrowers_returns_not_resource_owner
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower_a = create_borrower(email="owner-a@example.com")
    borrower_b = create_borrower(email="other-b@example.com")
    loan_a = create_loan(
        borrower_a["id"],
        loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=100_000, interest_rate_bps=0,
        disbursement_date="2026-06-01",
    )

    headers_b = make_borrower_headers(borrower_b["id"])
    res = api.get_loan(loan_a["id"], headers_b)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


# ─── Validation priority: existence before state ────


def test_validation_existence_check_runs_before_state_check(api, servicer_headers):
    """PRD §2.9: "Existence of every entity referenced by the URL path or
    request body is then verified, with `ERR_NOT_FOUND`, and path
    identifiers are validated left-to-right (a non-existent `borrower_id`
    in the path is reported before a non-existent `loan_id` further down,
    and parent path identifiers are checked before any body reference).
    State preconditions for the requested action come next, with
    `ERR_INVALID_STATE`..."

    DEFERMENT_END against a non-existent loan would simultaneously fail
    existence (404) and state (loan doesn't exist so its state can't be
    DEFERMENT, but that's a degenerate state check). PRD pins existence
    first → ERR_NOT_FOUND wins.

    Design: Corner/validations/validation_priority_existence_before_state
    """
    advance_clock("2026-06-01T00:00:00Z")
    res = api.create_servicing_event(
        "00000000-0000-0000-0000-000000000000",
        create_servicing_event_payload(
            "DEFERMENT_END", "2026-06-01", "OTHER",
        ),
        servicer_headers,
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Difficulty Rule 5a: state vs business_fiscal ──


def test_payment_on_paid_off_loan_with_overpay_returns_invalid_state(
    api, servicer_headers,
):
    """PRD §3.4: "Posting is permitted only when the parent loan is in
    `GRACE`, `REPAYMENT`, `DEFERMENT`, `FORBEARANCE`, `DELINQUENT`, or
    `DEFAULT`; an attempt against a `PAID_OFF` or `DISCHARGED` loan is
    rejected with `ERR_INVALID_STATE`."
    PRD §2.9: "State preconditions for the requested action come next,
    with `ERR_INVALID_STATE` for in-entity violations and a small family
    of cross-entity state errors (`ERR_BORROWER_DISCHARGED` for payment
    attempts on a fully-discharged borrower, `ERR_NOT_VETERAN` for VA
    discharge requests on a non-veteran borrower) following immediately.
    Field-shape and business-constraint checks (`ERR_PLAN_FIELDS_INVALID`,
    `ERR_PAYMENT_DATE_OUT_OF_WINDOW`, `ERR_PAYMENT_EXCEEDS_BALANCE`,
    `ERR_CERTIFICATION_FIELDS_INVALID`, `ERR_VA_DOC_REQUIRED_OR_FORBIDDEN`,
    `ERR_DEFAULT_THRESHOLD_NOT_MET`, `ERR_EMAIL_DUPLICATE`) are evaluated
    after state."

    A payment attempt against a PAID_OFF loan with amount_cents >> 0
    triggers BOTH the PAID_OFF state precondition and the
    exceeds-balance check. Per §2.9 the state error wins.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_payment_overpay_on_paidoff_loan
    """
    _, paid_off = setup_loan_paid_off(
        clock_set_to="2026-06-01T00:00:00Z",
        disbursement_date="2025-12-01",
        grace_begin_on="2025-12-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=100_000,
        interest_rate_bps=0,
        payment_posted_on="2026-06-01",
    )
    assert paid_off["status"] == "PAID_OFF"
    advance_clock("2026-06-15T00:00:00Z")
    res = api.create_payment(
        create_payment_payload(paid_off["id"], 999_999_999, "2026-06-15", "ACH"),
        servicer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_payment_on_paid_off_loan_returns_invalid_state_not_exceeds_balance(
    api, servicer_headers,
):
    """PRD §3.4: "an attempt against a `PAID_OFF` or `DISCHARGED` loan is
    rejected with `ERR_INVALID_STATE`."
    PRD §2.9: "Field-shape and business-constraint checks
    (`ERR_PLAN_FIELDS_INVALID`, `ERR_PAYMENT_DATE_OUT_OF_WINDOW`,
    `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_CERTIFICATION_FIELDS_INVALID`,
    `ERR_VA_DOC_REQUIRED_OR_FORBIDDEN`, `ERR_DEFAULT_THRESHOLD_NOT_MET`,
    `ERR_EMAIL_DUPLICATE`) are evaluated after state."

    Confirms the exact error_id returned is the state error, not the
    fiscal one — the two errors are mutually exclusive (different code
    families) and PRD pins the order.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_payment_overpay_on_paidoff_loan
    """
    _, paid_off = setup_loan_paid_off(
        clock_set_to="2026-06-01T00:00:00Z",
        disbursement_date="2025-12-01",
        grace_begin_on="2025-12-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=100_000,
        interest_rate_bps=0,
        payment_posted_on="2026-06-01",
    )
    advance_clock("2026-06-15T00:00:00Z")
    res = api.create_payment(
        create_payment_payload(paid_off["id"], 999_999_999, "2026-06-15", "ACH"),
        servicer_headers,
    )
    body = res.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"Expected ERR_INVALID_STATE per §2.9 (state before fiscal), got {body['data']['error_id']}"
    )
    assert body["data"]["error_id"] != "ERR_PAYMENT_EXCEEDS_BALANCE"


# ─── Difficulty Rule 5b: SoD vs OCC ─────────────────


def test_pslf_approve_sod_violation_wins_over_stale_version(api, servicer_headers):
    """PRD §2.9: "Only after authentication and authorization does the
    PSLF-specific segregation-of-duties check fire on discharge approval
    with `ERR_SOD_VIOLATION`."
    PRD §2.9: "Finally, the optimistic-concurrency check is the last gate
    before the write commits: a mismatched `expected_loan_version` (or
    any mismatched entry in `expected_loan_version_by_loan_id`) raises
    `ERR_STALE_VERSION` only after every prior check has passed."
    PRD §2.6: "If the adjudicator has ever recorded one of the
    contributing payments, the approval is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403). The check considers all loans of the
    borrower together — recording a single qualifying payment on any one
    of the borrower's loans disqualifies the adjudicator from approving
    that borrower's PSLF discharge."

    A PSLF approve request that simultaneously violates SoD (acting
    X-User-ID recorded a contributing payment) and OCC (the loan version
    advanced after the client's snapshot) must return ERR_SOD_VIOLATION
    (priority 12) — not ERR_STALE_VERSION (priority 40).

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_state_pslf_approval_sod_vs_stale_version
    """
    borrower, loan_latest, payment, tracker, app = (
        setup_pslf_sod_violation_scenario(
            shared_user_id="svc-shared",
            clean_adjudicator_user_id="adj-clean-1",
        )
    )
    # Read the loan version BEFORE another mutation makes it stale.
    h_shared = TEST_USERS["servicer_headers"]
    pre_stale_v = get_loan_version(loan_latest["id"])
    # Mutate the loan (FORBEARANCE_BEGIN under the shared servicer id) to
    # advance the loan version, making pre_stale_v stale.
    from test_helpers import make_servicer_headers
    h_actor = make_servicer_headers("svc-shared")
    fire_servicing_event(
        loan_latest["id"], "FORBEARANCE_BEGIN", "2027-01-15", "ADMIN_FORBEARANCE",
        headers=h_actor,
    )
    # Approve under the SAME shared X-User-ID acting as PSLFAdjudicator,
    # with the stale loan version → BOTH SoD violation AND OCC stale.
    res = api.approve_discharge_application(
        app["id"],
        approve_discharge_payload({loan_latest["id"]: pre_stale_v}),
        make_pslf_adjudicator_headers("svc-shared"),
    )
    validate_error(res, "ERR_SOD_VIOLATION", expected_status=403)


def test_pslf_approve_sod_violation_leaves_application_under_review(
    api, servicer_headers,
):
    """PRD §3.7: "The approve path is the system's most consequential
    transition and carries the heaviest set of preconditions. The
    application must be `UNDER_REVIEW`."
    PRD §2.6: "When a `PSLFAdjudicator` approves a `DischargeApplication`
    whose `discharge_type` is `PSLF_FORGIVENESS`, the server verifies that
    the adjudicator's own `X-User-ID` does not appear in
    `recorded_by_user_id` on any `Payment` that contributed to the
    borrower's `qualifying_payment_count`. If the adjudicator has ever
    recorded one of the contributing payments, the approval is rejected
    with `ERR_SOD_VIOLATION` (HTTP 403)."

    A rejected approve does not transition the application — its status
    remains UNDER_REVIEW.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_state_pslf_approval_sod_vs_stale_version
    """
    borrower, loan_latest, payment, tracker, app = (
        setup_pslf_sod_violation_scenario(
            shared_user_id="svc-shared",
            clean_adjudicator_user_id="adj-clean-2",
        )
    )
    pre_stale_v = get_loan_version(loan_latest["id"])
    from test_helpers import make_servicer_headers
    fire_servicing_event(
        loan_latest["id"], "FORBEARANCE_BEGIN", "2027-01-15", "ADMIN_FORBEARANCE",
        headers=make_servicer_headers("svc-shared"),
    )
    res = api.approve_discharge_application(
        app["id"],
        approve_discharge_payload({loan_latest["id"]: pre_stale_v}),
        make_pslf_adjudicator_headers("svc-shared"),
    )
    validate_error(res, "ERR_SOD_VIOLATION", expected_status=403)
    app_after = validate_success(api.get_discharge_application(
        app["id"], TEST_USERS["servicer_headers"],
    ), 200)
    assert app_after["status"] == "UNDER_REVIEW"


# ─── Difficulty Rule 8b: FORBEARANCE while in FORBEARANCE ──


def test_forbearance_begin_on_loan_in_forbearance_returns_invalid_state(
    api, servicer_headers,
):
    """PRD §3.2: "Forbearance follows a parallel structure: `FORBEARANCE_BEGIN`
    is accepted from either `REPAYMENT` or `DELINQUENT` with reason among
    `ECONOMIC_HARDSHIP`, `NATURAL_DISASTER`, `ADMIN_FORBEARANCE`, or
    `MEDICAL`."
    PRD §2.9: "State preconditions for the requested action come next,
    with `ERR_INVALID_STATE`..."

    A second FORBEARANCE_BEGIN on a loan already in FORBEARANCE fails
    the §3.2 from-state precondition → ERR_INVALID_STATE.

    Design: Difficulty/resource_temporal_overlap/forbearance_overlapping_active_window_collides_on_loan_status
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    attach_standard_10yr_plan(loan["id"])
    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP")
    loan_now = get_loan(loan["id"])
    assert loan_now["status"] == "FORBEARANCE"

    res = api.create_servicing_event(
        loan["id"],
        create_servicing_event_payload(
            "FORBEARANCE_BEGIN", "2026-06-15", "ECONOMIC_HARDSHIP",
        ),
        servicer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_forbearance_begin_on_loan_in_forbearance_leaves_status_unchanged(
    api, servicer_headers,
):
    """PRD §3.2: "Forbearance follows a parallel structure: `FORBEARANCE_BEGIN`
    is accepted from either `REPAYMENT` or `DELINQUENT` with reason among
    `ECONOMIC_HARDSHIP`, `NATURAL_DISASTER`, `ADMIN_FORBEARANCE`, or
    `MEDICAL`."

    The rejected second FORBEARANCE_BEGIN must not have transitioned the
    loan in any way — it is still in FORBEARANCE with the same status.

    Design: Difficulty/resource_temporal_overlap/forbearance_overlapping_active_window_collides_on_loan_status
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    attach_standard_10yr_plan(loan["id"])
    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP")
    api.create_servicing_event(
        loan["id"],
        create_servicing_event_payload(
            "FORBEARANCE_BEGIN", "2026-06-15", "ECONOMIC_HARDSHIP",
        ),
        servicer_headers,
    )
    loan_after = get_loan(loan["id"])
    assert loan_after["status"] == "FORBEARANCE"


# ─── ERR_FORBIDDEN_ROLE (corner) ────────────────────


def test_pslf_adjudicator_cannot_post_payment_returns_forbidden_role(
    api, pslf_adjudicator_headers,
):
    """PRD §2.1: "A request whose role is recognized but is not permitted
    to invoke the targeted endpoint per the RBAC mapping in §4 is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 (RBAC table for POST /v1/payments): only LoanServicer is
    authorized.

    Design: Corner/errors/error_forbidden_role_pslf_adjudicator_cannot_post_payment
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        original_principal_cents=100_000, interest_rate_bps=0,
    )
    attach_standard_10yr_plan(loan["id"])
    res = api.create_payment(
        create_payment_payload(loan["id"], 1_000, "2026-06-01", "ACH"),
        pslf_adjudicator_headers,
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_borrower_cannot_post_payment_returns_forbidden_role(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted
    to invoke the targeted endpoint per the RBAC mapping in §4 is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 (RBAC table for POST /v1/payments): only LoanServicer is
    authorized.

    Design: Corner/roles/borrower_cannot_post_payment
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower, loan = create_loan_in_repayment(
        borrower_overrides={"email": "self-paying@example.com"},
        original_principal_cents=100_000, interest_rate_bps=0,
    )
    attach_standard_10yr_plan(loan["id"])
    own_headers = make_borrower_headers(borrower["id"])
    res = api.create_payment(
        create_payment_payload(loan["id"], 1_000, "2026-06-01", "ACH"),
        own_headers,
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Invalid clock advance (corner) ─────────────────


def test_clock_advance_to_past_returns_invalid_clock(api, servicer_headers):
    """PRD §3.5: "A `LoanServicer` advances the clock by submitting a target
    instant `to_iso8601` to the clock-advance capability; the target must
    be strictly greater than the current clock, or the request is
    rejected with `ERR_INVALID_CLOCK`."

    Design: Corner/validations/invalid_clock_advance_to_past_returns_invalid
    """
    advance_clock("2026-06-01T00:00:00Z")
    res = api.advance_clock(advance_clock_payload("2026-05-15T00:00:00Z"),
                              servicer_headers)
    validate_error(res, "ERR_INVALID_CLOCK", expected_status=422)
