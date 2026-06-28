"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the clinic to be in a state that takes 5-15 API
calls to reach (register a child, create a therapist, author and finalize an
evaluation, build and activate a plan of care, create an authorization, book
appointments, ...). These helpers encapsulate those chains so tests focus on
assertions.

Identity threading (PRD §2.1): Evaluator and Therapist X-User-ID is the id of the
acting Therapist record. Every ownership/authorship-sensitive call here uses
make_evaluator_headers(therapist_id) / make_therapist_headers(therapist_id) with
the real therapist id, never the shared TEST_USERS fallback.

Each fixture uses get_success_data() (lenient) internally so a setup failure
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Every helper builds its preconditions from scratch: the server database is empty
at the start of every test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_child_payload, create_therapist_payload, create_evaluation_payload,
    create_plan_of_care_payload, create_goal_payload, create_authorization_payload,
    create_appointment_payload, complete_appointment_payload,
    create_coordination_plan_payload, create_home_program_payload,
    create_waitlist_entry_payload,
)
from .test_users import TEST_USERS, make_evaluator_headers, make_therapist_headers

ADMIN = TEST_USERS["clinic_admin_headers"]
COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]


# ─── Clock ───────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the logical clock; returns the clock response data
    ({current_utc, expired_authorization_ids})."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1/2: Base entities ────────────────────────────────────────────

def create_child(full_name="Test Child", date_of_birth="2023-01-01"):
    return get_success_data(api_client.create_child(
        create_child_payload(full_name=full_name, date_of_birth=date_of_birth), ADMIN))


def create_therapist(full_name="Test Therapist", discipline="SLP",
                     max_caseload=5, weekly_visit_minutes_cap=600):
    return get_success_data(api_client.create_therapist(
        create_therapist_payload(full_name=full_name, discipline=discipline,
                                 max_caseload=max_caseload,
                                 weekly_visit_minutes_cap=weekly_visit_minutes_cap),
        ADMIN))


def create_finalized_evaluation(child_id, therapist_id, discipline="SLP", severity_score=40):
    """Create a DRAFT evaluation as the Evaluator (acting as therapist_id) and
    finalize it. Returns the FINALIZED evaluation."""
    ev = get_success_data(api_client.create_evaluation(
        create_evaluation_payload(child_id, discipline=discipline, severity_score=severity_score),
        make_evaluator_headers(therapist_id)))
    return get_success_data(api_client.finalize_evaluation(
        ev["id"], make_evaluator_headers(therapist_id)))


def create_active_plan(child_id, evaluation_id, therapist_id, planned_weekly_minutes=60):
    """Create a DRAFT plan from a finalized evaluation and activate it. Returns
    the ACTIVE plan of care."""
    poc = get_success_data(api_client.create_plan_of_care(
        create_plan_of_care_payload(child_id, evaluation_id, therapist_id,
                                    planned_weekly_minutes=planned_weekly_minutes),
        make_evaluator_headers(therapist_id)))
    return get_success_data(api_client.activate_plan_of_care(
        poc["id"], make_evaluator_headers(therapist_id)))


def create_authorization(child_id, discipline="SLP", authorized_visits=3,
                         valid_from=None, valid_until=None):
    overrides = {"discipline": discipline, "authorized_visits": authorized_visits}
    if valid_from is not None:
        overrides["valid_from"] = valid_from
    if valid_until is not None:
        overrides["valid_until"] = valid_until
    return get_success_data(api_client.create_authorization(
        create_authorization_payload(child_id, **overrides), ADMIN))


def add_goal(plan_id, therapist_id, description="Test goal", weight=1,
             baseline_pct=0, target_pct=50):
    return get_success_data(api_client.create_goal(
        plan_id,
        create_goal_payload(description=description, weight=weight,
                            baseline_pct=baseline_pct, target_pct=target_pct),
        make_therapist_headers(therapist_id)))


# ─── Tier 2: Composite "active care" scenario ────────────────────────────

def setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP",
                      severity_score=40, max_caseload=5,
                      weekly_visit_minutes_cap=600, authorized_visits=3,
                      planned_weekly_minutes=60, valid_from=None, valid_until=None,
                      child_dob="2023-01-01"):
    """Full happy-path foundation: set clock, create a therapist, register a
    child, finalize an evaluation, activate a plan of care, and create an
    authorization. Returns dict with therapist, child, evaluation, plan, auth.

    This is the most common preamble across the test suite.
    """
    set_clock(clock)
    therapist = create_therapist(discipline=discipline, max_caseload=max_caseload,
                                 weekly_visit_minutes_cap=weekly_visit_minutes_cap)
    child = create_child(date_of_birth=child_dob)
    evaluation = create_finalized_evaluation(child["id"], therapist["id"],
                                             discipline=discipline,
                                             severity_score=severity_score)
    plan = create_active_plan(child["id"], evaluation["id"], therapist["id"],
                              planned_weekly_minutes=planned_weekly_minutes)
    auth = create_authorization(child["id"], discipline=discipline,
                                authorized_visits=authorized_visits,
                                valid_from=valid_from, valid_until=valid_until)
    return {
        "therapist": therapist,
        "child": child,
        "evaluation": evaluation,
        "plan": plan,
        "auth": auth,
    }


# ─── Tier 3: Booking & lifecycle shortcuts ───────────────────────────────

