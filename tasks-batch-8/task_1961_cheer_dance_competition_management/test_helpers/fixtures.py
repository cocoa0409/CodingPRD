"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Judge/HeadJudge/SafetyJudge calls are entity-backed by
Judge, so per-instance headers are built from the real Judge.id via the
make_* builders; TeamCoach calls thread the same opaque coach id used at
team registration. Setup calls use get_success_data so failures surface as
clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    create_appeal_payload,
    create_athlete_payload,
    create_deduction_payload,
    create_division_payload,
    create_event_payload,
    create_judge_payload,
    create_music_submission_payload,
    create_roster_entry_payload,
    create_score_sheet_payload,
    create_session_payload,
    create_team_payload,
    create_ticket_order_payload,
    mark_performed_payload,
)
from .test_users import (
    TEST_USERS,
    make_head_judge_headers,
    make_judge_headers,
    make_safety_judge_headers,
    make_spectator_headers,
    make_team_coach_headers,
)

DIRECTOR = TEST_USERS["event_director_headers"]
MUSIC = TEST_USERS["music_compliance_headers"]
ELIGIBILITY = TEST_USERS["eligibility_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_event(**overrides):
    """Create an event (born DRAFT, version 1). Returns the event."""
    return get_success_data(api_client.create_event(create_event_payload(**overrides),
                                                    DIRECTOR))


def create_judge(full_name="Judge", certified_levels=(3,)):
    """Create a judge. Returns the judge entity (id doubles as X-User-ID)."""
    return get_success_data(api_client.create_judge(
        create_judge_payload(full_name=full_name,
                             certified_levels=list(certified_levels)),
        DIRECTOR))


def create_panel(count=3, certified_levels=(3,), prefix="J"):
    """Create `count` panel judges plus a head judge and a safety judge.

    Returns (panel_judges, head_judge, safety_judge).
    """
    panel = [create_judge(f"{prefix}{i + 1}", certified_levels) for i in range(count)]
    head = create_judge("JH", certified_levels)
    safety = create_judge("JS", certified_levels)
    return panel, head, safety


def create_division(event_id, judge_ids, **overrides):
    """Create a division. Returns the division."""
    return get_success_data(api_client.create_division(
        create_division_payload(event_id, judge_ids, **overrides), DIRECTOR))


def open_registration(event_id):
    return get_success_data(api_client.open_registration(event_id, DIRECTOR))


def create_athlete(full_name="Ann", date_of_birth="2010-05-01",
                   coach_id="coach-1"):
    return get_success_data(api_client.create_athlete(
        create_athlete_payload(full_name=full_name, date_of_birth=date_of_birth),
        make_team_coach_headers(coach_id)))


def create_team(event_id, division_id, coach_id, **overrides):
    """Register a team. Returns the team."""
    return get_success_data(api_client.create_team(
        create_team_payload(event_id, division_id, coach_id, **overrides),
        make_team_coach_headers(coach_id)))


def add_roster_entry(team_id, athlete_id, coach_id, bib_number=1):
    return get_success_data(api_client.create_roster_entry(
        create_roster_entry_payload(team_id, athlete_id, bib_number=bib_number),
        make_team_coach_headers(coach_id)))


def submit_and_verify_music(team_id, coach_id, license_reference="LIC-1"):
    """Submit routine music and have MusicCompliance verify it."""
    submission = get_success_data(api_client.create_music_submission(
        team_id,
        create_music_submission_payload(license_reference=license_reference),
        make_team_coach_headers(coach_id)))
    get_success_data(api_client.review_music_submission(
        submission["id"], {"decision": "VERIFIED"}, MUSIC))
    return submission


def lock_roster(team_id, coach_id):
    return get_success_data(api_client.lock_roster(
        team_id, make_team_coach_headers(coach_id)))


def check_in_team(team_id, coach_id, athlete_ids):
    return get_success_data(api_client.check_in_team(
        team_id, athlete_ids, make_team_coach_headers(coach_id)))


def generate_schedule(division_id, division_version):
    return get_success_data(api_client.generate_schedule(
        division_id, division_version, DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 2: event + division + team hierarchies
# ---------------------------------------------------------------------------

def setup_event_with_division(panel_count=3, certified_levels=(3,),
                              division_overrides=None, open_reg=True):
    """Event + panel + division. Returns (event, division, panel, head, safety).

    The event is left in DRAFT unless open_reg is True (then REGISTRATION_OPEN).
    """
    event = create_event()
    panel, head, safety = create_panel(count=panel_count,
                                       certified_levels=certified_levels)
    division = create_division(event["id"], [j["id"] for j in panel],
                               **(division_overrides or {}))
    if open_reg:
        open_registration(event["id"])
        event = get_success_data(api_client.get_event(event["id"], DIRECTOR))
    return event, division, panel, head, safety


def setup_registered_team(division, coach_id="coach-1", athlete_name="Ann",
                          athlete_dob="2010-05-01", team_name="T1",
                          organization="Gym1"):
    """Add a REGISTERED team with one ACTIVE rostered athlete.

    Returns (team, athlete, roster_entry).
    """
    athlete = create_athlete(athlete_name, athlete_dob, coach_id)
    team = create_team(division["event_id"], division["id"], coach_id,
                       name=team_name, organization=organization,
                       category=division["category"], level=division["level"])
    entry = add_roster_entry(team["id"], athlete["id"], coach_id)
    return team, athlete, entry


def setup_locked_team_with_verified_music(division, coach_id="coach-1",
                                          athlete_name="Ann",
                                          athlete_dob="2010-05-01",
                                          team_name="T1", organization="Gym1",
                                          license_reference="LIC-1"):
    """REGISTERED team -> roster locked -> music VERIFIED.

    Returns (team, athlete, roster_entry).
    """
    team, athlete, entry = setup_registered_team(
        division, coach_id=coach_id, athlete_name=athlete_name,
        athlete_dob=athlete_dob, team_name=team_name, organization=organization)
    lock_roster(team["id"], coach_id)
    submit_and_verify_music(team["id"], coach_id, license_reference)
    return team, athlete, entry


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts (through scheduling and go-live)
# ---------------------------------------------------------------------------

def setup_live_event_with_checked_in_teams(team_specs, division_overrides=None,
                                           panel_count=3):
    """Full pipeline: event -> division -> teams (locked + music verified) ->
    close registration -> generate schedule -> go live -> check in every team.

    team_specs: list of dicts with keys coach_id, name, organization,
    athlete_name, athlete_dob, license_reference.

    Returns a dict with event, division, panel, head, safety, and `teams`
    (list of dicts: team, athlete, entry, coach_id, performance).
    """
    event, division, panel, head, safety = setup_event_with_division(
        panel_count=panel_count, division_overrides=division_overrides)

    teams = []
    for spec in team_specs:
        team, athlete, entry = setup_locked_team_with_verified_music(
            division,
            coach_id=spec["coach_id"],
            athlete_name=spec.get("athlete_name", "Ann"),
            athlete_dob=spec.get("athlete_dob", "2010-05-01"),
            team_name=spec.get("name", "T1"),
            organization=spec.get("organization", "Gym1"),
            license_reference=spec.get("license_reference", f"LIC-{spec['coach_id']}"))
        teams.append({"team": team, "athlete": athlete, "entry": entry,
                      "coach_id": spec["coach_id"]})

    get_success_data(api_client.close_registration(event["id"], DIRECTOR))
    division = get_success_data(api_client.get_division(division["id"], DIRECTOR))
    generate_schedule(division["id"], division["version"])
    get_success_data(api_client.go_live(event["id"], DIRECTOR))

    for item in teams:
        check_in_team(item["team"]["id"], item["coach_id"], [item["athlete"]["id"]])
        perfs, _ = validate_paginated(api_client.list_team_performances(
            item["team"]["id"], DIRECTOR))
        item["performance"] = perfs[0]

    event = get_success_data(api_client.get_event(event["id"], DIRECTOR))
    division = get_success_data(api_client.get_division(division["id"], DIRECTOR))
    return {"event": event, "division": division, "panel": panel,
            "head": head, "safety": safety, "teams": teams}


def mark_performance_performed(performance_id, safety_judge_id,
                               actual_duration_seconds=150, boundary_violations=0):
    return get_success_data(api_client.mark_performed(
        performance_id,
        mark_performed_payload(actual_duration_seconds, boundary_violations),
        make_safety_judge_headers(safety_judge_id)))


def submit_sheet_for_judge(performance_id, judge_id, building_difficulty=8.0,
                           building_execution=None, tumbling_difficulty=None,
                           overall_impression=None):
    """Create a DRAFT sheet as the judge and submit it. Returns the sheet.

    A single positional score applies flat to all four categories (matching
    submit_full_panel's documented scalar semantics); passing all four
    category values positions each explicitly.
    """
    if building_execution is None:
        building_execution = building_difficulty
    if tumbling_difficulty is None:
        tumbling_difficulty = building_difficulty
    if overall_impression is None:
        overall_impression = building_difficulty
    sheet = get_success_data(api_client.create_score_sheet(
        performance_id,
        create_score_sheet_payload(building_difficulty, building_execution,
                                   tumbling_difficulty, overall_impression),
        make_judge_headers(judge_id)))
    return get_success_data(api_client.submit_score_sheet(
        sheet["id"], make_judge_headers(judge_id)))


def submit_full_panel(performance_id, panel, score):
    """Submit the same four-category score from every panel judge.

    `score` is either a single flat value applied to all four categories or a
    (bd, be, td, oi) tuple. Returns the list of SUBMITTED sheets.
    """
    if isinstance(score, (int, float)):
        bd = be = td = oi = score
    else:
        bd, be, td, oi = score
    return [submit_sheet_for_judge(performance_id, j["id"], bd, be, td, oi)
            for j in panel]


def make_performance_official(performance_id, head_judge_id):
    return get_success_data(api_client.confirm_official(
        performance_id, make_head_judge_headers(head_judge_id)))


def setup_official_performance(sheet_score=8.0, actual_duration_seconds=150,
                               boundary_violations=0, division_overrides=None,
                               panel_count=3):
    """Single-team division walked to an OFFICIAL performance.

    Returns the context dict from setup_live_event_with_checked_in_teams with
    the team's performance already OFFICIAL (flat sheet_score from every judge,
    unless sheet_score is a (bd, be, td, oi) tuple).
    """
    ctx = setup_live_event_with_checked_in_teams(
        [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}],
        division_overrides=division_overrides, panel_count=panel_count)
    perf = ctx["teams"][0]["performance"]
    mark_performance_performed(perf["id"], ctx["safety"]["id"],
                               actual_duration_seconds, boundary_violations)
    submit_full_panel(perf["id"], ctx["panel"], sheet_score)
    perf = make_performance_official(perf["id"], ctx["head"]["id"])
    ctx["teams"][0]["performance"] = perf
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: deduction / appeal chains
# ---------------------------------------------------------------------------

def apply_safety_deduction(performance_id, safety_judge_id, quantity=1,
                           skill_tier=4):
    return get_success_data(api_client.create_deduction(
        performance_id, create_deduction_payload(quantity, skill_tier),
        make_safety_judge_headers(safety_judge_id)))


def appeal_deduction(deduction_id, coach_id, note="dispute", video_ref="vid-1"):
    return get_success_data(api_client.create_appeal(
        deduction_id, create_appeal_payload(note, video_ref),
        make_team_coach_headers(coach_id)))


def resolve_appeal(appeal_id, head_judge_id, decision):
    return get_success_data(api_client.resolve_appeal(
        appeal_id, decision, make_head_judge_headers(head_judge_id)))


# ---------------------------------------------------------------------------
# Tier 5: ticketing helpers
# ---------------------------------------------------------------------------

def setup_session(capacity=100, open_reg=True):
    """Event (+open registration by default) with one spectator session.

    Returns (event, session).
    """
    event = create_event()
    if open_reg:
        open_registration(event["id"])
    session = get_success_data(api_client.create_session(
        create_session_payload(event["id"], capacity=capacity), DIRECTOR))
    return event, session


def create_ticket_order(session_id, spectator_id, quantity=2):
    return get_success_data(api_client.create_ticket_order(
        create_ticket_order_payload(session_id, quantity),
        make_spectator_headers(spectator_id)))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def reset_clock():
    """Return the logical clock to its startup default."""
    return set_clock(CLOCK_DEFAULT)
