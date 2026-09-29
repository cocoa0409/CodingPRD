"""Corner queue - section state_machines, part C: terminal states and closure-plan guards."""
from test_helpers import (
    ApiErrorId,
    draft_plan,
    licensed_respondent,
    log_media,
    new_jurisdiction,
    new_respondent,
    raise_alert,
    read_alert,
    read_media,
    read_plan,
    submit_plan,
    triage_media,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, OFFICER, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _prospect():
    _de()
    return new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def _verified():
    _de()
    return licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def test_terminal_state_confirmed_adverse_media_rejects_second_triage(api):
    """Confirmation is the end of the adjudication road, so a later dismissal cannot undo
    it and the event keeps the state that earns its uplift.

    Design: Corner/state_machines/terminal_state_confirmed_adverse_media_rejects_second_triage
    """
    rid = _prospect()["id"]
    event = log_media(
        rid, headline="Regulator opens probe", category="REGULATORY_ACTION",
        severity_tier="TIER_2", source_reliability="B", event_date="2026-07-15T00:00:00Z",
    )
    triage_media(event["id"], "CONFIRM", OFFICER)

    response = api.triage_media(event["id"], {"action": "DISMISS"}, OFFICER)
    validate_error(response, ApiErrorId.ERR_INVALID_MEDIA_STATE)

    assert read_media(event["id"])["adjudication_state"] == "CONFIRMED"


def test_invalid_transition_alert_close_false_positive_directly_from_open_rejected(api):
    """Closure is reachable only from investigation, so closing an untouched OPEN alert is
    refused and the disposition reason is never recorded.

    Design: Corner/state_machines/invalid_transition_alert_close_false_positive_directly_from_open_rejected
    """
    rid = _prospect()["id"]
    alert = raise_alert(rid, "CORRIDOR_UNEXPECTED", "MEDIUM", ANALYST)

    response = api.dispose_alert(
        alert["id"],
        {"action": "CLOSE_FALSE_POSITIVE", "disposition_reason": "DATA_QUALITY"},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ALERT_STATE)

    stored = read_alert(alert["id"])
    assert stored["state"] == "OPEN"
    assert stored["disposition_reason"] is None


def test_invalid_transition_closure_plan_second_submission_rejected(api):
    """Submission consumes the draft state, so a plan already awaiting the committee cannot
    be resubmitted and its return counter is untouched.

    Design: Corner/state_machines/invalid_transition_closure_plan_second_submission_rejected
    """
    rid = _verified()["id"]
    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=100000,
    )
    submit_plan(plan["id"])

    response = api.submit_closure_plan(plan["id"], {}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_CLOSURE_STATE)

    stored = read_plan(plan["id"])
    assert stored["state"] == "PENDING_APPROVAL"
    assert stored["return_rounds"] == 0


def test_invalid_transition_closure_plan_approval_from_draft_rejected(api):
    """The committee decides only on submitted plans, so approving a draft is refused and
    neither the wind-down cap nor the approver identity is written.

    Design: Corner/state_machines/invalid_transition_closure_plan_approval_from_draft_rejected
    """
    rid = _verified()["id"]
    plan = draft_plan(
        rid, RM, termination_reason="RISK_APPETITE", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=0,
    )

    response = api.approve_closure_plan(plan["id"], {"action": "APPROVE"}, COMMITTEE)
    validate_error(response, ApiErrorId.ERR_INVALID_CLOSURE_STATE)

    stored = read_plan(plan["id"])
    assert stored["state"] == "DRAFT"
    assert stored["wind_down_cap_usd"] == 0
    assert stored["approved_by_user_id"] is None


def test_second_open_closure_plan_for_same_respondent_rejected(api):
    """At most one plan may be open per respondent, so a second draft is refused on that
    ground alone even though it carries a different termination reason.

    Design: Corner/state_machines/second_open_closure_plan_for_same_respondent_rejected
    """
    rid = _verified()["id"]
    draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=100000,
    )

    response = api.create_closure_plan(
        rid,
        {"termination_reason": "UNRESPONSIVE", "cap_basis": "FORWARD_PROJECTED",
         "original_obligation_cents": 50000},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_CLOSURE_PLAN_ALREADY_OPEN)

    _rows, meta = validate_paginated(
        api.list_closure_plans(RM, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 1
