"""Composite setup helpers.

Encapsulates the multi-step preambles that most claims require so tests can
focus on assertions. All helpers build their preconditions from scratch
against an empty database, using only PRD-declared endpoints. They use the
lenient get_success_data() validator internally so a setup failure surfaces a
clear "Setup failed" error rather than a confusing assertion deep in a test.

Identity threading: after creating an entity_backed Member/Flexologist, any
ownership-gated call uses make_member_headers(member_id) /
make_flexologist_headers(flexologist_id) with the real id.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_member_headers,
    make_flexologist_headers,
    make_front_desk_headers,
    make_studio_manager_headers,
)
from . import factories


SM = make_studio_manager_headers()
FD = make_front_desk_headers()


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _plus(clock_iso, **delta):
    """Return an ISO instant offset from clock_iso by the given timedelta kwargs."""
    raw = clock_iso[:-1] + "+00:00" if clock_iso.endswith("Z") else clock_iso
    base = datetime.fromisoformat(raw)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return _iso((base + timedelta(**delta)).astimezone(timezone.utc))


def set_clock(to_iso8601):
    """Move the logical clock (StudioManager-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, SM))


def sweep():
    """Run the no-show / expiry / strike sweep (StudioManager-only)."""
    return get_success_data(api_client.no_show_sweep(SM))


# ---------------------------------------------------------------------------
# Catalog primitives
# ---------------------------------------------------------------------------

def create_location(**overrides):
    return get_success_data(api_client.create_location(
        factories.create_location_payload(**overrides), SM))


def create_flexologist(location_id, **overrides):
    return get_success_data(api_client.create_flexologist(
        factories.create_flexologist_payload(location_id, **overrides), SM))


def create_table(location_id, **overrides):
    return get_success_data(api_client.create_table(
        factories.create_table_payload(location_id, **overrides), SM))


def create_service(location_id, **overrides):
    return get_success_data(api_client.create_service(
        factories.create_service_payload(location_id, **overrides), SM))


def create_member(home_location_id, **overrides):
    return get_success_data(api_client.create_member(
        factories.create_member_payload(home_location_id, **overrides), FD))


def create_credit_pack(member_id, location_id, **overrides):
    return get_success_data(api_client.create_credit_pack(
        factories.create_credit_pack_payload(member_id, location_id, **overrides), FD))


def create_membership(member_id, location_id, **overrides):
    return get_success_data(api_client.create_membership(
        factories.create_membership_payload(member_id, location_id, **overrides), FD))


# ---------------------------------------------------------------------------
# Tier 2: Entity hierarchy — base catalog + member
# ---------------------------------------------------------------------------

def setup_base_studio(open_minute_of_day=0, close_minute_of_day=1440,
                      clock="2026-04-10T00:00:00Z", n_tables=1, certified=True,
                      **loc_overrides):
    """Active studio: clock set, one OPEN location (24h by default), one
    flexologist, n tables, an INTRO service, and a fresh member.

    Returns a dict with: loc, flex, tables (list of ids), table (tables[0]),
    svc_intro, member (id).
    """
    set_clock(clock)
    loc = create_location(open_minute_of_day=open_minute_of_day,
                          close_minute_of_day=close_minute_of_day, **loc_overrides)
    flex = create_flexologist(loc["id"], full_name="Flex", certified_intro=certified)
    tables = [create_table(loc["id"], label=f"T{i + 1}")["id"] for i in range(n_tables)]
    svc_intro = create_service(loc["id"], name="Intro", kind="INTRO",
                               duration_minutes=25, credit_cost=0, list_price_cents=0)
    member = create_member(loc["id"], full_name="Mem", email="mem@x.com")
    return {
        "loc": loc,
        "flex": flex,
        "tables": tables,
        "table": tables[0],
        "svc_intro": svc_intro,
        "member": member,
    }


# ---------------------------------------------------------------------------
# Tier 3: Full lifecycle shortcut — complete the intro gate
# ---------------------------------------------------------------------------

def complete_intro(member_id, location_id, flexologist_id, table_id, svc_intro_id,
                   intro_start="2026-04-11T08:00:00Z",
                   complete_clock="2026-04-11T08:30:00Z",
                   assessment=None, pack_id=None):
    """Walk a member through their INTRO booking to COMPLETED so intro_completed
    flips true and mobility_tier is set. Returns the completed intro booking.

    If pack_id is None, a 1-credit pack is created to fund the (free, 0-credit)
    intro booking.
    """
    if pack_id is None:
        pack_id = create_credit_pack(member_id, location_id, pack_credits=1,
                                     base_unit_price_cents=100)["id"]
    b_intro = get_success_data(api_client.create_booking(
        factories.create_booking_payload(
            member_id, location_id, svc_intro_id, flexologist_id, table_id,
            intro_start, "CREDIT_PACK", pack_id), FD))
    get_success_data(api_client.confirm_booking(b_intro["id"], FD))
    set_clock(complete_clock)
    payload = assessment if assessment is not None else factories.intro_assessment_payload()
    completed = get_success_data(api_client.complete_booking(
        b_intro["id"], make_flexologist_headers(flexologist_id), payload))
    return completed


