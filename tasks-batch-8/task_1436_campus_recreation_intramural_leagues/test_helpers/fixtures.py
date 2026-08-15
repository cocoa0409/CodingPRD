"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a fresh, empty database; the logical clock
starts at 2026-08-01T00:00:00Z per PRD §2.4). Helpers use get_success_data()
so a broken precondition surfaces as a clear "Setup failed" error.

Identity threading: Member and Staff are entity-backed roles — every
ownership-gated call uses make_member_headers(entity_id) /
make_staff_headers(entity_id) with the actual entity id, never the shared
TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_member_payload,
    create_membership_payload,
    create_league_payload,
    create_team_payload,
    create_facility_payload,
    create_game_payload,
    create_closure_payload,
    create_score_report_payload,
    create_finalize_payload,
    create_official_payload,
    create_instructor_payload,
    create_injury_report_payload,
    create_equipment_pool_payload,
    create_checkout_payload,
    create_locker_payload,
    create_fitness_class_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_staff_headers

REC_ADMIN = TEST_USERS["rec_admin_headers"]
COORDINATOR = TEST_USERS["league_coordinator_headers"]
FACILITY_MANAGER = TEST_USERS["facility_manager_headers"]


# ---------------------------------------------------------------------------
# Clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; RecAdmin-only test-driving capability."""
    return get_success_data(api_client.set_clock(to_iso8601, REC_ADMIN))


# ---------------------------------------------------------------------------
# Members, waivers, memberships (PRD §3.1)
# ---------------------------------------------------------------------------

def create_member(email: str, full_name: str = "Test Member",
                  affiliation: str = "STUDENT") -> dict:
    """RecAdmin creates a member; returns the Member (version 1)."""
    return get_success_data(api_client.create_member(
        create_member_payload(
            email=email, full_name=full_name, affiliation=affiliation),
        REC_ADMIN,
    ))


def sign_waiver(member: dict) -> dict:
    """Member self-signs the waiver; returns the updated Member."""
    return get_success_data(api_client.sign_waiver(
        member["id"], make_member_headers(member["id"]),
    ))


def purchase_membership(member: dict, term: str = "FALL_2026") -> dict:
    """Member purchases a membership at their current version (OCC, PRD
    §2.5). Returns the new Membership."""
    return get_success_data(api_client.create_membership(
        member["id"],
        create_membership_payload(member["version"], term),
        make_member_headers(member["id"]),
    ))


def create_eligible_member(email: str, affiliation: str = "STUDENT",
                           term: str = "FALL_2026",
                           full_name: str = "Test Member") -> dict:
    """Member + waiver signed + membership purchased: passes the PRD §2.9
    eligibility gates. Returns the fresh Member record."""
    member = create_member(email, full_name=full_name, affiliation=affiliation)
    member = sign_waiver(member)
    purchase_membership(member, term)
    return get_success_data(api_client.get_member(member["id"], REC_ADMIN))


# ---------------------------------------------------------------------------
# Facilities (PRD §3.3, §2.10)
# ---------------------------------------------------------------------------

def create_facility(name: str = "Court 1", kind: str = "COURT",
                    days=(1, 3), open_minute: int = 1020,
                    close_minute: int = 1320) -> dict:
    """RecAdmin creates a facility with weekly recurring windows."""
    windows = [
        {"day_of_week": d, "open_minute": open_minute,
         "close_minute": close_minute}
        for d in days
    ]
    return get_success_data(api_client.create_facility(
        create_facility_payload(
            name=name, kind=kind, operating_windows=windows),
        REC_ADMIN,
    ))


def create_closure(facility: dict, start_at: str, end_at: str,
                   reason: str = "maintenance") -> dict:
    """FacilityManager creates a closure at the facility's current version."""
    return get_success_data(api_client.create_closure(
        facility["id"],
        create_closure_payload(
            facility["version"], start_at=start_at, end_at=end_at,
            reason=reason),
        FACILITY_MANAGER,
    ))


# ---------------------------------------------------------------------------
# League lifecycle and teams (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------

def create_league(**overrides) -> dict:
    """RecAdmin creates a league in DRAFT."""
    return get_success_data(
        api_client.create_league(create_league_payload(**overrides),
                                 REC_ADMIN))


def open_league(league_id: str) -> dict:
    return get_success_data(
        api_client.open_registration(league_id, COORDINATOR))


