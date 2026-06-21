"""Composite setup helpers (PRD §3.1–§3.7).

These encapsulate the multi-step API sequences that most tests need, so test
bodies focus on assertions. Setup calls use get_success_data() so a broken
precondition surfaces as a clear "Setup step failed" rather than a confusing
assertion deeper in the test.

The harness reboots the server before every test (empty DB each time), so every
helper builds its preconditions from scratch and pins the clock first.

Identity threading (PRD §3.7 segregation-of-duties): the MatchSpecialist who
accepts a proposal becomes the match's confirming user. Helpers default the
confirming specialist to "specialist-confirm" and the closing supervisor to
"supervisor-close" — distinct operator identities — so closure flows never trip
ERR_SEGREGATION_OF_DUTIES unless a test deliberately reuses one id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_coordinator_headers,
    make_background_screener_headers,
    make_match_specialist_headers,
    make_supervisor_headers,
)
from . import factories as f

REF_CLOCK = "2026-01-01T00:00:00Z"

COORD = make_coordinator_headers()
SCREENER = make_background_screener_headers()
SPECIALIST = make_match_specialist_headers()
SUPERVISOR = make_supervisor_headers()

# Default distinct operator identities for confirm vs finalize (PRD §3.7).
CONFIRM_SPECIALIST_ID = "specialist-confirm"
CLOSE_SUPERVISOR_ID = "supervisor-close"


# ─── Clock ────────────────────────────────────────────
def set_clock(iso, headers=None):
    """Advance the server clock and fire expiry/overdue sweeps (PRD §3.2)."""
    return get_success_data(api_client.set_clock(iso, headers or COORD))


# ─── Tier 1: state progression ────────────────────────
def create_volunteer(clock=REF_CLOCK, set_clock_first=True, **overrides):
    """Register a volunteer in APPLIED (PRD §3.1)."""
    if set_clock_first:
        set_clock(clock)
    payload = f.create_volunteer_payload(**overrides)
    return get_success_data(api_client.create_volunteer(payload, COORD))


def get_volunteer(volunteer_id):
    return get_success_data(api_client.get_volunteer(volunteer_id, SPECIALIST))


def screen_check_ids(volunteer_id, start_index=0):
    """Return the (criminal, dmv, child_abuse) check ids for the most recent
    screening cycle. submit-screening cascades them in that fixed order
    (PRD §3.1); start_index>0 selects a later re-screen cycle's checks."""
    checks = get_success_data(
        api_client.list_volunteer_background_checks(volunteer_id, SCREENER)
    )
    return (
        checks[start_index]["id"],
        checks[start_index + 1]["id"],
        checks[start_index + 2]["id"],
    )


def submit_and_clear_screening(volunteer_id, dmv_adverse=0, start_index=0):
    """Submit screening, then CLEAR all three checks → volunteer ELIGIBLE (PRD §3.1)."""
    get_success_data(api_client.submit_screening(volunteer_id, SCREENER))
    crim, dmv, car = screen_check_ids(volunteer_id, start_index)
    get_success_data(api_client.adjudicate_check(crim, f.adjudicate_payload("CLEAR", 0), SCREENER))
    get_success_data(api_client.adjudicate_check(dmv, f.adjudicate_payload("CLEAR", dmv_adverse), SCREENER))
    get_success_data(api_client.adjudicate_check(car, f.adjudicate_payload("CLEAR", 0), SCREENER))
    return crim, dmv, car


def create_eligible_volunteer(clock=REF_CLOCK, set_clock_first=True, **overrides):
    """Create a volunteer and screen it through to ELIGIBLE. Returns the
    re-read ELIGIBLE volunteer dict (PRD §3.1)."""
    vol = create_volunteer(clock=clock, set_clock_first=set_clock_first, **overrides)
    submit_and_clear_screening(vol["id"])
    return get_volunteer(vol["id"])


def create_guardian(consent_on_file=True, **overrides):
    """Register a guardian (PRD §3.3)."""
    payload = f.create_guardian_payload(consent_on_file=consent_on_file, **overrides)
    return get_success_data(api_client.create_guardian(payload, COORD))


