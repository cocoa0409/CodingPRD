"""Composite setup helpers — multi-step entity builders used across the suite.

Every helper drives only PRD-declared endpoints and builds from scratch (the
harness restarts the server before each test, so each test starts empty).
`get_success_data` is used inside fixtures so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
    DEFAULT_SCHEDULED_FOR,
    DEFAULT_WORK_INSTANT,
)
from .factories import (
    create_vendor_payload,
    create_instrument_payload,
    create_evidence_payload,
    create_guide_payload,
    create_guide_revision_payload,
    create_requisition_payload,
    create_cycle_payload,
    create_candidate_payload,
    create_invitation_payload,
    schedule_assessment_payload,
    complete_assessment_payload,
    create_accommodation_request_payload,
    create_interviewer_payload,
    create_calibration_payload,
    certify_calibration_payload,
    create_session_payload,
    create_scorecard_payload,
    create_decision_payload,
    create_snapshot_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_hm_headers,
    make_do_headers,
    make_co_headers,
    make_interviewer_headers,
    make_candidate_headers,
    make_vendorrep_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
HM = TEST_USERS["hm_headers"]
DO = TEST_USERS["do_headers"]
CO = TEST_USERS["co_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def create_vendor(**overrides):
    resp = api_client.create_vendor(create_vendor_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_instrument(vendor_id, **overrides):
    resp = api_client.create_instrument(create_instrument_payload(vendor_id, **overrides), ADMIN)
    return get_success_data(resp)


def file_evidence(instrument_id, **overrides):
    resp = api_client.create_evidence(instrument_id, create_evidence_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_guide(**overrides):
    resp = api_client.create_guide(create_guide_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_approved_guide(creator_headers=None, approver_headers=None, **overrides):
    """Create a guide and walk DRAFT -> PILOT -> APPROVED with SoD-safe ids."""
    creator_headers = creator_headers or make_admin_headers("admin-1")
    approver_headers = approver_headers or make_admin_headers("admin-2")
    resp = api_client.create_guide(create_guide_payload(**overrides), creator_headers)
    guide = get_success_data(resp)
    get_success_data(api_client.pilot_guide(guide["id"], creator_headers))
    resp = api_client.approve_guide(guide["id"], approver_headers)
    return get_success_data(resp)


def create_requisition(manager_headers=None, **overrides):
    manager_headers = manager_headers or HM
    resp = api_client.create_requisition(create_requisition_payload(**overrides), manager_headers)
    return get_success_data(resp)


def create_candidate(manager_headers=None, **overrides):
    manager_headers = manager_headers or HM
    resp = api_client.create_candidate(create_candidate_payload(**overrides), manager_headers)
    return get_success_data(resp)


def create_interviewer(**overrides):
    resp = api_client.create_interviewer(create_interviewer_payload(**overrides), ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: validated instrument + approved guide + active cycle chain
# ---------------------------------------------------------------------------

def create_validated_instrument(vendor_id=None, content_until=None, criterion_until=None,
                                **instrument_overrides):
    """Instrument walked DRAFT -> VALIDATION_REVIEW -> VALIDATED with one
    CRITERION and one CONTENT evidence record, both current at clock start."""
    vendor_id = vendor_id or create_vendor()["id"]
    instrument = create_instrument(vendor_id, **instrument_overrides)
    file_evidence(instrument["id"], evidence_type="CRITERION",
                  effective_until=criterion_until or "2027-08-01T00:00:00Z")
    file_evidence(instrument["id"], evidence_type="CONTENT",
                  effective_until=content_until or "2027-08-01T00:00:00Z")
    get_success_data(api_client.submit_instrument_validation_review(instrument["id"], ADMIN))
    resp = api_client.validate_instrument(instrument["id"], ADMIN)
    return get_success_data(resp)


def setup_active_cycle(manager_headers=None, retention_days=730, openings_count=2,
                       max_sessions_per_day=8, instrument_overrides=None,
                       guide_overrides=None,
                       window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END):
    """Full baseline: ACTIVE cycle with VALIDATED instrument + APPROVED guide.

    Returns dict(vendor, instrument, guide, requisition, cycle, manager_headers).
    """
    manager_headers = manager_headers or HM
    vendor = create_vendor()
    instrument = create_validated_instrument(vendor["id"], **(instrument_overrides or {}))
    guide = create_approved_guide(**(guide_overrides or {}))
    requisition = create_requisition(manager_headers, openings_count=openings_count,
                                     retention_days=retention_days)
    resp = api_client.create_cycle(
        requisition["id"],
        create_cycle_payload(instrument["id"], guide["id"],
                             administration_window_start=window_start,
                             administration_window_end=window_end,
                             max_sessions_per_day=max_sessions_per_day),
        manager_headers,
    )
    cycle = get_success_data(resp)
    get_success_data(api_client.activate_cycle(cycle["id"], manager_headers))
    cycle = get_success_data(api_client.get_cycle(cycle["id"], manager_headers))
    return {
        "vendor": vendor,
        "instrument": instrument,
        "guide": guide,
        "requisition": requisition,
        "cycle": cycle,
        "manager_headers": manager_headers,
    }


def create_calibrated_interviewer(guide_id, **interviewer_overrides):
    """Interviewer with a CALIBRATED CalibrationRecord for the given guide."""
    interviewer = create_interviewer(**interviewer_overrides)
    resp = api_client.create_calibration(
        interviewer["id"], create_calibration_payload(guide_id), ADMIN,
    )
    calibration = get_success_data(resp)
    get_success_data(
        api_client.certify_calibration(calibration["id"], certify_calibration_payload(), ADMIN)
    )
    calibration = get_success_data(api_client.get_calibration(calibration["id"], ADMIN))
    return interviewer, calibration


def invite_candidate(cycle_id, candidate_id, manager_headers=None):
    manager_headers = manager_headers or HM
    resp = api_client.create_invitation(
        cycle_id, create_invitation_payload(candidate_id), manager_headers,
    )
    return get_success_data(resp)


def schedule_assessment(assessment_id, scheduled_for=DEFAULT_SCHEDULED_FOR, manager_headers=None):
    manager_headers = manager_headers or HM
    resp = api_client.schedule_assessment(
        assessment_id, schedule_assessment_payload(scheduled_for=scheduled_for), manager_headers,
    )
    return get_success_data(resp)


def complete_assessment_at(assessment_id, raw_score=72, work_instant=DEFAULT_WORK_INSTANT,
                           manager_headers=None):
    """Clock to work_instant, then start + complete the assessment."""
    manager_headers = manager_headers or HM
    get_success_data(api_client.set_clock(set_clock_payload(work_instant), ADMIN))
    get_success_data(api_client.start_assessment(assessment_id, manager_headers))
    resp = api_client.complete_assessment(
        assessment_id, complete_assessment_payload(raw_score=raw_score), manager_headers,
    )
    return get_success_data(resp)


def invite_and_complete_candidate(cycle_id, candidate_id, raw_score=72,
                                  scheduled_for=DEFAULT_SCHEDULED_FOR,
                                  work_instant=DEFAULT_WORK_INSTANT, manager_headers=None):
    """Invite -> schedule -> start -> complete. Returns the COMPLETED assessment."""
    manager_headers = manager_headers or HM
    assessment = invite_candidate(cycle_id, candidate_id, manager_headers)
    schedule_assessment(assessment["id"], scheduled_for, manager_headers)
    return complete_assessment_at(assessment["id"], raw_score, work_instant, manager_headers)


# ---------------------------------------------------------------------------
# Tier 3: session / scorecard lifecycle builders
# ---------------------------------------------------------------------------

def book_completed_session(cycle_id, candidate_id, interviewer_id, guide_id,
                           scheduled_start, scheduled_end, manager_headers=None):
    """Book a session then complete it (clock set to scheduled_end first)."""
    manager_headers = manager_headers or HM
    resp = api_client.create_session(
        cycle_id,
        create_session_payload(candidate_id, interviewer_id, guide_id,
                               scheduled_start=scheduled_start, scheduled_end=scheduled_end),
        manager_headers,
    )
    session = get_success_data(resp)
    get_success_data(api_client.set_clock(set_clock_payload(scheduled_end), ADMIN))
    get_success_data(api_client.complete_session(session["id"], manager_headers))
    return session


def submit_scorecard(session_id, interviewer_id, ratings=None, overall_recommendation="YES"):
    """Create + submit a scorecard as the session's own interviewer."""
    headers = make_interviewer_headers(interviewer_id)
    payload = create_scorecard_payload(overall_recommendation=overall_recommendation)
    if ratings is not None:
        payload["ratings"] = ratings
    resp = api_client.create_scorecard(session_id, payload, headers)
    scorecard = get_success_data(resp)
    resp = api_client.submit_scorecard(scorecard["id"], headers)
    return get_success_data(resp)


