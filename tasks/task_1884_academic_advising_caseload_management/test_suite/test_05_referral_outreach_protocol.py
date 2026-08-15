"""Early-alert referral claims: SLA deadlines and strict breach boundary, the
outreach retry cycle, manual and automatic escalation cascades, and closure."""
from test_helpers import (
    ApiErrorId,
    assert_referral,
    create_referral,
    create_referral_payload,
    create_student,
    get_student,
    list_interventions_for,
    log_outreach,
    set_logical_clock,
    setup_escalation_candidate,
    validate_error,
    validate_success,
)


# ─── Difficulty: non_linear_state_machine / referral_outreach_retry_cycle ────

def test_outreach_no_answer_cycles_working_states(api, director_headers):
    """PRD §3.6: "A `NO_ANSWER` outcome cycles the referral through its working states: `OPEN → OUTREACH_IN_PROGRESS`, `OUTREACH_IN_PROGRESS → NO_RESPONSE`, and `NO_RESPONSE → OUTREACH_IN_PROGRESS`."
    PRD §3.6: "Every logged attempt increments `attempt_count` by 1."

    Design: Difficulty/non_linear_state_machine/referral_outreach_retry_cycle
    """
    student = create_student(full_name="N2", email="n2@x.edu")
    referral = create_referral(
        student["id"], severity="MEDIUM", source="STAFF", reason="missed registration"
    )
    first = log_outreach(referral["id"], "NO_ANSWER")
    assert first["status"] == "OUTREACH_IN_PROGRESS"
    assert first["attempt_count"] == 1
    second = log_outreach(referral["id"], "NO_ANSWER")
    assert second["status"] == "NO_RESPONSE"
    assert second["attempt_count"] == 2


def test_outreach_reached_from_no_response_responds(api, director_headers):
    """PRD §3.6: "A `REACHED` outcome moves the referral to `RESPONDED` from any of those three working states."
    PRD §3.6: "The protocol tolerates at most three attempts. When a `NO_ANSWER` would bring `attempt_count` to 3, the normal cycle does not apply: the referral is instead auto-escalated, its `attempt_count` is set to 3 as part of the same outreach call, and the escalation cascade below fires."

    Design: Difficulty/non_linear_state_machine/referral_outreach_retry_cycle
    """
    student = create_student(full_name="N2", email="n2@x.edu")
    referral = create_referral(
        student["id"], severity="MEDIUM", source="STAFF", reason="missed registration"
    )
    log_outreach(referral["id"], "NO_ANSWER")
    log_outreach(referral["id"], "NO_ANSWER")
    # REACHED (not NO_ANSWER) on the third attempt: RESPONDED, not ESCALATED.
    third = log_outreach(referral["id"], "REACHED")
    assert third["status"] == "RESPONDED"
    assert third["attempt_count"] == 3


# ─── Difficulty: transitive_cascade / referral_escalation_cascades_to_clearance_block

def test_escalation_creates_linked_open_intervention(api, director_headers):
    """PRD §3.6: "Manual escalation and auto-escalation fire an identical four-step cascade. First, an intervention is created for the referred student with `referral_id` pointing at this referral, `intervention_type` set to `ACADEMIC_COACHING`, and status `OPEN`."
    PRD §3.6: "The director may escalate any referral in `OPEN`, `OUTREACH_IN_PROGRESS`, or `NO_RESPONSE`, optionally attaching a `reason`; the state guard is the same `ERR_REFERRAL_INVALID_STATE`."

    Design: Difficulty/transitive_cascade/referral_escalation_cascades_to_clearance_block
    """
    student, referral = setup_escalation_candidate()
    escalated = validate_success(
        api.escalate_referral(referral["id"], {"reason": "unreachable"}, director_headers),
        200,
    )
    assert escalated["status"] == "ESCALATED"
    interventions = list_interventions_for(
        director_headers, student_id=student["id"]
    )
    assert len(interventions) == 1, "the cascade creates exactly one intervention"
    link = interventions[0]
    assert link["status"] == "OPEN"
    assert link["referral_id"] == referral["id"]
    assert link["intervention_type"] == "ACADEMIC_COACHING"


def test_escalation_flips_tier_and_blocks_clearance(api, director_headers):
    """PRD §3.6: "Second, that creation recomputes the student's `at_risk_score` — ten points for the new `OPEN` intervention — which may flip the `risk_tier`. Third, if the tier becomes `HIGH`, the system sets `advising_required_flag` to true and recomputes `advising_requirement_status`, which becomes `REQUIRED` absent a completed current-term appointment, and `registration_clearance`, which becomes `BLOCKED`."
    PRD §3.2: "From the score, the `risk_tier` is `HIGH` when the score is 70 or higher, `MEDIUM` when it is at least 40 but below 70, and `LOW` below 40."

    Design: Difficulty/transitive_cascade/referral_escalation_cascades_to_clearance_block
    """
    student, referral = setup_escalation_candidate()
    before = get_student(student["id"])
    assert before["at_risk_score"] == 60, "40 base (gpa 1.5) + 20 HIGH referral"
    assert before["risk_tier"] == "MEDIUM"
    assert before["registration_clearance"] == "CLEARED"

    validate_success(
        api.escalate_referral(referral["id"], {"reason": "unreachable"}, director_headers),
        200,
    )
    after = get_student(student["id"])
    assert after["at_risk_score"] == 70, "60 + 10 for the cascade intervention"
    assert after["risk_tier"] == "HIGH"
    assert after["advising_required_flag"] is True
    assert after["advising_requirement_status"] == "REQUIRED"
    assert after["registration_clearance"] == "BLOCKED"


# ─── Difficulty: boundary_precision_check / referral_sla_breach_strict_greater_than