def create_child(guardian_id, **overrides):
    """Enroll a WAITLISTED child (PRD §3.3)."""
    payload = f.create_child_payload(guardian_id, **overrides)
    return get_success_data(api_client.create_child(payload, SPECIALIST))


def create_consented_child(clock=REF_CLOCK, set_clock_first=True, child_overrides=None,
                           guardian_overrides=None):
    """Consented guardian + WAITLISTED child. Returns (guardian, child)."""
    if set_clock_first:
        set_clock(clock)
    guardian = create_guardian(consent_on_file=True, **(guardian_overrides or {}))
    child = create_child(guardian["id"], **(child_overrides or {}))
    return guardian, child


# ─── Tier 2/3: proposal → confirmed match ─────────────
def propose_match(child_id, specialist_headers=None):
    """Run the matching engine for a WAITLISTED child (PRD §3.3). Reads the
    child's current version and supplies it as expected_child_version."""
    child = get_success_data(api_client.get_child(child_id, specialist_headers or SPECIALIST))
    resp = api_client.propose_match(
        child_id,
        {"expected_child_version": child["version"]},
        specialist_headers or SPECIALIST,
    )
    return get_success_data(resp)


def accept_proposal(proposal_id, volunteer_id, specialist_headers=None):
    """Accept a proposal, binding the volunteer into a CONFIRMED match (PRD §3.4).
    Reads the volunteer's current version for expected_volunteer_version."""
    vol = get_volunteer(volunteer_id)
    resp = api_client.accept_proposal(
        proposal_id,
        {"expected_volunteer_version": vol["version"]},
        specialist_headers or SPECIALIST,
    )
    return get_success_data(resp)


def setup_confirmed_match(clock=REF_CLOCK, child_overrides=None, guardian_overrides=None,
                          volunteer_overrides=None, confirm_specialist_id=CONFIRM_SPECIALIST_ID):
    """Full chain to a CONFIRMED Match (PRD §3.1→§3.4).
    Returns dict(volunteer, guardian, child, proposal, match, specialist_headers).
    The confirming specialist's operator identity is `confirm_specialist_id`."""
    set_clock(clock)
    volunteer = create_eligible_volunteer(set_clock_first=False, **(volunteer_overrides or {}))
    guardian = create_guardian(consent_on_file=True, **(guardian_overrides or {}))
    child = create_child(guardian["id"], **(child_overrides or {}))
    spec = make_match_specialist_headers(confirm_specialist_id)
    proposal = propose_match(child["id"], specialist_headers=spec)
    match = accept_proposal(proposal["id"], volunteer["id"], specialist_headers=spec)
    return {
        "volunteer": volunteer,
        "guardian": guardian,
        "child": child,
        "proposal": proposal,
        "match": match,
        "specialist_headers": spec,
        "confirm_specialist_id": confirm_specialist_id,
    }


def schedule_meeting(match_id, start, end, location="Library", specialist_headers=None):
    resp = api_client.schedule_meeting(
        match_id, f.schedule_meeting_payload(start, end, location),
        specialist_headers or SPECIALIST,
    )
    return get_success_data(resp)


def setup_introduced_match(clock=REF_CLOCK, meeting_start="2026-01-02T10:00:00Z",
                           meeting_end="2026-01-02T11:00:00Z", confirm_specialist_id=CONFIRM_SPECIALIST_ID,
                           **kwargs):
    """CONFIRMED match → schedule meeting → HOLD it → Match INTRODUCED (PRD §3.5).
    Returns the confirmed-match dict plus `meeting`."""
    ctx = setup_confirmed_match(clock=clock, confirm_specialist_id=confirm_specialist_id, **kwargs)
    spec = ctx["specialist_headers"]
    meeting = schedule_meeting(ctx["match"]["id"], meeting_start, meeting_end, specialist_headers=spec)
    get_success_data(api_client.hold_meeting(meeting["id"], {}, spec))
    ctx["meeting"] = meeting
    return ctx


