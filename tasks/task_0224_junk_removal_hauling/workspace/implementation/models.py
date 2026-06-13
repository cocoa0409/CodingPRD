"""Entity construction, common-field management, and serialization.

Common fields (PRD §2.4): id, created_at, updated_at, version (starts 1, +1 per
mutation). DiversionRecord and DumpTicket are leaner: id + created_at only, never
mutated (no updated_at, no version).

Entities are stored as plain dicts; serialization returns a copy of the public
fields (computed fields are recomputed at read time by services where required and
stored back, so the stored dict is always the source of truth).
"""
from util import new_id, iso_now_3
from db import db


def _stamp_create(obj, versioned=True):
    ts = iso_now_3()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["_seq"] = db.next_seq()
    if versioned:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Record a mutation: refresh updated_at and bump version. Only for versioned entities."""
    obj["updated_at"] = iso_now_3()
    obj["version"] = obj.get("version", 1) + 1


# --------------------------------------------------------------------------
# Constructors
# --------------------------------------------------------------------------

def make_pricing_policy(name, full_truck_cents, tier_breaks, mattress_surcharge_cents,
                        appliance_surcharge_cents, freon_surcharge_cents,
                        dump_fee_per_ton_cents, full_truck_dump_cents,
                        recycle_fee_per_ton_cents, diversion_credit_per_ton_cents,
                        min_billable_fraction, fraction_step, same_day_surcharge_pct,
                        tax_pct, cancel_pct_scheduled, cancel_pct_dispatched, status):
    obj = {
        "name": name,
        "full_truck_cents": full_truck_cents,
        "tier_breaks": tier_breaks,
        "min_billable_fraction": min_billable_fraction,
        "fraction_step": fraction_step,
        "mattress_surcharge_cents": mattress_surcharge_cents,
        "appliance_surcharge_cents": appliance_surcharge_cents,
        "freon_surcharge_cents": freon_surcharge_cents,
        "dump_fee_per_ton_cents": dump_fee_per_ton_cents,
        "full_truck_dump_cents": full_truck_dump_cents,
        "recycle_fee_per_ton_cents": recycle_fee_per_ton_cents,
        "diversion_credit_per_ton_cents": diversion_credit_per_ton_cents,
        "same_day_surcharge_pct": same_day_surcharge_pct,
        "tax_pct": tax_pct,
        "cancel_pct_scheduled": cancel_pct_scheduled,
        "cancel_pct_dispatched": cancel_pct_dispatched,
        "status": status,
    }
    return _stamp_create(obj)


def make_customer(email, full_name, credit_limit_cents):
    obj = {
        "email": email,
        "full_name": full_name,
        "credit_limit_cents": credit_limit_cents,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    }
    return _stamp_create(obj)


def make_crew(name, shift_start_utc, shift_end_utc, buffer_minutes, hazmat_certified):
    obj = {
        "name": name,
        "shift_start_utc": shift_start_utc,
        "shift_end_utc": shift_end_utc,
        "buffer_minutes": buffer_minutes,
        "hazmat_certified": hazmat_certified,
        "reserved_minutes": 0,
        "status": "ON_DUTY",
    }
    return _stamp_create(obj)


def make_truck(name):
    obj = {
        "name": name,
        "status": "IN_SERVICE",
    }
    return _stamp_create(obj)


def make_haul_job(customer_id, pricing_policy_id, service_type, address):
    obj = {
        "customer_id": customer_id,
        "pricing_policy_id": pricing_policy_id,
        "service_type": service_type,
        "address": address,
        "estimated_truck_fraction": None,
        "measured_truck_fraction": None,
        "estimated_total_cents": None,
        "final_total_cents": None,
        "cancellation_fee_cents": None,
        "status": "DRAFT",
    }
    return _stamp_create(obj)


def make_job_item(haul_job_id, category, quantity, description):
    obj = {
        "haul_job_id": haul_job_id,
        "category": category,
        "quantity": quantity,
        "description": description,
    }
    return _stamp_create(obj)


def make_photo_estimate(haul_job_id, photo_url, raw_fraction, declared_items):
    obj = {
        "haul_job_id": haul_job_id,
        "photo_url": photo_url,
        "raw_fraction": raw_fraction,
        "declared_items": declared_items,
        "accepted": False,
        "status": "SUBMITTED",
    }
    return _stamp_create(obj)


def make_dispatch(haul_job_id, crew_id, truck_id, window_start_utc, window_end_utc,
                  window_minutes):
    obj = {
        "haul_job_id": haul_job_id,
        "crew_id": crew_id,
        "truck_id": truck_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "window_minutes": window_minutes,
        "dispatch_status": "RESERVED",
    }
    return _stamp_create(obj)


def make_diversion_record(haul_job_id, destination, tons):
    obj = {
        "haul_job_id": haul_job_id,
        "destination": destination,
        "tons": tons,
    }
    return _stamp_create(obj, versioned=False)


def make_dump_ticket(haul_job_id, landfill_tons, landfill_fraction, fee_basis):
    obj = {
        "haul_job_id": haul_job_id,
        "landfill_tons": landfill_tons,
        "landfill_fraction": landfill_fraction,
        "fee_basis": fee_basis,
        "dump_fee_cents": None,
    }
    return _stamp_create(obj, versioned=False)


def make_invoice(haul_job_id, customer_id, total_cents, kind):
    obj = {
        "haul_job_id": haul_job_id,
        "customer_id": customer_id,
        "total_cents": total_cents,
        "kind": kind,
        "billing_status": "ISSUED",
        "dispute_status": "NONE",
    }
    return _stamp_create(obj)


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------

_PUBLIC_VERSIONED = ["id", "created_at", "updated_at", "version"]
_PUBLIC_LEAN = ["id", "created_at"]


def _serialize(obj, fields, versioned=True):
    out = {}
    base = _PUBLIC_VERSIONED if versioned else _PUBLIC_LEAN
    for f in base:
        out[f] = obj[f]
    for f in fields:
        out[f] = obj.get(f)
    return out


def ser_pricing_policy(o):
    return _serialize(o, [
        "name", "full_truck_cents", "tier_breaks", "min_billable_fraction",
        "fraction_step", "mattress_surcharge_cents", "appliance_surcharge_cents",
        "freon_surcharge_cents", "dump_fee_per_ton_cents", "full_truck_dump_cents",
        "recycle_fee_per_ton_cents", "diversion_credit_per_ton_cents",
        "same_day_surcharge_pct", "tax_pct", "cancel_pct_scheduled",
        "cancel_pct_dispatched", "status",
    ])


def ser_customer(o):
    return _serialize(o, [
        "email", "full_name", "credit_limit_cents", "outstanding_balance_cents",
        "status",
    ])


def ser_crew(o):
    return _serialize(o, [
        "name", "shift_start_utc", "shift_end_utc", "buffer_minutes",
        "hazmat_certified", "reserved_minutes", "status",
    ])


def ser_truck(o):
    return _serialize(o, ["name", "status"])


def ser_haul_job(o):
    return _serialize(o, [
        "customer_id", "pricing_policy_id", "service_type", "address",
        "estimated_truck_fraction", "measured_truck_fraction",
        "estimated_total_cents", "final_total_cents", "cancellation_fee_cents",
        "status",
    ])


def ser_job_item(o):
    return _serialize(o, ["haul_job_id", "category", "quantity", "description"])


def ser_photo_estimate(o):
    return _serialize(o, [
        "haul_job_id", "photo_url", "raw_fraction", "declared_items", "accepted",
        "status",
    ])


def ser_dispatch(o):
    return _serialize(o, [
        "haul_job_id", "crew_id", "truck_id", "window_start_utc", "window_end_utc",
        "window_minutes", "dispatch_status",
    ])


def ser_diversion_record(o):
    return _serialize(o, ["haul_job_id", "destination", "tons"], versioned=False)


def ser_dump_ticket(o):
    return _serialize(o, [
        "haul_job_id", "landfill_tons", "landfill_fraction", "fee_basis",
        "dump_fee_cents",
    ], versioned=False)


def ser_invoice(o):
    return _serialize(o, [
        "haul_job_id", "customer_id", "total_cents", "kind", "billing_status",
        "dispute_status",
    ])
