"""Payload factories — one per entity, input fields only.

Only `source: input` fields appear here. System/computed fields are minted by the
server and never sent. Optional fields (those with a PRD-stated default) are omitted
unless explicitly overridden.
"""


def create_season_payload(**overrides) -> dict:
    """Required: name, sport, registration_opens_at, registration_closes_at,
    refund_full_cutoff_at. Optional: refund_partial_pct (defaults to 50)."""
    defaults = {
        "name": "Test Season",
        "sport": "SOCCER",
        "registration_opens_at": "2026-08-01T00:00:00Z",
        "registration_closes_at": "2026-09-01T00:00:00Z",
        "refund_full_cutoff_at": "2026-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_division_payload(**overrides) -> dict:
    """Required: name, skill_tier, min_roster_size, max_roster_size, team_capacity,
    registration_fee_cents. Optional: standings_tiebreaker (defaults HEAD_TO_HEAD)."""
    defaults = {
        "name": "Test Division",
        "skill_tier": "REC",
        "min_roster_size": 1,
        "max_roster_size": 8,
        "team_capacity": 4,
        "registration_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(captain_player_id, expected_division_version, **overrides) -> dict:
    """Required: name, captain_player_id, expected_division_version."""
    defaults = {
        "name": "Test Team",
        "captain_player_id": captain_player_id,
        "expected_division_version": expected_division_version,
    }
    defaults.update(overrides)
    return defaults


def create_player_payload(**overrides) -> dict:
    """Required: full_name, email."""
    defaults = {
        "full_name": "Test Player",
        "email": "player@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    """Required: name, field_count. Optional: turnover_buffer_minutes (defaults 30)."""
    defaults = {
        "name": "Test Venue",
        "field_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_referee_payload(**overrides) -> dict:
    """Required: full_name, certified_sports."""
    defaults = {
        "full_name": "Test Referee",
        "certified_sports": ["SOCCER"],
    }
    defaults.update(overrides)
    return defaults


def create_game_payload(home_team_id, away_team_id, venue_id, **overrides) -> dict:
    """Required: home_team_id, away_team_id, venue_id, field_index, round_index,
    starts_at, ends_at. Optional: stage (defaults REGULAR)."""
    defaults = {
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "venue_id": venue_id,
        "field_index": 1,
        "round_index": 1,
        "starts_at": "2026-09-15T18:00:00Z",
        "ends_at": "2026-09-15T19:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def fee_payload(amount_cents, **overrides) -> dict:
    """pay-fee body. Required: amount_cents."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def refund_adjustment_payload(amount_cents, **overrides) -> dict:
    """refund-adjustment body. Required: amount_cents."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def roster_add_payload(player_id, **overrides) -> dict:
    """roster add body. Required: player_id."""
    defaults = {"player_id": player_id}
    defaults.update(overrides)
    return defaults


def submit_score_payload(home_score, away_score, expected_game_version, **overrides) -> dict:
    """submit-score body. Required: home_score, away_score, expected_game_version."""
    defaults = {
        "home_score": home_score,
        "away_score": away_score,
        "expected_game_version": expected_game_version,
    }
    defaults.update(overrides)
    return defaults


def forfeit_payload(forfeiting_team_id, **overrides) -> dict:
    """forfeit body. Required: forfeiting_team_id."""
    defaults = {"forfeiting_team_id": forfeiting_team_id}
    defaults.update(overrides)
    return defaults


def reschedule_payload(venue_id, field_index, starts_at, ends_at, **overrides) -> dict:
    """reschedule body. Required: venue_id, field_index, starts_at, ends_at."""
    defaults = {
        "venue_id": venue_id,
        "field_index": field_index,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def conduct_report_payload(game_id, player_id, severity, **overrides) -> dict:
    """conduct-report body. Required: game_id, player_id, severity."""
    defaults = {
        "game_id": game_id,
        "player_id": player_id,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def transition_payload(target, **overrides) -> dict:
    """conduct-report transition body. Required: target."""
    defaults = {"target": target}
    defaults.update(overrides)
    return defaults


def season_transition_payload(target, expected_season_version, **overrides) -> dict:
    """season transition body. Required: target, expected_season_version. Optional: force."""
    defaults = {
        "target": target,
        "expected_season_version": expected_season_version,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601) -> dict:
    """clock set body. Required: to_iso8601."""
    return {"to_iso8601": to_iso8601}
