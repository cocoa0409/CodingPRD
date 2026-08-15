"""Composite setup helpers.

Every fixture builds its preconditions from an empty database using only
PRD-declared endpoints. The standard date plan (used by most scenarios):

  2026-08-01  coaches / clients / tiers created
  2026-08-02  discovery call at 10:00Z (45 min), completed, fit-assessed
  2026-08-03  enrollment paid -> ACTIVE (activated_at = 2026-08-03)

Fixtures use get_success_data() so setup failures surface as clear
"Setup failed" errors instead of confusing assertion failures.
"""
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, TEST_DEFAULTS, TIER_PKG8
from .factories import (
    create_client_payload,
    create_coach_payload,
    create_cohort_payload,
    create_discovery_call_payload,
    create_enrollment_payload,
    create_fit_assessment_payload,
    create_goal_payload,
    create_program_tier_payload,
    create_session_payload,
    create_testimonial_payload,
    simulate_payment_payload,
)
from .test_users import TEST_USERS, make_client_headers, make_coach_headers

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["practice_manager_headers"]


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def reset_clock():
    """Pin the logical clock at the documented epoch (PRD §2.5)."""
    set_clock(CLOCK_EPOCH)


def create_coach(verify: bool = True, **overrides) -> dict:
    """Register a coach; verify the credential by default. Returns Coach."""
    resp = api_client.create_coach(create_coach_payload(**overrides), PM)
    coach = get_success_data(resp)
    if verify:
        resp = api_client.verify_credential(coach["id"], PM)
        coach = get_success_data(resp)
    return coach


def create_client(**overrides) -> dict:
    resp = api_client.create_client(create_client_payload(**overrides), PM)
    return get_success_data(resp)


def create_tier(**overrides) -> dict:
    resp = api_client.create_program_tier(
        create_program_tier_payload(**overrides), ADMIN)
    return get_success_data(resp)


def setup_coach_pair() -> Tuple[dict, dict]:
    """Two VERIFIED coaches: (coach_a, coach_b). coach_b plays the
    segregation-of-duties assessor role for discovery calls taken by coach_a.
    Clock is pinned at the epoch."""
    reset_clock()
    coach_a = create_coach(credential_level="PCC")
    coach_b = create_coach(credential_level="MCC")
    return coach_a, coach_b


def complete_discovery_call_with_fit(
    client: dict,
    coach_a: dict,
    assessor: dict,
    scheduled_start: str = "2026-08-02T10:00:00Z",
    duration_minutes: int = 45,
    scope_fit: str = "WITHIN_SCOPE",
    commitment_score: int = 70,
) -> dict:
    """Book a discovery call, advance the clock past its start, have the
    owning coach complete it, and have the assessor file the fit assessment.
    Returns the fit assessment response data (includes computed outcome)."""
    client_h = make_client_headers(client["id"])
    coach_h = make_coach_headers(coach_a["id"])
    resp = api_client.create_discovery_call(
        create_discovery_call_payload(
            client["id"], coach_a["id"],
            scheduled_start=scheduled_start, duration_minutes=duration_minutes),
        client_h,
    )
    call = get_success_data(resp)
    set_clock("2026-08-02T12:30:00Z")
    get_success_data(api_client.complete_discovery_call(call["id"], coach_h))
    resp = api_client.create_fit_assessment(
        call["id"],
        create_fit_assessment_payload(
            scope_fit=scope_fit, commitment_score=commitment_score),
        make_coach_headers(assessor["id"]),
    )
    fa = get_success_data(resp)
    fa["_call"] = call
    return fa


def create_fit_approved_enrollment(
    client: dict,
    coach_a: dict,
    assessor: dict,
    tier: dict,
    installment_count: int = 1,
    scheduled_start: str = "2026-08-02T10:00:00Z",
    duration_minutes: int = 45,
    commitment_score: int = 70,
) -> dict:
    """Discovery call -> complete -> PROCEED fit -> enrollment created
    (PENDING_PAYMENT). Returns the enrollment."""
    fa = complete_discovery_call_with_fit(
        client, coach_a, assessor,
        scheduled_start=scheduled_start, duration_minutes=duration_minutes,
        commitment_score=commitment_score,
    )
    resp = api_client.create_enrollment(
        create_enrollment_payload(
            client["id"], coach_a["id"], tier["id"], fa["_call"]["id"],
            installment_count=installment_count),
        make_client_headers(client["id"]),
    )
    return get_success_data(resp)


