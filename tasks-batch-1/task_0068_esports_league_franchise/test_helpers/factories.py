"""Payload factories — one per entity, input fields only."""

DEFAULT_TERM_START = "2026-01-01T00:00:00.000Z"
DEFAULT_TERM_END = "2026-12-31T00:00:00.000Z"


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Season",
        "salary_cap_cents": 50_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": "Test Team",
        "market_size_weight": 1,
    }
    defaults.update(overrides)
    return defaults


def create_player_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "handle": "test_handle",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(team_id: str, player_id: str, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "player_id": player_id,
        "base_salary_cents": 5_000_000,
        "contract_type": "STANDARD",
        "term_start": DEFAULT_TERM_START,
        "term_end": DEFAULT_TERM_END,
    }
    defaults.update(overrides)
    return defaults


def create_stint_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "starts_at": "2026-03-01T00:00:00.000Z",
        "ends_at": "2026-03-10T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_trade_payload(season_id: str, from_team_id: str, to_team_id: str,
                         contract_ids_out=None, contract_ids_in=None, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "from_team_id": from_team_id,
        "to_team_id": to_team_id,
        "contract_ids_out": contract_ids_out if contract_ids_out is not None else [],
        "contract_ids_in": contract_ids_in if contract_ids_in is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_fine_payload(team_id: str, player_id: str, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "player_id": player_id,
        "amount_cents": 100_000,
        "penalty_points": 1,
    }
    defaults.update(overrides)
    return defaults


def create_sponsorship_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "sponsor_name": "Acme",
        "pool_cents": 10_000_000,
        "league_share_pct": 0.40,
    }
    defaults.update(overrides)
    return defaults
