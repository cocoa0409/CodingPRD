"""Derived entity views and shared domain guards (rentability, overlap checks)."""
from datetime import timedelta

import db
from db import store
from services import calc


def next_inspection_due(last_annual_inspection_date):
    return (db.parse_date(last_annual_inspection_date) + timedelta(days=365)).isoformat()


def unit_rentable(unit):
    """Rentable iff AVAILABLE and the logical-clock date is on/before the due date."""
    due = db.parse_date(next_inspection_due(unit["last_annual_inspection_date"]))
    return unit["status"] == "AVAILABLE" and db.logical_date() <= due


def view_customer(c):
    out = {k: v for k, v in c.items() if not k.startswith("_")}
    out["outstanding_balance_cents"] = calc.customer_balance_cents(c["id"])
    return out


def view_class(cls):
    return {k: v for k, v in cls.items() if not k.startswith("_")}


def view_unit(u):
    out = {k: v for k, v in u.items() if not k.startswith("_")}
    out["next_inspection_due_date"] = next_inspection_due(u["last_annual_inspection_date"])
    return out


def view_contract(c):
    out = {k: v for k, v in c.items() if not k.startswith("_")}
    r = calc.rental_subtotal_cents(c["id"])
    l = calc.logistics_subtotal_cents(c["id"])
    d = calc.damage_subtotal_cents(c["id"])
    out["rental_subtotal_cents"] = r
    out["logistics_subtotal_cents"] = l
    out["damage_subtotal_cents"] = d
    out["invoice_total_cents"] = r + l + d
    return out


def invoice_view(c):
    return {
        "contract_id": c["id"],
        "status": c["status"],
        "rental_subtotal_cents": calc.rental_subtotal_cents(c["id"]),
        "logistics_subtotal_cents": calc.logistics_subtotal_cents(c["id"]),
        "damage_subtotal_cents": calc.damage_subtotal_cents(c["id"]),
        "invoice_total_cents": calc.invoice_total_cents(c["id"]),
    }


def view_line(line):
    out = {k: v for k, v in line.items() if not k.startswith("_")}
    out["provisional_charge_cents"] = calc.provisional_charge_cents(line)
    return out


def view_trip(t):
    return {k: v for k, v in t.items() if not k.startswith("_")}


def view_inspection(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def view_claim(c):
    return {k: v for k, v in c.items() if not k.startswith("_")}


def view_training(t):
    """Training records carry id and created_at only — no updated_at/version."""
    valid_until = db.parse_datetime(t["trained_at"]) + timedelta(days=365)
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "customer_id": t["customer_id"],
        "class_id": t["class_id"],
        "trainee_name": t["trainee_name"],
        "trained_at": t["trained_at"],
        "trainer_id": t["trainer_id"],
        "valid_until": db.iso_logical(valid_until),
        "is_valid": db.LOGICAL_CLOCK < valid_until,
    }


def line_window(line):
    """Half-open calendar window [requested_start_date, requested_end_date + 1 day)."""
    start = db.parse_date(line["requested_start_date"])
    end = db.parse_date(line["requested_end_date"]) + timedelta(days=1)
    return start, end


def unit_window_conflict(unit_id, start, end):
    """True when another RESERVED/OUT_ON_RENT/OFF_RENT line on the unit overlaps.

    Half-open intersection; adjacency (existing end == new start) is not overlap.
    """
    for line in store.lines.values():
        if line["unit_id"] != unit_id:
            continue
        if line["status"] not in ("RESERVED", "OUT_ON_RENT", "OFF_RENT"):
            continue
        s, e = line_window(line)
        if s < end and start < e:
            return True
    return False


def route_window_conflict(driver_id, start_dt, end_dt):
    """True when a SCHEDULED/EN_ROUTE trip of the same driver overlaps with its
    buffered window [planned_start - 45min, planned_end + 45min)."""
    buf = timedelta(minutes=45)
    for trip in store.trips.values():
        if trip["driver_id"] != driver_id:
            continue
        if trip["status"] not in ("SCHEDULED", "EN_ROUTE"):
            continue
        s = db.parse_datetime(trip["planned_start_utc"]) - buf
        e = db.parse_datetime(trip["planned_end_utc"]) + buf
        if s < end_dt and start_dt < e:
            return True
    return False


def has_valid_training(customer_id, class_id):
    """A qualifying record matches customer and class and has is_valid true now."""
    for t in store.training.values():
        if t["customer_id"] != customer_id or t["class_id"] != class_id:
            continue
        valid_until = db.parse_datetime(t["trained_at"]) + timedelta(days=365)
        if db.LOGICAL_CLOCK < valid_until:
            return True
    return False
