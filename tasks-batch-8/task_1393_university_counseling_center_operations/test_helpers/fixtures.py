"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database; the logical clock reads 2026-08-01T00:00:00Z at startup per PRD
section 2.5). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    book_session_payload,
    create_counselor_payload,
    create_crisis_shift_payload,
    create_crisis_visit_payload,
    create_group_program_payload,
    create_intake_payload,
    create_policy_payload,
    create_student_payload,
    match_referral_payload,
)
from .test_users import (
    TEST_USERS,
    make_clinical_director_headers,
    make_counselor_headers,
    make_triage_screener_headers,
)

FD = TEST_USERS["front_desk_headers"]
RC = TEST_USERS["referral_coordinator_headers"]
CD = TEST_USERS["clinical_director_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}")


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError:
        _fail(step, resp)


# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation
# ---------------------------------------------------------------------------

def create_counselor(license_id="LIC-1", full_name="Test Counselor",
                     specialties=None, weekly_capacity=20,
                     max_risk_points=1000, active=None):
    payload = create_counselor_payload(
        license_id=license_id, full_name=full_name,
        specialties=specialties or ["GEN"],
        weekly_individual_capacity=weekly_capacity,
        max_caseload_risk_points=max_risk_points)
    if active is not None:
        payload["active"] = active
    return _ok("create_counselor", api_client.create_counselor(payload, CD))


def create_student(student_number="S100", full_name="Test Student",
                   enrollment_status="ENROLLED", funding_model="STUDENT_FEE",
                   academic_record_flags=None):
    payload = create_student_payload(
        student_number=student_number, full_name=full_name,
        enrollment_status=enrollment_status, funding_model=funding_model)
    if academic_record_flags is not None:
        payload["academic_record_flags"] = academic_record_flags
    return _ok("create_student", api_client.create_student(payload, FD))


def create_policy_draft(academic_term="2026-FALL", base_session_limit=8,
                        no_show_strike_limit=3, late_cancel_window_hours=24):
    payload = create_policy_payload(
        academic_term=academic_term, base_session_limit=base_session_limit,
        no_show_strike_limit=no_show_strike_limit,
        late_cancel_window_hours=late_cancel_window_hours)
    return _ok("create_policy", api_client.create_policy(payload, CD))


def publish_policy(policy_id):
    return _ok("publish_policy", api_client.publish_policy(policy_id, CD))


def create_published_policy(academic_term="2026-FALL", base_session_limit=8,
                            no_show_strike_limit=3,
                            late_cancel_window_hours=24):
    policy = create_policy_draft(academic_term, base_session_limit,
                                 no_show_strike_limit,
                                 late_cancel_window_hours)
    return publish_policy(policy["id"])


def create_intake(student_id, screener_id, phq9=10, gad7=8,
                  ideation=False, attempt=False):
    """Create an intake assessment as TriageScreener with the screener's id."""
    payload = create_intake_payload(
        student_id, screener_id, phq9_score=phq9, gad7_score=gad7,
        ideation_flag=ideation, recent_attempt_flag=attempt)
    return _ok("create_intake",
               api_client.create_intake_assessment(
                   payload, make_triage_screener_headers(screener_id)))


def advance_clock(to_iso8601):
    return _ok("set_clock",
               api_client.set_clock({"to_iso8601": to_iso8601}, CD))


# ---------------------------------------------------------------------------
# Tier 2 — intake completion and episode creation
# ---------------------------------------------------------------------------

def complete_intake_short_term(assessment_id, counselor_id,
                               academic_term="2026-FALL"):
    """Complete a LOW/MODERATE intake, producing an OPEN CareEpisode."""
    payload = {"primary_counselor_id": counselor_id,
               "academic_term": academic_term}
    return _ok("complete_intake",
               api_client.complete_intake_assessment(
                   assessment_id, payload,
                   make_triage_screener_headers(counselor_id)))


