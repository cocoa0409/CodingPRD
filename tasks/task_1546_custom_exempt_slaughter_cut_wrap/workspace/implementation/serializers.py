"""Entity -> public-dict serializers.

Computed fields are derived at serialization time:
- Customer.status / CapacityDay.booked_head / CapacityDay.status are always
  derived live.
- StorageRecord.days_stored / accrued_fee_cents reflect the logical clock
  (as-of-now while STORED; frozen at pickup / abandonment).
- Invoice.storage_cents / total_cents / amount_due_cents are the final-variant
  view: storage is the live accrual while the share's record is STORED,
  otherwise the value persisted at the last pinned recomputation (payment,
  pickup, waive-storage, abandonment).

Datetime fields are stored internally as naive-UTC datetimes under a
`<field>_dt` key; the public payload exposes the logical-clock string.
Weights/fractions are stored as Decimal; the public payload exposes floats.
"""

import db
from calc import (customer_status, fmt_ts, get_now, storage_accrued_cents,
                  storage_days_stored)


def _f(d):
    """Decimal -> float (None passthrough)."""
    return None if d is None else float(d)


def _ts(e, key):
    dt = e.get(key + "_dt")
    return None if dt is None else fmt_ts(dt)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def record_of_share(share_id):
    for r in db.storage_records.values():
        if r["share_id"] == share_id:
            return r
    return None


def invoice_of_share(share_id):
    for inv in db.invoices.values():
        if inv["share_id"] == share_id:
            return inv
    return None


def label_of_share(share_id):
    for lbl in db.labels.values():
        if lbl["share_id"] == share_id:
            return lbl
    return None


def sheet_of_share(share_id):
    for cs in db.cut_sheets.values():
        if cs["share_id"] == share_id:
            return cs
    return None


def day_booked_head(day_id):
    """Sum of head_count over appointments on the day in PENDING_DEPOSIT or
    CONFIRMED (SCAFFOLD entities.CapacityDay.booked_head)."""
    return sum(a["head_count"] for a in db.appointments.values()
               if a["capacity_day_id"] == day_id
               and a["status"] in ("PENDING_DEPOSIT", "CONFIRMED"))


# ---------------------------------------------------------------------------
# Storage accrual views (storage_fee)
# ---------------------------------------------------------------------------

def record_days_stored(rec, now=None):
    if rec["status"] == "STORED":
        return storage_days_stored(rec["ready_at_dt"], now or get_now())
    if rec["status"] == "PICKED_UP":
        return storage_days_stored(rec["ready_at_dt"], rec["picked_up_at_dt"])
    return rec["days_stored"]  # ABANDONED: frozen at the sweep instant


def record_accrued_cents(rec, now=None):
    if rec["status"] == "ABANDONED":
        return rec["accrued_fee_cents"]  # frozen
    return storage_accrued_cents(record_days_stored(rec, now))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def customer_out(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "phone": c["phone"],
        "email": c["email"],
        "no_show_strikes": c["no_show_strikes"],
        "status": customer_status(c["no_show_strikes"]),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def capacity_day_out(d):
    booked = day_booked_head(d["id"])
    return {
        "id": d["id"],
        "date": d["date"],
        "capacity_head": d["capacity_head"],
        "booked_head": booked,
        "status": "FULL" if booked == d["capacity_head"] else "OPEN",
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def appointment_out(a):
    return {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "capacity_day_id": a["capacity_day_id"],
        "species": a["species"],
        "head_count": a["head_count"],
        "appointment_date": a["appointment_date"],
        "deposit_amount_cents": a["deposit_amount_cents"],
        "deposit_paid_cents": a["deposit_paid_cents"],
        "deposit_due_at": _ts(a, "deposit_due_at"),
        "refund_cents": a["refund_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def animal_out(a):
    return {
        "id": a["id"],
        "appointment_id": a["appointment_id"],
        "tag_id": a["tag_id"],
        "species": a["species"],
        "live_weight_lbs": _f(a["live_weight_lbs"]),
        "hanging_weight_lbs": _f(a["hanging_weight_lbs"]),
        "received_at": _ts(a, "received_at"),
        "slaughtered_at": _ts(a, "slaughtered_at"),
        "weighed_at": _ts(a, "weighed_at"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def share_out(s):
    return {
        "id": s["id"],
        "animal_id": s["animal_id"],
        "owner_customer_id": s["owner_customer_id"],
        "share_fraction": _f(s["share_fraction"]),
        "intended_use": s["intended_use"],
        "share_hanging_weight_lbs": _f(s["share_hanging_weight_lbs"]),
        "estimated_share_weight_lbs": _f(s["estimated_share_weight_lbs"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def cut_sheet_out(cs):
    return {
        "id": cs["id"],
        "share_id": cs["share_id"],
        "grind_pct": cs["grind_pct"],
        "package_weight_lbs": _f(cs["package_weight_lbs"]),
        "steak_thickness_in": _f(cs["steak_thickness_in"]),
        "notes": cs["notes"],
        "status": cs["status"],
        "created_at": cs["created_at"],
        "updated_at": cs["updated_at"],
        "version": cs["version"],
    }


def invoice_live_amounts(inv, now=None):
    """Final-variant (storage_cents, total_cents, amount_due_cents) view."""
    rec = record_of_share(inv["share_id"])
    if rec is not None and rec["status"] == "STORED":
        storage = record_accrued_cents(rec, now)
    else:
        storage = inv["storage_cents"]
    total = (inv["processing_fee_cents"] + inv["slaughter_share_cents"]
             + (0 if inv["storage_waived"] else storage)
             + inv["surcharge_cents"] - inv["deposit_credit_cents"])
    due = max(0, total - inv["amount_paid_cents"])
    return storage, total, due


def invoice_out(inv):
    storage, total, due = invoice_live_amounts(inv)
    return {
        "id": inv["id"],
        "share_id": inv["share_id"],
        "species": inv["species"],
        "processing_fee_cents": inv["processing_fee_cents"],
        "slaughter_share_cents": inv["slaughter_share_cents"],
        "storage_cents": storage,
        "storage_waived": inv["storage_waived"],
        "surcharge_cents": inv["surcharge_cents"],
        "deposit_credit_cents": inv["deposit_credit_cents"],
        "provisional_total_cents": inv["provisional_total_cents"],
        "total_cents": total,
        "amount_paid_cents": inv["amount_paid_cents"],
        "amount_due_cents": due,
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def storage_record_out(rec):
    return {
        "id": rec["id"],
        "share_id": rec["share_id"],
        "ready_at": _ts(rec, "ready_at"),
        "picked_up_at": _ts(rec, "picked_up_at"),
        "freezer_units": rec["freezer_units"],
        "days_stored": record_days_stored(rec),
        "accrued_fee_cents": record_accrued_cents(rec),
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def label_out(lbl):
    return {
        "id": lbl["id"],
        "share_id": lbl["share_id"],
        "program": lbl["program"],
        "label_text": lbl["label_text"],
        "status": lbl["status"],
        "created_at": lbl["created_at"],
        "updated_at": lbl["updated_at"],
        "version": lbl["version"],
    }