def setup_quorum_ready_candidate(num_sessions=2, raw_score=72, manager_headers=None):
    """ACTIVE cycle; one candidate COMPLETED; num_sessions sessions SCORED.

    Sessions are booked on consecutive hours on 2026-08-12, alternating between
    two CALIBRATED interviewers. Returns a dict with the full context:
      vendor, instrument, guide, requisition, cycle, manager_headers,
      candidate, assessment, interviewers, sessions, scorecards
    """
    manager_headers = manager_headers or HM
    ctx = setup_active_cycle(manager_headers=manager_headers)
    guide = ctx["guide"]
    cycle = ctx["cycle"]

    interviewers = []
    for _ in range(max(2, num_sessions)):
        interviewer, _cal = create_calibrated_interviewer(guide["id"])
        interviewers.append(interviewer)

    candidate = create_candidate(manager_headers)
    assessment = invite_and_complete_candidate(
        cycle["id"], candidate["id"], raw_score=raw_score, manager_headers=manager_headers,
    )

    sessions = []
    scorecards = []
    default_ratings = [
        [{"competency_code": "COMM", "rating": 4}, {"competency_code": "ANAL", "rating": 5}],
        [{"competency_code": "COMM", "rating": 5}, {"competency_code": "ANAL", "rating": 3}],
        [{"competency_code": "COMM", "rating": 4}, {"competency_code": "ANAL", "rating": 4}],
    ]
    for idx in range(num_sessions):
        interviewer = interviewers[idx % len(interviewers)]
        hour = 9 + idx
        session = book_completed_session(
            cycle["id"], candidate["id"], interviewer["id"], guide["id"],
            scheduled_start=f"2026-08-12T{hour:02d}:00:00Z",
            scheduled_end=f"2026-08-12T{hour + 1:02d}:00:00Z",
            manager_headers=manager_headers,
        )
        scorecard = submit_scorecard(
            session["id"], interviewer["id"],
            ratings=default_ratings[idx % len(default_ratings)],
        )
        sessions.append(session)
        scorecards.append(scorecard)

    ctx.update({
        "candidate": candidate,
        "assessment": assessment,
        "interviewers": interviewers,
        "sessions": sessions,
        "scorecards": scorecards,
    })
    return ctx


