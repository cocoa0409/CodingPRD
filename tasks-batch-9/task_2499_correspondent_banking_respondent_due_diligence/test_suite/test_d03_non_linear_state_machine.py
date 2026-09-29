"""Difficulty queue - rule non_linear_state_machine.

Two cycles that are not the identity map: the respondent's dd_state round trip that
leaves the parallel payment_posture dimension behind, and the questionnaire
clarification loop whose trip count is bounded by a monotonic counter.
"""
from test_helpers import (
    ApiErrorId,
    add_control_rows,
    add_verified_owner,
    assert_instant_equals,
    get_success_data,
    licensed_respondent,
    lift,
    new_jurisdiction,
    open_questionnaire,
    overlay_row,
    read_respondent,
    restrict,
    score_respondent,
    submit_questionnaire,
    validate_error,
    validate_success,
    committee_decision,
)
from test_helpers.fixtures import ANALYST, OFFICER, RM, assess_questionnaire, return_questionnaire


DOMAINS = [
    "GOVERNANCE", "KYC_ONBOARDING", "TRANSACTION_MONITORING", "SANCTIONS_SCREENING",
    "PEP_HANDLING", "TRAINING", "AUDIT", "NESTED_CONTROLS",
]


def _restricted_low_respondent():
    """LOW-rated respondent approved at the default clock, widened to OPEN, then
    restricted by the officer lever."""
    code = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    respondent = licensed_respondent(
        code, legal_name="Posture Dimension Bank", expected_monthly_volume_usd=4500000.00
    )
    rid = respondent["id"]
    add_verified_owner(rid, code, owner_name="Majority Holder", ownership_pct=80.00)
    questionnaire = open_questionnaire(rid, version="V1")
    add_control_rows(questionnaire["id"], rid, {d: 4 for d in DOMAINS})
    submit_questionnaire(questionnaire["id"], rid)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["residual_risk_score"] == 9.28  # round(round(14.00*0.6625, 2), 2)
    assert scored["risk_rating"] == "LOW"
    committee_decision(rid, "APPROVE")
    return code, rid


def test_dd_state_round_trip_leaves_the_posture_dimension_behind(api):
    """The cycle APPROVED -> RESTRICTED -> APPROVED closes exactly, but the parallel
    posture dimension does not: OPEN was forced to BLOCKED by RESTRICT and LIFT returns
    it only as far as SCREEN_ONLY.

    Design: Difficulty/non_linear_state_machine/respondent_dd_state_cycle_does_not_restore_the_parallel_payment_posture
    """
    code, rid = _restricted_low_respondent()
    approved = read_respondent(rid)
    assert approved["dd_state"] == "APPROVED"
    assert approved["payment_posture"] == "OPEN"  # LOW rating widens the posture
    assert approved["approved_risk_rating"] == "LOW"
    assert_instant_equals(approved["refresh_due_date"], "2029-08-01T00:00:00Z")

    restrict(rid, "OFFICER_ACTION")
    restricted = read_respondent(rid)
    assert restricted["dd_state"] == "RESTRICTED"
    assert restricted["payment_posture"] == "BLOCKED"
    assert restricted["restriction_reason"] == "OFFICER_ACTION"

    lifted = validate_success(api.restrict_respondent(rid, {"action": "LIFT"}, OFFICER))

    assert lifted["dd_state"] == "APPROVED"
    assert lifted["payment_posture"] == "SCREEN_ONLY"  # never back to OPEN
    assert lifted["restriction_reason"] is None
    assert lifted["approved_risk_rating"] == "LOW"
    assert lifted["residual_risk_score"] == 9.28
    assert lifted["undisclosed_nested_count"] == 0
    assert lifted["unresponsive_strikes"] == 0


def test_reopening_the_posture_dimension_takes_a_separate_amendment(api):
    """Because the lift stops at SCREEN_ONLY, the posture must be re-widened by its own
    amendment, which is admissible precisely because dd_state came back to APPROVED and
    undisclosed_nested_count is 0.

    Design: Difficulty/non_linear_state_machine/respondent_dd_state_cycle_does_not_restore_the_parallel_payment_posture
    """
    code, rid = _restricted_low_respondent()
    restrict(rid, "OFFICER_ACTION")
    lift(rid)
    assert read_respondent(rid)["payment_posture"] == "SCREEN_ONLY"

    widened = validate_success(
        api.amend_respondent(rid, {"payment_posture": "OPEN"}, RM)
    )

    assert widened["payment_posture"] == "OPEN"
    assert widened["dd_state"] == "APPROVED"
    assert widened["restriction_reason"] is None


def _clarification_loop(rounds):
    """Walk the SUBMITTED -> UNDER_ASSESSMENT -> RETURNED_FOR_CLARIFICATION -> SUBMITTED
    loop the requested number of times, leaving the row in UNDER_ASSESSMENT."""
    code = new_jurisdiction(name="Germany", basel_aml_index=4.0)["jurisdiction_code"]
    respondent = licensed_respondent(code, legal_name="Clarification Loop Bank")
    rid = respondent["id"]
    questionnaire = open_questionnaire(rid, version="V1")
    rows = add_control_rows(questionnaire["id"], rid, {d: 3 for d in DOMAINS})
    qid = questionnaire["id"]
    submit_questionnaire(qid, rid)
    for _ in range(rounds):
        overlay_row(rows["GOVERNANCE"]["id"], assessed_rating=3, gap_severity="MINOR")
        return_questionnaire(qid)
        submit_questionnaire(qid, rid)
    overlay_row(rows["GOVERNANCE"]["id"], assessed_rating=3, gap_severity="MINOR")
    return qid, rid, rows


def test_clarification_rounds_are_monotonic_across_re_entries(api):
    """Re-entering SUBMITTED never resets the counter, so three trips round the loop
    leave clarification_rounds at exactly 3 and the row back under assessment.

    Design: Difficulty/non_linear_state_machine/questionnaire_clarification_cycle_exhausts_rounds_on_the_fourth_return
    """
    qid, rid, rows = _clarification_loop(3)

    stored = get_success_data(api.get_questionnaire(qid, ANALYST))
    assert stored["clarification_rounds"] == 3
    assert stored["state"] == "UNDER_ASSESSMENT"

    governance = get_success_data(api.get_control_assessment(rows["GOVERNANCE"]["id"], ANALYST))
    assert governance["assessed_rating"] == 3
    assert governance["gap_severity"] == "MINOR"
    assert governance["remediation_required"] is False  # MINOR never forces remediation


def test_fourth_clarification_return_is_refused_with_rounds_exhausted(api):
    """The loop is bounded: with clarification_rounds already 3 the fourth RETURN is
    refused and the questionnaire keeps its position in the cycle.

    Design: Difficulty/non_linear_state_machine/questionnaire_clarification_cycle_exhausts_rounds_on_the_fourth_return
    """
    qid, rid, rows = _clarification_loop(3)

    response = api.decide_assessment(
        qid, {"action": "RETURN", "clarification_note": "round 4 - must be refused"}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_ROUNDS_EXHAUSTED)

    stored = get_success_data(api.get_questionnaire(qid, ANALYST))
    assert stored["clarification_rounds"] == 3
    assert stored["state"] == "UNDER_ASSESSMENT"
