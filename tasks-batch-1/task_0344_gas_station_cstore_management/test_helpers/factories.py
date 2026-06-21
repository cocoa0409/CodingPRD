"""Payload factories — one per entity, input fields only."""
import itertools

_phone_counter = itertools.count(5550000)


def unique_phone() -> str:
    """A station-unique phone for loyalty enrollment."""
    return str(next(_phone_counter))


def create_station_payload(**overrides) -> dict:
    defaults = {"name": "Test Station", "brand": "Acme"}
    defaults.update(overrides)
    return defaults


def set_clock_payload(station_id, to_iso8601, **overrides) -> dict:
    defaults = {"station_id": station_id, "to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def create_fuel_grade_payload(station_id, code="REGULAR", octane=87, **overrides) -> dict:
    defaults = {"station_id": station_id, "code": code, "octane": octane}
    defaults.update(overrides)
    return defaults


def reprice_payload(new_price_cents, **overrides) -> dict:
    defaults = {"new_price_cents": new_price_cents}
    defaults.update(overrides)
    return defaults


def create_tank_payload(station_id, fuel_grade_id, label="T1",
                        capacity_gallons=10000, reorder_point_gallons=1500,
                        **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "fuel_grade_id": fuel_grade_id,
        "label": label,
        "capacity_gallons": capacity_gallons,
        "reorder_point_gallons": reorder_point_gallons,
    }
    defaults.update(overrides)
    return defaults


def create_pump_payload(station_id, tank_id, number=1, **overrides) -> dict:
    defaults = {"station_id": station_id, "tank_id": tank_id, "number": number}
    defaults.update(overrides)
    return defaults


def create_delivery_payload(station_id, tank_id, vendor_name="DSD",
                           net_gallons=5000, unit_cost_cents=280, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "tank_id": tank_id,
        "vendor_name": vendor_name,
        "net_gallons": net_gallons,
        "unit_cost_cents": unit_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def post_delivery_payload(expected_tank_version, **overrides) -> dict:
    defaults = {"expected_tank_version": expected_tank_version}
    defaults.update(overrides)
    return defaults


def create_shift_payload(station_id, opening_float_cents=20000, **overrides) -> dict:
    defaults = {"station_id": station_id, "opening_float_cents": opening_float_cents}
    defaults.update(overrides)
    return defaults


def drop_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def close_shift_payload(counted_drawer_cents, expected_shift_version, **overrides) -> dict:
    defaults = {
        "counted_drawer_cents": counted_drawer_cents,
        "expected_shift_version": expected_shift_version,
    }
    defaults.update(overrides)
    return defaults


def create_fuel_transaction_payload(station_id, pump_id, shift_id, gallons=12,
                                    tender="CARD", **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "pump_id": pump_id,
        "shift_id": shift_id,
        "gallons": gallons,
        "tender": tender,
    }
    defaults.update(overrides)
    return defaults


def settle_fuel_payload(expected_shift_version, **overrides) -> dict:
    defaults = {"expected_shift_version": expected_shift_version}
    defaults.update(overrides)
    return defaults


def line_item(sku="A", name="Item", category="GROCERY", unit_price_cents=500,
              qty=1, taxable=True, min_age=0) -> dict:
    # PRD §3.7: "Each line item carries a `sku`, a `name`, a `category`, a
    # `unit_price_cents`, a `qty`, a `taxable` flag, and a `min_age`." min_age is
    # a carried field of every line item; a value of 0 marks it not age-restricted.
    item = {
        "sku": sku,
        "name": name,
        "category": category,
        "unit_price_cents": unit_price_cents,
        "qty": qty,
        "taxable": taxable,
        "min_age": min_age,
    }
    return item


def create_store_transaction_payload(station_id, shift_id, line_items=None,
                                     tender="CARD", **overrides) -> dict:
    if line_items is None:
        line_items = [line_item()]
    defaults = {
        "station_id": station_id,
        "shift_id": shift_id,
        "tender": tender,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def create_loyalty_account_payload(station_id, phone=None, name="Member", **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "phone": phone if phone is not None else unique_phone(),
        "name": name,
    }
    defaults.update(overrides)
    return defaults


def redeem_points_payload(points, **overrides) -> dict:
    defaults = {"points": points}
    defaults.update(overrides)
    return defaults


def create_car_wash_code_payload(station_id, package="BASIC", **overrides) -> dict:
    defaults = {"station_id": station_id, "package": package}
    defaults.update(overrides)
    return defaults


def create_margin_report_payload(station_id, window_start, window_end,
                                 cost_basis="WAC", **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "window_start": window_start,
        "window_end": window_end,
        "cost_basis": cost_basis,
    }
    defaults.update(overrides)
    return defaults
