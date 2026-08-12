"""Payload factories — one per creatable resource, input fields only (PRD §3)."""


def create_tour_payload(**overrides) -> dict:
    defaults = {
        "tour_name": "Summer Tour",
        "artist_name": "Test Artist",
        "window_start_date": "2026-07-01",
        "window_end_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_market_payload(**overrides) -> dict:
    defaults = {
        "market_code": "NYC",
        "metro_name": "New York",
        "country_code": "US",
        "radius_miles": 60,
        "exclusivity_window_days": 30,
        "territory_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "venue_name": "Test Arena",
        "capacity": 1000,
        "base_rent_cents": 100000,
        "curfew_local_time": "23:00",
        "available_dates": ["2026-08-01"],
    }
    defaults.update(overrides)
    return defaults


def create_routing_leg_payload(from_market_id: str, to_market_id: str, **overrides) -> dict:
    defaults = {
        "from_market_id": from_market_id,
        "to_market_id": to_market_id,
        "travel_date": "2026-08-10",
        "drive_miles": 100,
        "leg_index": 1,
    }
    defaults.update(overrides)
    return defaults


def create_show_payload(market_id: str, venue_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "venue_id": venue_id,
        "show_date": "2026-08-01",
        "on_sale_at": "2026-07-01T00:00:00Z",
        "avg_ticket_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(**overrides) -> dict:
    defaults = {
        "promoter_name": "Test Promoter",
        "guarantee_cents": 1000000,
        "versus_pct": 80,
    }
    defaults.update(overrides)
    return defaults


def counter_hold_payload(expected_show_version: int, **overrides) -> dict:
    defaults = {
        "guarantee_cents": 1100000,
        "versus_pct": 82,
        "expected_show_version": expected_show_version,
    }
    defaults.update(overrides)
    return defaults


def respond_counter_payload(accept_counter: bool = False) -> dict:
    return {"accept_counter": accept_counter}


def confirm_show_payload(expected_tour_version: int) -> dict:
    return {"expected_tour_version": expected_tour_version}


def approve_section_payload(expected_packet_revision: int) -> dict:
    return {"expected_packet_revision": expected_packet_revision}


def update_tickets_payload(tickets_sold: int) -> dict:
    return {"tickets_sold": tickets_sold}


def create_budget_line_payload(**overrides) -> dict:
    defaults = {
        "category": "CREW",
        "description": "crew cost",
        "estimated_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_marketing_spend_payload(**overrides) -> dict:
    defaults = {
        "channel": "RADIO",
        "spend_cents": 1000,
        "flight_start_date": "2026-06-15",
        "flight_end_date": "2026-07-15",
        "attributed_ticket_sales": 3,
    }
    defaults.update(overrides)
    return defaults


def submit_settlement_payload(**overrides) -> dict:
    defaults = {
        "box_office_gross_cents": 500000,
        "taxes_cents": 30000,
        "facility_fees_cents": 20000,
        "promoter_expenses_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_hold_payload(**overrides) -> dict:
    defaults = {
        "hold_kind": "BUDGET_OVERRUN",
        "severity": "STANDARD",
        "reason": "manual flag",
    }
    defaults.update(overrides)
    return defaults
