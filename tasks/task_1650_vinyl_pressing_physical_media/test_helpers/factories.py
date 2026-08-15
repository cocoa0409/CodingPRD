"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Label",
    "CUSTOMER_EMAIL": "label@example.com",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "CATALOG_NUMBER": "CAT-001",
    "TITLE": "Test Release",
    "FORMAT": "LP",
    "WEIGHT_GRAM": 180,
    "RELEASE_DATE": "2026-12-01",
    "QUANTITY_ORDERED": 1000,
    "SIDES": 2,
    "PLATING_ROUTE": "TWO_STEP",
    "LINE_CODE": "L1",
    "TONNAGE_CLASS": "STANDARD",
    "HOURS_PER_DAY": 16,
    "DAILY_UNIT_CAPACITY": 5000,
    "BATH_CODE": "B1",
    "RINSE_GAP_MINUTES": 2,
    "TP_QUANTITY": 5,
    "PRINTER_NAME": "PrintCo",
    "PRINT_DUE_DATE": "2026-09-01",
    "SHIP_DATE": "2026-08-15",
    "SLOT_DATE": "2026-08-10",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "contact_email": DEFAULTS["CUSTOMER_EMAIL"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "catalog_number": DEFAULTS["CATALOG_NUMBER"],
        "title": DEFAULTS["TITLE"],
        "format": DEFAULTS["FORMAT"],
        "weight_gram": DEFAULTS["WEIGHT_GRAM"],
        "release_date": DEFAULTS["RELEASE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_press_order_payload(release_id: str, **overrides) -> dict:
    quantity = overrides.pop("quantity_ordered", DEFAULTS["QUANTITY_ORDERED"])
    defaults = {
        "release_id": release_id,
        "quantity_ordered": quantity,
        "sides": DEFAULTS["SIDES"],
        "plating_route": DEFAULTS["PLATING_ROUTE"],
        "variants": [{"color_config": "BLACK", "quantity": quantity}],
    }
    defaults.update(overrides)
    return defaults


def create_press_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": DEFAULTS["LINE_CODE"],
        "tonnage_class": DEFAULTS["TONNAGE_CLASS"],
        "hours_per_day": DEFAULTS["HOURS_PER_DAY"],
        "daily_unit_capacity": DEFAULTS["DAILY_UNIT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_plating_bath_payload(**overrides) -> dict:
    defaults = {
        "bath_code": DEFAULTS["BATH_CODE"],
        "rinse_gap_minutes": DEFAULTS["RINSE_GAP_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_slot_spec(press_line_id: str, date: str = None, start_hour: int = 0,
                     end_hour: int = 8, planned_units: int = None, **overrides) -> dict:
    spec = {
        "press_line_id": press_line_id,
        "date": date or DEFAULTS["SLOT_DATE"],
        "start_hour": start_hour,
        "end_hour": end_hour,
        "planned_units": planned_units if planned_units is not None else DEFAULTS["QUANTITY_ORDERED"],
    }
    spec.update(overrides)
    return spec


def create_maintenance_payload(**overrides) -> dict:
    defaults = {
        "date": DEFAULTS["SLOT_DATE"],
        "start_hour": 8,
        "end_hour": 10,
        "reason": "scheduled maintenance",
    }
    defaults.update(overrides)
    return defaults


def create_test_pressing_payload(**overrides) -> dict:
    defaults = {"quantity": DEFAULTS["TP_QUANTITY"]}
    defaults.update(overrides)
    return defaults


def create_print_job_payload(quantity: int = None, **overrides) -> dict:
    defaults = {
        "component": "JACKET",
        "quantity": quantity if quantity is not None else DEFAULTS["QUANTITY_ORDERED"],
        "printer_name": DEFAULTS["PRINTER_NAME"],
        "due_date": DEFAULTS["PRINT_DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(release_id: str, **overrides) -> dict:
    defaults = {"release_id": release_id, "zone": "A"}
    defaults.update(overrides)
    return defaults


def create_stock_event_payload(event: str, quantity: int, **overrides) -> dict:
    defaults = {"event": event, "quantity": quantity, "event_date": "2026-08-01"}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(release_id: str, distributor_customer_id: str, **overrides) -> dict:
    defaults = {
        "release_id": release_id,
        "distributor_customer_id": distributor_customer_id,
        "quantity": 100,
        "requested_ship_date": DEFAULTS["SHIP_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_qc_report_payload(units_pressed: int, units_rejected: int, **overrides) -> dict:
    defaults = {"units_pressed": units_pressed, "units_rejected": units_rejected}
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_credit_memo_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": "goodwill"}
    defaults.update(overrides)
    return defaults
