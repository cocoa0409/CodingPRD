"""Composite setup helpers for multi-step test prerequisites.

All helpers build state from scratch against an empty database using only
PRD-declared endpoints, and use get_success_data() so a setup failure
surfaces as a clear "Setup failed" message rather than a confusing
assertion failure.

Ownership threading: any call whose role is entity-backed (Volunteer,
Captain, GroupLeader) is issued with per-instance headers built from the
real entity id (make_volunteer_headers / make_captain_headers /
make_group_leader_headers), never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import constants as C
from .api_client import api_client
from .factories import (
    create_course_segment_payload,
    create_debrief_report_payload,
    create_event_payload,
    create_fundraising_group_payload,
    create_role_adjustment_payload,
    create_role_catalog_entry_payload,
    create_shift_payload,
    create_signup_payload,
    create_supply_inventory_payload,
    create_training_record_payload,
    create_volunteer_payload,
)
from .test_users import (
    TEST_USERS,
    make_captain_headers,
    make_volunteer_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-step primitives (clock, event, catalog building blocks)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=C.IN_GENERAL_WINDOW):
    """Drive the server logical clock (PRD §2.4). Defaults to an instant
    inside the general signup window of the standard event window."""
    return get_success_data(api_client.set_current_utc(to_iso8601, DIRECTOR))


def create_event(clock=C.IN_GENERAL_WINDOW, **overrides):
    """Set the clock and create a DRAFT event on the standard window."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.create_event(create_event_payload(**overrides), DIRECTOR))


def add_segment(event_id, **overrides):
    return get_success_data(api_client.create_course_segment(
        create_course_segment_payload(event_id, **overrides), COORDINATOR))


def add_role(event_id, **overrides):
    return get_success_data(api_client.create_role_catalog_entry(
        create_role_catalog_entry_payload(event_id, **overrides), COORDINATOR))


def add_shift(event_id, role_entry_id, segment_id, **overrides):
    return get_success_data(api_client.create_shift(
        create_shift_payload(event_id, role_entry_id, segment_id, **overrides), COORDINATOR))


def publish_event(event_id):
    return get_success_data(api_client.publish_event(event_id, DIRECTOR))


def add_group(event_id, **overrides):
    return get_success_data(api_client.create_fundraising_group(
        create_fundraising_group_payload(event_id, **overrides), DIRECTOR))


def add_inventory(event_id, **overrides):
    return get_success_data(api_client.create_supply_inventory(
        create_supply_inventory_payload(event_id, **overrides), COORDINATOR))


# ---------------------------------------------------------------------------
# Tier 2: volunteers and training
# ---------------------------------------------------------------------------

def register_volunteer(event_id, **overrides):
    """Self-service registration as Anonymous (PRD §3.3). Starts REGISTERED."""
    return get_success_data(api_client.create_volunteer(
        create_volunteer_payload(event_id, **overrides), ANONYMOUS))


def screen_volunteer(volunteer_id):
    """REGISTERED -> ELIGIBLE (PRD §3.3)."""
    return get_success_data(api_client.screen_volunteer(volunteer_id, COORDINATOR))


def register_eligible_volunteer(event_id, **overrides):
    """Register + screen. Returns the ELIGIBLE volunteer."""
    vol = register_volunteer(event_id, **overrides)
    return screen_volunteer(vol["id"])


def enroll_and_pass(event_id, volunteer_id, module_code):
    """Create a training record and pass it. Returns the PASSED record."""
    rec = get_success_data(api_client.create_training_record(
        create_training_record_payload(event_id, volunteer_id, module_code=module_code),
        COORDINATOR))
    return get_success_data(api_client.pass_training_record(rec["id"], COORDINATOR))


# ---------------------------------------------------------------------------
# Tier 3: signup pipeline shortcuts (PRD §3.5)
# ---------------------------------------------------------------------------

def request_signup(volunteer_id, shift_id, as_self=False):
    """Create a signup (REQUESTED when a seat is free, WAITLISTED when full)."""
    headers = make_volunteer_headers(volunteer_id) if as_self else COORDINATOR
    return get_success_data(api_client.create_signup(
        create_signup_payload(volunteer_id, shift_id), headers))


def approve_signup(signup_id):
    return get_success_data(api_client.approve_signup(signup_id, COORDINATOR))


def confirm_signup(signup_id, volunteer_id):
    """Confirmation is personal: X-User-ID must equal the signup's volunteer_id."""
    return get_success_data(api_client.confirm_signup(
        signup_id, make_volunteer_headers(volunteer_id)))


