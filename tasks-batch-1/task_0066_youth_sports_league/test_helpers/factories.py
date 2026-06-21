"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


# Shared default scalars used across the suite.
DEFAULTS = {
    "LEAGUE_NAME": "Spring",
    "SEASON_YEAR": 2026,
    "AGE_CUTOFF_DATE": "2026-08-31",
    "REG_OPEN_ISO": "2026-01-01T00:00:00Z",
    "REG_CLOSE_ISO": "2026-12-31T00:00:00Z",
    "DIVISION_NAME": "Majors",
    "MIN_LEAGUE_AGE": 9,
    "MAX_LEAGUE_AGE": 12,
    "ROSTER_CAP": 12,
    "FIELD_NAME": "Field 1",
    "TURNOVER_BUFFER_MINUTES": 30,
    "REFEREE_USER_ID": "ref-1",
    "REFEREE_NAME": "Ref One",
    "MAX_GAMES_PER_DAY": 10,
}


def create_league_payload(**overrides) -> dict:
    """Required: name, season_year, age_cutoff_date, registration_open_iso,
    registration_close_iso. Optional: draft_snake (defaults true server-side)."""
    payload = {
        "name": DEFAULTS["LEAGUE_NAME"],
        "season_year": DEFAULTS["SEASON_YEAR"],
        "age_cutoff_date": DEFAULTS["AGE_CUTOFF_DATE"],
        "registration_open_iso": DEFAULTS["REG_OPEN_ISO"],
        "registration_close_iso": DEFAULTS["REG_CLOSE_ISO"],
    }
    payload.update(overrides)
    return payload


def create_division_payload(league_id, **overrides) -> dict:
    payload = {
        "league_id": league_id,
        "name": DEFAULTS["DIVISION_NAME"],
        "min_league_age": DEFAULTS["MIN_LEAGUE_AGE"],
        "max_league_age": DEFAULTS["MAX_LEAGUE_AGE"],
        "roster_cap": DEFAULTS["ROSTER_CAP"],
    }
    payload.update(overrides)
    return payload


def create_family_payload(league_id, **overrides) -> dict:
    payload = {
        "league_id": league_id,
        "guardian_email": "fam@x.com",
        "guardian_name": "Fam",
        "volunteer_deposit_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_player_payload(league_id, family_id, division_id, **overrides) -> dict:
    """Required: league_id, family_id, division_id, full_name, birth_date.
    Optional: birth_certificate_ref."""
    payload = {
        "league_id": league_id,
        "family_id": family_id,
        "division_id": division_id,
        "full_name": "Kid",
        "birth_date": "2015-01-15",
    }
    payload.update(overrides)
    return payload


def create_team_payload(league_id, division_id, **overrides) -> dict:
    payload = {
        "league_id": league_id,
        "division_id": division_id,
        "name": "X",
        "coach_user_id": "cx",
        "draft_slot": 1,
    }
    payload.update(overrides)
    return payload


def create_field_payload(league_id, **overrides) -> dict:
    payload = {
        "league_id": league_id,
        "name": DEFAULTS["FIELD_NAME"],
        "turnover_buffer_minutes": DEFAULTS["TURNOVER_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_referee_payload(league_id, **overrides) -> dict:
    payload = {
        "league_id": league_id,
        "user_id": DEFAULTS["REFEREE_USER_ID"],
        "full_name": DEFAULTS["REFEREE_NAME"],
        "max_games_per_day": DEFAULTS["MAX_GAMES_PER_DAY"],
    }
    payload.update(overrides)
    return payload


def create_game_payload(league_id, division_id, home_team_id, away_team_id,
                        field_id, start_iso, end_iso, **overrides) -> dict:
    """Required: league_id, division_id, home_team_id, away_team_id, field_id,
    start_iso, end_iso. Optional: game_type, playoff_round."""
    payload = {
        "league_id": league_id,
        "division_id": division_id,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "field_id": field_id,
        "start_iso": start_iso,
        "end_iso": end_iso,
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(game_id, referee_id, **overrides) -> dict:
    """Required: game_id, referee_id. Optional: role (defaults PLATE)."""
    payload = {
        "game_id": game_id,
        "referee_id": referee_id,
        "role": "PLATE",
    }
    payload.update(overrides)
    return payload


def create_volunteer_commitment_payload(game_id, family_id, role, credit_cents,
                                        **overrides) -> dict:
    """Required: game_id, family_id, role, credit_cents."""
    payload = {
        "game_id": game_id,
        "family_id": family_id,
        "role": role,
        "credit_cents": credit_cents,
    }
    payload.update(overrides)
    return payload
