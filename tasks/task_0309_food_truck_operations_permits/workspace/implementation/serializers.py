"""Serialize internal records to API output shapes (PRD §1.1 fields).

Computed/derived fields are recomputed on read so every read reflects current
state (PRD §2.6: derived state is always reconciled to underlying facts).
"""

from db import db
import services


def _common(rec, include_version=True):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }
    if include_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def commissary(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "state_code": rec["state_code"],
        "status": rec["status"],
        "docked_truck_count": services.docked_truck_count(rec["id"]),
    })
    return out


def truck(rec):
    out = _common(rec)
    out.update({
        "commissary_id": rec["commissary_id"],
        "name": rec["name"],
        "home_state_code": rec["home_state_code"],
        "operability": rec["operability"],
        "propane_psi": rec["propane_psi"],
        "generator_runtime_hours": rec["generator_runtime_hours"],
        "reservation_fee_balance_cents": services.reservation_fee_balance(rec["id"]),
        "gross_sales_cents": rec["gross_sales_cents"],
    })
    return out


def permit(rec):
    out = _common(rec)
    out.update({
        "truck_id": rec["truck_id"],
        "permit_number": rec["permit_number"],
        "state_code": rec["state_code"],
        "status": rec["status"],
        "issued_at": rec["issued_at"],
        "expires_at": rec["expires_at"],
    })
    return out


def spot(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "state_code": rec["state_code"],
        "concurrent_capacity": rec["concurrent_capacity"],
        "buffer_minutes": rec["buffer_minutes"],
        "reservation_fee_cents": rec["reservation_fee_cents"],
    })
    return out


def event(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "starts_at": rec["starts_at"],
        "ends_at": rec["ends_at"],
        "status": rec["status"],
    })
    return out


def booking(rec):
    out = _common(rec)
    out.update({
        "truck_id": rec["truck_id"],
        "spot_id": rec["spot_id"],
        "event_id": rec["event_id"],
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "status": rec["status"],
        "reservation_fee_cents": rec["reservation_fee_cents"],
        "fee_refunded_cents": rec["fee_refunded_cents"],
    })
    return out


def menu_item(rec):
    out = _common(rec)
    out.update({
        "truck_id": rec["truck_id"],
        "sku": rec["sku"],
        "name": rec["name"],
        "unit_price_cents": rec["unit_price_cents"],
        "par_units": rec["par_units"],
        "prepared_units": services.prepared_units(rec["id"]),
        "status": rec["status"],
    })
    return out


def prep_batch(rec):
    out = _common(rec)
    out.update({
        "truck_id": rec["truck_id"],
        "menu_item_id": rec["menu_item_id"],
        "units_made": rec["units_made"],
        "prepped_at": rec["prepped_at"],
        "status": rec["status"],
    })
    return out


def staff_shift(rec):
    out = _common(rec)
    out.update({
        "truck_id": rec["truck_id"],
        "staff_name": rec["staff_name"],
        "role": rec["role"],
        "shift_start": rec["shift_start"],
        "shift_end": rec["shift_end"],
        "status": rec["status"],
    })
    return out


def utility_log(rec):
    # Append-only: id + created_at only (no updated_at / version).
    out = _common(rec, include_version=False)
    out.update({
        "truck_id": rec["truck_id"],
        "utility": rec["utility"],
        "propane_psi_after": rec["propane_psi_after"],
        "generator_delta_hours": rec["generator_delta_hours"],
        "logged_at": rec["logged_at"],
    })
    return out


def order(rec):
    out = _common(rec)
    out.update({
        "truck_id": rec["truck_id"],
        "booking_id": rec["booking_id"],
        "lifecycle_status": rec["lifecycle_status"],
        "payment_status": rec["payment_status"],
        "tip_cents": rec["tip_cents"],
        "discount_code": rec["discount_code"],
        "live_total_cents": rec["live_total_cents"],
        "settled_total_cents": rec["settled_total_cents"],
    })
    return out


def order_line(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "menu_item_id": rec["menu_item_id"],
        "quantity": rec["quantity"],
        "unit_price_cents": rec["unit_price_cents"],
        "line_subtotal_cents": rec["line_subtotal_cents"],
    })
    return out
