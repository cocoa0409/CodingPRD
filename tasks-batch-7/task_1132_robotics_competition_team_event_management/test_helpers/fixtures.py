"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch via the public API —
each test runs against a freshly restarted server with an empty database.
Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup failed" assertion rather than a confusing test assertion.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_event_payload,
    create_interview_slot_payload,
    create_match_payload,
    create_milestone_payload,
    create_part_order_payload,
    create_person_payload,
    create_queue_slot_payload,
    create_robot_inspection_payload,
    create_score_breakdown_payload,
    create_screening_record_payload,
    create_team_payload,
    create_violation_payload,
)
from .test_users import (
    TEST_USERS,
    make_head_referee_headers,
    make_inspector_headers,
    make_judge_headers,
    make_lead_inspector_headers,
    make_scorekeeper_headers,
    make_team_lead_headers,
)

ED = TEST_USERS["event_director_headers"]
RO = TEST_USERS["registration_officer_headers"]
SO = TEST_USERS["screening_officer_headers"]
PO = TEST_USERS["procurement_officer_headers"]
QM = TEST_USERS["queue_manager_headers"]
FRC = TEST_USERS["field_reset_crew_headers"]
JA = TEST_USERS["judge_advisor_headers"]
TO = TEST_USERS["travel_officer_headers"]

SLOT_POSITIONS = ["RED_1", "RED_2", "RED_3", "BLUE_1", "BLUE_2", "BLUE_3"]


def _d(resp, what="setup call"):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed ({what}): expected object payload, got {data!r}"
    return data


def _l(resp, what="setup list call"):
    """Extract the data array from a list endpoint during setup."""
    data = get_success_data(resp)
    assert isinstance(data, list), f"Setup failed ({what}): expected array payload, got {data!r}"
    return data


def _list_all(list_fn, *args, what="setup list call", **kwargs):
    """Page through a list endpoint (PRD §2.3 caps limit at 100, so large
    slates — e.g. 128 generated matches for a 24-team event — need offset
    pagination). `list_fn` is called as list_fn(*args, params={...}, **kwargs)."""
    items = []
    offset = 0
    while True:
        params = dict(kwargs.pop("params", None) or {})
        params.update({"limit": 100, "offset": offset})
        page = _l(list_fn(*args, params=params, **kwargs), what)
        items.extend(page)
        if len(page) < 100:
            return items
        offset += 100


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_current_utc(to_iso8601, ED)
    _d(resp, "set clock")


# ---------------------------------------------------------------------------
# Event + milestones
# ---------------------------------------------------------------------------

def create_event(**overrides):
    resp = api_client.create_event(create_event_payload(**overrides), ED)
    return _d(resp, "create event")


def add_milestone(event_id, kind, scheduled_at, window_minutes=0):
    resp = api_client.create_milestone(
        event_id,
        create_milestone_payload(kind=kind, scheduled_at=scheduled_at, window_minutes=window_minutes),
        ED,
    )
    return _d(resp, f"create milestone {kind}")


def open_registration(event_id):
    resp = api_client.open_registration(event_id, ED)
    return _d(resp, "open registration")


def get_event(event_id):
    resp = api_client.get_event(event_id, ED)
    return _d(resp, "get event")


def setup_event_registration_open(**event_overrides):
    """Event with a KICKOFF milestone, moved SETUP -> REGISTRATION_OPEN."""
    event = create_event(**event_overrides)
    add_milestone(event["id"], "KICKOFF", "2026-01-10T17:00:00Z")
    event = open_registration(event["id"])
    return event


# ---------------------------------------------------------------------------
# Persons + screening
# ---------------------------------------------------------------------------

def add_person(event_id, team_id, role_kind, email):
    resp = api_client.create_person(
        event_id,
        create_person_payload(team_id=team_id, role_kind=role_kind, email=email),
        RO,
    )
    return _d(resp, f"create person {role_kind}")


def submit_screening(event_id, person_id):
    resp = api_client.create_screening_record(
        event_id, person_id, create_screening_record_payload(), SO,
    )
    return _d(resp, "submit screening record")