def book_appointment(ctx, start_time, end_time, headers=None,
                     child_id=None, therapist_id=None, authorization_id=None,
                     plan_of_care_id=None):
    """Book one appointment from a setup_active_care ctx (or explicit ids).
    Returns the raw response so callers can assert on success or error."""
    return api_client.create_appointment(
        create_appointment_payload(
            child_id or ctx["child"]["id"],
            therapist_id or ctx["therapist"]["id"],
            authorization_id or ctx["auth"]["id"],
            plan_of_care_id or ctx["plan"]["id"],
            start_time, end_time),
        headers or ADMIN)


def book_appointment_ok(ctx, start_time, end_time, **kwargs):
    """Book one appointment expecting success. Returns the appointment data."""
    return get_success_data(book_appointment(ctx, start_time, end_time, **kwargs))


def complete_appointment(appointment_id, therapist_id, narrative="Session completed fine.",
                         minutes_delivered=45, goal_progress_entries=None):
    """Complete a (past) appointment as its Therapist. Returns the response."""
    return api_client.complete_appointment(
        appointment_id,
        complete_appointment_payload(narrative=narrative,
                                     minutes_delivered=minutes_delivered,
                                     goal_progress_entries=goal_progress_entries),
        make_therapist_headers(therapist_id))


def get_authorization(authorization_id):
    return get_success_data(api_client.get_authorization(authorization_id, ADMIN))


def get_appointment(appointment_id):
    return get_success_data(api_client.get_appointment(appointment_id, ADMIN))


def get_goal(goal_id):
    return get_success_data(api_client.get_goal(goal_id, ADMIN))


def get_plan(plan_id):
    return get_success_data(api_client.get_plan_of_care(plan_id, ADMIN))


def get_therapist(therapist_id):
    return get_success_data(api_client.get_therapist(therapist_id, ADMIN))


def get_child(child_id):
    return get_success_data(api_client.get_child(child_id, ADMIN))


def get_waitlist_entry(waitlist_entry_id):
    return get_success_data(api_client.get_waitlist_entry(waitlist_entry_id, ADMIN))


# ─── Tier 3/4: Authorization at EXHAUSTED via a single reserved visit ─────

def setup_exhausted_authorization(clock="2026-06-05T12:00:00Z", discipline="SLP",
                                  appt_start="2026-06-10T09:00:00Z",
                                  appt_end="2026-06-10T09:45:00Z"):
    """Active care with an authorization of authorized_visits=1 fully reserved by
    one SCHEDULED appointment, so available_visits==0 and the authorization is
    EXHAUSTED. Returns (ctx, appointment).
    """
    ctx = setup_active_care(clock=clock, discipline=discipline, authorized_visits=1)
    appt = book_appointment_ok(ctx, appt_start, appt_end)
    return ctx, appt


# ─── Tier 4: Two-goal plan (combinatorial roll-up) ───────────────────────

def setup_two_goal_plan(clock="2026-06-20T12:00:00Z", discipline="OT",
                        severity_score=72,
                        goal_a=dict(description="Goal A", weight=2, baseline_pct=20, target_pct=70),
                        goal_b=dict(description="Goal B", weight=3, baseline_pct=0, target_pct=50)):
    """Active care with two OPEN goals on the plan. Returns dict with the active
    care ctx plus goal_a / goal_b ids."""
    ctx = setup_active_care(clock=clock, discipline=discipline,
                            severity_score=severity_score, planned_weekly_minutes=90)
    ga = add_goal(ctx["plan"]["id"], ctx["therapist"]["id"], **goal_a)
    gb = add_goal(ctx["plan"]["id"], ctx["therapist"]["id"], **goal_b)
    ctx["goal_a"] = ga
    ctx["goal_b"] = gb
    return ctx


# ─── Tier 4: Reauth (request, then ready-to-grant) ───────────────────────

def request_reauth(authorization_id, expected_version):
    return get_success_data(api_client.request_reauth(
        authorization_id, {"expected_authorization_version": expected_version}, ADMIN))


def setup_reauth_requested(clock="2026-06-05T12:00:00Z", authorized_visits=2):
    """Create a child + authorization, move the authorization into
    REAUTH_REQUESTED, returning (child, auth_after_request, version_after_request)
    where the version is freshly captured (suitable for a subsequent grant)."""
    set_clock(clock)
    child = create_child()
    auth = create_authorization(child["id"], authorized_visits=authorized_visits)
    requested = request_reauth(auth["id"], auth["version"])
    return child, requested, requested["version"]


# ─── Tier 4: Waitlist promotion scenarios ────────────────────────────────

def create_child_with_active_plan_and_auth(therapist_id, discipline="SLP",
                                           severity_score=50, authorized_visits=3,
                                           full_name="Kid"):
    """Register a child, finalize an evaluation against the shared therapist,
    activate a plan, and create an authorization with available visits. Returns
    dict {child, evaluation, plan, auth}."""
    child = create_child(full_name=full_name)
    evaluation = create_finalized_evaluation(child["id"], therapist_id,
                                             discipline=discipline,
                                             severity_score=severity_score)
    plan = create_active_plan(child["id"], evaluation["id"], therapist_id)
    auth = create_authorization(child["id"], discipline=discipline,
                                authorized_visits=authorized_visits)
    return {"child": child, "evaluation": evaluation, "plan": plan, "auth": auth}


def add_waitlist_entry(child_id, therapist_id, evaluation_id, discipline="SLP",
                       requested_minutes=45):
    return get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(child_id, therapist_id, evaluation_id,
                                      discipline=discipline,
                                      requested_minutes=requested_minutes),
        COORDINATOR))
