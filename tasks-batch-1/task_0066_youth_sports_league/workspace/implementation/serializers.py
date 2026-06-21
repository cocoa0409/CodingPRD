"""Convert internal records to API output dicts (field projection)."""

COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(record, fields):
    return {f: record.get(f) for f in fields}


def league_out(r):
    return _pick(r, [
        "id", "name", "season_year", "age_cutoff_date",
        "registration_open_iso", "registration_close_iso", "draft_snake",
        "status", "total_registered_players", "draft_round_index",
        "created_at", "updated_at", "version",
    ])


def division_out(r):
    return _pick(r, [
        "id", "league_id", "name", "min_league_age", "max_league_age",
        "roster_cap", "created_at", "updated_at", "version",
    ])


def family_out(r):
    return _pick(r, [
        "id", "league_id", "guardian_email", "guardian_name",
        "volunteer_deposit_cents", "volunteer_credit_cents",
        "created_at", "updated_at", "version",
    ])


def player_out(r):
    return _pick(r, [
        "id", "league_id", "family_id", "division_id", "full_name",
        "birth_date", "league_age", "birth_certificate_ref",
        "eval_speed", "eval_hitting", "eval_fielding", "eval_score",
        "tier", "team_id", "status", "created_at", "updated_at", "version",
    ])


def team_out(r):
    return _pick(r, [
        "id", "division_id", "league_id", "name", "coach_user_id",
        "draft_slot", "roster_count", "wins", "losses", "run_differential",
        "seed", "created_at", "updated_at", "version",
    ])


def draft_pick_out(r):
    return _pick(r, [
        "id", "league_id", "team_id", "player_id", "round_number",
        "overall_number", "status", "created_at", "updated_at", "version",
    ])


def field_out(r):
    return _pick(r, [
        "id", "league_id", "name", "turnover_buffer_minutes",
        "created_at", "updated_at", "version",
    ])


def referee_out(r):
    return _pick(r, [
        "id", "league_id", "user_id", "full_name", "max_games_per_day",
        "created_at", "updated_at", "version",
    ])


def game_out(r):
    return _pick(r, [
        "id", "league_id", "division_id", "home_team_id", "away_team_id",
        "field_id", "start_iso", "end_iso", "game_type", "playoff_round",
        "home_runs", "away_runs", "winner_team_id", "rainout_count",
        "status", "created_at", "updated_at", "version",
    ])


def assignment_out(r):
    return _pick(r, [
        "id", "game_id", "referee_id", "role", "status",
        "created_at", "updated_at", "version",
    ])


def commitment_out(r):
    return _pick(r, [
        "id", "game_id", "family_id", "role", "credit_cents", "status",
        "created_at", "updated_at", "version",
    ])