def clear_person(event_id, person_id):
    """Submit + approve a screening package; returns the CLEARED person."""
    record = submit_screening(event_id, person_id)
    person = _d(api_client.get_person(event_id, person_id, SO), "get person")
    resp = api_client.approve_screening(
        event_id, person_id, record["id"], person["version"], SO,
    )
    return _d(resp, "approve screening")


def add_cleared_person(event_id, team_id, role_kind, email):
    """Create a person and drive them to CLEARED. Caller ensures the event is
    in SETUP / REGISTRATION_OPEN / REGISTRATION_LOCKED (PRD §3.2 gate)."""
    person = add_person(event_id, team_id, role_kind, email)
    return clear_person(event_id, person["id"])


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

def register_and_confirm_team(event_id, team_number):
    """Full registration pipeline: create -> mentor+student -> mentor CLEARED
    -> payment -> roster -> confirm. Returns {"team", "mentor", "student"}."""
    team = _d(
        api_client.create_team(
            event_id, create_team_payload(team_number=team_number), RO,
        ),
        "create team",
    )
    mentor = add_person(event_id, team["id"], "MENTOR", f"mentor{team_number}@example.com")
    student = add_person(event_id, team["id"], "STUDENT", f"student{team_number}@example.com")
    mentor = clear_person(event_id, mentor["id"])
    _d(api_client.mark_payment_cleared(event_id, team["id"], RO), "mark payment")
    _d(
        api_client.submit_roster(event_id, team["id"], make_team_lead_headers(mentor["id"])),
        "submit roster",
    )
    team = _d(api_client.confirm_team(event_id, team["id"], RO), "confirm team")
    return {"team": team, "mentor": mentor, "student": student}


def setup_confirmed_teams(num_teams=1, **event_overrides):
    """Event at REGISTRATION_OPEN with `num_teams` fully CONFIRMED teams."""
    event = setup_event_registration_open(**event_overrides)
    teams = [register_and_confirm_team(event["id"], 1000 + i) for i in range(num_teams)]
    return {"event": get_event(event["id"]), "teams": teams}


# ---------------------------------------------------------------------------
# Lifecycle advancement
# ---------------------------------------------------------------------------

def advance_to_build_season(ctx, stop_build_at="2026-02-25T04:00:00Z"):
    """REGISTRATION_OPEN -> REGISTRATION_LOCKED -> BUILD_SEASON."""
    event_id = ctx["event"]["id"]
    ctx["stop_build"] = add_milestone(event_id, "STOP_BUILD", stop_build_at)
    _d(api_client.lock_registration(event_id, ED), "lock registration")
    _d(api_client.open_build_season(event_id, ED), "open build season")
    ctx["event"] = get_event(event_id)
    return ctx


def advance_to_inspection(ctx):
    """BUILD_SEASON -> INSPECTION (STOP_BUILD must be PASSED)."""
    event_id = ctx["event"]["id"]
    _d(api_client.mark_milestone_passed(event_id, ctx["stop_build"]["id"], ED), "pass stop-build")
    _d(api_client.open_inspection(event_id, ED), "open inspection")
    ctx["event"] = get_event(event_id)
    return ctx


def inspect_team_pass(event_id, team_id, inspector_person_id, **inspection_overrides):
    """Create -> submit -> pass a robot inspection for a team."""
    payload = create_robot_inspection_payload(inspector_id=inspector_person_id, **inspection_overrides)
    insp = _d(
        api_client.create_robot_inspection(
            event_id, team_id, payload, make_inspector_headers(inspector_person_id),
        ),
        "create inspection",
    )
    _d(
        api_client.submit_robot_inspection(
            event_id, team_id, insp["id"], make_inspector_headers(inspector_person_id),
        ),
        "submit inspection",
    )
    insp = _d(
        api_client.pass_robot_inspection(
            event_id, team_id, insp["id"], make_lead_inspector_headers(inspector_person_id),
        ),
        "pass inspection",
    )
    return insp


def start_matches(ctx):
    """INSPECTION -> MATCHES_RUNNING with the OCC event-version guard."""
    event_id = ctx["event"]["id"]
    event = get_event(event_id)
    _d(api_client.start_matches(event_id, event["version"], ED), "start matches")
    ctx["event"] = get_event(event_id)
    return ctx