def get_episode_for_student(student_id, counselor_id):
    data = _ok("list_episodes",
               api_client.list_episodes(
                   make_counselor_headers(counselor_id),
                   params={"student_id": student_id}))
    items = data if isinstance(data, list) else data.get("data", data)
    assert items, f"Setup failed: no episode found for student {student_id}"
    return items[0]


def setup_open_episode(student_number="S100", full_name="Test Student",
                       funding_model="STUDENT_FEE",
                       phq9=10, gad7=8, ideation=False, attempt=False,
                       academic_term="2026-FALL", base_session_limit=8,
                       no_show_strike_limit=3, late_cancel_window_hours=24,
                       weekly_capacity=20, max_risk_points=1000,
                       license_id="LIC-1", publish=True):
    """Counselor + (optionally) PUBLISHED policy + student + intake completed
    to SHORT_TERM_CARE. Returns (counselor, student, episode)."""
    counselor = create_counselor(license_id=license_id,
                                 weekly_capacity=weekly_capacity,
                                 max_risk_points=max_risk_points)
    if publish:
        create_published_policy(academic_term, base_session_limit,
                                no_show_strike_limit,
                                late_cancel_window_hours)
    student = create_student(student_number, full_name,
                             funding_model=funding_model)
    intake = create_intake(student["id"], counselor["id"],
                           phq9=phq9, gad7=gad7, ideation=ideation,
                           attempt=attempt)
    complete_intake_short_term(intake["id"], counselor["id"], academic_term)
    episode = get_episode_for_student(student["id"], counselor["id"])
    return counselor, student, episode


# ---------------------------------------------------------------------------
# Tier 3 — sessions
# ---------------------------------------------------------------------------

def book_session(episode_id, counselor_id, starts_at, duration_minutes=60,
                 director_override=None):
    """Re-read the episode for its current version, then book as FrontDesk."""
    episode = _ok("get_episode", api_client.get_episode(episode_id, FD))
    payload = book_session_payload(
        counselor_id, episode["version"], starts_at=starts_at,
        duration_minutes=duration_minutes)
    if director_override is not None:
        payload["director_override"] = director_override
    return _ok("book_session",
               api_client.book_session(episode_id, payload, FD))


def book_past_session_and_age(episode_id, counselor_id, starts_at,
                              age_clock_to, duration_minutes=60):
    """Book a session, then move the logical clock past its start so that
    completion / no-show determinations become legal."""
    session = book_session(episode_id, counselor_id, starts_at,
                           duration_minutes)
    advance_clock(age_clock_to)
    return session


def complete_session(session_id, counselor_id):
    return _ok("complete_session",
               api_client.complete_session(
                   session_id, make_counselor_headers(counselor_id)))


def mark_no_show(session_id, counselor_id, chargeable=True):
    return _ok("mark_no_show",
               api_client.mark_session_no_show(
                   session_id, {"chargeable": chargeable},
                   make_counselor_headers(counselor_id)))


def excuse_no_show(session_id, director_counselor_id):
    """ClinicalDirector overturns a charged no-show (compensating action)."""
    return _ok("excuse_no_show",
               api_client.excuse_session_no_show(
                   session_id,
                   make_clinical_director_headers(director_counselor_id)))


# ---------------------------------------------------------------------------
# Tier 4 — crisis coverage
# ---------------------------------------------------------------------------

def create_crisis_shift(coverage_date="2026-08-01", shift_kind="WALK_IN",
                        starts_at="2026-08-01T08:00:00Z",
                        ends_at="2026-08-01T20:00:00Z"):
    payload = create_crisis_shift_payload(
        coverage_date=coverage_date, shift_kind=shift_kind,
        starts_at=starts_at, ends_at=ends_at)
    return _ok("create_crisis_shift",
               api_client.create_crisis_shift(payload, CD))


def claim_shift(shift_id, counselor_id, expected_version=None):
    if expected_version is None:
        shift = _ok("get_crisis_shift",
                    api_client.get_crisis_shift(
                        shift_id, make_counselor_headers(counselor_id)))
        expected_version = shift["version"]
    return _ok("claim_shift",
               api_client.claim_crisis_shift(
                   shift_id,
                   {"expected_crisis_shift_version": expected_version},
                   make_counselor_headers(counselor_id)))


