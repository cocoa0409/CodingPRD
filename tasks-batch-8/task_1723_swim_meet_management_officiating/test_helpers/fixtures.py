"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: TeamCoach calls carry X-User-ID == the acting Team.id;
DeckOfficial / MeetReferee calls carry X-User-ID == the acting Official.id.
Fixtures build per-instance headers from the real entity ids and never fall
back to the shared constants for ownership-gated calls.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_MEET_DAY_1000,
    CLOCK_PAST_DEADLINE,
)
from .factories import (
    create_disqualification_payload,
    create_entry_payload,
    create_event_payload,
    create_meet_payload,
    create_official_assignment_payload,
    create_official_payload,
    create_relay_leg_payload,
    create_relay_team_payload,
    create_standing_record_payload,
    create_swimmer_payload,
    create_team_payload,
    readings_payload,
)
from .test_users import (
    TEST_USERS,
    make_deck_official_headers,
    make_meet_referee_headers,
    make_team_coach_headers,
)

DIRECTOR = TEST_USERS["meet_director_headers"]
TIMING = TEST_USERS["timing_operator_headers"]
RECORDS = TEST_USERS["records_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and small steps
# ---------------------------------------------------------------------------

def create_meet(meet_name="Test Meet", **overrides):
    """Create a meet (born SETUP). Returns the meet."""
    payload = create_meet_payload(meet_name=meet_name, **overrides)
    return get_success_data(api_client.create_meet(payload, DIRECTOR))


def open_meet(meet_id):
    """SETUP -> ENTRIES_OPEN. Returns the meet."""
    return get_success_data(api_client.open_entries(meet_id, DIRECTOR))


def create_open_meet(meet_name="Test Meet", **overrides):
    """Create a meet and open entries. Returns the meet (ENTRIES_OPEN)."""
    meet = create_meet(meet_name=meet_name, **overrides)
    return open_meet(meet["id"])


def add_team(meet_id, team_code="AAA", team_name="Aquatics"):
    """Register a team (born REGISTERED, points and count zero)."""
    payload = create_team_payload(meet_id, team_code=team_code, team_name=team_name)
    return get_success_data(api_client.create_team(payload, DIRECTOR))


def add_swimmer(team_id, full_name="Test Swimmer", birth_date="2014-03-10",
                gender="M"):
    """Register a swimmer onto a team; coach identity is the team id."""
    payload = create_swimmer_payload(
        team_id, full_name=full_name, birth_date=birth_date, gender=gender)
    return get_success_data(
        api_client.create_swimmer(payload, make_team_coach_headers(team_id)))


def add_event(meet_id, event_number=1, gender="M", age_group="ELEVEN_TWELVE",
              stroke="FREESTYLE", distance_meters=50, is_relay=False,
              qualifying_time_cs=None, session_date="2026-08-15",
              scheduled_start_minute=540, scheduled_end_minute=570):
    """Define an event (born PENDING)."""
    payload = create_event_payload(
        meet_id, event_number=event_number, gender=gender, age_group=age_group,
        stroke=stroke, distance_meters=distance_meters, is_relay=is_relay,
        session_date=session_date, scheduled_start_minute=scheduled_start_minute,
        scheduled_end_minute=scheduled_end_minute)
    if qualifying_time_cs is not None:
        payload["qualifying_time_cs"] = qualifying_time_cs
    return get_success_data(api_client.create_event(payload, DIRECTOR))


def add_entry(event_id, swimmer_id, team_id, seed_time_cs=None):
    """Create an individual entry (ENTERED / UNVERIFIED) as the team's coach."""
    payload = create_entry_payload(event_id, swimmer_id)
    if seed_time_cs is not None:
        payload["seed_time_cs"] = seed_time_cs
    return get_success_data(
        api_client.create_entry(payload, make_team_coach_headers(team_id)))


def verify_entry(entry_id):
    """Director decides the entry's qualification. Returns the entry."""
    return get_success_data(api_client.verify_entry(entry_id, DIRECTOR))


def add_official(meet_id, full_name="Test Official", lsc_membership_id="LSC-001",
                 certifications=("REFEREE",), certification_expires_on="2027-01-01"):
    """Roster an official. Returns the official."""
    payload = create_official_payload(
        meet_id, full_name=full_name, lsc_membership_id=lsc_membership_id,
        certifications=list(certifications),
        certification_expires_on=certification_expires_on)
    return get_success_data(api_client.create_official(payload, DIRECTOR))


def propose_assignment(event_id, official_id, role_on_deck):
    """Propose an official assignment (born PROPOSED)."""
    payload = create_official_assignment_payload(official_id, role_on_deck)
    return get_success_data(
        api_client.create_official_assignment(event_id, payload, DIRECTOR))


def confirm_assignment(assignment_id, official_id, as_referee=False):
    """The assigned official confirms their own assignment.

    as_referee=True presents the MeetReferee role, otherwise DeckOfficial.
    """
    headers = (make_meet_referee_headers(official_id) if as_referee
               else make_deck_official_headers(official_id))
    return get_success_data(
        api_client.confirm_official_assignment(assignment_id, headers))


# ---------------------------------------------------------------------------
# Tier 2: relay construction
# ---------------------------------------------------------------------------

def declare_relay(team_id, event_id, relay_name="A", seed_time_cs=None):
    """Declare a relay team (DECLARED); its EventEntry is auto-created."""
    payload = create_relay_team_payload(team_id, event_id, relay_name=relay_name)
    if seed_time_cs is not None:
        payload["seed_time_cs"] = seed_time_cs
    return get_success_data(
        api_client.create_relay_team(payload, make_team_coach_headers(team_id)))


def add_relay_leg(relay_team_id, team_id, leg_number, swimmer_id):
    """Add or replace a leg while the relay is DECLARED."""
    payload = create_relay_leg_payload(leg_number, swimmer_id)
    return get_success_data(api_client.add_relay_leg(
        relay_team_id, payload, make_team_coach_headers(team_id)))


def declare_relay_with_legs(team_id, event_id, swimmer_ids, relay_name="A",
                            seed_time_cs=None, lock=False):
    """Relay DECLARED with the given legs posted; optionally verified + locked."""
    relay = declare_relay(team_id, event_id, relay_name=relay_name,
                          seed_time_cs=seed_time_cs)
    for i, swimmer_id in enumerate(swimmer_ids, start=1):
        add_relay_leg(relay["id"], team_id, i, swimmer_id)
    if lock:
        verify_entry(relay["entry_id"])
        relay = get_success_data(api_client.lock_relay_team(
            relay["id"], make_team_coach_headers(team_id)))
    return relay


# ---------------------------------------------------------------------------
# Tier 3: meet progression (close + seed) and deck coverage
# ---------------------------------------------------------------------------

def seed_meet(meet_id, clock_to=CLOCK_PAST_DEADLINE):
    """Advance the clock past the deadline, close entries, then seed (OCC).

    Returns the seeded meet.
    """
    get_success_data(api_client.set_clock(clock_to, DIRECTOR))
    closed = get_success_data(api_client.close_entries(meet_id, DIRECTOR))
    return get_success_data(
        api_client.seed_meet(meet_id, closed["version"], DIRECTOR))


def setup_deck_coverage(event_id, meet_id, lsc_prefix="LSC"):
    """Roster + propose + CONFIRM a REFEREE and a STROKE_TURN_JUDGE.

    Returns {"referee": official, "judge": official} — full deck coverage so
    the event can start (PRD §3.7).
    """
    referee = add_official(meet_id, full_name="Ref R",
                           lsc_membership_id=f"{lsc_prefix}-R",
                           certifications=["REFEREE"])
    judge = add_official(meet_id, full_name="Jud J",
                         lsc_membership_id=f"{lsc_prefix}-J",
                         certifications=["STROKE_TURN_JUDGE"])
    oa_ref = propose_assignment(event_id, referee["id"], "REFEREE")
    confirm_assignment(oa_ref["id"], referee["id"], as_referee=True)
    oa_jud = propose_assignment(event_id, judge["id"], "STROKE_TURN_JUDGE")
    confirm_assignment(oa_jud["id"], judge["id"], as_referee=False)
    return {"referee": referee, "judge": judge,
            "oa_referee": oa_ref, "oa_judge": oa_jud}


def start_event(event_id):
    """SEEDED -> IN_PROGRESS. Returns the started event (captures version)."""
    return get_success_data(api_client.start_event(event_id, DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 4: lane helpers and readings
# ---------------------------------------------------------------------------

def lane_for_entry(entry_id):
    """The single LaneAssignment seeded for an entry."""
    lanes = get_success_data(
        api_client.list_lane_assignments(DIRECTOR, params={"entry_id": entry_id}))
    assert len(lanes) == 1, f"expected exactly one lane for entry {entry_id}"
    return lanes[0]


def lanes_for_event(event_id):
    return get_success_data(
        api_client.list_lane_assignments(DIRECTOR, params={"event_id": event_id}))


def submit_clean_readings(lane_id, pad_cs):
    """Readings that always auto-confirm: backups sit 6cs from the pad."""
    payload = readings_payload(pad_cs=pad_cs, backup1_cs=pad_cs + 5,
                               backup2_cs=pad_cs + 7)
    return get_success_data(api_client.submit_readings(lane_id, payload, TIMING))


# ---------------------------------------------------------------------------
# Tier 5: full event lifecycle workspaces
# ---------------------------------------------------------------------------

def setup_in_progress_event(meet_name="Meet", meet_overrides=None,
                            event_overrides=None, seed_times=(2900,),
                            team_codes=("AAA",), swimmer_teams=None):
    """Full chain to a single individual event IN_PROGRESS.

    seed_times: per-swimmer seed times (one swimmer per entry).
    team_codes: available team codes; swimmer_teams maps each seed index to a
        team code (default: all swimmers on the first team).

    Returns a workspace dict:
        meet, event, teams {code: team}, swimmers [..], entries [..],
        lanes [..], coverage {referee, judge, ...}, event_version (post-start).
    """
    meet_overrides = meet_overrides or {}
    event_overrides = event_overrides or {}
    meet = create_open_meet(meet_name=meet_name, **meet_overrides)
    teams = {code: add_team(meet["id"], team_code=code, team_name=f"Team {code}")
             for code in team_codes}
    event = add_event(meet["id"], **{"event_number": 1, **event_overrides})

    swimmers, entries = [], []
    for i, seed in enumerate(seed_times):
        code = (swimmer_teams[i] if swimmer_teams else team_codes[0])
        team = teams[code]
        swimmer = add_swimmer(team["id"], full_name=f"Sw {i + 1}",
                              birth_date=f"2014-03-{(i % 27) + 1:02d}")
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=seed)
        verify_entry(entry["id"])
        swimmers.append(swimmer)
        entries.append(entry)

    coverage = setup_deck_coverage(event["id"], meet["id"])
    seed_meet(meet["id"])
    started = start_event(event["id"])
    lanes = [lane_for_entry(entry["id"]) for entry in entries]
    return {
        "meet": get_success_data(api_client.get_meet(meet["id"], DIRECTOR)),
        "event": get_success_data(api_client.get_event(event["id"], DIRECTOR)),
        "teams": teams,
        "swimmers": swimmers,
        "entries": entries,
        "lanes": lanes,
        "coverage": coverage,
        "event_version": started["version"],
    }


def complete_event_with_times(workspace, pad_times):
    """Submit auto-confirming readings for every lane, then complete the event.

    pad_times: per-lane pad readings (index-aligned with workspace["lanes"]).
    Returns the completed event.
    """
    for lane, pad in zip(workspace["lanes"], pad_times):
        submit_clean_readings(lane["id"], pad)
    return get_success_data(api_client.complete_event(
        workspace["event"]["id"], workspace["event_version"], DIRECTOR))


def record_dq(lane_id, judge_id, dq_code="FALSE_START", call_notes="call"):
    """A confirmed STROKE_TURN_JUDGE records a call on the lane (RECORDED)."""
    payload = create_disqualification_payload(dq_code=dq_code,
                                              call_notes=call_notes)
    return get_success_data(api_client.record_disqualification(
        lane_id, payload, make_deck_official_headers(judge_id)))


def notify_dq(disqualification_id, referee_id,
              clock_to=CLOCK_MEET_DAY_1000):
    """Referee marks the coach notified at the given logical instant."""
    get_success_data(api_client.set_clock(clock_to, DIRECTOR))
    return get_success_data(api_client.notify_coach(
        disqualification_id, make_meet_referee_headers(referee_id)))


def create_standing_record(event_id, record_time_cs=2450, holder_name="Old Star",
                           holder_team="OLD", set_on_date="2025-06-01"):
    """RecordsOfficer creates the standing record (born CURRENT)."""
    payload = create_standing_record_payload(
        record_time_cs=record_time_cs, holder_name=holder_name,
        holder_team=holder_team, set_on_date=set_on_date)
    return get_success_data(
        api_client.create_standing_record(event_id, payload, RECORDS))
