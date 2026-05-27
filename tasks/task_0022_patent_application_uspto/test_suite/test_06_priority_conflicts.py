"""Validation-priority conflicts: when both a higher-priority and a
lower-priority rule are violated by the same request, PRD §2.7 names which
one short-circuits. State (ERR_INVALID_STATE) precedes fee-amount-exactness;
maintenance-window timeliness (ERR_MAINTENANCE_WINDOW_CLOSED) precedes
fee-amount-exactness.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock,
    setup_applicant_and_application, setup_utility_with_maintenance_fees,
    create_pay_issue_fee_payload, create_fee_payment_payload,
)


# =============================================================================
# Difficulty / priority_pair_validation_conflict /
#   state_vs_fiscal_pay_issue_fee_wrong_state_and_wrong_amount
# =============================================================================

def test_pay_issue_fee_on_filed_application_returns_invalid_state_not_fee_mismatch(api):
    """Pay-issue-fee against an Application in FILED carrying both a wrong
    state AND a wrong amount returns ERR_INVALID_STATE (state precedes
    fiscal in PRD §2.7's ordering), NOT ERR_FEE_AMOUNT_MISMATCH.

    PRD §2.7: "Only after these gates pass does the server evaluate
    state-machine admissibility (`ERR_INVALID_STATE` if the transition is
    not defined out of the current state, `ERR_TERMINAL_STATE` if the
    source state is in the entity's terminal set... followed by business
    rules in the order: continuation-relationship coherence, micro-entity
    eligibility, PCT 30-month timeliness, provisional-conversion 12-month
    timeliness, single-shot conversion, maintenance-fee window timeliness,
    fee-amount exactness, claim-count range, maintenance-window ordering,
    extension-month range, OCC version match, single-outstanding office
    action, and singleton PCT phase entry."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_pay_issue_fee_wrong_state_and_wrong_amount
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_applicant_and_application(
        entity_size="LARGE", application_type="UTILITY",
    )
    # Application is in FILED, not ALLOWED — and amount_cents is also wrong.
    res = api.pay_issue_fee(
        application["id"],
        create_pay_issue_fee_payload(amount_cents=99999,
                                     expected_application_version=application["version"]),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_issue_fee_on_awaiting_examination_returns_invalid_state(api):
    """Same priority rule, second state on the wrong side of the transition.
    Pay-issue-fee against an AWAITING_EXAMINATION Application is rejected
    with ERR_INVALID_STATE (the transition is defined only out of ALLOWED).

    PRD §2.7: "Only after these gates pass does the server evaluate
    state-machine admissibility (`ERR_INVALID_STATE` if the transition is
    not defined out of the current state..."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_pay_issue_fee_wrong_state_and_wrong_amount
    """
    set_clock("2026-01-01T00:00:00.000Z")
    from test_helpers import setup_application_in_awaiting_examination
    applicant, application = setup_application_in_awaiting_examination(
        entity_size="LARGE", application_type="UTILITY",
    )
    res = api.pay_issue_fee(
        application["id"],
        create_pay_issue_fee_payload(amount_cents=50,
                                     expected_application_version=application["version"]),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# Difficulty / priority_pair_validation_conflict /
#   temporal_vs_fiscal_maintenance_outside_window_and_wrong_amount
# =============================================================================

def test_pay_maintenance_before_window_open_returns_window_closed_not_fee_mismatch(api):
    """Paying W1 before window_open_date (so well outside the window) AND
    with amount_cents=0 must return ERR_MAINTENANCE_WINDOW_CLOSED — the
    maintenance-fee-window-timeliness validation precedes fee-amount-exactness
    per PRD §2.7's ordering.

    PRD §2.7: "...followed by business rules in the order: continuation-
    relationship coherence, micro-entity eligibility, PCT 30-month
    timeliness, provisional-conversion 12-month timeliness, single-shot
    conversion, maintenance-fee window timeliness, fee-amount exactness,
    claim-count range..."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_maintenance_outside_window_and_wrong_amount
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, fees = setup_utility_with_maintenance_fees(entity_size="LARGE")
    w1 = sorted(fees, key=lambda f: f["window_number"])[0]

    # Clock one day after issuance — well before W1 window_open (issue+3.5y).
    set_clock("2026-01-02T00:00:00.000Z")
    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W1",
            amount_cents=0,  # also wrong
            maintenance_fee_id=w1["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MAINTENANCE_WINDOW_CLOSED.value)


def test_pay_maintenance_after_grace_returns_window_closed_not_fee_mismatch(api):
    """Symmetric boundary: paying after the grace date (window also closed)
    with a wrong amount must surface ERR_MAINTENANCE_WINDOW_CLOSED rather
    than ERR_FEE_AMOUNT_MISMATCH.

    PRD §3.8: "a payment before the window opens or after the grace cutoff
    is rejected with `ERR_MAINTENANCE_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_maintenance_outside_window_and_wrong_amount
    """
    set_clock("2020-01-01T00:00:00.000Z")
    applicant, application, fees = setup_utility_with_maintenance_fees(entity_size="LARGE")
    w1 = sorted(fees, key=lambda f: f["window_number"])[0]

    # Far past W1 grace (issue + 4y + 6mo = 2024-07-01). 2099 is unambiguously past.
    set_clock("2099-01-01T00:00:00.000Z")
    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W1",
            amount_cents=1,
            maintenance_fee_id=w1["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MAINTENANCE_WINDOW_CLOSED.value)
