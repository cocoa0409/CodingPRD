"""Composite setup helpers for the casting-domain workflows.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup failed" assertion, not a confusing
validation error deep inside a test.

Standard happy-path spine used across this domain (PRD section 3):
production -> role -> breakdown -> release -> talent -> submission ->
start-review -> shortlist -> session -> appointment -> confirm appointment ->
clock past session start -> complete appointment (submission reaches
CALLBACK_COMPLETED) -> offer (OFFER_PENDING) -> accept (DealMemo EXECUTED)
-> booking (PENDING, submission BOOKED, role CAST) -> confirm (CONFIRMED).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS as _D
from .factories import (
    create_accept_payload,
    create_agent_payload,
    create_appointment_payload,
    create_booking_payload,
    create_breakdown_payload,
    create_counter_payload,
    create_guardian_payload,
    create_hold_payload,
    create_offer_payload,
    create_permit_payload,
    create_production_payload,
    create_role_payload,
    create_self_tape_payload,
    create_session_payload,
    create_submission_payload,
    create_talent_payload,
)
from .test_users import TEST_USERS, make_agent_headers

DIRECTOR = TEST_USERS["director_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def setup_failed(step: str, resp) -> AssertionError:
    body = resp.text[:400] if hasattr(resp, "text") else str(resp)
    return AssertionError(f"Setup failed at step '{step}': HTTP {resp.status_code} {body}")


def _ok(resp, step: str) -> dict:
    data = get_success_data(resp)
    if not isinstance(data, dict):
        raise setup_failed(step, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1: leaf creators and the logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers=None) -> str:
    resp = api.set_clock({"to_iso8601": to_iso8601}, headers or DIRECTOR)
    data = _ok(resp, "set_clock")
    return data.get("current_utc", to_iso8601)


def create_production(**overrides) -> dict:
    return _ok(api.create_production(create_production_payload(**overrides), DIRECTOR), "create_production")


def create_role(production_id: str, **overrides) -> dict:
    return _ok(api.create_role(production_id, create_role_payload(**overrides), DIRECTOR), "create_role")


def create_breakdown(production_id: str, role_id: str, **overrides) -> dict:
    return _ok(api.create_breakdown(production_id, create_breakdown_payload(role_id, **overrides), DIRECTOR), "create_breakdown")


def release_breakdown(breakdown_id: str, distribution: str = "OPEN_CALL") -> dict:
    return _ok(api.release_breakdown(breakdown_id, {"distribution": distribution}, DIRECTOR), "release_breakdown")


def create_agent(**overrides) -> dict:
    return _ok(api.create_agent(create_agent_payload(**overrides), DIRECTOR), "create_agent")


def create_guardian(**overrides) -> dict:
    return _ok(api.create_guardian(create_guardian_payload(**overrides), COORDINATOR), "create_guardian")


def create_talent(**overrides) -> dict:
    return _ok(api.create_talent(create_talent_payload(**overrides), DIRECTOR), "create_talent")


def create_session(breakdown_id: str, **overrides) -> dict:
    return _ok(api.create_session(breakdown_id, create_session_payload(**overrides), ASSOCIATE), "create_session")


def create_permit(talent_id: str, production_id: str, guardian_user_id: str, **overrides) -> dict:
    return _ok(
        api.create_permit(create_permit_payload(talent_id, production_id, guardian_user_id, **overrides), COORDINATOR),
        "create_permit",
    )


# ---------------------------------------------------------------------------
# Tier 2: hierarchy — production + role + released breakdown
# ---------------------------------------------------------------------------

def setup_released_breakdown(
    production_overrides=None,
    role_overrides=None,
    breakdown_overrides=None,
    distribution: str = "OPEN_CALL",
    clock: str = None,
) -> dict:
    """Production + role + breakdown released to the requested channel.

    Returns {"production", "role", "breakdown"} (breakdown post-release).
    """
    if clock:
        set_clock(clock)
    production = create_production(**(production_overrides or {}))
    role = create_role(production["id"], **(role_overrides or {}))
    breakdown = create_breakdown(production["id"], role["id"], **(breakdown_overrides or {}))
    breakdown = release_breakdown(breakdown["id"], distribution=distribution)
    return {"production": production, "role": role, "breakdown": breakdown}


def _breakdown_version(breakdown_id: str) -> int:
    return _ok(api.get_breakdown(breakdown_id, DIRECTOR), "get_breakdown")["version"]


# ---------------------------------------------------------------------------
# Tier 3: submission intake and review pipeline
# ---------------------------------------------------------------------------

def submit_talent(breakdown_id: str, talent_id: str, agent_id: str = None) -> dict:
    """Submit talent to a released breakdown with a fresh OCC version read.

    Self-submit path (no agent_id) is performed by a CastingAssociate; the
    agent path is performed by the representing Agent (X-User-ID == agent_id).
    """
    version = _breakdown_version(breakdown_id)
    payload = create_submission_payload(talent_id, version, agent_id=agent_id)
    headers = make_agent_headers(agent_id) if agent_id else ASSOCIATE
    return _ok(api.create_submission(breakdown_id, payload, headers), "create_submission")


def setup_submission(
    distribution: str = "OPEN_CALL",
    agent: bool = False,
    talent_overrides=None,
    **kwargs,
) -> dict:
    """Released breakdown + talent + one live (SUBMITTED) submission."""
    ctx = setup_released_breakdown(
        production_overrides=kwargs.get("production_overrides"),
        role_overrides=kwargs.get("role_overrides"),
        breakdown_overrides=kwargs.get("breakdown_overrides"),
        distribution=distribution,
        clock=kwargs.get("clock", _D["SETUP_CLOCK"]),
    )
    agent_row = create_agent() if agent else None
    talent_kw = dict(talent_overrides or {})
    if agent_row:
        talent_kw.setdefault("agent_id", agent_row["id"])
    talent = create_talent(**talent_kw)
    submission = submit_talent(ctx["breakdown"]["id"], talent["id"], agent_id=agent_row["id"] if agent_row else None)
    ctx.update({"talent": talent, "submission": submission, "agent": agent_row})
    return ctx


def advance_to_shortlisted(submission_id: str) -> dict:
    _ok(api.start_review(submission_id, ASSOCIATE), "start_review")
    return _ok(api.shortlist_submission(submission_id, ASSOCIATE), "shortlist")


def setup_shortlisted_submission(**kwargs) -> dict:
    ctx = setup_submission(**kwargs)
    ctx["submission"] = advance_to_shortlisted(ctx["submission"]["id"])
    return ctx


def propose_appointment(session_id: str, submission_id: str, **overrides) -> dict:
    return _ok(api.create_appointment(session_id, create_appointment_payload(submission_id, **overrides), ASSOCIATE), "create_appointment")


def confirm_appointment(appointment_id: str, agent_id: str = None) -> dict:
    """Confirm a PROPOSED appointment: the submission's agent, or a
    CastingAssociate standing in for a self-submission (PRD 3.5)."""
    headers = make_agent_headers(agent_id) if agent_id else ASSOCIATE
    return _ok(api.confirm_appointment(appointment_id, headers), "confirm_appointment")


# ---------------------------------------------------------------------------
# Tier 3b: callback completion -> offer -> deal memo -> booking
# ---------------------------------------------------------------------------

def setup_callback_completed(
    session_overrides=None,
    appointment_overrides=None,
    post_session_clock: str = "2026-08-04T13:00:00Z",
    **kwargs,
) -> dict:
    """Submission walked to CALLBACK_COMPLETED via a confirmed, completed
    callback appointment."""
    ctx = setup_shortlisted_submission(**kwargs)
    session = create_session(ctx["breakdown"]["id"], **(session_overrides or {}))
    agent_id = ctx["agent"]["id"] if ctx.get("agent") else None
    appointment = propose_appointment(session["id"], ctx["submission"]["id"], **(appointment_overrides or {}))
    appointment = confirm_appointment(appointment["id"], agent_id=agent_id)
    if post_session_clock:
        set_clock(post_session_clock)
    _ok(api.complete_appointment(appointment["id"], ASSOCIATE), "complete_appointment")
    ctx["submission"] = _ok(api.get_submission(ctx["submission"]["id"], DIRECTOR), "get_submission")
    ctx.update({"session": session, "appointment": appointment})
    return ctx


def create_offer(submission_id: str, **overrides) -> dict:
    return _ok(api.create_offer(submission_id, create_offer_payload(**overrides), DIRECTOR), "create_offer")


def setup_offer_pending(offer_overrides=None, **kwargs) -> dict:
    """CALLBACK_COMPLETED submission + round-1 offer EXTENDED (OFFER_PENDING)."""
    ctx = setup_callback_completed(**kwargs)
    offer = create_offer(ctx["submission"]["id"], **(offer_overrides or {}))
    ctx["offer"] = offer
    ctx["submission"] = _ok(api.get_submission(ctx["submission"]["id"], DIRECTOR), "get_submission")
    return ctx


def accept_offer(offer: dict, submission: dict, agent_id: str = None, **overrides) -> dict:
    """Accept a live offer; returns the created DealMemo.

    Actor rule (PRD 3.7): the submission's own agent accepts for represented
    submissions; a CastingDirector countersigns self-submissions.
    """
    payload = create_accept_payload(**overrides)
    headers = make_agent_headers(agent_id) if agent_id else DIRECTOR
    return _ok(api.accept_offer(offer["id"], payload, headers), "accept_offer")


def setup_accepted_memo(accept_overrides=None, **kwargs) -> dict:
    ctx = setup_offer_pending(**kwargs)
    agent_id = ctx["agent"]["id"] if ctx.get("agent") else None
    memo = accept_offer(ctx["offer"], ctx["submission"], agent_id=agent_id, **(accept_overrides or {}))
    ctx["memo"] = memo
    ctx["offer"] = _ok(api.get_offer(ctx["offer"]["id"], DIRECTOR), "get_offer")
    return ctx


def create_booking(submission_id: str, deal_memo_id: str, work_permit_id: str = None) -> dict:
    return _ok(
        api.create_booking(create_booking_payload(submission_id, deal_memo_id, work_permit_id=work_permit_id), COORDINATOR),
        "create_booking",
    )


def confirm_booking(booking_id: str) -> dict:
    return _ok(api.confirm_booking(booking_id, COORDINATOR), "confirm_booking")


def setup_pending_booking(work_permit_id: str = None, **kwargs) -> dict:
    ctx = setup_accepted_memo(**kwargs)
    booking = create_booking(ctx["submission"]["id"], ctx["memo"]["id"], work_permit_id=work_permit_id)
    ctx["booking"] = booking
    return ctx


def setup_confirmed_booking(**kwargs) -> dict:
    ctx = setup_pending_booking(**kwargs)
    ctx["booking"] = confirm_booking(ctx["booking"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: multi-engagement accumulation (union eligibility, overlap)
# ---------------------------------------------------------------------------

def book_talent_on_new_role(
    production_id: str,
    talent: dict,
    character_name: str,
    engagement_start: str,
    engagement_end: str,
    session_date: str,
    confirm: bool = True,
    is_union_covered: bool = True,
    offer_expires: str = None,
) -> dict:
    """Full chain for one engagement of an existing talent on a fresh role of
    an existing production: role -> breakdown -> release -> submission ->
    review -> shortlist -> session -> appointment -> confirm -> complete ->
    offer -> accept -> booking -> (optional) confirm.

    `session_date` is a YYYY-MM-DD style date prefix ("2026-08-04"); the
    session occupies 09:00-12:00 that day and the clock is advanced to 13:00
    that day before the appointment is completed and the booking confirmed.
    """
    role = create_role(
        production_id,
        character_name=character_name,
        is_union_covered=is_union_covered,
        engagement_start=f"{engagement_start}T00:00:00Z",
        engagement_end=f"{engagement_end}T00:00:00Z",
    )
    breakdown = create_breakdown(production_id, role["id"])
    breakdown = release_breakdown(breakdown["id"], distribution="OPEN_CALL")
    submission = submit_talent(breakdown["id"], talent["id"])
    submission = advance_to_shortlisted(submission["id"])
    session = create_session(
        breakdown["id"],
        session_start=f"{session_date}T09:00:00Z",
        session_end=f"{session_date}T12:00:00Z",
    )
    appointment = propose_appointment(
        session["id"],
        submission["id"],
        slot_start=f"{session_date}T09:00:00Z",
        slot_end=f"{session_date}T09:30:00Z",
    )
    confirm_appointment(appointment["id"])
    set_clock(f"{session_date}T13:00:00Z")
    _ok(api.complete_appointment(appointment["id"], ASSOCIATE), "complete_appointment")
    offer_kw = {}
    if offer_expires:
        offer_kw["expires_at"] = offer_expires
    offer = create_offer(submission["id"], **offer_kw)
    memo = accept_offer(
        offer,
        submission,
        engagement_start=f"{engagement_start}T00:00:00Z",
        engagement_end=f"{engagement_end}T00:00:00Z",
        proration_mode="CALENDAR_SPAN",
    )
    booking = create_booking(submission["id"], memo["id"])
    if confirm:
        booking = confirm_booking(booking["id"])
    return {
        "role": role,
        "breakdown": breakdown,
        "submission": submission,
        "session": session,
        "appointment": appointment,
        "offer": offer,
        "memo": memo,
        "booking": booking,
    }


# ---------------------------------------------------------------------------
# Tier 5: minor-permit pipeline helpers
# ---------------------------------------------------------------------------

def setup_minor_pipeline(with_verified_permit: bool = False, **kwargs) -> dict:
    """Minor-role production + minor talent walked to OFFER_PENDING, with a
    guardian and (optionally pre-verified) permit registered."""
    kwargs.setdefault("role_overrides", {})
    kwargs["role_overrides"]["is_minor_role"] = True
    kwargs.setdefault("talent_overrides", {})
    kwargs["talent_overrides"]["date_of_birth"] = _D["MINOR_DOB"]
    ctx = setup_offer_pending(**kwargs)
    guardian = create_guardian()
    permit = create_permit(ctx["talent"]["id"], ctx["production"]["id"], guardian["id"])
    if with_verified_permit:
        permit = _ok(api.verify_permit(permit["id"], COORDINATOR), "verify_permit")
    ctx.update({"guardian": guardian, "permit": permit})
    return ctx


def place_hold(submission_id: str, talent_id: str, **overrides) -> dict:
    return _ok(api.create_hold(submission_id, create_hold_payload(talent_id, **overrides), DIRECTOR), "create_hold")


def upload_self_tape(submission_id: str, **overrides) -> dict:
    return _ok(api.create_self_tape(submission_id, create_self_tape_payload(**overrides), ASSOCIATE), "create_self_tape")


def counter_offer(offer: dict, as_agent_id: str = None, **overrides) -> dict:
    """Counter a live offer; returns the newly created next-round offer."""
    payload = create_counter_payload(offer["version"], **overrides)
    headers = make_agent_headers(as_agent_id) if as_agent_id else DIRECTOR
    return _ok(api.counter_offer(offer["id"], payload, headers), "counter_offer")
