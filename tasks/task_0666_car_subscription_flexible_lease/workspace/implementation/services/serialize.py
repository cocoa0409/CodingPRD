"""Serialize internal records into API output shape.

PRD §2.4 common fields: id, created_at, updated_at, version on every entity EXCEPT
Invoice, which carries only id + created_at (immutable; no updated_at, no version).

Computed fields (Fleet.utilization, Subscription.lifetime_billed_cents, etc.) are
recomputed eagerly on each mutation, but serializers also derive what is purely a
function of stored state to keep reads authoritative.
"""
from db import db
from services import calc

# Internal bookkeeping keys never exposed in API payloads.
_INTERNAL = {"_seq"}


def _public(record, drop=()):
    return {k: v for k, v in record.items() if k not in _INTERNAL and k not in drop}


def serialize_plan(p):
    return _public(p)


def serialize_fleet(f):
    out = _public(f)
    # Derived counts recomputed live (PRD §2.6: always derived, never client-written).
    total, in_use = _fleet_counts(f["id"])
    out["total_vehicles"] = total
    out["in_use_count"] = in_use
    out["utilization_pct"] = calc.utilization_pct(in_use, total)
    return out


def _fleet_counts(fleet_id):
    total = 0
    in_use = 0
    for v in db.vehicles.values():
        if v["fleet_id"] == fleet_id:
            total += 1
            if v["status"] in ("RESERVED", "ASSIGNED"):
                in_use += 1
    return total, in_use


def serialize_vehicle(v):
    return _public(v)


def serialize_applicant(a):
    return _public(a)


def serialize_subscription(s):
    out = _public(s)
    # lifetime_billed_cents = running sum of posted Invoice.amount_cents (PRD §3.14).
    out["lifetime_billed_cents"] = sum(
        inv["amount_cents"] for inv in db.invoices.values() if inv["subscription_id"] == s["id"]
    )
    return out


def serialize_billing_cycle(c):
    return _public(c)


def serialize_invoice(inv):
    # Invoice immutable: id + created_at only among common fields (PRD §2.4).
    return _public(inv, drop=("updated_at", "version"))


def serialize_swap_request(sr):
    return _public(sr)


def serialize_return_inspection(ri):
    return _public(ri)


def serialize_damage_line_item(d):
    return _public(d)


def serialize_courier(c):
    return _public(c)


def serialize_delivery_slot(ds):
    return _public(ds)
