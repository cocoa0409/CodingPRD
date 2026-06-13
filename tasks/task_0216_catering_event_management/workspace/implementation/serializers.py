"""Convert internal records into API-facing JSON dicts.

Internal records store datetimes as datetime objects and carry an internal
`_seq` ordering key; serializers emit ISO strings and strip internal fields.
Field sets trace to SCAFFOLD §1.1 entity tables.
"""
from common import iso


def ser_client(c):
    return {
        "id": c["id"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
        "company_name": c["company_name"],
        "billing_email": c["billing_email"],
        "tax_exempt": c["tax_exempt"],
        "gratuity_policy": c["gratuity_policy"],
        "status": c["status"],
    }


def ser_package(p):
    return {
        "id": p["id"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
        "name": p["name"],
        "per_head_cents": p["per_head_cents"],
        "min_headcount": p["min_headcount"],
        "lead_time_hours": p["lead_time_hours"],
        "volume_tiers": p["volume_tiers"],
        "allergen_flags": p["allergen_flags"],
        "status": p["status"],
    }


def ser_venue(v):
    return {
        "id": v["id"],
        "created_at": iso(v["created_at"]),
        "updated_at": iso(v["updated_at"]),
        "version": v["version"],
        "name": v["name"],
        "tax_rate_bps": v["tax_rate_bps"],
        "service_fee_bps": v["service_fee_bps"],
        "max_overlapping_events": v["max_overlapping_events"],
    }


def ser_route(r):
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
        "route_date": iso(r["route_date"]),
        "vehicle_capacity_legs": r["vehicle_capacity_legs"],
        "posture": r["posture"],
        "dispatched_leg_count": r["dispatched_leg_count"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "created_at": iso(o["created_at"]),
        "updated_at": iso(o["updated_at"]),
        "version": o["version"],
        "client_id": o["client_id"],
        "package_id": o["package_id"],
        "venue_id": o["venue_id"],
        "route_id": o["route_id"],
        "booked_headcount": o["booked_headcount"],
        "guaranteed_headcount": o["guaranteed_headcount"],
        "event_start": iso(o["event_start"]),
        "event_end": iso(o["event_end"]),
        "locked_package_version": o["locked_package_version"],
        "dietary_counts": o["dietary_counts"],
        "lifecycle_status": o["lifecycle_status"],
        "settlement_status": o["settlement_status"],
        "provisional_total_cents": o["provisional_total_cents"],
        "final_total_cents": o["final_total_cents"],
        "deposit_due_cents": o["deposit_due_cents"],
    }


def ser_addon(a):
    return {
        "id": a["id"],
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
        "order_id": a["order_id"],
        "kind": a["kind"],
        "unit_cents": a["unit_cents"],
        "quantity": a["quantity"],
        "per_head_scaled": a["per_head_scaled"],
        "staff_ratio": a["staff_ratio"],
    }


def ser_leg(l):
    return {
        "id": l["id"],
        "created_at": iso(l["created_at"]),
        "updated_at": iso(l["updated_at"]),
        "version": l["version"],
        "order_id": l["order_id"],
        "route_id": l["route_id"],
        "preceding_leg_id": l["preceding_leg_id"],
        "window_start": iso(l["window_start"]),
        "window_end": iso(l["window_end"]),
        "stop_status": l["stop_status"],
    }


def ser_reservation(r):
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
        "order_id": r["order_id"],
        "reserved_staff": r["reserved_staff"],
        "status": r["status"],
    }


def ser_change_request(cr):
    return {
        "id": cr["id"],
        "created_at": iso(cr["created_at"]),
        "updated_at": iso(cr["updated_at"]),
        "version": cr["version"],
        "order_id": cr["order_id"],
        "requested_headcount": cr["requested_headcount"],
        "requested_event_start": iso(cr["requested_event_start"]),
        "counter_headcount": cr["counter_headcount"],
        "change_fee_cents": cr["change_fee_cents"],
        "status": cr["status"],
    }


def ser_ledger(e):
    # DepositLedgerEntry is the common-fields exception (PRD §2.4): id +
    # created_at only, plus its own business fields. No updated_at/version.
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "order_id": e["order_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "reason": e["reason"],
    }