def setup_intro_completed_member(clock="2026-04-10T00:00:00Z",
                                 open_minute_of_day=0, close_minute_of_day=1440,
                                 n_tables=1, n_flexologists=1, certified=True,
                                 assessment=None, **loc_overrides):
    """Full preamble producing an intro-completed member ready to book non-INTRO
    services and to purchase a membership.

    Returns dict: loc, flexes (list of ids), flex (flexes[0]), tables (list),
    table (tables[0]), svc_intro, member (id). The intro booking is completed
    using a transient 1-credit pack on tables[0] / flexes[0].
    """
    set_clock(clock)
    loc = create_location(open_minute_of_day=open_minute_of_day,
                          close_minute_of_day=close_minute_of_day, **loc_overrides)
    flex_objs = [create_flexologist(loc["id"], full_name=f"Flex{i}", certified_intro=certified)
                 for i in range(n_flexologists)]
    flexes = [f["id"] for f in flex_objs]
    tables = [create_table(loc["id"], label=f"T{i + 1}")["id"] for i in range(n_tables)]
    svc_intro = create_service(loc["id"], name="Intro", kind="INTRO",
                               duration_minutes=25, credit_cost=0, list_price_cents=0)
    member = create_member(loc["id"], full_name="Mem", email="mem@x.com")
    # Intro booking must start strictly after the current clock and be completed
    # only once the clock has reached its start. Derive both relative to the
    # caller-supplied clock so the preamble is valid for any clock value, then
    # leave the clock back at the caller's clock so the test starts from a known
    # instant (complete_intro advances the clock to complete_clock).
    intro_start = _plus(clock, hours=1)
    complete_clock = _plus(clock, hours=1, minutes=30)
    complete_intro(member["id"], loc["id"], flexes[0], tables[0], svc_intro["id"],
                   intro_start=intro_start, complete_clock=complete_clock,
                   assessment=assessment)
    set_clock(clock)
    return {
        "loc": loc,
        "flexes": flexes,
        "flex": flex_objs[0],
        "tables": tables,
        "table": tables[0],
        "svc_intro": svc_intro,
        "member": member,
    }


# ---------------------------------------------------------------------------
# Booking lifecycle helpers
# ---------------------------------------------------------------------------

def create_booking(member_id, location_id, service_id, flexologist_id, table_id,
                   session_start_utc, funding_source, funding_id, **overrides):
    return get_success_data(api_client.create_booking(
        factories.create_booking_payload(
            member_id, location_id, service_id, flexologist_id, table_id,
            session_start_utc, funding_source, funding_id, **overrides), FD))


def create_confirmed_booking(member_id, location_id, service_id, flexologist_id,
                             table_id, session_start_utc, funding_source, funding_id,
                             **overrides):
    """Create + confirm. Returns the booking after confirm (CONFIRMED)."""
    bk = create_booking(member_id, location_id, service_id, flexologist_id, table_id,
                        session_start_utc, funding_source, funding_id, **overrides)
    confirmed = get_success_data(api_client.confirm_booking(bk["id"], FD))
    return confirmed


def create_completed_booking(member_id, location_id, service_id, flexologist_id,
                             table_id, session_start_utc, funding_source, funding_id,
                             complete_clock, complete_payload=None, **overrides):
    """Create + confirm + complete. Advances the clock to complete_clock before
    completing (the complete precondition requires clock >= session_start_utc).
    Returns the completed booking."""
    bk = create_booking(member_id, location_id, service_id, flexologist_id, table_id,
                        session_start_utc, funding_source, funding_id, **overrides)
    get_success_data(api_client.confirm_booking(bk["id"], FD))
    set_clock(complete_clock)
    completed = get_success_data(api_client.complete_booking(
        bk["id"], make_flexologist_headers(flexologist_id), complete_payload or {}))
    return completed


# ---------------------------------------------------------------------------
# Tier 4: Accumulation / threshold targeting — strike score & suspension
# ---------------------------------------------------------------------------

def drive_no_shows(member_id, location_id, service_id, flexologist_id, table_ids,
                   start_instants, sweep_clock, funding_source, funding_id):
    """Create + confirm one booking per (table_id, start) pair, then advance the
    clock past their ends and run the sweep so they all become NO_SHOW (2 pts
    each). Caller supplies distinct tables/instants to avoid overlaps.
    Returns the list of booking ids."""
    bks = []
    for tbl, start in zip(table_ids, start_instants):
        bk = create_confirmed_booking(member_id, location_id, service_id,
                                      flexologist_id, tbl, start,
                                      funding_source, funding_id)
        bks.append(bk["id"])
    set_clock(sweep_clock)
    sweep()
    return bks
