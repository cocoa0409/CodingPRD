"""Complaint case lifecycle: fork guard, manual escalation, terminal states
(PRD §2.10, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_complaint_case,
    create_complaint,
    setup_draft_formula,
    triage_complaint,
    validate_error,
    validate_success,
)


def test_complaint_close_no_action_blocked_for_adverse_event(api, quality_analyst_headers):
    """PRD §3.8: "From `TRIAGED`, a `QualityAnalyst` opens an investigation, moving
    the case to `INVESTIGATING`, or closes it without action, moving it to
    `CLOSED_NO_ACTION`; closure without action is forbidden when the
    `adverse_event_flag` is true and is rejected with `ERR_ADVERSE_CLOSE_FORBIDDEN`
    (HTTP 422)."
    PRD §3.8: "Severity contributes 5 points for `MINOR`, 20 for `SERIOUS`, 45 for
    `LIFE_THREATENING`, and 60 for `DEATH`. Category contributes 2 for
    `PALATABILITY`, 3 for `PACKAGING`, 8 for `LABEL_DEFECT`, 12 for
    `FOREIGN_MATERIAL`, and 15 for `ILLNESS`. A confirmed adverse event adds a
    further 10 points."

    Design: Corner/state_machines/complaint_close_no_action_blocked_for_adverse_event
    """
    ctx = setup_draft_formula()
    brand_id = ctx["brand"]["id"]
    formula_id = ctx["formula"]["id"]

    case_a = create_complaint(
        brand_id, formula_id, severity="SERIOUS", category="ILLNESS",
        adverse_event_flag=True,
    )
    assert case_a["status"] == "INTAKE"
    triaged_a = triage_complaint(case_a["id"], confirm_flag=True)
    assert triaged_a["triage_score"] == pytest.approx(45.0, abs=0.005)
    assert triaged_a["status"] == "TRIAGED"

    case_b = create_complaint(
        brand_id, formula_id, severity="MINOR", category="PALATABILITY",
        adverse_event_flag=False,
    )
    triage_complaint(case_b["id"], confirm_flag=False)

    resp = api.close_complaint_no_action(case_a["id"], quality_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_ADVERSE_CLOSE_FORBIDDEN.value)

    closed_b = validate_success(
        api.close_complaint_no_action(case_b["id"], quality_analyst_headers)
    )
    assert closed_b["status"] == "CLOSED_NO_ACTION"


def test_complaint_escalate_from_investigating_succeeds(
    api, quality_analyst_headers, qa_approver_headers
):
    """PRD §3.8: "From `INVESTIGATING`, a `QualityAnalyst` resolves the case
    (`RESOLVED`), which recomputes the brand's `complaint_score` with closure
    decay applied, while a `QAApprover` may instead escalate it to
    `ESCALATED_RECALL`."

    Design: Corner/state_machines/complaint_escalate_from_investigating_succeeds
    """
    ctx = setup_draft_formula()
    case = create_complaint(
        ctx["brand"]["id"], ctx["formula"]["id"],
        severity="MINOR", category="PACKAGING", adverse_event_flag=False,
    )
    triaged = triage_complaint(case["id"], confirm_flag=False)
    assert triaged["status"] == "TRIAGED"
    assert triaged["triage_score"] == pytest.approx(8.0, abs=0.005)

    investigating = validate_success(
        api.open_investigation(case["id"], quality_analyst_headers)
    )
    assert investigating["status"] == "INVESTIGATING"
    escalated = validate_success(api.escalate_complaint(case["id"], qa_approver_headers))
    assert escalated["status"] == "ESCALATED_RECALL"


def test_complaint_resolved_is_terminal(api, quality_analyst_headers, qa_approver_headers):
    """PRD §3.8: "`RESOLVED`, `ESCALATED_RECALL`, and `CLOSED_NO_ACTION` are
    terminal."
    PRD §2.10: "a resource already in a terminal state accepts no further
    transitions at all and rejects them with `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/complaint_resolved_is_terminal
    """
    ctx = setup_draft_formula()
    case = create_complaint(
        ctx["brand"]["id"], ctx["formula"]["id"],
        severity="MINOR", category="PALATABILITY", adverse_event_flag=False,
    )
    triage_complaint(case["id"], confirm_flag=False)
    validate_success(api.open_investigation(case["id"], quality_analyst_headers))
    resolved = validate_success(api.resolve_complaint(case["id"], quality_analyst_headers))
    assert_complaint_case(resolved)
    assert resolved["status"] == "RESOLVED"

    resp = api.escalate_complaint(case["id"], qa_approver_headers)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value)