def create_claimed_shift(counselor_id, coverage_date="2026-08-01",
                         shift_kind="WALK_IN",
                         starts_at="2026-08-01T08:00:00Z",
                         ends_at="2026-08-01T20:00:00Z"):
    shift = create_crisis_shift(coverage_date, shift_kind, starts_at, ends_at)
    return claim_shift(shift["id"], counselor_id, shift["version"])


def create_queued_visit(student_id, shift_id, presenting_band, screener_id):
    payload = create_crisis_visit_payload(
        student_id, shift_id, presenting_risk_band=presenting_band)
    return _ok("create_crisis_visit",
               api_client.create_crisis_visit(
                   payload, make_triage_screener_headers(screener_id)))


def setup_stabilized_visit(counselor_license="LIC-1",
                           student_number="S100",
                           presenting_band="HIGH"):
    """Claimed WALK_IN shift + student + visit driven QUEUED -> IN_ROOM ->
    STABILIZED. Returns (counselor, student, shift, visit)."""
    counselor = create_counselor(license_id=counselor_license,
                                 specialties=["CRISIS"])
    shift = create_claimed_shift(counselor["id"])
    student = create_student(student_number)
    visit = create_queued_visit(student["id"], shift["id"],
                                presenting_band, counselor["id"])
    headers = make_counselor_headers(counselor["id"])
    visit = _ok("room_visit", api_client.room_crisis_visit(visit["id"], headers))
    visit = _ok("stabilize_visit",
                api_client.stabilize_crisis_visit(visit["id"], headers))
    return counselor, student, shift, visit


# ---------------------------------------------------------------------------
# Tier 4 — referrals
# ---------------------------------------------------------------------------

def setup_pending_referral_high(counselor_license="LIC-1",
                                student_number="S100",
                                funding_model="STUDENT_FEE"):
    """HIGH-band intake routed to COMMUNITY_REFERRAL. Returns
    (counselor, student, referral)."""
    counselor = create_counselor(license_id=counselor_license)
    student = create_student(student_number, funding_model=funding_model)
    intake = create_intake(student["id"], counselor["id"],
                           phq9=20, gad7=20)  # 40 points -> HIGH
    _ok("complete_intake_high",
        api_client.complete_intake_assessment(
            intake["id"], {}, make_triage_screener_headers(counselor["id"])))
    referrals = _ok("list_referrals",
                    api_client.list_referrals(
                        RC, params={"student_id": student["id"]}))
    items = referrals if isinstance(referrals, list) else referrals
    assert items, "Setup failed: no referral created for HIGH-band student"
    return counselor, student, items[0]


def match_referral(referral_id, provider_name="ProvA", specialty="GEN"):
    return _ok("match_referral",
               api_client.match_referral(
                   referral_id,
                   match_referral_payload(provider_name=provider_name,
                                          provider_specialty=specialty),
                   RC))


def decline_and_rematch(referral_id, provider_name="ProvA"):
    """One full MATCHED -> DECLINED -> PENDING loop."""
    _ok("decline_referral", api_client.decline_referral(referral_id, RC))
    return _ok("rematch_referral", api_client.rematch_referral(referral_id, RC))


# ---------------------------------------------------------------------------
# Tier 5 — accumulation / terminal-state scenarios
# ---------------------------------------------------------------------------

