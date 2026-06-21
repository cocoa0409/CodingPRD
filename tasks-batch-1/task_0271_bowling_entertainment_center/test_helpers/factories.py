"""Payload factories — one per entity, input fields only.

Unique fields (lane number, bay name, customer email) are auto-incremented per
process so multiple entities created within a single test never collide. The
test harness restarts the server (empty DB) before every test, so counters do
not need to be reset between tests.
"""
import itertools

_lane_number = itertools.count(1)
_bay_seq = itertools.count(1)
_email_seq = itertools.count(1)
_night_index = itertools.count(1)


def next_lane_number() -> int:
    return next(_lane_number)


def next_bay_name(prefix: str = "Bay") -> str:
    return f"{prefix} {next(_bay_seq)}"


def next_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_email_seq)}@example.com"


def next_night_index() -> int:
    return next(_night_index)


# --- RateCard (PRD §3.1) --------------------------------------------------
def create_rate_card_payload(**overrides) -> dict:
    defaults = {
        "name": "Standard Rate Card",
        "per_game_cents": 800,
        "per_hour_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


# --- Lane (PRD §3.1) ------------------------------------------------------
def create_lane_payload(**overrides) -> dict:
    defaults = {
        "number": next_lane_number(),
    }
    defaults.update(overrides)
    return defaults


# --- Bay (PRD §3.1) -------------------------------------------------------
def create_bay_payload(**overrides) -> dict:
    defaults = {
        "name": next_bay_name(),
    }
    defaults.update(overrides)
    return defaults


# --- Customer (PRD §3.2) --------------------------------------------------
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": next_email("cust"),
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


# --- PartyPackage (PRD §3.1) ----------------------------------------------
def create_party_package_payload(**overrides) -> dict:
    defaults = {
        "name": "Birthday Bash",
        "base_cents": 15000,
        "included_guests": 8,
        "extra_guest_cents": 1200,
        "max_guests": 20,
    }
    defaults.update(overrides)
    return defaults


# --- FoodItem (PRD §3.1) --------------------------------------------------
def create_food_item_payload(**overrides) -> dict:
    defaults = {
        "name": "Nachos",
        "unit_cents": 199,
    }
    defaults.update(overrides)
    return defaults


# --- RentalItem (PRD §3.1) ------------------------------------------------
def create_rental_item_payload(**overrides) -> dict:
    defaults = {
        "kind": "SHOES",
        "label": "Mens 10",
        "unit_price_cents": 300,
        "total_count": 4,
    }
    defaults.update(overrides)
    return defaults


# --- Reservation (PRD §3.3) -----------------------------------------------
def create_reservation_payload(customer_id, rate_card_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "rate_card_id": rate_card_id,
        "resource_kind": "LANE",
        "pricing_mode": "PER_GAME",
        "start_at": "2026-07-01T18:00:00.000Z",
        "end_at": "2026-07-01T19:00:00.000Z",
        "bowler_count": 2,
    }
    defaults.update(overrides)
    return defaults


# --- FoodOrderLine (PRD §3.4) ---------------------------------------------
def create_food_line_payload(reservation_id, food_item_id, quantity=1, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "food_item_id": food_item_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


# --- RentalLine (PRD §3.4) ------------------------------------------------
def create_rental_line_payload(reservation_id, rental_item_id, quantity=1, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "rental_item_id": rental_item_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


# --- League (PRD §3.8) ----------------------------------------------------
def create_league_payload(rate_card_id, **overrides) -> dict:
    defaults = {
        "name": "Thursday Night League",
        "rate_card_id": rate_card_id,
        "season_night_count": 4,
        "lanes_per_night": 1,
        "weekly_fee_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


# --- LeagueNight (PRD §3.8) -----------------------------------------------
def create_league_night_payload(league_id, **overrides) -> dict:
    defaults = {
        "league_id": league_id,
        "night_index": next_night_index(),
        "start_at": "2026-07-02T18:00:00.000Z",
        "end_at": "2026-07-02T20:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults
