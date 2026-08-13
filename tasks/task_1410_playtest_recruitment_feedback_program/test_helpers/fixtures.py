"""Composite setup helpers.

The harness restarts the server before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints. Identity
threading: Participant and Moderator are entity-backed roles, so every
ownership-gated call is made with make_participant_headers(entity["id"]) /
make_moderator_headers(entity["id"]) — never the shared fallback constants.
"""
from datetime import timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import parse_instant
from .constants import (
    CLOCK_START_ISO,
    LEGAL_1,
    OFFICER_1,
    RESEARCHER_1,
)
from .factories import (
    create_application_payload,
    create_booking_payload,
    create_breach_payload,
    create_build_payload,
    create_access_key_payload,
    create_instrument_payload,
    create_moderator_payload,
    create_nda_payload,
    create_participant_payload,
    create_payout_payload,
    create_response_payload,
    create_session_payload,
    create_station_payload,
    create_study_payload,
    create_ticket_payload,
)
from .test_users import (
    TEST_USERS,
    make_legal_headers,
    make_moderator_headers,
    make_officer_headers,
    make_participant_headers,
    make_researcher_headers,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]
LEGAL = TEST_USERS["legal_headers"]


# ---------------------------------------------------------------------------
# Clock and sweeps (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START_ISO):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_expiry_sweep():
    return get_success_data(api_client.run_expiry_sweep(ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: roster primitives (PRD §3.1)
# ---------------------------------------------------------------------------

def register_participant(email=None, full_name="Test Participant", age_years=25,
                         region_code="US-W", platform_tags=None, active=True):
    """Register a participant; ACTIVE by default."""
    p = get_success_data(api_client.create_participant(
        create_participant_payload(email=email, full_name=full_name,
                                   age_years=age_years, region_code=region_code,
                                   platform_tags=platform_tags), ADMIN))
    if active:
        p = get_success_data(api_client.activate_participant(p["id"], ADMIN))
    return p


def create_moderator(display_name="Test Mod", email=None):
    return get_success_data(api_client.create_moderator(
        create_moderator_payload(display_name=display_name, email=email), ADMIN))


def create_station(station_code=None, location="Lab A", equipment_tags=None):
    return get_success_data(api_client.create_lab_station(
        create_station_payload(station_code=station_code, location=location,
                               equipment_tags=equipment_tags), ADMIN))


def get_participant(participant_id):
    return get_success_data(api_client.get_participant(participant_id, ADMIN))


def get_study(study_id):
    return get_success_data(api_client.get_study(study_id, ADMIN))


def get_session(session_id):
    return get_success_data(api_client.get_session(session_id, RESEARCHER))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, ADMIN))


def get_build(build_id):
    return get_success_data(api_client.get_build(build_id, ADMIN))


def get_payout(payout_id):
    return get_success_data(api_client.get_incentive_payout(payout_id, TEST_USERS["officer_headers"]))


# ---------------------------------------------------------------------------
# Tier 1: studies and NDA paperwork (PRD §3.1, §3.3)
# ---------------------------------------------------------------------------

def create_study(open_recruitment=True, **overrides):
    """Create a study; RECRUITING by default (set open_recruitment=False for DRAFT)."""
    study = get_success_data(api_client.create_study(create_study_payload(**overrides), ADMIN))
    if open_recruitment:
        study = get_success_data(api_client.open_recruitment(study["id"], ADMIN))
    return study


def create_nda(study_id, version_label="v1", body_text="NDA text", publish=False):
    agreement = get_success_data(api_client.create_nda_agreement(
        create_nda_payload(study_id, version_label=version_label, body_text=body_text),
        LEGAL))
    if publish:
        agreement = get_success_data(api_client.publish_nda_agreement(agreement["id"], LEGAL))
    return agreement


def setup_study_with_published_nda(**study_overrides):
    """Study in RECRUITING + a PUBLISHED NDA v1. Returns (study, nda)."""
    study = create_study(open_recruitment=True, **study_overrides)
    nda = create_nda(study["id"], publish=True)
    return study, nda