def setup_decided_candidate(decision="ADVANCE", rationale=None, decision_officer_headers=None,
                            manager_headers=None, retention_days=730, raw_score=72,
                            decision_time="2026-08-15T12:00:00Z"):
    """Quorum-ready candidate with a FINALIZED hiring decision already created.

    Returns the setup_quorum_ready_candidate context plus decision under
    ctx["decision"].
    """
    manager_headers = manager_headers or HM
    decision_officer_headers = decision_officer_headers or DO
    ctx = setup_quorum_ready_candidate(
        num_sessions=2, raw_score=raw_score, manager_headers=manager_headers,
    )
    get_success_data(api_client.set_clock(set_clock_payload(decision_time), ADMIN))
    payload = create_decision_payload(
        ctx["candidate"]["id"], decision=decision,
        rationale=rationale or (
            "Candidate demonstrated strong structured problem solving "
            "and communication across panels."
        ),
    )
    resp = api_client.create_decision(ctx["cycle"]["id"], payload, decision_officer_headers)
    ctx["decision"] = get_success_data(resp)
    return ctx


def setup_purged_assessment(manager_headers=None, retention_days=730,
                            decision_time="2026-08-15T12:00:00Z"):
    """Full lifecycle: decided candidate, clock past retention, sweep executed.

    Decision lands at decision_time; clock moves to retention expiry + 1s;
    the retention sweep purges the assessment. Returns ctx with "decision" and
    "sweep" keys.
    """
    manager_headers = manager_headers or HM
    ctx = setup_decided_candidate(manager_headers=manager_headers,
                                  retention_days=retention_days,
                                  decision_time=decision_time)
    expiry = plus_days(decision_time, retention_days)
    get_success_data(api_client.set_clock(set_clock_payload(_plus_one_second(expiry)), ADMIN))
    resp = api_client.run_retention_sweep(CO)
    ctx["sweep"] = get_success_data(resp)
    return ctx


# ---------------------------------------------------------------------------
# Helpers for datetime arithmetic used by purge-oriented fixtures
# ---------------------------------------------------------------------------

def _plus_one_second(iso8601: str) -> str:
    """Add exactly one second to a 'YYYY-MM-DDTHH:MM:SSZ' timestamp."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(iso8601, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (dt + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_days(iso8601: str, days: int) -> str:
    """Add whole days to a 'YYYY-MM-DDTHH:MM:SSZ' timestamp."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(iso8601, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (dt + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