def close_league(league_id: str) -> dict:
    return get_success_data(
        api_client.close_registration(league_id, COORDINATOR))


def start_season(league_id: str) -> dict:
    return get_success_data(api_client.start_season(league_id, COORDINATOR))


def create_team(league_id: str, name: str, captain_member_id: str,
                skill_rating: int = 5) -> dict:
    return get_success_data(api_client.create_team(
        create_team_payload(
            league_id, captain_member_id, name=name,
            skill_rating=skill_rating),
        COORDINATOR,
    ))


def add_roster_entry(team: dict, member_id: str) -> dict:
    """The team's captain adds a member (captain-gated, PRD §3.2)."""
    return get_success_data(api_client.add_roster_entry(
        team["id"], {"member_id": member_id},
        make_member_headers(team["captain_member_id"]),
    ))


def place_team(team_id: str, division_name: str = "A") -> dict:
    return get_success_data(api_client.place_division(
        team_id, {"division_name": division_name}, COORDINATOR,
    ))


def open_league_context(divisions=None, with_facility=True,
                        facility_days=(1, 3), facility_kind="COURT",
                        facility_name="Court 1", **league_overrides) -> dict:
    """Facility (optional) + league walked DRAFT -> REGISTRATION_OPEN."""
    facility = (
        create_facility(name=facility_name, kind=facility_kind,
                        days=facility_days)
        if with_facility else None
    )
    league = create_league(divisions=divisions, **league_overrides) \
        if divisions is not None else create_league(**league_overrides)
    league = open_league(league["id"])
    return {"league": league, "facility": facility}


def register_teams(league_id: str, count: int, skill_rating: int = 5,
                   email_prefix: str = "cap",
                   add_captain_entry: bool = True):
    """Create `count` teams, each with its own eligible captain member;
    optionally add the captain's roster entry (role CAPTAIN)."""
    teams, captains = [], []
    for i in range(count):
        captain = create_eligible_member(f"{email_prefix}{i}@x.edu",
                                         full_name=f"Cap {i}")
        team = create_team(league_id, f"Team{i}", captain["id"],
                           skill_rating=skill_rating)
        if add_captain_entry:
            add_roster_entry(team, captain["id"])
            team = get_success_data(api_client.get_team(team["id"],
                                                        COORDINATOR))
        teams.append(team)
        captains.append(captain)
    return teams, captains


def scheduling_context(num_teams: int = 2, division_name: str = "A",
                       place: bool = True, **kwargs) -> dict:
    """League walked to SCHEDULING with `num_teams` teams (each with its
    captain rostered). Teams are placed into `division_name` when place=True.
    """
    ctx = open_league_context(**kwargs)
    teams, captains = register_teams(ctx["league"]["id"], num_teams)
    ctx["league"] = close_league(ctx["league"]["id"])
    if place:
        teams = [place_team(t["id"], division_name) for t in teams]
    ctx["teams"] = teams
    ctx["captains"] = captains
    return ctx


def season_context(num_teams: int = 2, division_name: str = "A",
                   **kwargs) -> dict:
    """Full walk to IN_SEASON: all teams PLACED -> ACTIVE, rosters locked."""
    ctx = scheduling_context(num_teams, division_name, place=True, **kwargs)
    ctx["league"] = start_season(ctx["league"]["id"])
    ctx["teams"] = [
        get_success_data(api_client.get_team(t["id"], COORDINATOR))
        for t in ctx["teams"]
    ]
    return ctx


# ---------------------------------------------------------------------------
# Games (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------

def schedule_game(league_id: str, home_team_id: str, away_team_id: str,
                  facility_id: str, start_at: str, end_at: str) -> dict:
    """Coordinator schedules a game at the league's current version (OCC)."""
    league = get_success_data(api_client.get_league(league_id, COORDINATOR))
    return get_success_data(api_client.create_game(
        league_id,
        create_game_payload(home_team_id, away_team_id, facility_id,
                            league["version"], start_at=start_at,
                            end_at=end_at),
        COORDINATOR,
    ))


def season_game_context(num_teams: int = 2, start_at="2026-09-08T18:00:00Z",
                        end_at="2026-09-08T19:30:00Z", **kwargs) -> dict:
    """IN_SEASON league + one SCHEDULED game between teams[0] and teams[1]."""
    ctx = season_context(num_teams, **kwargs)
    ctx["game"] = schedule_game(
        ctx["league"]["id"], ctx["teams"][0]["id"], ctx["teams"][1]["id"],
        ctx["facility"]["id"], start_at, end_at,
    )
    return ctx


