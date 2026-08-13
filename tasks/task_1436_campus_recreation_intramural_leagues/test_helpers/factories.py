"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "MEMBER_EMAIL": "member@x.edu",
    "MEMBER_FULL_NAME": "Test Member",
    "MEMBER_AFFILIATION": "STUDENT",
    "LEAGUE_NAME": "Hoops",
    "LEAGUE_SPORT": "BASKETBALL",
    "DIVISION_NAME": "A",
    "TEAM_SKILL": 5,
    "FACILITY_NAME": "Court 1",
    "FACILITY_KIND": "COURT",
    "OFFICIAL_RATE": 2000,
    "INSTRUCTOR_RATE": 3000,
    "POOL_ITEM": "BASKETBALL",
    "POOL_QTY": 5,
    "POOL_DAILY_LATE": 150,
    "POOL_REPLACEMENT": 900,
}


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["MEMBER_EMAIL"],
        "full_name": DEFAULTS["MEMBER_FULL_NAME"],
        "affiliation": DEFAULTS["MEMBER_AFFILIATION"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(member_version, term="FALL_2026") -> dict:
    return {"term": term, "expected_member_version": member_version}


def create_league_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LEAGUE_NAME"],
        "sport": DEFAULTS["LEAGUE_SPORT"],
        "divisions": [
            {
                "name": DEFAULTS["DIVISION_NAME"],
                "capacity": 4,
                "skill_min": 1,
                "skill_max": 10,
            }
        ],
        "registration_open_at": "2026-08-20T00:00:00Z",
        "registration_close_at": "2026-09-05T00:00:00Z",
        "season_start_at": "2026-09-07T00:00:00Z",
        "season_end_at": "2026-12-04T00:00:00Z",
        "team_capacity": 4,
        "min_teams": 2,
        "roster_min": 1,
        "roster_max": 3,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(league_id, captain_member_id, **overrides) -> dict:
    defaults = {
        "league_id": league_id,
        "name": "Team",
        "captain_member_id": captain_member_id,
        "skill_rating": DEFAULTS["TEAM_SKILL"],
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    """Default weekly window: Tuesday + Thursday 17:00-22:00."""
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "kind": DEFAULTS["FACILITY_KIND"],
        "operating_windows": [
            {"day_of_week": 1, "open_minute": 1020, "close_minute": 1320},
            {"day_of_week": 3, "open_minute": 1020, "close_minute": 1320},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_game_payload(
    home_team_id, away_team_id, facility_id, league_version, **overrides
) -> dict:
    defaults = {
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "facility_id": facility_id,
        "start_at": "2026-09-08T18:00:00Z",
        "end_at": "2026-09-08T19:30:00Z",
        "expected_league_version": league_version,
    }
    defaults.update(overrides)
    return defaults


def create_closure_payload(facility_version, **overrides) -> dict:
    defaults = {
        "start_at": "2026-09-08T17:00:00Z",
        "end_at": "2026-09-08T21:00:00Z",
        "reason": "burst pipe",
        "expected_facility_version": facility_version,
    }
    defaults.update(overrides)
    return defaults


def create_score_report_payload(side, home_score, away_score,
                                opponent_sportsmanship) -> dict:
    return {
        "side": side,
        "home_score": home_score,
        "away_score": away_score,
        "opponent_sportsmanship": opponent_sportsmanship,
    }


def create_finalize_payload(home_score=2, away_score=1, home_sportsmanship=4,
                            away_sportsmanship=5,
                            actual_duration_minutes=90) -> dict:
    return {
        "home_score": home_score,
        "away_score": away_score,
        "home_sportsmanship": home_sportsmanship,
        "away_sportsmanship": away_sportsmanship,
        "actual_duration_minutes": actual_duration_minutes,
    }


def create_official_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ref O",
        "staff_role": "OFFICIAL",
        "base_hourly_rate_cents": DEFAULTS["OFFICIAL_RATE"],
        "certification_level": 1,
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Instr I",
        "staff_role": "INSTRUCTOR",
        "base_hourly_rate_cents": DEFAULTS["INSTRUCTOR_RATE"],
        "certified_class_types": ["YOGA"],
    }
    defaults.update(overrides)
    return defaults


def create_injury_report_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "severity": "MINOR",
        "description": "bruise",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_pool_payload(**overrides) -> dict:
    defaults = {
        "item_type": DEFAULTS["POOL_ITEM"],
        "total_qty": DEFAULTS["POOL_QTY"],
        "daily_late_fee_cents": DEFAULTS["POOL_DAILY_LATE"],
        "unit_replacement_cents": DEFAULTS["POOL_REPLACEMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_checkout_payload(pool_id, member_id, **overrides) -> dict:
    defaults = {
        "equipment_pool_id": pool_id,
        "member_id": member_id,
        "quantity": 1,
        "due_at": "2026-10-01T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_locker_payload(**overrides) -> dict:
    defaults = {"locker_number": 101, "size": "M"}
    defaults.update(overrides)
    return defaults


def create_fitness_class_payload(instructor_staff_id, facility_id,
                                 **overrides) -> dict:
    defaults = {
        "title": "Yoga PM",
        "class_type": "YOGA",
        "instructor_staff_id": instructor_staff_id,
        "facility_id": facility_id,
        "start_at": "2026-09-08T18:00:00Z",
        "end_at": "2026-09-08T19:00:00Z",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults
