"""Violation adjudication branches, the depth-3 sanction escalation cascade, the FTA
cascade, and segregation-of-duties on adjudication/approval.

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml rules non_linear_state_machine.
violation_branch_sanction_vs_dismiss, transitive_cascade.sanction_escalation_depth3,
transitive_cascade.fta_creates_violation_depth2; and SCAFFOLD_CORNER_DESIGN.yaml
validations.assessment_approve_by_submitter_returns_sod and
violations.violation_adjudicate_by_reporter_returns_sod.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    make_judicial_headers,
    create_defendant, create_under_review_violation, create_submitted_assessment,
    activate_defendant, create_court_event_payload, set_clock,
)

SUPERVISING = TEST_USERS["supervising_headers"]
JUDICIAL = TEST_USERS["judicial_headers"]


# ─── non_linear_state_machine / violation_branch_sanction_vs_dismiss ───────

def test_sanction_sets_severity_points_and_raises_score(api):
    """PRD §3.7: "A **sanction** (`UNDER_REVIEW → ADJUDICATED_SANCTION`) sets
    `severity_points` from the severity band — `MINOR` is 3 points, `MODERATE` is 6 points,
    `MAJOR` is 10 points — and then recomputes the defendant's `cumulative_violation_score`."

    Design: Difficulty/non_linear_state_machine/violation_branch_sanction_vs_dismiss
    """
    d = create_defendant()
    v = create_under_review_violation(d["id"], severity="MODERATE",
                                      reporter_id="u_sup", reviewer_id="u_judge")
    sanc = validate_success(api.transition_violation(
        v["id"], "ADJUDICATED_SANCTION", make_judicial_headers("u_judge")), 200)
    assert sanc["severity_points"] == 6
    fresh = validate_success(api.get_defendant(d["id"], JUDICIAL), 200)
    assert fresh["cumulative_violation_score"] == 6


def test_dismiss_leaves_severity_points_zero(api):
    """PRD §3.7: "A **dismissal** (`UNDER_REVIEW → ADJUDICATED_DISMISS`) leaves
    `severity_points` at 0 and triggers no escalation."

    Design: Difficulty/non_linear_state_machine/violation_branch_sanction_vs_dismiss
    """
    d = create_defendant()
    v = create_under_review_violation(d["id"], severity="MODERATE",
                                      reporter_id="u_sup", reviewer_id="u_judge")
    dism = validate_success(api.transition_violation(
        v["id"], "ADJUDICATED_DISMISS", make_judicial_headers("u_judge")), 200)
    assert dism["severity_points"] == 0
    fresh = validate_success(api.get_defendant(d["id"], JUDICIAL), 200)
    assert fresh["cumulative_violation_score"] == 0


# ─── transitive_cascade / sanction_escalation_depth3 ───────────────────────

def test_major_sanction_escalates_level_to_maximum(api):
    """PRD §3.7: "If, after a sanction, the recomputed `cumulative_violation_score` is at
    least 10, the defendant's supervision level escalates one step along the ladder
    `MINIMUM → MEDIUM → MAXIMUM`."

    Design: Difficulty/transitive_cascade/sanction_escalation_depth3
    """
    ctx = activate_defendant(ordered_conditions=["CHECK_IN", "GPS_MONITORING"],
                             assessment_overrides={"prior_failures": 2,
                                                   "pending_charges_count": 0})
    d = ctx["defendant"]
    assert d["supervision_level"] == "MEDIUM"
    v = create_under_review_violation(d["id"], violation_type="NEW_ARREST", severity="MAJOR",
                                      reporter_id="u_sup", reviewer_id="u_judge")
    sanc = validate_success(api.transition_violation(
        v["id"], "ADJUDICATED_SANCTION", make_judicial_headers("u_judge")), 200)
    assert sanc["severity_points"] == 10
    fresh = validate_success(api.get_defendant(d["id"], JUDICIAL), 200)
    assert fresh["cumulative_violation_score"] == 10
    assert fresh["supervision_level"] == "MAXIMUM"


def test_escalation_creates_escalation_checkin(api):
    """PRD §3.7: "it creates an escalation check-in — a `CheckIn` with `origin`
    `ESCALATION`, in `SCHEDULED` status, whose `due_at` is the current clock plus 7 days."

    Design: Difficulty/transitive_cascade/sanction_escalation_depth3
    """
    ctx = activate_defendant(ordered_conditions=["CHECK_IN", "GPS_MONITORING"],
                             assessment_overrides={"prior_failures": 2,
                                                   "pending_charges_count": 0})
    d = ctx["defendant"]
    v = create_under_review_violation(d["id"], violation_type="NEW_ARREST", severity="MAJOR",
                                      reporter_id="u_sup", reviewer_id="u_judge")
    validate_success(api.transition_violation(
        v["id"], "ADJUDICATED_SANCTION", make_judicial_headers("u_judge")), 200)
    data, _ = validate_paginated(api.list_defendant_check_ins(d["id"], JUDICIAL))
    escalation = [c for c in data if c["origin"] == "ESCALATION"]
    assert len(escalation) >= 1, "escalation must create an ESCALATION-origin check-in"
    assert escalation[0]["status"] == "SCHEDULED"


# ─── transitive_cascade / fta_creates_violation_depth2 ─────────────────────

def test_fta_transition_sets_status(api):
    """PRD §3.6: "Recording a **failure-to-appear** (`SCHEDULED → FTA`) requires the event
    to be `SCHEDULED` and requires the current clock to be strictly after the hearing instant
    plus a failure-to-appear grace period of 2 hours."

    Design: Difficulty/transitive_cascade/fta_creates_violation_depth2
    """
    d = create_defendant()
    ce = validate_success(api.create_court_event(
        create_court_event_payload(d["id"], hearing_at="2026-06-01T09:00:00Z"),
        SUPERVISING), 201)
    set_clock("2026-06-01T12:00:00Z")
    data = validate_success(api.transition_court_event(ce["id"], "FTA", SUPERVISING), 200)
    assert data["status"] == "FTA"


def test_fta_cascades_major_violation(api):
    """PRD §3.6: "Recording a failure-to-appear cascades the automatic creation of a
    `ViolationEvent` with `violation_type` `FTA` and `severity` `MAJOR`, in `REPORTED`
    status, with the court event's `id` as its `source_ref`."

    Design: Difficulty/transitive_cascade/fta_creates_violation_depth2
    """
    d = create_defendant()
    ce = validate_success(api.create_court_event(
        create_court_event_payload(d["id"], hearing_at="2026-06-01T09:00:00Z"),
        SUPERVISING), 201)
    set_clock("2026-06-01T12:00:00Z")
    validate_success(api.transition_court_event(ce["id"], "FTA", SUPERVISING), 200)
    data, _ = validate_paginated(api.list_defendant_violations(d["id"], JUDICIAL))
    fta = [v for v in data if v["violation_type"] == "FTA"]
    assert len(fta) == 1, "exactly one FTA violation must be auto-created"
    assert fta[0]["status"] == "REPORTED"
    assert fta[0]["severity"] == "MAJOR"
    assert fta[0]["source_ref"] == ce["id"]


# ─── Corner SoD ────────────────────────────────────────────────────────────

def test_approve_assessment_by_submitter_returns_sod(api):
    """PRD §2.8: "an approve or reject whose `X-User-ID` equals `submitted_by_user_id` is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/validations/assessment_approve_by_submitter_returns_sod
    """
    d = create_defendant()
    a = create_submitted_assessment(d["id"], submitter_id="u_same")
    resp = api.transition_assessment(a["id"], "APPROVED", make_judicial_headers("u_same"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)


def test_adjudicate_violation_by_reporter_returns_sod(api):
    """PRD §2.8: "an adjudication — whether to sanction or to dismiss — whose `X-User-ID`
    equals `reported_by_user_id` is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/violation_adjudicate_by_reporter_returns_sod
    """
    d = create_defendant()
    v = create_under_review_violation(d["id"], severity="MINOR",
                                      reporter_id="u_rep", reviewer_id="u_judge")
    resp = api.transition_violation(v["id"], "ADJUDICATED_SANCTION",
                                    make_judicial_headers("u_rep"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)