def report_scores(game_id: str, home_captain: dict, away_captain: dict,
                  home_score: int = 2, away_score: int = 1,
                  home_rates_opponent: int = 4,
                  away_rates_opponent: int = 5) -> dict:
    """Both captains file matching score reports -> game FINAL (PRD §3.4)."""
    get_success_data(api_client.submit_score_report(
        game_id,
        create_score_report_payload(
            "HOME", home_score, away_score, home_rates_opponent),
        make_member_headers(home_captain["id"]),
    ))
    return get_success_data(api_client.submit_score_report(
        game_id,
        create_score_report_payload(
            "AWAY", home_score, away_score, away_rates_opponent),
        make_member_headers(away_captain["id"]),
    ))


def finalize_game(game_id: str, home_score: int = 2, away_score: int = 1,
                  home_sportsmanship: int = 4, away_sportsmanship: int = 5,
                  actual_duration_minutes: int = 90) -> dict:
    return get_success_data(api_client.finalize_game(
        game_id,
        create_finalize_payload(
            home_score, away_score, home_sportsmanship, away_sportsmanship,
            actual_duration_minutes),
        REC_ADMIN,
    ))


def declare_forfeit(game_id: str, forfeiting_team_id: str) -> dict:
    return get_success_data(api_client.declare_forfeit(
        game_id, {"forfeiting_team_id": forfeiting_team_id}, COORDINATOR,
    ))


# ---------------------------------------------------------------------------
# Staff, officials, payroll (PRD §3.6)
# ---------------------------------------------------------------------------

def create_official(rate: int = 2000, cert: int = 1,
                    name: str = "Ref O") -> dict:
    return get_success_data(api_client.create_staff(
        create_official_payload(
            full_name=name, base_hourly_rate_cents=rate,
            certification_level=cert),
        REC_ADMIN,
    ))


def create_instructor(rate: int = 3000, class_types=("YOGA",),
                      name: str = "Instr I") -> dict:
    return get_success_data(api_client.create_staff(
        create_instructor_payload(
            full_name=name, base_hourly_rate_cents=rate,
            certified_class_types=list(class_types)),
        REC_ADMIN,
    ))


def assign_official(game_id: str, staff_id: str) -> dict:
    return get_success_data(api_client.create_officiating_assignment(
        game_id, {"staff_id": staff_id}, COORDINATOR,
    ))


def respond_assignment(assignment: dict, response: str) -> dict:
    """The assigned official responds (ownership-gated, PRD §3.6)."""
    return get_success_data(api_client.respond_assignment(
        assignment["id"], {"response": response},
        make_staff_headers(assignment["staff_id"]),
    ))


def game_with_accepted_official(cert: int = 2, rate: int = 2000,
                                **kwargs) -> dict:
    """season_game_context + an ACCEPTED officiating assignment on the game."""
    ctx = season_game_context(**kwargs)
    official = create_official(rate=rate, cert=cert)
    assignment = assign_official(ctx["game"]["id"], official["id"])
    assignment = respond_assignment(assignment, "ACCEPT")
    ctx["official"] = official
    ctx["assignment"] = assignment
    return ctx


# ---------------------------------------------------------------------------
# Fitness classes (PRD §3.8)
# ---------------------------------------------------------------------------

def create_class(instructor_id: str, facility_id: str,
                 title: str = "Yoga PM", class_type: str = "YOGA",
                 start_at: str = "2026-09-08T18:00:00Z",
                 end_at: str = "2026-09-08T19:00:00Z",
                 capacity: int = 5) -> dict:
    return get_success_data(api_client.create_fitness_class(
        create_fitness_class_payload(
            instructor_id, facility_id, title=title, class_type=class_type,
            start_at=start_at, end_at=end_at, capacity=capacity),
        REC_ADMIN,
    ))


def register_for_class(class_id: str, member: dict) -> dict:
    """Member self-registers (eligibility-gated, PRD §3.8)."""
    return get_success_data(api_client.create_class_registration(
        class_id, {"member_id": member["id"]},
        make_member_headers(member["id"]),
    ))


