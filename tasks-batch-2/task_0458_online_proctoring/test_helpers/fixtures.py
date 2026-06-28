"""Composite setup helpers for multi-step test prerequisites (Online Proctoring API).

Uses get_success_data() (lenient validator) for every setup call so that a broken
precondition surfaces as a clear "Setup step failed" error rather than a confusing
downstream assertion failure.

Identity threading: every fixture that needs an ownership-gated call (check-in by a
Candidate, flag/escalation by a Proctor, claim/decide/retake by a ReviewOfficer)
calls the matching make_<role>_headers(<entity id>) builder with the real id —
never the shared TEST_USERS constant — per PRD §2.1.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_institution_payload,
    create_proctor_payload,
    create_candidate_payload,
    create_exam_payload,
    create_accommodation_payload,
    create_appointment_payload,
    create_identity_verification_payload,
    create_incident_flag_payload,
    create_escalation_payload,
    create_decide_payload,
    create_integrity_report_payload,
    create_retake_authorization_payload,
)
from .test_users import (
    TEST_USERS,
    make_coordinator_headers,
    make_proctor_headers,
    make_review_officer_headers,
    make_candidate_headers,
)

COORD = TEST_USERS["coordinator_headers"]

# Monotonic email generator so candidate-email uniqueness within an institution
# never collides across the many candidates a single test may create.
_email_counter = itertools.count()


def _unique_email(prefix="cand"):
    return f"{prefix}{next(_email_counter)}@example.com"


# ─── Tier 0: Primitive creators ───────────────────────

def create_institution(name="Test Institution", **overrides):
    res = api_client.create_institution(create_institution_payload(name=name, **overrides), COORD)
    return get_success_data(res)


def create_proctor(institution_id, full_name="Test Proctor", concurrent_capacity=4):
    res = api_client.create_proctor(
        create_proctor_payload(institution_id, full_name=full_name,
                               concurrent_capacity=concurrent_capacity),
        COORD,
    )
    return get_success_data(res)


def create_candidate(institution_id, full_name="Test Candidate", email=None):
    res = api_client.create_candidate(
        create_candidate_payload(institution_id, email or _unique_email(),
                                 full_name=full_name),
        COORD,
    )
    return get_success_data(res)


def create_exam(institution_id, monitoring_mode="LIVE", base_duration_minutes=60,
                window_start_utc="2026-07-01T08:00:00Z",
                window_end_utc="2026-07-01T23:00:00Z",
                lockdown_required=False, title="Test Exam", **overrides):
    res = api_client.create_exam(
        create_exam_payload(
            institution_id, title=title, monitoring_mode=monitoring_mode,
            base_duration_minutes=base_duration_minutes,
            window_start_utc=window_start_utc, window_end_utc=window_end_utc,
            lockdown_required=lockdown_required, **overrides,
        ),
        COORD,
    )
    return get_success_data(res)


def create_accommodation(candidate_id, exam_id, **overrides):
    res = api_client.create_accommodation(
        create_accommodation_payload(candidate_id, exam_id, **overrides), COORD)
    return get_success_data(res)


def create_appointment(exam_id, candidate_id, proctor_id, scheduled_start_utc, **overrides):
    res = api_client.create_appointment(
        create_appointment_payload(exam_id, candidate_id, proctor_id,
                                   scheduled_start_utc, **overrides),
        COORD,
    )
    return get_success_data(res)


def set_clock(to_iso8601):
    get_success_data(api_client.set_clock(to_iso8601, COORD))


# ─── Tier 1: Base catalog ─────────────────────────────

def setup_catalog(monitoring_mode="LIVE", base_duration_minutes=60,
                  concurrent_capacity=4, lockdown_required=False,
                  window_start_utc="2026-07-01T08:00:00Z",
                  window_end_utc="2026-07-01T23:00:00Z",
                  report_threshold_score=None):
    """Institution + one proctor + one candidate + one exam. Returns a dict of all four."""
    inst_kwargs = {}
    if report_threshold_score is not None:
        inst_kwargs["report_threshold_score"] = report_threshold_score
    institution = create_institution(**inst_kwargs)
    proctor = create_proctor(institution["id"], concurrent_capacity=concurrent_capacity)
    candidate = create_candidate(institution["id"])
    exam = create_exam(
        institution["id"], monitoring_mode=monitoring_mode,
        base_duration_minutes=base_duration_minutes,
        window_start_utc=window_start_utc, window_end_utc=window_end_utc,
        lockdown_required=lockdown_required,
    )
    return {
        "institution": institution,
        "proctor": proctor,
        "candidate": candidate,
        "exam": exam,
    }


# ─── Tier 2: Active session ───────────────────────────

def create_active_session(monitoring_mode="LIVE", base_duration_minutes=60,
                          concurrent_capacity=4,
                          scheduled_start_utc="2026-07-01T09:00:00Z"):
    """Catalog + scheduled appointment + check-in -> one ACTIVE session.

    Advances the logical clock to the appointment start so the check-in passes the
    temporal gate. Returns a dict including the session, appointment, proctor,
    candidate, exam, and institution.
    """
    cat = setup_catalog(monitoring_mode=monitoring_mode,
                        base_duration_minutes=base_duration_minutes,
                        concurrent_capacity=concurrent_capacity,
                        lockdown_required=False)
    set_clock(scheduled_start_utc)
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], scheduled_start_utc)
    session = get_success_data(
        api_client.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"])))
    return {**cat, "appointment": appt, "session": session}


def raise_flag(session_id, proctor_id, kind, severity):
    """Raise one incident flag as the owning proctor. Returns the flag (or the void
    cascade payload if the flag tipped the session — callers re-read the session)."""
    res = api_client.raise_flag(
        session_id, create_incident_flag_payload(kind, severity),
        make_proctor_headers(proctor_id))
    return get_success_data(res)


def get_session(session_id, proctor_id):
    return get_success_data(
        api_client.get_session(session_id, make_proctor_headers(proctor_id)))


# ─── Tier 3: Escalation pipelines ─────────────────────

def setup_session_with_open_escalation(
        monitoring_mode="LIVE",
        flag_kind="SECOND_FACE", flag_severity="MAJOR",
        scheduled_start_utc="2026-07-01T09:00:00Z"):
    """One ACTIVE session, a single flag raised, then an Escalation opened on it by the
    session proctor. The session is now REVIEW_HELD, the flag ESCALATED. A separate
    review officer proctor is provisioned (distinct id) for the claim/decide steps.

    Returns a dict with session, appointment, flag, escalation, opener (the session
    proctor), officer (the separate review officer), candidate, exam, institution.
    """
    cat = setup_catalog(monitoring_mode=monitoring_mode, lockdown_required=False)
    opener = cat["proctor"]
    officer = create_proctor(cat["institution"]["id"], full_name="Review Officer")
    set_clock(scheduled_start_utc)
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              opener["id"], scheduled_start_utc)
    session = get_success_data(
        api_client.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"])))
    flag = raise_flag(session["id"], opener["id"], flag_kind, flag_severity)
    escalation = get_success_data(api_client.create_escalation(
        create_escalation_payload(session["id"], flag["id"]),
        make_proctor_headers(opener["id"])))
    return {
        "institution": cat["institution"],
        "exam": cat["exam"],
        "candidate": cat["candidate"],
        "opener": opener,
        "officer": officer,
        "appointment": appt,
        "session": session,
        "flag": flag,
        "escalation": escalation,
    }


def setup_under_review_escalation(monitoring_mode="LIVE",
                                  flag_kind="SECOND_FACE", flag_severity="MAJOR",
                                  scheduled_start_utc="2026-07-01T09:00:00Z"):
    """As setup_session_with_open_escalation, plus the separate review officer CLAIMS
    the escalation (status -> UNDER_REVIEW, version bumped). Returns the same dict with
    the escalation re-read post-claim under key 'escalation' and the claimed version
    under 'escalation_version'."""
    ctx = setup_session_with_open_escalation(
        monitoring_mode=monitoring_mode, flag_kind=flag_kind,
        flag_severity=flag_severity, scheduled_start_utc=scheduled_start_utc)
    claimed = get_success_data(api_client.claim_escalation(
        ctx["escalation"]["id"], make_review_officer_headers(ctx["officer"]["id"])))
    ctx["escalation"] = claimed
    ctx["escalation_version"] = claimed["version"]
    return ctx


# ─── Tier 4: Terminal sessions and reports ────────────

def create_completed_session(monitoring_mode="LIVE",
                             scheduled_start_utc="2026-07-01T09:00:00Z"):
    """One session run cleanly and COMPLETED (score 100). Returns the active-session
    context dict plus the completed session under key 'session'."""
    ctx = create_active_session(monitoring_mode=monitoring_mode,
                                scheduled_start_utc=scheduled_start_utc)
    completed = get_success_data(api_client.complete_session(
        ctx["session"]["id"], make_proctor_headers(ctx["proctor"]["id"])))
    ctx["session"] = completed
    return ctx


def create_voided_session_via_autothreshold(scheduled_start_utc="2026-07-01T09:00:00Z"):
    """One session driven to VOIDED via auto-threshold: a CRITICAL flag (penalty 40,
    score 60) then a MAJOR flag (penalty 55, score 45 < 50) auto-voids it. Returns the
    active-session context dict; the voided session is re-read under key 'session'."""
    ctx = create_active_session(scheduled_start_utc=scheduled_start_utc)
    raise_flag(ctx["session"]["id"], ctx["proctor"]["id"], "PROHIBITED_MATERIAL", "CRITICAL")
    raise_flag(ctx["session"]["id"], ctx["proctor"]["id"], "SECOND_FACE", "MAJOR")
    ctx["session"] = get_session(ctx["session"]["id"], ctx["proctor"]["id"])
    return ctx


def setup_authorized_retake(scheduled_start_utc="2026-07-01T09:00:00Z"):
    """A VOIDED session, a separate review officer, an AUTHORIZED retake on it, and the
    original appointment's current version read back. Returns a dict with session,
    appointment, retake, officer, opener (session proctor), original_version, plus the
    base catalog entities."""
    cat = setup_catalog(lockdown_required=False,
                        window_start_utc="2026-07-01T08:00:00Z",
                        window_end_utc="2026-07-01T23:00:00Z")
    opener = cat["proctor"]
    officer = create_proctor(cat["institution"]["id"], full_name="Review Officer")
    set_clock(scheduled_start_utc)
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              opener["id"], scheduled_start_utc)
    session = get_success_data(
        api_client.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"])))
    raise_flag(session["id"], opener["id"], "PROHIBITED_MATERIAL", "CRITICAL")
    raise_flag(session["id"], opener["id"], "SECOND_FACE", "MAJOR")
    retake = get_success_data(api_client.create_retake_authorization(
        create_retake_authorization_payload(session["id"]),
        make_review_officer_headers(officer["id"])))
    original = get_success_data(api_client.get_appointment(appt["id"], COORD))
    return {
        "institution": cat["institution"],
        "exam": cat["exam"],
        "candidate": cat["candidate"],
        "opener": opener,
        "officer": officer,
        "appointment": original,
        "session": get_session(session["id"], opener["id"]),
        "retake": retake,
        "original_version": original["version"],
    }


def build_terminal_session_with_score(institution_id, exam_id, candidate_id, proctor_id,
                                      flags, scheduled_start_utc, complete=True):
    """Check a candidate into a fresh appointment, raise the given flags, optionally
    complete, and return the (possibly completed) session. `flags` is a list of
    (kind, severity). The caller supplies a clock-aligned scheduled_start_utc and is
    responsible for setting the clock beforehand."""
    set_clock(scheduled_start_utc)
    appt = create_appointment(exam_id, candidate_id, proctor_id, scheduled_start_utc)
    session = get_success_data(
        api_client.check_in(appt["id"], make_candidate_headers(candidate_id)))
    for kind, severity in flags:
        raise_flag(session["id"], proctor_id, kind, severity)
    if complete:
        session = get_success_data(api_client.complete_session(
            session["id"], make_proctor_headers(proctor_id)))
    else:
        session = get_session(session["id"], proctor_id)
    return appt, session


def deliver_report(institution_id, candidate_id, exam_id, session_ids):
    """Draft + deliver an integrity report over the given terminal sessions. Returns the
    delivered report."""
    report = get_success_data(api_client.create_integrity_report(
        create_integrity_report_payload(institution_id, candidate_id, exam_id, session_ids),
        COORD))
    return get_success_data(api_client.deliver_integrity_report(report["id"], COORD))