def close_study(study_id):
    return get_success_data(api_client.close_recruitment(study_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: application / enrollment chains (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------

def apply_to_study(study_id, participant_id):
    """Participant applies; returns the SUBMITTED application."""
    return get_success_data(api_client.create_application(
        create_application_payload(study_id), make_participant_headers(participant_id)))


def start_review(application_id):
    return get_success_data(api_client.start_review(application_id, RESEARCHER))


def approve_application(application_id):
    return get_success_data(api_client.approve_application(application_id, RESEARCHER))


def get_pending_signature(participant_id):
    """The participant's PENDING signature (exactly one exists after approve)."""
    sigs = get_success_data(api_client.list_nda_signatures(
        ADMIN, params={"participant_id": participant_id, "status": "PENDING"}))
    assert isinstance(sigs, list) and len(sigs) == 1, (
        f"expected exactly one PENDING signature, got {sigs!r}")
    return sigs[0]


def sign_signature(signature_id, participant_id):
    return get_success_data(api_client.sign_nda_signature(
        signature_id, make_participant_headers(participant_id)))


def enroll_participant(study_id, participant):
    """Full enrollment chain: apply -> start-review -> approve -> sign.

    Requires the study RECRUITING with a PUBLISHED NDA and the participant
    ACTIVE with a passing (verified) fit. Returns (application, signature);
    the application ends ENROLLED.
    """
    pid = participant["id"]
    app = apply_to_study(study_id, pid)
    app = start_review(app["id"])
    app = approve_application(app["id"])
    assert app["status"] == "APPROVED", f"approve failed to land APPROVED: {app!r}"
    sig = get_pending_signature(pid)
    sig = sign_signature(sig["id"], pid)
    assert sig["status"] == "SIGNED", f"sign failed to land SIGNED: {sig!r}"
    app = get_success_data(api_client.get_application(app["id"], RESEARCHER))
    assert app["status"] == "ENROLLED", f"enrollment bubble-up failed: {app!r}"
    return app, sig


def setup_enrolled_participant(email=None, age_years=25, region_code="US-W",
                               platform_tags=None, study_overrides=None):
    """Study RECRUITING with NDA v1 PUBLISHED + one ENROLLED participant.

    Returns dict(study, nda, participant, application, signature).
    """
    study, nda = setup_study_with_published_nda(**(study_overrides or {}))
    participant = register_participant(email=email, age_years=age_years,
                                       region_code=region_code,
                                       platform_tags=platform_tags)
    app, sig = enroll_participant(study["id"], participant)
    return {"study": study, "nda": nda, "participant": participant,
            "application": app, "signature": sig}


# ---------------------------------------------------------------------------
# Tier 2: sessions and bookings (PRD §3.5)
# ---------------------------------------------------------------------------

def create_remote_session(study_id, starts_at, ends_at, seat_capacity=5):
    return get_success_data(api_client.create_session(
        create_session_payload(study_id, starts_at, ends_at,
                               seat_capacity=seat_capacity, mode="REMOTE"),
        RESEARCHER))


def create_lab_session(study_id, station_id, starts_at, ends_at, seat_capacity=4):
    return get_success_data(api_client.create_session(
        create_session_payload(study_id, starts_at, ends_at,
                               seat_capacity=seat_capacity, mode="IN_LAB",
                               station_id=station_id),
        RESEARCHER))


def assign_moderator(session_id, moderator_id):
    return get_success_data(api_client.assign_moderator(session_id, moderator_id, RESEARCHER))


def book_session(session_id, participant_id):
    return get_success_data(api_client.create_booking(
        create_booking_payload(session_id), make_participant_headers(participant_id)))


def _midpoint(starts_at, ends_at):
    start = parse_instant(starts_at)
    end = parse_instant(ends_at)
    mid = start + (end - start) / 2
    return mid.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_session(session_id, moderator_id, at, attend_booking_ids=(), no_show_booking_ids=()):
    """Drive a session through its live window: set the logical clock inside
    the window, start as the assigned moderator, mark the given bookings
    ATTENDED (explicit no-shows optional), then complete. Any booking still
    BOOKED/PROMOTED at completion auto-flips to NO_SHOW (PRD §3.5)."""
    mod_headers = make_moderator_headers(moderator_id)
    set_clock(at)
    get_success_data(api_client.start_session(session_id, mod_headers))
    for booking_id in attend_booking_ids:
        get_success_data(api_client.mark_booking_attended(booking_id, mod_headers))
    for booking_id in no_show_booking_ids:
        get_success_data(api_client.mark_booking_no_show(booking_id, mod_headers))
    return get_success_data(api_client.complete_session(session_id, mod_headers))


def run_session_at_midpoint(session, moderator_id, attend_booking_ids=(),
                            no_show_booking_ids=()):
    return run_session(session["id"], moderator_id,
                       _midpoint(session["starts_at"], session["ends_at"]),
                       attend_booking_ids=attend_booking_ids,
                       no_show_booking_ids=no_show_booking_ids)


def setup_booked_session(email=None, capacity=5, starts_at="2026-08-10T10:00:00Z",
                         ends_at="2026-08-10T11:00:00Z", with_moderator=True,
                         study_overrides=None):
    """Enrolled participant holding a BOOKED booking on a SCHEDULED session.

    Returns dict(study, nda, participant, application, session, booking, moderator).
    """
    ctx = setup_enrolled_participant(email=email, study_overrides=study_overrides)
    moderator = create_moderator() if with_moderator else None
    session = create_remote_session(ctx["study"]["id"], starts_at, ends_at,
                                    seat_capacity=capacity)
    if moderator is not None:
        assign_moderator(session["id"], moderator["id"])
    booking = book_session(session["id"], ctx["participant"]["id"])
    assert booking["status"] == "BOOKED", f"expected BOOKED, got {booking!r}"
    ctx.update({"session": session, "booking": booking, "moderator": moderator})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: attendance histories for incentive and strike workflows (PRD §3.5/§3.8)
# ---------------------------------------------------------------------------

# Non-overlapping one-hour slots on 2026-08-10 (participant closed-interval and
# moderator 15-minute buffer rules are both satisfied by hourly gaps).
SESSION_SLOTS = [
    ("2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z"),
    ("2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z"),
    ("2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z"),
    ("2026-08-10T16:00:00Z", "2026-08-10T17:00:00Z"),
]


def setup_participant_session_history(participant, study, moderator, outcomes,
                                      seat_capacity=5):
    """Book one session per outcome and run them in order.

    outcomes: list like ["attended", "attended", "no_show"] — one REMOTE
    session per entry on the 2026-08-10 slots. The study is closed before the
    first session starts (session start requires CLOSED/ANALYSIS, PRD §3.5).

    Returns dict(sessions=[...], bookings=[...]) parallel to `outcomes`.
    """
    assert len(outcomes) <= len(SESSION_SLOTS)
    sessions, bookings = [], []
    for (start, end), _outcome in zip(SESSION_SLOTS, outcomes):
        session = create_remote_session(study["id"], start, end,
                                        seat_capacity=seat_capacity)
        assign_moderator(session["id"], moderator["id"])
        booking = book_session(session["id"], participant["id"])
        sessions.append(session)
        bookings.append(booking)
    close_study(study["id"])
    for session, booking, outcome in zip(sessions, bookings, outcomes):
        if outcome == "attended":
            run_session_at_midpoint(session, moderator["id"],
                                    attend_booking_ids=[booking["id"]])
        elif outcome == "no_show":
            run_session_at_midpoint(session, moderator["id"])
        else:
            raise ValueError(f"unknown outcome {outcome!r}")
    return {"sessions": sessions, "bookings": bookings}


def create_and_publish_instrument(study_id, questions=None, pass_threshold=50,
                                  title="Survey"):
    instrument = get_success_data(api_client.create_survey_instrument(
        create_instrument_payload(study_id, title=title, questions=questions,
                                  pass_threshold=pass_threshold), RESEARCHER))
    return get_success_data(api_client.publish_survey_instrument(instrument["id"], RESEARCHER))


def submit_response(instrument_id, session_id, participant_id, answers=None):
    """Create + submit a response as its owning participant. Returns SUBMITTED response."""
    response = get_success_data(api_client.create_survey_response(
        create_response_payload(instrument_id, session_id, answers=answers),
        make_participant_headers(participant_id)))
    return get_success_data(api_client.submit_survey_response(
        response["id"], make_participant_headers(participant_id)))


def setup_payout_ready(outcomes=("attended",), passed_surveys=0, budget=1000000,
                       survey_points=8, survey_max_points=10, survey_threshold=50):
    """Full incentive-payout precondition chain (PRD §3.8).

    An ENROLLED participant with the requested attendance history and
    `passed_surveys` SUBMITTED+passed responses (one per attended session, in
    order). Returns dict(study, nda, participant, application, session/booking
    history, moderator, payout=None)."""
    study, nda = setup_study_with_published_nda(incentive_budget_cents=budget)
    participant = register_participant()
    enroll_participant(study["id"], participant)
    moderator = create_moderator()
    history = setup_participant_session_history(participant, study, moderator,
                                                list(outcomes))
    if passed_surveys:
        questions = [{"question_key": "q1", "weight": 1, "max_points": survey_max_points}]
        instrument = create_and_publish_instrument(
            study["id"], questions=questions, pass_threshold=survey_threshold)
        attended_sessions = [s for s, o in zip(history["sessions"], outcomes)
                             if o == "attended"]
        assert passed_surveys <= len(attended_sessions)
        for session in attended_sessions[:passed_surveys]:
            submitted = submit_response(
                instrument["id"], session["id"], participant["id"],
                answers=[{"question_key": "q1", "points": survey_points}])
            assert submitted["passed"] is True, f"survey did not pass: {submitted!r}"
    return {"study": study, "nda": nda, "participant": participant,
            "moderator": moderator, "history": history}


# ---------------------------------------------------------------------------
# Tier 3: payout lifecycle (PRD §3.8)
# ---------------------------------------------------------------------------

def create_draft_payout(study_id, participant_id, officer_id=OFFICER_1):
    return get_success_data(api_client.create_incentive_payout(
        create_payout_payload(study_id, participant_id),
        make_officer_headers(officer_id)))


def submit_payout(payout_id, officer_id=OFFICER_1):
    return get_success_data(api_client.submit_payout(
        payout_id, make_officer_headers(officer_id)))


def approve_payout(payout_id, officer_id):
    return get_success_data(api_client.approve_payout(
        payout_id, make_officer_headers(officer_id)))


def issue_payout(payout_id, officer_id):
    return get_success_data(api_client.issue_payout(
        payout_id, make_officer_headers(officer_id)))


# ---------------------------------------------------------------------------
# Tier 2: builds and keys (PRD §3.4)
# ---------------------------------------------------------------------------

def create_build(study_id, build_label=None, max_keys=5, key_ttl_hours=None):
    """Register a build; it starts STAGED (PRD §3.4)."""
    return get_success_data(api_client.create_build(
        create_build_payload(study_id, build_label=build_label, max_keys=max_keys,
                             key_ttl_hours=key_ttl_hours), ADMIN))


def create_released_build(study_id, build_label=None, max_keys=5, key_ttl_hours=None):
    build = create_build(study_id, build_label=build_label, max_keys=max_keys,
                         key_ttl_hours=key_ttl_hours)
    return get_success_data(api_client.release_build(build["id"], ADMIN))


def issue_key(build_id, participant_id):
    return get_success_data(api_client.create_access_key(
        create_access_key_payload(build_id, participant_id), ADMIN))


def list_exposures(participant_id=None, build_id=None, event_type=None):
    params = {}
    if participant_id is not None:
        params["participant_id"] = participant_id
    if build_id is not None:
        params["build_id"] = build_id
    if event_type is not None:
        params["event_type"] = event_type
    return get_success_data(api_client.list_exposure_records(ADMIN, params=params))


# ---------------------------------------------------------------------------
# Tier 2: breach cases (PRD §3.9)
# ---------------------------------------------------------------------------

def report_breach(participant_id, study_id, severity="MINOR",
                  reporter="researcher", reporter_id=RESEARCHER_1,
                  evidence_summary="Leak evidence"):
    """File a breach case. reporter='researcher' uses the opaque researcher id;
    reporter='moderator' uses the entity-backed moderator id as reporter."""
    if reporter == "moderator":
        headers = make_moderator_headers(reporter_id)
    else:
        headers = make_researcher_headers(reporter_id)
    return get_success_data(api_client.create_breach_case(
        create_breach_payload(participant_id, study_id,
                              evidence_summary=evidence_summary, severity=severity),
        headers))


def open_case(case_id, legal_id=LEGAL_1):
    return get_success_data(api_client.open_investigation(
        case_id, make_legal_headers(legal_id)))


def create_ticket(study_id, severity="MEDIUM", reach_count=10,
                  reproducibility_pct=0.5, title="Issue", as_role="researcher",
                  reporter_id=None):
    headers = (make_moderator_headers(reporter_id) if as_role == "moderator"
               else RESEARCHER)
    return get_success_data(api_client.create_feedback_ticket(
        create_ticket_payload(study_id, title=title, severity=severity,
                              reach_count=reach_count,
                              reproducibility_pct=reproducibility_pct), headers))