def class_context(capacity: int = 5, rate: int = 3000,
                  class_types=("YOGA",), class_type: str = "YOGA",
                  start_at: str = "2026-09-08T18:00:00Z",
                  end_at: str = "2026-09-08T19:00:00Z",
                  facility_days=(1, 3)) -> dict:
    """ROOM facility + instructor + one SCHEDULED class."""
    facility = create_facility(name="Studio", kind="ROOM",
                               days=facility_days)
    instructor = create_instructor(rate=rate, class_types=class_types)
    fclass = create_class(
        instructor["id"], facility["id"], class_type=class_type,
        start_at=start_at, end_at=end_at, capacity=capacity,
    )
    return {"facility": facility, "instructor": instructor, "class": fclass}


def register_members(class_id: str, count: int,
                     email_prefix: str = "m") -> list:
    """Create `count` eligible members and register each for the class."""
    members, registrations = [], []
    for i in range(count):
        member = create_eligible_member(
            f"{email_prefix}{i}@x.edu", full_name=f"Mem {i}")
        members.append(member)
        registrations.append(register_for_class(class_id, member))
    return members, registrations


# ---------------------------------------------------------------------------
# Equipment and lockers (PRD §3.9)
# ---------------------------------------------------------------------------

def create_pool(item_type: str = "BASKETBALL", total_qty: int = 5,
                daily_late_fee_cents: int = 150,
                unit_replacement_cents: int = 900) -> dict:
    return get_success_data(api_client.create_equipment_pool(
        create_equipment_pool_payload(
            item_type=item_type, total_qty=total_qty,
            daily_late_fee_cents=daily_late_fee_cents,
            unit_replacement_cents=unit_replacement_cents),
        REC_ADMIN,
    ))


def create_checkout(pool_id: str, member: dict, quantity: int = 1,
                    due_at: str = "2026-10-01T17:00:00Z") -> dict:
    return get_success_data(api_client.create_equipment_checkout(
        create_checkout_payload(
            pool_id, member["id"], quantity=quantity, due_at=due_at),
        make_member_headers(member["id"]),
    ))


def create_locker(locker_number: int = 101, size: str = "M") -> dict:
    return get_success_data(api_client.create_locker(
        create_locker_payload(locker_number=locker_number, size=size),
        REC_ADMIN,
    ))


# ---------------------------------------------------------------------------
# Injury reports (PRD §3.7)
# ---------------------------------------------------------------------------

def file_injury(member_id: str, severity: str = "SEVERE",
                description: str = "injury", game_id=None) -> dict:
    payload = create_injury_report_payload(
        member_id, severity=severity, description=description)
    if game_id is not None:
        payload["game_id"] = game_id
    return get_success_data(
        api_client.create_injury_report(payload, FACILITY_MANAGER))


# ---------------------------------------------------------------------------
# Playoffs (PRD §3.5)
# ---------------------------------------------------------------------------

def playoff_championship_context(home_sportsmanship: int = 4,
                                 away_sportsmanship: int = 5) -> dict:
    """2-team league: regular game FINAL (home wins 2-1 via a HOME report
    followed by RecAdmin finalize), then start-playoffs. Both teams finish
    eligible (ratings 4.00/5.00, zero forfeits), so the single division
    produces one CHAMPIONSHIP shell born RESCHEDULE_REQUIRED with null slot.
    Returns ctx with 'game' (the FINAL regular game) and 'championship'.
    """
    ctx = season_game_context()
    set_clock("2026-09-08T20:00:00Z")
    get_success_data(api_client.submit_score_report(
        ctx["game"]["id"],
        create_score_report_payload("HOME", 2, 1, 5),
        make_member_headers(ctx["captains"][0]["id"]),
    ))
    ctx["game"] = finalize_game(
        ctx["game"]["id"], 2, 1, home_sportsmanship, away_sportsmanship, 90)
    ctx["league"] = get_success_data(
        api_client.start_playoffs(ctx["league"]["id"], COORDINATOR))
    games, meta = validate_paginated(api_client.list_games(
        COORDINATOR,
        params={"league_id": ctx["league"]["id"],
                "bracket_round": "CHAMPIONSHIP"}))
    assert meta["total_count"] == 1, (
        "2 eligible teams must produce exactly one CHAMPIONSHIP game")
    ctx["championship"] = games[0]
    return ctx