def test_sla_not_breached_at_exact_due_instant(api, director_headers):
    """PRD §3.6: "The `is_sla_breached` flag tracks the service level against the logical clock: it is true when the current logical time is strictly later than `due_at` and the referral is in a state other than `RESPONDED` or `CLOSED`. At the exact `due_at` instant the referral is not yet breached — the comparison is strict."
    PRD §3.6: "The new referral starts `OPEN` with `attempt_count` at 0, and its `due_at` is computed at creation as the creation time plus the severity's service level: 2 days for `HIGH`, 5 days for `MEDIUM`, 10 days for `LOW`, at second precision."

    Design: Difficulty/boundary_precision_check/referral_sla_breach_strict_greater_than
    """
    student = create_student(full_name="BS3", email="bs3@x.edu")
    referral = create_referral(student["id"], severity="HIGH", reason="quiz failures")
    # Created at the default clock 2026-08-01T00:00:00Z; HIGH -> +2 days.
    assert referral["due_at"] == "2026-08-03T00:00:00Z"
    set_logical_clock("2026-08-03T00:00:00Z")  # exactly due_at
    at_due = validate_success(api.get_referral(referral["id"], director_headers), 200)
    assert at_due["is_sla_breached"] is False, "now == due_at, strict > not satisfied"


def test_sla_breached_one_second_after_due(api, director_headers):
    """PRD §3.6: "The `is_sla_breached` flag tracks the service level against the logical clock: it is true when the current logical time is strictly later than `due_at` and the referral is in a state other than `RESPONDED` or `CLOSED`. At the exact `due_at` instant the referral is not yet breached — the comparison is strict."
    PRD §3.6: "The flag is recomputed on every referral read and again during the daily close, and the referral list can be filtered by `student_id`, `status`, `severity`, or `is_sla_breached`."

    Design: Difficulty/boundary_precision_check/referral_sla_breach_strict_greater_than
    """
    student = create_student(full_name="BS3", email="bs3@x.edu")
    referral = create_referral(student["id"], severity="HIGH", reason="quiz failures")
    assert referral["due_at"] == "2026-08-03T00:00:00Z"
    set_logical_clock("2026-08-02T23:59:59Z")  # one second before due_at
    before_due = validate_success(api.get_referral(referral["id"], director_headers), 200)
    assert before_due["is_sla_breached"] is False
    set_logical_clock("2026-08-03T00:00:01Z")  # one second after due_at
    after_due = validate_success(api.get_referral(referral["id"], director_headers), 200)
    assert after_due["is_sla_breached"] is True, "now = due_at + 1s -> breached"


# ─── Corner: state_machines / referral_auto_escalates_on_third_no_answer ──────

def test_referral_auto_escalates_on_third_no_answer(api, director_headers):
    """PRD §3.6: "The protocol tolerates at most three attempts. When a `NO_ANSWER` would bring `attempt_count` to 3, the normal cycle does not apply: the referral is instead auto-escalated, its `attempt_count` is set to 3 as part of the same outreach call, and the escalation cascade below fires."

    Design: Corner/state_machines/referral_auto_escalates_on_third_no_answer
    """
    student = create_student(full_name="S6", email="s6c@x.edu")
    referral = create_referral(
        student["id"], severity="MEDIUM", source="FACULTY", reason="low quiz scores"
    )
    log_outreach(referral["id"], "NO_ANSWER")
    log_outreach(referral["id"], "NO_ANSWER")
    third = log_outreach(referral["id"], "NO_ANSWER")
    assert third["status"] == "ESCALATED"
    assert third["attempt_count"] == 3
    interventions = list_interventions_for(director_headers, referral_id=referral["id"])
    assert len(interventions) == 1
    assert interventions[0]["status"] == "OPEN", (
        "auto-escalation fires the same cascade, creating the linked intervention"
    )


# ─── Corner: state_machines / referral_close_from_open_rejected ──────────────

def test_referral_close_from_open_rejected(api, director_headers):
    """PRD §3.6: "A referral in `RESPONDED` or `ESCALATED` may be closed by the assigned advisor or the director, moving it to `CLOSED`; closure from any other state is rejected with `ERR_REFERRAL_INVALID_STATE`."

    Design: Corner/state_machines/referral_close_from_open_rejected
    """
    student = create_student(full_name="S8", email="s8c@x.edu")
    referral = create_referral(student["id"], severity="LOW", source="STAFF", reason="minor")
    res = api.close_referral(referral["id"], director_headers)
    validate_error(res, ApiErrorId.ERR_REFERRAL_INVALID_STATE)


# ─── Corner: calculations / sla_due_at_computed_by_severity ──────────────────

def test_sla_due_at_computed_by_severity(api, faculty_headers):
    """PRD §3.6: "The new referral starts `OPEN` with `attempt_count` at 0, and its `due_at` is computed at creation as the creation time plus the severity's service level: 2 days for `HIGH`, 5 days for `MEDIUM`, 10 days for `LOW`, at second precision."
    PRD §2.4: "Before it has ever been set, the logical clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own."

    Design: Corner/calculations/sla_due_at_computed_by_severity
    """
    student = create_student(full_name="QC3", email="qc3@x.edu")
    res = api.create_referral(
        create_referral_payload(
            student["id"], source="FACULTY", severity="MEDIUM", reason="attendance"
        ),
        faculty_headers,
    )
    referral = validate_success(res, 201)
    assert_referral(referral)
    assert referral["due_at"] == "2026-08-06T00:00:00Z", (
        "default clock 2026-08-01T00:00:00Z + MEDIUM 5 days"
    )
    assert referral["is_sla_breached"] is False, "at creation now < due_at"
