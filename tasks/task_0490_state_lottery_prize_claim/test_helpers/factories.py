"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "GAME_NAME": "Test Game",
    "RETAILER_NAME": "Test Retailer",
    "PLAYER_NAME": "Test Player",
    "PRICE_CENTS": 200,
    "PRIZE_POOL_CENTS": 500000,
}


def create_game_payload(**overrides) -> dict:
    """DrawingGame input fields. game_type defaults JACKPOT so annuity tests work;
    optional tax/payout params omitted so PRD defaults apply unless overridden."""
    defaults = {
        "name": DEFAULTS["GAME_NAME"],
        "game_type": "JACKPOT",
        "claim_window_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_retailer_payload(**overrides) -> dict:
    """Retailer input fields. tax_id is required and unique — caller must supply
    a distinct value (no default, since each test runs against a fresh DB but a
    single test may create several retailers)."""
    defaults = {
        "business_name": DEFAULTS["RETAILER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_terminal_payload(retailer_id, serial_number, **overrides) -> dict:
    defaults = {
        "retailer_id": retailer_id,
        "serial_number": serial_number,
    }
    defaults.update(overrides)
    return defaults


def create_player_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PLAYER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(game_id, terminal_id, serial, **overrides) -> dict:
    """Ticket input fields. Defaults to a non-winner (declared_tier 0,
    gross_prize_cents 0); winner tests override declared_tier and gross_prize_cents."""
    defaults = {
        "game_id": game_id,
        "terminal_id": terminal_id,
        "serial": serial,
        "price_cents": DEFAULTS["PRICE_CENTS"],
        "draw_date": "2026-01-10T00:00:00Z",
        "declared_tier": 0,
        "gross_prize_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_prize_claim_payload(ticket_id, player_id, payout_option="CASH", **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "player_id": player_id,
        "payout_option": payout_option,
    }
    defaults.update(overrides)
    return defaults


def create_drawing_payload(game_id, **overrides) -> dict:
    defaults = {
        "game_id": game_id,
        "entry_deadline": "2026-02-01T00:00:00Z",
        "prize_pool_cents": DEFAULTS["PRIZE_POOL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(drawing_id, ticket_id, **overrides) -> dict:
    defaults = {
        "drawing_id": drawing_id,
        "ticket_id": ticket_id,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(retailer_id, period_start, period_end,
                              expected_retailer_version, **overrides) -> dict:
    defaults = {
        "retailer_id": retailer_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_retailer_version": expected_retailer_version,
    }
    defaults.update(overrides)
    return defaults


def self_exclude_payload(exclusion_days, **overrides) -> dict:
    defaults = {"exclusion_days": exclusion_days}
    defaults.update(overrides)
    return defaults
