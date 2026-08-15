"""Composite setup helpers for multi-step BIT workflows (PRD §3).

Every fixture builds its preconditions from scratch via the public API; the
test harness restarts the server before each test, so nothing is shared.
All helpers return plain dicts of created entities / ids so tests can pick
what they need.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_concern_report_payload,
    create_disclosure_grant_payload,
    create_intervention_plan_payload,
    create_mandated_assessment_payload,
    create_reentry_evaluation_payload,
    create_risk_scoring_payload,
    create_staff_payload,
    create_student_payload,
)
from .test_users import (
    make_bit_chair_headers,
    make_case_manager_headers,
    make_counseling_evaluator_headers,
    make_dean_headers,
    make_privacy_officer_headers,
    make_reporter_headers,
    make_system_admin_headers,
)

# ---------------------------------------------------------------------------
# Tier 0: atomic creators (staff members of each office, students)
# ---------------------------------------------------------------------------


def create_staff(full_name: str, office: str) -> dict:
    admin = make_system_admin_headers()
    data = get_success_data(
        api_client.create_staff(create_staff_payload(full_name=full_name, office=office), admin)
    )
    return data


def create_student(external_ref: str = None, full_name: str = "Test Student") -> dict:
    admin = make_system_admin_headers()
    payload = create_student_payload(full_name=full_name)
    if external_ref:
        payload["external_ref"] = external_ref
    return get_success_data(api_client.create_student(payload, admin))


def setup_staff_group(
    chair=True,
    case_manager=True,
    reporter=True,
    evaluator=False,
    dean=False,
    dean2=False,
    privacy_officer=False,
    case_manager2=False,
    reporter2=False,
):
    """Create the standard cast of staff members and per-role headers.

    Returns a dict with entity dicts plus ready-to-use header dicts keyed as
    e.g. ``ctx["chair_headers"]`` (identity-threaded to the actual staff id).
    """
    ctx = {}
    if chair:
        ctx["chair"] = create_staff("Chair One", "BIT_OFFICE")
        ctx["chair_headers"] = make_bit_chair_headers(ctx["chair"]["id"])
    if case_manager:
        ctx["cm"] = create_staff("Manager One", "BIT_OFFICE")
        ctx["cm_headers"] = make_case_manager_headers(ctx["cm"]["id"])
    if case_manager2:
        ctx["cm2"] = create_staff("Manager Two", "BIT_OFFICE")
        ctx["cm2_headers"] = make_case_manager_headers(ctx["cm2"]["id"])
    if reporter:
        ctx["rep"] = create_staff("Prof Rep", "FACULTY_AFFAIRS")
        ctx["rep_headers"] = make_reporter_headers(ctx["rep"]["id"])
    if reporter2:
        ctx["rep2"] = create_staff("Rep Two", "FACULTY_AFFAIRS")
        ctx["rep2_headers"] = make_reporter_headers(ctx["rep2"]["id"])
    if evaluator:
        ctx["ev"] = create_staff("Eval One", "COUNSELING_CENTER")
        ctx["ev_headers"] = make_counseling_evaluator_headers(ctx["ev"]["id"])
    if dean:
        ctx["dean"] = create_staff("Dean One", "DEAN_OF_STUDENTS")
        ctx["dean_headers"] = make_dean_headers(ctx["dean"]["id"])
    if dean2:
        ctx["dean2"] = create_staff("Dean Two", "DEAN_OF_STUDENTS")
        ctx["dean2_headers"] = make_dean_headers(ctx["dean2"]["id"])
    if privacy_officer:
        ctx["po"] = create_staff("Privacy One", "PRIVACY_OFFICE")
        ctx["po_headers"] = make_privacy_officer_headers(ctx["po"]["id"])
    ctx["admin_headers"] = make_system_admin_headers()
    return ctx


# ---------------------------------------------------------------------------
# Tier 1: concern-report intake chain
# ---------------------------------------------------------------------------


def submit_report(ctx: dict, student_id: str, category: str = "WELLBEING_GENERAL",
                  narrative: str = "n", observed_at: str = "2026-07-31T10:00:00Z",
                  related_report_id=None) -> dict:
    payload = create_concern_report_payload(
        student_id=student_id, category=category, narrative=narrative,
        observed_at=observed_at,
    )
    if related_report_id is not None:
        payload["related_report_id"] = related_report_id
    return get_success_data(
        api_client.create_concern_report(payload, ctx["rep_headers"])
    )


def accept_report_and_get_case(ctx: dict, report_id: str, case_manager_id: str = None):
    """start-review + accept; returns (accepted_report, case_id)."""
    chair_h = ctx["chair_headers"]
    get_success_data(api_client.start_review_concern_report(report_id, chair_h))
    accepted = get_success_data(
        api_client.accept_concern_report(
            report_id,
            {"case_manager_id": case_manager_id or ctx["cm"]["id"]},
            chair_h,
        )
    )
    return accepted, accepted["care_case_id"]


def setup_case_in_intake(ctx: dict, external_ref: str = None,
                         category: str = "WELLBEING_GENERAL") -> dict:
    """Create student + submitted report + accept -> case in INTAKE.

    Returns ctx enriched with ``student``, ``report``, ``case_id``.
    """
    ctx["student"] = create_student(external_ref=external_ref)
    ctx["report"] = submit_report(ctx, ctx["student"]["id"], category=category)
    _, ctx["case_id"] = accept_report_and_get_case(ctx, ctx["report"]["id"])
    return ctx


def get_case(ctx: dict, case_id: str) -> dict:
    return get_success_data(api_client.get_care_case(case_id, ctx["chair_headers"]))


def get_case_version(ctx: dict, case_id: str) -> int:
    return get_case(ctx, case_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: triage — scoring helpers
# ---------------------------------------------------------------------------


def score_case(ctx: dict, case_id: str, mode: str = "INITIAL",
               harm_to_self: int = 0, harm_to_others: int = 0,
               academic_disruption: int = 0, substance_involvement: int = 0,
               rationale: str = "rubric") -> dict:
    payload = create_risk_scoring_payload(
        case_id=case_id, mode=mode,
        harm_to_self=harm_to_self, harm_to_others=harm_to_others,
        academic_disruption=academic_disruption,
        substance_involvement=substance_involvement, rationale=rationale,
    )
    return get_success_data(
        api_client.create_risk_scoring(payload, ctx["chair_headers"])
    )


def setup_case_triaged(ctx: dict, external_ref: str = None,
                       category: str = "WELLBEING_GENERAL",
                       dims=(0, 0, 0, 0)) -> dict:
    """Case in INTAKE + one INITIAL scoring -> TRIAGED.

    ``dims`` is (harm_to_self, harm_to_others, academic_disruption, substance_involvement).
    """
    setup_case_in_intake(ctx, external_ref=external_ref, category=category)
    ctx["scoring1"] = score_case(ctx, ctx["case_id"], mode="INITIAL", **dict(zip(
        ("harm_to_self", "harm_to_others", "academic_disruption", "substance_involvement"), dims
    )))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: plan lifecycle — draft / submit / approve
# ---------------------------------------------------------------------------


def draft_plan(ctx: dict, case_id: str, objectives=None, success_criteria: str = "s",
               drafter: str = "cm") -> dict:
    version = get_case_version(ctx, case_id)
    payload = create_intervention_plan_payload(
        case_id=case_id,
        expected_case_version=version,
        objectives=objectives or ["o"],
        success_criteria=success_criteria,
    )
    return get_success_data(
        api_client.create_intervention_plan(payload, ctx[f"{drafter}_headers"])
    )


def approve_plan(ctx: dict, plan_id: str, approver: str = "chair") -> dict:
    return get_success_data(
        api_client.approve_intervention_plan(plan_id, ctx[f"{approver}_headers"])
    )


def setup_case_plan_active(ctx: dict, external_ref: str = None,
                           category: str = "WELLBEING_GENERAL",
                           dims=(0, 0, 0, 0)) -> dict:
    """Full chain to PLAN_ACTIVE with an ACTIVE plan p1.

    Returns ctx enriched with ``plan`` (ACTIVE) and leaves exactly one
    SCHEDULED check-in on the case.
    """
    setup_case_triaged(ctx, external_ref=external_ref, category=category, dims=dims)
    ctx["plan"] = draft_plan(ctx, ctx["case_id"])
    get_success_data(api_client.submit_intervention_plan(ctx["plan"]["id"], ctx["cm_headers"]))
    ctx["plan"] = approve_plan(ctx, ctx["plan"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3b: check-in helpers
# ---------------------------------------------------------------------------


def get_scheduled_checkin(ctx: dict, case_id: str) -> dict:
    """Return the single SCHEDULED check-in for the case (list query)."""
    data = get_success_data(
        api_client.list_follow_up_checkins(
            ctx["chair_headers"], params={"case_id": case_id, "status": "SCHEDULED"}
        )
    )
    items = data if isinstance(data, list) else data.get("items") or data.get("results") or []
    # The envelope's data for list endpoints is the array itself.
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly one SCHEDULED check-in for case {case_id}, got: {data}"
    )
    return data[0]


def complete_checkin(ctx: dict, checkin_id: str, outcome: str = "STABLE",
                     note: str = "ok", completer: str = "cm"):
    return api_client.complete_follow_up_checkin(
        checkin_id, {"outcome": outcome, "note": note}, ctx[f"{completer}_headers"]
    )


def complete_stable(ctx: dict, case_id: str) -> dict:
    """Complete the currently SCHEDULED check-in with STABLE; returns it."""
    k = get_scheduled_checkin(ctx, case_id)
    completed = get_success_data(complete_checkin(ctx, k["id"], outcome="STABLE"))
    return completed


def accumulate_stable_checkins(ctx: dict, case_id: str, count: int) -> None:
    for _ in range(count):
        complete_stable(ctx, case_id)


# ---------------------------------------------------------------------------
# Tier 4: closure-ready and closed cases
# ---------------------------------------------------------------------------


def setup_case_closable(ctx: dict, external_ref: str = None) -> dict:
    """PLAN_ACTIVE case, tier LOW, exactly 3 consecutive STABLE check-ins."""
    setup_case_plan_active(ctx, external_ref=external_ref, dims=(0, 0, 0, 0))
    accumulate_stable_checkins(ctx, ctx["case_id"], 3)
    return ctx


def setup_case_closed(ctx: dict, external_ref: str = None) -> dict:
    """Full lifecycle through CLOSED (PRD §3.8)."""
    setup_case_closable(ctx, external_ref=external_ref)
    ctx["closed_case"] = get_success_data(
        api_client.close_care_case(ctx["case_id"], ctx["chair_headers"])
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: mandated assessment / leave / re-entry lifecycle
# ---------------------------------------------------------------------------


def order_assessment(ctx: dict, case_id: str, due_at: str = "2026-08-10T00:00:00Z",
                     evaluator_key: str = "ev", rationale: str = "mandate"):
    payload = create_mandated_assessment_payload(
        case_id=case_id, evaluator_id=ctx[evaluator_key]["id"],
        due_at=due_at, rationale=rationale,
    )
    return api_client.create_mandated_assessment(payload, ctx["chair_headers"])


def setup_case_in_mandated_assessment(ctx: dict, external_ref: str = None,
                                      due_at: str = "2026-08-10T00:00:00Z") -> dict:
    """PLAN_ACTIVE (HIGH) case + one SCHEDULED mandated assessment."""
    setup_case_plan_active(ctx, external_ref=external_ref,
                           category="SELF_HARM_RISK", dims=(20, 20, 5, 5))
    ctx["assessment"] = get_success_data(order_assessment(ctx, ctx["case_id"], due_at=due_at))
    return ctx


def setup_case_in_leave_decision(ctx: dict, external_ref: str = None,
                                 due_at: str = "2026-08-10T00:00:00Z") -> dict:
    """Case in LEAVE_DECISION with a PENDING LeaveDecision (NOT_CLEARED path)."""
    setup_case_in_mandated_assessment(ctx, external_ref=external_ref, due_at=due_at)
    get_success_data(
        api_client.record_assessment_outcome(
            ctx["assessment"]["id"],
            {"outcome": "NOT_CLEARED", "findings_summary": "not cleared"},
            ctx["ev_headers"],
        )
    )
    decisions = get_success_data(
        api_client.list_leave_decisions(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
    )
    assert isinstance(decisions, list) and len(decisions) == 1
    ctx["leave_decision"] = decisions[0]
    return ctx


def setup_case_on_leave(ctx: dict, external_ref: str = None) -> dict:
    """Full leave path: case ON_LEAVE, student LEAVE_OF_ABSENCE, plan SUSPENDED."""
    setup_case_in_leave_decision(ctx, external_ref=external_ref)
    get_success_data(
        api_client.decide_leave(
            ctx["leave_decision"]["id"],
            {"decision": "GRANT_LEAVE", "rationale": "safety"},
            ctx["dean_headers"],
        )
    )
    return ctx


def file_reentry_petition(ctx: dict, case_id: str, petitioner: str = "cm"):
    version = get_case_version(ctx, case_id)
    payload = create_reentry_evaluation_payload(
        case_id=case_id, expected_case_version=version,
    )
    return api_client.create_reentry_evaluation(payload, ctx[f"{petitioner}_headers"])


def setup_reentry_pending(ctx: dict, external_ref: str = None) -> dict:
    """Case in REENTRY_REVIEW with a PENDING ReentryEvaluation (``reentry``)."""
    setup_case_on_leave(ctx, external_ref=external_ref)
    ctx["reentry"] = get_success_data(file_reentry_petition(ctx, ctx["case_id"]))
    return ctx


# ---------------------------------------------------------------------------
# Disclosure grant helpers
# ---------------------------------------------------------------------------


def request_grant(ctx: dict, case_id: str, to_office: str = "RESIDENCE_LIFE",
                  scope: str = "SUMMARY_ONLY",
                  effective_from: str = "2026-08-01T00:00:00Z",
                  expires_at: str = "2026-09-01T00:00:00Z",
                  purpose: str = "coordination"):
    payload = create_disclosure_grant_payload(
        case_id=case_id, to_office=to_office, scope=scope,
        effective_from=effective_from, expires_at=expires_at, purpose=purpose,
    )
    return api_client.create_disclosure_grant(payload, ctx["cm_headers"])


def setup_approved_grant(ctx: dict, case_id: str, to_office: str = "RESIDENCE_LIFE",
                         scope: str = "SUMMARY_ONLY",
                         effective_from: str = "2026-08-01T00:00:00Z",
                         expires_at: str = "2026-09-01T00:00:00Z") -> dict:
    grant = get_success_data(
        request_grant(ctx, case_id, to_office=to_office, scope=scope,
                      effective_from=effective_from, expires_at=expires_at)
    )
    return get_success_data(
        api_client.approve_disclosure_grant(grant["id"], ctx["po_headers"])
    )


def set_clock(ctx: dict, to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ctx["admin_headers"]))