def activate_enrollment(enrollment_id: str, pay_date: str = "2026-08-03T00:00:00Z") -> dict:
    """Advance the clock to pay_date and pay the first installment so the
    enrollment activates. Returns the refreshed enrollment."""
    set_clock(pay_date)
    resp = api_client.simulate_payment(
        simulate_payment_payload(enrollment_id), ADMIN)
    return get_success_data(resp)


def setup_active_enrollment(
    installment_count: int = 1,
    tier_overrides: Optional[dict] = None,
    coach_overrides: Optional[dict] = None,
    activation_date: str = "2026-08-03T00:00:00Z",
) -> dict:
    """The canonical scenario: VERIFIED coach + assessor, one client, one
    tier, one fit-approved enrollment paid to ACTIVE on 2026-08-03.

    Returns a dict with keys: coach_a, coach_b, client, tier, enrollment.
    """
    coach_a, coach_b = setup_coach_pair()
    if coach_overrides:
        # rebuild coach_a with overrides (e.g. credential expiry, capacity)
        coach_a = create_coach(**coach_overrides)
    client = create_client()
    tier = create_tier(**(tier_overrides or {}))
    enrollment = create_fit_approved_enrollment(
        client, coach_a, coach_b, tier, installment_count=installment_count)
    enrollment = activate_enrollment(enrollment["id"], activation_date)
    return {
        "coach_a": coach_a,
        "coach_b": coach_b,
        "client": client,
        "tier": tier,
        "enrollment": enrollment,
    }


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, PM))


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_session(session_id, PM))


def get_client(client_id: str, params: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.get_client(client_id, PM, params=params))


def get_coach(coach_id: str) -> dict:
    return get_success_data(api_client.get_coach(coach_id, PM))


def get_cohort(cohort_id: str) -> dict:
    return get_success_data(api_client.get_cohort(cohort_id, PM))


def get_membership(cohort_id: str, membership_id: str) -> dict:
    """Fetch one membership by filtering the cohort's member list by id."""
    data, _meta = _list_members(cohort_id)
    for m in data:
        if m["id"] == membership_id:
            return m
    raise AssertionError(f"Setup failed: membership {membership_id} not found")


def _list_members(cohort_id: str):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_cohort_members(cohort_id, PM)
    return validate_paginated(resp)


def book_session(enrollment_id: str, client: dict,
                 scheduled_start: str = "2026-08-10T10:00:00Z",
                 duration_minutes: int = 60, **overrides) -> dict:
    """Book a session as the owning client. Returns the Session."""
    resp = api_client.book_session(
        enrollment_id,
        create_session_payload(
            scheduled_start=scheduled_start,
            duration_minutes=duration_minutes, **overrides),
        make_client_headers(client["id"]),
    )
    return get_success_data(resp)


def complete_session(session_id: str, coach: dict) -> dict:
    resp = api_client.complete_session(session_id, make_coach_headers(coach["id"]))
    return get_success_data(resp)


def pause_enrollment(enrollment_id: str, client: dict) -> dict:
    """OCC-correct pause: read the fresh version, then pause."""
    fresh = get_enrollment(enrollment_id)
    resp = api_client.pause_enrollment(
        enrollment_id,
        {"expected_enrollment_version": fresh["version"]},
        make_client_headers(client["id"]),
    )
    return get_success_data(resp)


def resume_enrollment(enrollment_id: str, client: dict) -> dict:
    fresh = get_enrollment(enrollment_id)
    resp = api_client.resume_enrollment(
        enrollment_id,
        {"expected_enrollment_version": fresh["version"]},
        make_client_headers(client["id"]),
    )
    return get_success_data(resp)


