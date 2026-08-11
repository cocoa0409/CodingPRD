"""Payload factories — one per create/update endpoint, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_shipper_payload(**overrides) -> dict:
    defaults = {
        "name": f"Shipper {_seq()}",
        "paca_license": f"PACA-{_seq():04d}",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": f"Buyer {_seq()}",
        "credit_limit_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def update_customer_payload(expected_customer_version, **overrides) -> dict:
    payload = {"expected_customer_version": expected_customer_version}
    payload.update(overrides)
    return payload


def create_commodity_payload(**overrides) -> dict:
    defaults = {
        "code": f"C{_seq():04d}",
        "name": f"Commodity {_seq()}",
        "ethylene_class": "PRODUCER",
        "temp_min_f": 45,
        "temp_max_f": 55,
        "max_violation_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_daily_price_payload(commodity_id, **overrides) -> dict:
    defaults = {
        "commodity_id": commodity_id,
        "market_date": "2026-05-01",
        "low_price": 8.00,
        "high_price": 12.00,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_lot_payload(shipper_id, commodity_id, **overrides) -> dict:
    defaults = {
        "shipper_id": shipper_id,
        "commodity_id": commodity_id,
        "market_date": "2026-05-01",
        "quantity_units": 100,
        "shipper_unit_price": 10.00,
        "declared_grade": "US1",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(purchase_lot_id, **overrides) -> dict:
    defaults = {
        "purchase_lot_id": purchase_lot_id,
        "inspected_grade": "US1",
        "defect_pct": 0,
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_temperature_reading_payload(purchase_lot_id, **overrides) -> dict:
    defaults = {
        "purchase_lot_id": purchase_lot_id,
        "recorded_at": "2026-05-01T09:00:00Z",
        "temp_f": 50,
        "duration_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_ripening_room_payload(**overrides) -> dict:
    defaults = {
        "name": f"R{_seq()}",
        "capacity_pallets": 50,
        "ethylene_capable": True,
    }
    defaults.update(overrides)
    return defaults


def create_ripening_booking_payload(room_id, purchase_lot_id, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "purchase_lot_id": purchase_lot_id,
        "pallet_count": 4,
        "start_time": "2026-05-02T10:00:00Z",
        "end_time": "2026-05-02T12:00:00Z",
        "ethylene_enabled": False,
        "target_stage": "STAGE_4",
    }
    defaults.update(overrides)
    return defaults


def create_shrink_record_payload(purchase_lot_id, **overrides) -> dict:
    defaults = {
        "purchase_lot_id": purchase_lot_id,
        "quantity": 10,
        "reason": "DUMP",
    }
    defaults.update(overrides)
    return defaults


def order_line(lot_id, quantity, unit_price) -> dict:
    return {"lot_id": lot_id, "quantity": quantity, "unit_price": unit_price}


def create_sales_order_payload(customer_id, lines, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "delivery_date": "2026-05-02",
        "window_start": "08:00",
        "window_end": "10:00",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(sales_order_id, **overrides) -> dict:
    defaults = {"sales_order_id": sales_order_id}
    defaults.update(overrides)
    return defaults


def create_payment_payload(invoice_id, amount_cents, **overrides) -> dict:
    defaults = {"invoice_id": invoice_id, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_labor_ticket_payload(purchase_lot_id, **overrides) -> dict:
    defaults = {
        "purchase_lot_id": purchase_lot_id,
        "ticket_type": "HOURLY",
        "work_date": "2026-05-01",
        "hours": 8,
        "hourly_rate": 20.00,
    }
    defaults.update(overrides)
    return defaults