def create_confirmed_signup(volunteer_id, shift_id):
    """request -> approve -> confirm. Returns the CONFIRMED signup."""
    sg = request_signup(volunteer_id, shift_id)
    approve_signup(sg["id"])
    return confirm_signup(sg["id"], volunteer_id)


# ---------------------------------------------------------------------------
# Tier 4: event phase walks
# ---------------------------------------------------------------------------

def lock_and_start_race_day(event_id, at=C.EVENT_START):
    """PUBLISHED -> LOCKED -> (clock to race start) -> RACE_DAY."""
    get_success_data(api_client.lock_signups(event_id, DIRECTOR))
    set_clock(at)
    return get_success_data(api_client.start_race_day(event_id, DIRECTOR))


def complete_and_open_debrief(event_id, at=C.EVENT_END):
    """RACE_DAY -> COMPLETED -> DEBRIEF_OPEN (clock at/after event end)."""
    set_clock(at)
    get_success_data(api_client.complete_event(event_id, DIRECTOR))
    return get_success_data(api_client.open_debrief(event_id, DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 5: composite scenarios
# ---------------------------------------------------------------------------

def setup_event_with_shift(headcount=1, role_overrides=None, shift_overrides=None,
                           event_overrides=None, clock=C.IN_GENERAL_WINDOW,
                           segment_overrides=None, publish=True):
    """Event + one segment + one role + one shift; optionally PUBLISHED.

    Returns a context dict with keys: event, segment, role, shift.
    """
    event = create_event(clock=clock, **(event_overrides or {}))
    segment = add_segment(event["id"], **(segment_overrides or {}))
    role = add_role(event["id"], **(role_overrides or {}))
    shift = add_shift(event["id"], role["id"], segment["id"],
                      **(shift_overrides or {"required_headcount": headcount}))
    if publish:
        publish_event(event["id"])
        event = get_success_data(api_client.get_event(event["id"], DIRECTOR))
    return {"event": event, "segment": segment, "role": role, "shift": shift}


def setup_published_with_volunteers(volunteer_specs, **kwargs):
    """setup_event_with_shift + one ELIGIBLE volunteer per spec.

    volunteer_specs: list of dicts of volunteer overrides.
    Returns ctx with extra key "volunteers" (list).
    """
    ctx = setup_event_with_shift(**kwargs)
    vols = [register_eligible_volunteer(ctx["event"]["id"], **spec)
            for spec in volunteer_specs]
    ctx["volunteers"] = vols
    return ctx


def setup_race_day_with_confirmed(volunteer_specs, checkin_at=None, **kwargs):
    """Published shift + one CONFIRMED signup per volunteer, event at RACE_DAY.

    Returns ctx with keys: event, segment, role, shift, volunteers, signups.
    The clock ends at `checkin_at` (default: the shift's start instant).
    """
    ctx = setup_published_with_volunteers(volunteer_specs, **kwargs)
    signups = [create_confirmed_signup(v["id"], ctx["shift"]["id"])
               for v in ctx["volunteers"]]
    lock_and_start_race_day(ctx["event"]["id"])
    if checkin_at is not None:
        set_clock(checkin_at)
    ctx["signups"] = signups
    return ctx


def check_in_signup(signup_id):
    return get_success_data(api_client.check_in_signup(signup_id, COORDINATOR))


def check_out_signup(signup_id, at_iso, break_minutes=None):
    """Move the clock and check out; returns the COMPLETED signup."""
    set_clock(at_iso)
    return get_success_data(api_client.check_out_signup(
        signup_id, COORDINATOR, break_minutes=break_minutes))


def fetch_hour_log_for_signup(signup_id):
    """Fetch the single hour log spawned at check-out (PRD §3.6)."""
    resp = api_client.list_hour_logs(COORDINATOR, params={"signup_id": signup_id})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"Setup failed: expected exactly 1 hour log for {signup_id}, got {len(data)}"
    return data[0]


def create_completed_signup_with_log(volunteer_id, shift_id, checkin_at,
                                     checkout_at, break_minutes=None):
    """Race-day walk for one signup: check-in -> check-out -> hour log.

    Assumes the event is already RACE_DAY and the signup is CONFIRMED.
    Returns (completed_signup, hour_log).
    """
    set_clock(checkin_at)
    check_in_signup(signup_id)
    completed = check_out_signup(signup_id, checkout_at, break_minutes=break_minutes)
    log = fetch_hour_log_for_signup(signup_id)
    return completed, log


def setup_captain_on_shift(volunteer_overrides=None, **kwargs):
    """Published shift + an ELIGIBLE volunteer with passed CAPTAIN_COURSE,
    CONFIRMED signup, designated captain. Returns ctx with keys
    event/segment/role/shift/captain (volunteer)/captain_signup."""
    ctx = setup_event_with_shift(**kwargs)
    vol = register_eligible_volunteer(ctx["event"]["id"], **(volunteer_overrides or {}))
    enroll_and_pass(ctx["event"]["id"], vol["id"], "CAPTAIN_COURSE")
    sg = create_confirmed_signup(vol["id"], ctx["shift"]["id"])
    sg = get_success_data(api_client.assign_captain(sg["id"], COORDINATOR))
    ctx["captain"] = vol
    ctx["captain_signup"] = sg
    return ctx


def setup_debrief_open_with_captain(volunteer_overrides=None, checkin_at=None,
                                    checkout_at="2026-10-04T10:00:00Z", **kwargs):
    """Full lifecycle to DEBRIEF_OPEN with a captain who worked the shift.

    Walk: published shift -> captain signup CONFIRMED + is_captain -> lock ->
    RACE_DAY -> check-in -> check-out -> complete -> open-debrief.
    Returns ctx with keys event/segment/role/shift/captain/captain_signup/hour_log.
    """
    ctx = setup_captain_on_shift(volunteer_overrides=volunteer_overrides, **kwargs)
    shift = ctx["shift"]
    sg = ctx["captain_signup"]
    lock_and_start_race_day(ctx["event"]["id"])
    check_in_at = checkin_at or shift["start_at"]
    set_clock(check_in_at)
    check_in_signup(sg["id"])
    completed = check_out_signup(sg["id"], checkout_at)
    ctx["captain_signup"] = completed
    ctx["hour_log"] = fetch_hour_log_for_signup(sg["id"])
    complete_and_open_debrief(ctx["event"]["id"])
    return ctx


def create_debrief(ctx, headcount_actual=1, rating=3, **overrides):
    """Captain-authored DRAFT debrief for the context's shift (PRD §3.9)."""
    payload = create_debrief_report_payload(
        ctx["event"]["id"], ctx["shift"]["id"], ctx["captain"]["id"],
        headcount_actual=headcount_actual, role_effectiveness_rating=rating,
        **overrides)
    return get_success_data(api_client.create_debrief_report(
        payload, make_captain_headers(ctx["captain"]["id"])))


def submit_debrief(ctx, debrief_id):
    return get_success_data(api_client.submit_debrief_report(
        debrief_id, make_captain_headers(ctx["captain"]["id"])))


def setup_acknowledged_debrief(**kwargs):
    """DEBRIEF_OPEN context + a captain debrief driven to ACKNOWLEDGED.

    Returns (ctx, debrief).
    """
    ctx = setup_debrief_open_with_captain(**kwargs)
    debrief = create_debrief(ctx)
    submit_debrief(ctx, debrief["id"])
    debrief = get_success_data(api_client.acknowledge_debrief_report(debrief["id"], COORDINATOR))
    return ctx, debrief


def propose_adjustment(ctx, debrief_id, **overrides):
    payload = create_role_adjustment_payload(
        ctx["event"]["id"], ctx["role"]["id"], debrief_id, **overrides)
    return get_success_data(api_client.create_role_adjustment(payload, COORDINATOR))


# ---------------------------------------------------------------------------
# Credit / recognition scenario helpers (PRD §3.8, §3.9)
# ---------------------------------------------------------------------------

def add_group_volunteer(ctx, group_id, **overrides):
    """Register + screen a volunteer affiliated with the given group."""
    return register_eligible_volunteer(ctx["event"]["id"], group_id=group_id, **overrides)


def work_signup_to_log(signup_id, checkin_at, checkout_at, break_minutes=None):
    """Race-day: check in at checkin_at, check out at checkout_at, return the log."""
    set_clock(checkin_at)
    check_in_signup(signup_id)
    return check_out_and_fetch_log(signup_id, checkout_at, break_minutes=break_minutes)


def check_out_and_fetch_log(signup_id, checkout_at, break_minutes=None):
    completed = check_out_signup(signup_id, checkout_at, break_minutes=break_minutes)
    return fetch_hour_log_for_signup(signup_id)


def verify_log(hour_log_id):
    return get_success_data(api_client.verify_hour_log(hour_log_id, COORDINATOR))