def create_open_cohort(coach: dict, capacity: int = 3,
                       window_start: str = "2026-08-10",
                       window_end: str = "2026-09-10",
                       title: str = "Momentum Group") -> dict:
    """Create a cohort as its facilitating coach and open it. Returns Cohort."""
    coach_h = make_coach_headers(coach["id"])
    resp = api_client.create_cohort(
        create_cohort_payload(
            coach["id"], title=title, capacity=capacity,
            window_start=window_start, window_end=window_end),
        coach_h,
    )
    cohort = get_success_data(resp)
    resp = api_client.open_cohort(cohort["id"], coach_h)
    return get_success_data(resp)


def add_member(cohort_id: str, enrollment_id: str, coach: dict) -> dict:
    resp = api_client.add_cohort_member(
        cohort_id, {"enrollment_id": enrollment_id},
        make_coach_headers(coach["id"]),
    )
    return get_success_data(resp)


def create_goal(enrollment_id: str, client: dict, title: str = "Habit goal",
                target_count: int = 5) -> dict:
    resp = api_client.create_goal(
        enrollment_id,
        create_goal_payload(title=title, target_count=target_count),
        make_client_headers(client["id"]),
    )
    return get_success_data(resp)


def file_check_in(goal_id: str, client: dict, check_in_date: str,
                  completed: bool = True) -> dict:
    resp = api_client.create_check_in(
        goal_id, {"check_in_date": check_in_date, "completed": completed},
        make_client_headers(client["id"]),
    )
    return get_success_data(resp)


def create_testimonial(enrollment_id: str, client: dict,
                       outcome_rating: int = 5,
                       body_text: str = "Transformed my mornings.") -> dict:
    resp = api_client.create_testimonial(
        create_testimonial_payload(
            enrollment_id, outcome_rating=outcome_rating, body_text=body_text),
        make_client_headers(client["id"]),
    )
    return get_success_data(resp)


def setup_multi_client_active_enrollments(
    client_count: int,
    tier_overrides: Optional[dict] = None,
    coach_overrides: Optional[dict] = None,
) -> dict:
    """One VERIFIED coach pair + N clients, each with a fit-approved,
    ACTIVE-since-2026-08-03 enrollment. Discovery calls are staggered
    (09:00, 10:00, 11:00, ... 30 min each) so they never collide.

    Returns dict: coach_a, coach_b, tier, clients[list], enrollments[list].
    """
    coach_a, coach_b = setup_coach_pair()
    if coach_overrides:
        coach_a = create_coach(**coach_overrides)
    tier = create_tier(**(tier_overrides or {}))
    clients: List[dict] = []
    enrollments: List[dict] = []
    for i in range(client_count):
        client = create_client()
        start_hour = 9 + i  # 09:00, 10:00, 11:00 — non-overlapping 30m calls
        enrollment = create_fit_approved_enrollment(
            client, coach_a, coach_b, tier,
            installment_count=1,
            scheduled_start=f"2026-08-02T{start_hour:02d}:00:00Z",
            duration_minutes=30,
        )
        clients.append(client)
        enrollments.append(enrollment)
    activated = [
        activate_enrollment(e["id"], "2026-08-03T00:00:00Z") for e in enrollments
    ]
    return {
        "coach_a": coach_a,
        "coach_b": coach_b,
        "tier": tier,
        "clients": clients,
        "enrollments": activated,
    }


def complete_sessions_for_enrollment(enrollment_id: str, client: dict, coach: dict,
                                     count: int,
                                     start_date_prefix: str = "2026-08-04",
                                     hour: int = 10) -> List[dict]:
    """Book and complete `count` sessions on consecutive days at `hour`:00Z.
    The clock is advanced past each start before completion. Returns sessions."""
    sessions: List[dict] = []
    for i in range(count):
        day = int(start_date_prefix[-2:]) + i
        start = f"2026-08-{day:02d}T{hour:02d}:00:00Z"
        sess = book_session(enrollment_id, client, scheduled_start=start)
        set_clock(f"2026-08-{day:02d}T{hour + 1:02d}:30:00Z")
        sessions.append(complete_session(sess["id"], coach))
    return sessions
