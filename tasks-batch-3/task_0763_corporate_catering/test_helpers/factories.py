"""Payload factories — one per entity, input fields only.

Every factory returns a dict of the entity's PRD-declared input fields with sensible
defaults; pass **overrides to control any value or add/remove a field for a test.
"""

DEFAULTS = {
    "SITE_NAME": "HQ",
    "CLIENT_NAME": "Acme",
    "EMPLOYER_SUBSIDY_PCT": 0.5,
    "DAILY_SUBSIDY_CAP_CENTS": 1000,
    "FOOD_COST_TARGET_PCT": 0.32,
    "CYCLE_NAME": "Spring",
    "CYCLE_LENGTH_WEEKS": 4,
    "VENUE_NAME": "Hall A",
    "VENUE_CAPACITY": 100,
    "EVENT_DATE": "2026-03-10",
    "EVENT_START": "2026-03-10T10:00:00Z",
    "EVENT_END": "2026-03-10T11:00:00Z",
    "SERVICE_DATE": "2026-03-02",
    "WINDOW_START": "2026-03-02T11:00:00Z",
    "WINDOW_END": "2026-03-02T12:00:00Z",
}


def create_client_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "client_name": DEFAULTS["CLIENT_NAME"],
        "employer_subsidy_pct": DEFAULTS["EMPLOYER_SUBSIDY_PCT"],
        "daily_subsidy_cap_cents": DEFAULTS["DAILY_SUBSIDY_CAP_CENTS"],
        "food_cost_target_pct": DEFAULTS["FOOD_COST_TARGET_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(client_site_id, **overrides) -> dict:
    defaults = {
        "client_site_id": client_site_id,
        "badge_id": "B1",
        "full_name": "Dee Iner",
    }
    defaults.update(overrides)
    return defaults


def create_menu_cycle_payload(client_site_id, **overrides) -> dict:
    defaults = {
        "client_site_id": client_site_id,
        "name": DEFAULTS["CYCLE_NAME"],
        "cycle_length_weeks": DEFAULTS["CYCLE_LENGTH_WEEKS"],
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(menu_cycle_id, **overrides) -> dict:
    defaults = {
        "menu_cycle_id": menu_cycle_id,
        "name": "Wrap",
        "category": "ENTREE",
        "price_cents": 350,
        "standard_recipe_cost_cents": 120,
    }
    defaults.update(overrides)
    return defaults


def create_catering_venue_payload(client_site_id, **overrides) -> dict:
    defaults = {
        "client_site_id": client_site_id,
        "name": DEFAULTS["VENUE_NAME"],
        "capacity": DEFAULTS["VENUE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_service_session_payload(client_site_id, menu_cycle_id, **overrides) -> dict:
    defaults = {
        "client_site_id": client_site_id,
        "menu_cycle_id": menu_cycle_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
        "meal_period": "LUNCH",
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "forecast_headcount": 50,
    }
    defaults.update(overrides)
    return defaults


def create_badge_transaction_payload(employee_id, service_session_id, lines, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "service_session_id": service_session_id,
        "lines": lines,
        "payment_method": "BADGE_PAYROLL",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": "FreshCo",
        "category": "DRY_GOODS",
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(vendor_id, client_site_id, lines, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "client_site_id": client_site_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_catering_order_payload(client_site_id, venue_id, lines, **overrides) -> dict:
    defaults = {
        "client_site_id": client_site_id,
        "venue_id": venue_id,
        "event_date": DEFAULTS["EVENT_DATE"],
        "event_start": DEFAULTS["EVENT_START"],
        "event_end": DEFAULTS["EVENT_END"],
        "headcount": 25,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_invoice_payload(vendor_id, purchase_order_id, invoiced_amount_cents, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "purchase_order_id": purchase_order_id,
        "invoiced_amount_cents": invoiced_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_waste_event_payload(client_site_id, inventory_lot_id, qty, reason="SPOILAGE", **overrides) -> dict:
    defaults = {
        "client_site_id": client_site_id,
        "inventory_lot_id": inventory_lot_id,
        "qty": qty,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_satisfaction_survey_payload(client_site_id, rating, **overrides) -> dict:
    defaults = {
        "client_site_id": client_site_id,
        "rating": rating,
    }
    defaults.update(overrides)
    return defaults
