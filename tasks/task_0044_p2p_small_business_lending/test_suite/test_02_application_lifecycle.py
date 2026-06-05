"""Application lifecycle: the SCORED -> {APPROVED, REJECTED} branch, the
segregation-of-duties / fundability precedence, and invalid transitions.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_application, create_scored_application,
    list_loans_for_application,
    UW_SCORER, UW_APPROVER, make_underwriter_headers,
    F_GRADE_PROFILE,
)


# =====================================================================
# Rule 3a — non-linear state machine: SCORED -> APPROVED vs SCORED -> REJECTED
# =====================================================================

def test_approve_scored_application_originates_loan(api):
    """PRD §3.3: "Approval advances the application from `SCORED` to `APPROVED`"
    PRD §3.3: "Approving an application originates a new `Loan`."

    Design: Difficulty/non_linear_state_machine/loan_application_branch_scored_to_approved_vs_rejected
    """
    borrower, scored = create_scored_application()  # A-grade
    resp = api.approve_application(scored["id"], UW_APPROVER)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"
    loans, _ = list_loans_for_application(scored["id"])
    assert len(loans) == 1, f"approval must originate exactly 1 Loan, got {len(loans)}"


def test_reject_scored_application_creates_no_loan(api):
    """PRD §3.3: "rejection advances it from `SCORED` to `REJECTED`"
    PRD §3.3: "Rejection, by contrast, creates no loan at all."

    Design: Difficulty/non_linear_state_machine/loan_application_branch_scored_to_approved_vs_rejected
    """
    # An F-grade application: rejection is its only forward move.
    borrower, scored = create_scored_application(plaid_profile=F_GRADE_PROFILE)
    assert scored["risk_grade"] == "F"
    resp = api.reject_application(scored["id"], UW_APPROVER)
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"
    loans, _ = list_loans_for_application(scored["id"])
    assert len(loans) == 0, f"rejection must create no Loan, got {len(loans)}"


# =====================================================================
# Rule 5a — priority pair: segregation (priority 5) vs grade (priority 6)
# =====================================================================

def test_approve_same_underwriter_f_grade_returns_segregation(api):
    """PRD §3.3: "The segregation-of-duties rule is checked first: the acting
    underwriter's `X-User-ID` must differ from the application's `scored_by_user_id`,
    so that the person who scored an application cannot also approve it; a violation
    is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.3: "The fundability rule is checked next: an application whose `risk_grade`
    is `F` may not be approved, and an attempt to do so is rejected with
    `ERR_GRADE_NOT_FUNDABLE`."

    Design: Difficulty/priority_pair_validation_conflict/approve_segregation_vs_grade_state_pair
    """
    # F-grade application scored by uw_scorer; the SAME underwriter attempts approve.
    borrower, scored = create_scored_application(plaid_profile=F_GRADE_PROFILE,
                                                 scorer_id="uw_scorer")
    assert scored["risk_grade"] == "F"
    resp = api.approve_application(scored["id"], make_underwriter_headers("uw_scorer"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


def test_approve_same_underwriter_a_grade_returns_segregation(api):
    """PRD §3.3: "The segregation-of-duties rule is checked first: the acting
    underwriter's `X-User-ID` must differ from the application's `scored_by_user_id`,
    so that the person who scored an application cannot also approve it; a violation
    is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/approve_segregation_vs_grade_state_pair
    """
    # A-grade (fundable) scored by uw_scorer; same underwriter approves -> only the
    # segregation rule can fire, isolating it from the grade rule.
    borrower, scored = create_scored_application(scorer_id="uw_scorer")
    assert scored["risk_grade"] == "A"
    resp = api.approve_application(scored["id"], make_underwriter_headers("uw_scorer"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


# =====================================================================
# Corner — errors: F-grade application cannot be approved (segregation satisfied)
# =====================================================================

def test_f_grade_application_cannot_be_approved_by_different_underwriter(api):
    """PRD §3.3: "an application whose `risk_grade` is `F` may not be approved, and
    an attempt to do so is rejected with `ERR_GRADE_NOT_FUNDABLE`."

    Design: Corner/errors/grade_f_application_cannot_be_approved
    """
    borrower, scored = create_scored_application(plaid_profile=F_GRADE_PROFILE,
                                                 scorer_id="uw_scorer")
    assert scored["risk_grade"] == "F"
    # Different underwriter approves -> segregation satisfied, grade rule fires.
    resp = api.approve_application(scored["id"], UW_APPROVER)
    validate_error(resp, ApiErrorId.ERR_GRADE_NOT_FUNDABLE.value, 422)


# =====================================================================
# Corner — state_machines: invalid transitions
# =====================================================================

def test_rescore_already_scored_application_invalid_state(api):
    """PRD §3.2: "a scoring attempt on an application that is not in `SUBMITTED` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/score_application_from_already_scored_returns_invalid_state
    """
    borrower, scored = create_scored_application()
    resp = api.score_application(scored["id"], UW_SCORER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_approve_rejected_application_invalid_state(api):
    """PRD §3.3: "both are valid only from `SCORED`, and an attempt from any other
    state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_terminal_rejected_application_returns_invalid_state
    """
    borrower, scored = create_scored_application()
    validate_success(api.reject_application(scored["id"], UW_APPROVER), 200)
    resp = api.approve_application(scored["id"], UW_APPROVER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