# ---------------------------------------------------------------------------
# Match pipeline
# ---------------------------------------------------------------------------

def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def next_safe_match_time(event_id, field_index, fallback="2026-04-02T10:00:00Z"):
    """Pick a scheduled_at on `field_index` at least 1 hour after every existing
    match on that field, so manual creation never trips the 300-second field
    interval rule against pre-existing matches (PRD §3.5)."""
    matches = _list_all(
        api_client.list_matches, event_id, ED,
        what="list matches for field", params={"field_index": field_index},
    )
    times = [_parse_iso(m["scheduled_at"]) for m in matches if m.get("scheduled_at")]
    if not times:
        return fallback
    return (max(times) + timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_manual_alliance(event_id, seed, captain_team_id):
    resp = api_client.create_alliance(
        event_id, {"seed": seed, "captain_team_id": captain_team_id}, ED,
    )
    return _d(resp, "create alliance")


def create_manual_match(ctx, red_captain_id, blue_captain_id, match_number,
                        field_index=1, scheduled_at=None):
    """Two manual alliances + one SCHEDULED match between them."""
    event_id = ctx["event"]["id"]
    red = create_manual_alliance(event_id, 100 + match_number, red_captain_id)
    blue = create_manual_alliance(event_id, 200 + match_number, blue_captain_id)
    if scheduled_at is None:
        scheduled_at = next_safe_match_time(event_id, field_index)
    resp = api_client.create_match(
        event_id,
        create_match_payload(
            match_number=match_number,
            scheduled_at=scheduled_at,
            field_index=field_index,
            red_alliance_id=red["id"],
            blue_alliance_id=blue["id"],
        ),
        make_scorekeeper_headers(ctx["scorekeeper"]["id"]),
    )
    return _d(resp, "create match")


def add_queue_slots(ctx, match_id, team_ids):
    """Create the six queue slots (RED_1..BLUE_3) for a match."""
    event_id = ctx["event"]["id"]
    slots = []
    for team_id, position in zip(team_ids, SLOT_POSITIONS):
        resp = api_client.create_queue_slot(
            event_id, match_id,
            create_queue_slot_payload(team_id=team_id, position=position),
            QM,
        )
        slots.append(_d(resp, "create queue slot"))
    return slots


def queue_and_take_field(ctx, match_id, slots):
    """SCHEDULED -> QUEUED -> ON_FIELD (all slots AT_FIELD first)."""
    event_id = ctx["event"]["id"]
    _d(api_client.queue_match(event_id, match_id, QM), "queue match")
    for slot in slots:
        _d(api_client.mark_slot_at_field(event_id, match_id, slot["id"], QM), "mark at field")
    resp = api_client.take_field(event_id, match_id, QM)
    return _d(resp, "take field")


def attach_breakdowns_and_score(ctx, match_id, red_breakdown, blue_breakdown):
    """Attach both MatchScoreBreakdown rows, then ON_FIELD -> SCORED."""
    event_id = ctx["event"]["id"]
    sk = make_scorekeeper_headers(ctx["scorekeeper"]["id"])
    red = dict(red_breakdown)
    red["alliance_color"] = "RED"
    blue = dict(blue_breakdown)
    blue["alliance_color"] = "BLUE"
    _d(api_client.create_score_breakdown(event_id, match_id, create_score_breakdown_payload(**red), sk), "red breakdown")
    _d(api_client.create_score_breakdown(event_id, match_id, create_score_breakdown_payload(**blue), sk), "blue breakdown")
    resp = api_client.score_match(event_id, match_id, sk)
    return _d(resp, "score match")


def finalize_match(ctx, match_id):
    """SCORED -> FINALIZED as HeadReferee (a different human than the scorekeeper)."""
    event_id = ctx["event"]["id"]
    resp = api_client.finalize_match(
        event_id, match_id, make_head_referee_headers(ctx["referee"]["id"]),
    )
    return _d(resp, "finalize match")


def complete_open_reset_log(ctx, match_id):
    """Complete the IN_PROGRESS FieldResetLog created at score time, if any."""
    event_id = ctx["event"]["id"]
    logs = _l(api_client.list_field_reset_logs(event_id, match_id, FRC), "list reset logs")
    for log in logs:
        if log.get("status") == "IN_PROGRESS":
            return _d(
                api_client.complete_field_reset_log(event_id, match_id, log["id"], FRC),
                "complete reset log",
            )
    return None


def drive_match_to_scored(ctx, match_id, team_ids, red_breakdown, blue_breakdown):
    """Full pipeline: slots -> queue -> at-field -> take-field -> breakdowns -> score."""
    slots = add_queue_slots(ctx, match_id, team_ids)
    queue_and_take_field(ctx, match_id, slots)
    match = attach_breakdowns_and_score(ctx, match_id, red_breakdown, blue_breakdown)
    return match, slots


def drive_match_to_finalized(ctx, match_id, team_ids, red_breakdown, blue_breakdown):
    match, slots = drive_match_to_scored(ctx, match_id, team_ids, red_breakdown, blue_breakdown)
    complete_open_reset_log(ctx, match_id)
    match = finalize_match(ctx, match_id)
    return match, slots


# ---------------------------------------------------------------------------
# Full event lifecycles
# ---------------------------------------------------------------------------

def setup_matches_running(num_teams=6, field_count=2, with_judge=False,
                          championship_slots=2, team_capacity=40):
    """Event driven all the way to MATCHES_RUNNING.

    Chain: event -> KICKOFF/STOP_BUILD -> REGISTRATION_OPEN -> N confirmed
    teams (each with CLEARED mentor) -> support persons -> lock -> build
    season -> STOP_BUILD passed -> INSPECTION -> all teams PASSED ->
    start-matches (OCC).
    """
    ctx = setup_confirmed_teams(
        num_teams=num_teams, field_count=field_count,
        championship_slots=championship_slots, team_capacity=team_capacity,
    )
    event_id = ctx["event"]["id"]
    # Support persons. Screening record creation is only permitted while the
    # event is in SETUP / REGISTRATION_OPEN / REGISTRATION_LOCKED (PRD §3.2),
    # so anyone who must be CLEARED later is cleared now.
    ctx["inspector"] = add_cleared_person(
        event_id, None, "VOLUNTEER", f"inspector-{event_id[:8]}@example.com",
    )
    ctx["scorekeeper"] = add_person(
        event_id, None, "VOLUNTEER", f"scorekeeper-{event_id[:8]}@example.com",
    )
    ctx["referee"] = add_person(
        event_id, None, "VOLUNTEER", f"referee-{event_id[:8]}@example.com",
    )
    ctx["judge"] = (
        add_cleared_person(event_id, None, "JUDGE", f"judge-{event_id[:8]}@example.com")
        if with_judge else None
    )
    advance_to_build_season(ctx)
    advance_to_inspection(ctx)
    for entry in ctx["teams"]:
        inspect_team_pass(event_id, entry["team"]["id"], ctx["inspector"]["id"])
    start_matches(ctx)
    return ctx


def setup_qualified_team():
    """A MATCHES_RUNNING event whose first team is qualified for championship
    via the CHAIRMANS decide cascade (PRD §3.7): the only team with a
    COMPLETED interview wins the requires-interview branch.

    Returns (ctx, team_entry, award).
    """
    ctx = setup_matches_running(num_teams=6, field_count=2, with_judge=True)
    event_id = ctx["event"]["id"]
    target = ctx["teams"][0]
    award = _d(
        api_client.create_award(
            event_id, {"award_kind": "CHAIRMANS", "requires_interview": True}, JA,
        ),
        "create award",
    )
    _d(api_client.begin_judging(event_id, award["id"], JA), "begin judging")
    slot = _d(
        api_client.create_interview_slot(
            event_id, award["id"],
            create_interview_slot_payload(team_id=target["team"]["id"], judge_id=ctx["judge"]["id"]),
            JA,
        ),
        "create interview slot",
    )
    _d(
        api_client.confirm_interview_slot(
            event_id, award["id"], slot["id"], make_team_lead_headers(target["mentor"]["id"]),
        ),
        "confirm interview slot",
    )
    _d(
        api_client.complete_interview_slot(
            event_id, award["id"], slot["id"], 88, make_judge_headers(ctx["judge"]["id"]),
        ),
        "complete interview slot",
    )
    award = _d(api_client.decide_award(event_id, award["id"], JA), "decide award")
    ctx["event"] = get_event(event_id)
    return ctx, target, award


# ---------------------------------------------------------------------------
# Mega fixtures: alliance selection + closed event
# ---------------------------------------------------------------------------

def _alliance_member_ids(ctx, alliance_id):
    """The three member team ids of an alliance (captain, pick1, pick2)."""
    event_id = ctx["event"]["id"]
    alliance = _d(api_client.get_alliance(event_id, alliance_id, ED), "get alliance")
    return [
        alliance[key] for key in ("captain_team_id", "pick1_team_id", "pick2_team_id")
        if alliance.get(key)
    ]


def _finalize_generated_schedule(ctx):
    """Drive every generated QUALIFICATION match to FINALIZED.

    The six participants are read from the match's red/blue alliance rows so
    the queue slots always name the teams the schedule put on the match.
    Identical breakdowns for every match (RED wins 60-30, no bonus points)
    keep rankings a pure function of the generated pairings.
    """
    event_id = ctx["event"]["id"]
    matches = _list_all(api_client.list_matches, event_id, ED, what="list generated matches")
    red_bd = {"auto_points": 10, "teleop_points": 40, "endgame_points": 10,
              "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"}
    blue_bd = {"auto_points": 5, "teleop_points": 20, "endgame_points": 5,
               "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"}
    for match in matches:
        members = (
            _alliance_member_ids(ctx, match["red_alliance_id"])
            + _alliance_member_ids(ctx, match["blue_alliance_id"])
        )
        assert len(members) == 6, f"Setup failed: match {match['id']} does not have 6 members"
        drive_match_to_finalized(ctx, match["id"], members, red_bd, blue_bd)
    return matches


def list_all_teams(event_id):
    return _list_all(api_client.list_teams, event_id, ED, what="list teams")


def ranked_confirmed_teams(event_id):
    """CONFIRMED teams sorted by the pinned ranking order (PRD §3.6/§3.8):
    ranking_score DESC, ranking_tie_break DESC, team_number ASC, created_at ASC."""
    teams = [t for t in list_all_teams(event_id) if t.get("registration_status") == "CONFIRMED"]
    return sorted(
        teams,
        key=lambda t: (
            -(t.get("ranking_score") or 0.0),
            -(t.get("ranking_tie_break") or 0.0),
            t.get("team_number", 0),
            t.get("created_at", ""),
        ),
    )


def list_selection_alliances(event_id):
    """The seeded selection alliances (PRD §3.6: one Alliance per captain with
    `seed` equal to its 1-based ranking position). Schedule-generated
    qualification alliances carry no seed and are excluded."""
    alliances = _list_all(api_client.list_alliances, event_id, ED, what="list alliances")
    return [a for a in alliances if a.get("seed") is not None]


def setup_alliance_selection(num_teams=24):
    """Event driven to ALLIANCE_SELECTION: 24 confirmed+inspected teams, the
    whole generated qualification slate FINALIZED, then open-alliance-selection
    (seeds 8 captains, opens round 1). Returns ctx with "rounds" and "alliances"."""
    ctx = setup_matches_running(
        num_teams=num_teams, field_count=2, with_judge=True, team_capacity=40,
    )
    event_id = ctx["event"]["id"]
    _finalize_generated_schedule(ctx)
    _d(api_client.open_alliance_selection(event_id, ED), "open alliance selection")
    ctx["event"] = get_event(event_id)
    ctx["rounds"] = _l(api_client.list_selection_rounds(event_id, ED), "list rounds")
    ctx["alliances"] = list_selection_alliances(event_id)
    return ctx


def _mentor_by_team_id(ctx):
    return {entry["team"]["id"]: entry["mentor"] for entry in ctx["teams"]}


def run_full_snake_draft(ctx):
    """Complete both pick rounds. Picks are made by each current captain's
    TeamLead (the captain team's mentor Person) with a fresh OCC version read
    before every pick. Returns the updated ctx."""
    event_id = ctx["event"]["id"]
    mentors = _mentor_by_team_id(ctx)
    captain_ids = {a["captain_team_id"] for a in ctx["alliances"]}
    pick_pool = [
        entry["team"]["id"] for entry in sorted(
            ctx["teams"], key=lambda e: e["team"]["team_number"],
        )
        if entry["team"]["id"] not in captain_ids
    ]
    pick_iter = iter(pick_pool)
    for round_no in (1, 2):
        round_row = _d(
            api_client.get_selection_round(event_id, ctx["rounds"][round_no - 1]["id"], ED),
            "get round",
        )
        for _ in range(len(ctx["alliances"])):
            captain_team_id = round_row["current_captain_team_id"]
            captain_mentor = mentors[captain_team_id]
            _d(
                api_client.submit_pick(
                    event_id, round_row["id"], next(pick_iter),
                    round_row["version"], make_team_lead_headers(captain_mentor["id"]),
                ),
                f"draft pick round {round_no}",
            )
            round_row = _d(
                api_client.get_selection_round(event_id, round_row["id"], ED), "get round",
            )
        assert round_row["status"] == "COMPLETE", f"Setup failed: round {round_no} not COMPLETE"
        if round_no == 1:
            ctx["rounds"] = _l(api_client.list_selection_rounds(event_id, ED), "list rounds")
            ctx["rounds"].sort(key=lambda r: r["round_index"])
    ctx["alliances"] = list_selection_alliances(event_id)
    return ctx


def setup_closed_event_with_chairmans():
    """Full lifecycle to CLOSED with a CHAIRMANS winner decided by interview.

    The CHAIRMANS winner is teams[0] — decided via a completed interview at
    MATCHES_RUNNING (interview branch of winner selection, so the winner is
    independent of ranking). The event has championship_slots=2 so the
    waterfall fills: bucket 1 = CHAIRMANS winner, bucket 4 = best-ranked
    remaining CONFIRMED team.

    Returns (ctx, chairmans_entry, award).
    """
    ctx = setup_matches_running(num_teams=24, field_count=2, with_judge=True, team_capacity=40)
    event_id = ctx["event"]["id"]
    target = ctx["teams"][0]
    award = _d(
        api_client.create_award(
            event_id, {"award_kind": "CHAIRMANS", "requires_interview": True}, JA,
        ),
        "create award",
    )
    _d(api_client.begin_judging(event_id, award["id"], JA), "begin judging")
    slot = _d(
        api_client.create_interview_slot(
            event_id, award["id"],
            create_interview_slot_payload(team_id=target["team"]["id"], judge_id=ctx["judge"]["id"]),
            JA,
        ),
        "create interview slot",
    )
    _d(
        api_client.confirm_interview_slot(
            event_id, award["id"], slot["id"], make_team_lead_headers(target["mentor"]["id"]),
        ),
        "confirm interview slot",
    )
    _d(
        api_client.complete_interview_slot(
            event_id, award["id"], slot["id"], 88, make_judge_headers(ctx["judge"]["id"]),
        ),
        "complete interview slot",
    )
    award = _d(api_client.decide_award(event_id, award["id"], JA), "decide chairmans")
    _finalize_generated_schedule(ctx)
    _d(api_client.open_alliance_selection(event_id, ED), "open alliance selection")
    ctx["event"] = get_event(event_id)
    ctx["rounds"] = _l(api_client.list_selection_rounds(event_id, ED), "list rounds")
    ctx["rounds"].sort(key=lambda r: r["round_index"])
    ctx["alliances"] = list_selection_alliances(event_id)
    run_full_snake_draft(ctx)
    _d(api_client.close_alliance_selection(event_id, ED), "close alliance selection")
    _d(api_client.present_award(event_id, award["id"], ED), "present chairmans")
    _d(api_client.close_event(event_id, ED), "close event")
    ctx["event"] = get_event(event_id)
    return ctx, target, award