def setup_active_match(clock=REF_CLOCK, meeting_start="2026-01-02T10:00:00Z",
                       meeting_end="2026-01-02T11:00:00Z", confirm_specialist_id=CONFIRM_SPECIALIST_ID,
                       **kwargs):
    """INTRODUCED match → AFFIRM meeting → Match ACTIVE, first SupervisionContact
    OPEN (PRD §3.5). Returns confirmed-match dict plus `meeting`."""
    ctx = setup_introduced_match(clock=clock, meeting_start=meeting_start,
                                 meeting_end=meeting_end, confirm_specialist_id=confirm_specialist_id, **kwargs)
    spec = ctx["specialist_headers"]
    get_success_data(api_client.affirm_meeting(ctx["meeting"]["id"], spec))
    return ctx


# ─── Tier 4: supervision / activity accumulation ──────
def first_open_contact_id(match_id):
    """Return the id of the match's first (only) OPEN SupervisionContact."""
    contacts = get_success_data(
        api_client.list_match_supervision_contacts(match_id, SUPERVISOR)
    )
    return contacts[0]["id"]


def log_activity(match_id, occurred_at, duration_minutes, activity_type="OUTING",
                 specialist_headers=None):
    resp = api_client.log_activity(
        match_id, f.activity_payload(occurred_at, duration_minutes, activity_type),
        specialist_headers or SPECIALIST,
    )
    return get_success_data(resp)


def complete_contact(contact_id, contacted_at, party="BIG"):
    resp = api_client.complete_contact(
        contact_id, f.complete_contact_payload(contacted_at, party), SUPERVISOR
    )
    return get_success_data(resp)


# ─── Tier 5: exit / finalization / survey ─────────────
def open_exit(match_id, exit_type="SUCCESSFUL_CLOSURE", initiated_by="AGENCY",
              reason_code="GRADUATION", specialist_headers=None):
    """Open a DRAFT ExitTransition (PRD §3.7). Opened by the confirming
    MatchSpecialist by default (allowed; SoD only bites at finalize)."""
    resp = api_client.open_exit_transition(
        match_id, f.exit_transition_payload(exit_type, initiated_by, reason_code),
        specialist_headers or SPECIALIST,
    )
    return get_success_data(resp)


def finalize_exit(exit_id, supervisor_user_id=CLOSE_SUPERVISOR_ID):
    """Finalize the exit, closing the match (PRD §3.7). Uses a supervisor whose
    operator identity differs from the confirming specialist."""
    sup = make_supervisor_headers(supervisor_user_id)
    return get_success_data(api_client.finalize_exit(exit_id, sup))


def setup_closed_match(clock=REF_CLOCK, exit_type="SUCCESSFUL_CLOSURE",
                       reach_active=True, confirm_specialist_id=CONFIRM_SPECIALIST_ID,
                       close_supervisor_id=CLOSE_SUPERVISOR_ID, **kwargs):
    """Full chain to a CLOSED Match (PRD §3.7).
    reach_active=True  → match ACTIVE before exit;
    reach_active=False → match only INTRODUCED before exit (held, not affirmed).
    Returns confirmed-match dict plus `meeting`, `exit_transition`."""
    if reach_active:
        ctx = setup_active_match(clock=clock, confirm_specialist_id=confirm_specialist_id, **kwargs)
    else:
        ctx = setup_introduced_match(clock=clock, confirm_specialist_id=confirm_specialist_id, **kwargs)
    et = open_exit(ctx["match"]["id"], exit_type=exit_type,
                   specialist_headers=ctx["specialist_headers"])
    finalize_exit(et["id"], supervisor_user_id=close_supervisor_id)
    ctx["exit_transition"] = et
    ctx["close_supervisor_id"] = close_supervisor_id
    return ctx


def submit_survey(match_id, exit_transition_id, relationship_quality=4,
                  child_outcome=4, would_rematch=False):
    resp = api_client.create_outcome_survey(
        f.outcome_survey_payload(match_id, exit_transition_id, relationship_quality,
                                 child_outcome, would_rematch),
        SUPERVISOR,
    )
    return get_success_data(resp)