def setup_exhausted_episode(student_number="S100", license_id="LIC-1",
                            base_session_limit=4, phq9=10, gad7=8,
                            funding_model="STUDENT_FEE",
                            future_session_start="2026-08-12T09:00:00Z"):
    """Drive an episode to EXHAUSTED by completing exactly session_limit
    sessions. Returns a dict with counselor, student, episode, referral,
    completed session ids and the still-SCHEDULED future session.

    With base 4 and a MODERATE STUDENT_FEE student the limit is 4.
    """
    counselor, student, episode = setup_open_episode(
        student_number=student_number, funding_model=funding_model,
        phq9=phq9, gad7=gad7, base_session_limit=base_session_limit,
        no_show_strike_limit=5, license_id=license_id)
    limit = episode["session_limit"]
    past_starts = ["2026-08-02T%02d:00:00Z" % (8 + 2 * i)
                   for i in range(limit)]
    sessions = [book_session(episode["id"], counselor["id"], s)
                for s in past_starts]
    future_session = book_session(episode["id"], counselor["id"],
                                  future_session_start)
    advance_clock("2026-08-03T00:00:00Z")
    for s in sessions:
        complete_session(s["id"], counselor["id"])
    episode = _ok("get_episode", api_client.get_episode(episode["id"], FD))
    assert episode["status"] == "EXHAUSTED", (
        f"Setup failed: episode did not exhaust, status {episode['status']}")
    referrals = _ok("list_referrals",
                    api_client.list_referrals(
                        RC, params={"student_id": student["id"]}))
    return {
        "counselor": counselor,
        "student": student,
        "episode": episode,
        "sessions": sessions,
        "future_session": future_session,
        "referral": referrals[0] if referrals else None,
    }


def setup_student_with_strikes(strike_limit, num_strikes,
                               future_session_starts=(),
                               student_number="S100", license_id="LIC-1",
                               base_session_limit=8):
    """Student with an OPEN episode and `num_strikes` charged no-shows under
    a policy whose strike limit is `strike_limit`. Optionally books extra
    future sessions (post-strike) listed in future_session_starts — those are
    booked BEFORE the strikes land so the SUSPENDED cascade can reach them.
    Returns a context dict."""
    counselor, student, episode = setup_open_episode(
        student_number=student_number,
        base_session_limit=base_session_limit,
        no_show_strike_limit=strike_limit,
        license_id=license_id, weekly_capacity=30)
    past_sessions = []
    for i in range(num_strikes):
        past_sessions.append(book_session(
            episode["id"], counselor["id"],
            "2026-08-02T%02d:00:00Z" % (9 + 2 * i)))
    future_sessions = [book_session(episode["id"], counselor["id"], s)
                       for s in future_session_starts]
    advance_clock("2026-08-03T00:00:00Z")
    for s in past_sessions:
        mark_no_show(s["id"], counselor["id"], chargeable=True)
    episode = _ok("get_episode", api_client.get_episode(episode["id"], FD))
    student = _ok("get_student",
                  api_client.get_student(
                      student["id"],
                      make_clinical_director_headers(counselor["id"])))
    return {
        "counselor": counselor,
        "student": student,
        "episode": episode,
        "past_sessions": past_sessions,
        "future_sessions": future_sessions,
    }


# ---------------------------------------------------------------------------
# Tier 2 — groups
# ---------------------------------------------------------------------------

def create_group_program(facilitator_id, title="Support Group", capacity=5,
                         meeting_day="TUE", starts_at="2026-09-01T17:00:00Z",
                         weeks=8, risk_band_ceiling="HIGH"):
    payload = create_group_program_payload(
        facilitator_id, title=title, capacity=capacity,
        meeting_day=meeting_day, starts_at=starts_at, weeks=weeks,
        risk_band_ceiling=risk_band_ceiling)
    return _ok("create_group_program",
               api_client.create_group_program(
                   payload, make_counselor_headers(facilitator_id)))


def publish_program(program_id, facilitator_id):
    return _ok("publish_program",
               api_client.publish_group_program(
                   program_id, make_counselor_headers(facilitator_id)))


def create_open_program(facilitator_id, **kwargs):
    program = create_group_program(facilitator_id, **kwargs)
    return publish_program(program["id"], facilitator_id)


def enroll_student(program_id, student_id):
    return _ok("enroll_student",
               api_client.enroll_in_group_program(
                   program_id, {"student_id": student_id}, FD))
