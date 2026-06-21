"""Serialize internal records into API output objects (drop internal keys)."""


def _common(rec, with_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if with_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def venue_out(v):
    out = _common(v)
    out.update({
        "name": v["name"],
        "timezone": v["timezone"],
        "cancellation_tier": v["cancellation_tier"],
        "force_majeure_fee_pct": v["force_majeure_fee_pct"],
        "status": v["status"],
    })
    return out


def space_out(s):
    out = _common(s)
    out.update({
        "venue_id": s["venue_id"],
        "name": s["name"],
        "space_kind": s["space_kind"],
        "max_capacity": s["max_capacity"],
        "base_rental_cents": s["base_rental_cents"],
        "turnover_buffer_minutes": s["turnover_buffer_minutes"],
        "status": s["status"],
    })
    return out


def package_out(p):
    out = _common(p)
    out.update({
        "venue_id": p["venue_id"],
        "tier": p["tier"],
        "per_head_cents": p["per_head_cents"],
        "fb_minimum_cents": p["fb_minimum_cents"],
        "service_charge_pct": p["service_charge_pct"],
        "tax_pct": p["tax_pct"],
        "status": p["status"],
    })
    return out


def client_out(c):
    out = _common(c)
    out.update({"full_name": c["full_name"], "email": c["email"]})
    return out


def coordinator_out(c):
    out = _common(c)
    out.update({
        "venue_id": c["venue_id"],
        "full_name": c["full_name"],
        "active_booking_cap": c["active_booking_cap"],
        "assigned_active_count": c["assigned_active_count"],
    })
    return out


def booking_out(b):
    out = _common(b)
    out.update({
        "client_id": b["client_id"],
        "venue_id": b["venue_id"],
        "package_id": b["package_id"],
        "coordinator_id": b["coordinator_id"],
        "event_date": b["event_date"],
        "ceremony_start": b["ceremony_start"],
        "ceremony_end": b["ceremony_end"],
        "reception_start": b["reception_start"],
        "reception_end": b["reception_end"],
        "expected_guest_count": b["expected_guest_count"],
        "booking_status": b["booking_status"],
        "payment_status": b["payment_status"],
        "hold_expires_at": b["hold_expires_at"],
        "amount_paid_cents": b["amount_paid_cents"],
        "event_charge_cents": b["event_charge_cents"],
        "balance_due_cents": b["balance_due_cents"],
        "cancelled_reason": b["cancelled_reason"],
    })
    return out


def hold_out(h):
    out = _common(h)
    out.update({
        "booking_id": h["booking_id"],
        "space_id": h["space_id"],
        "block_role": h["block_role"],
        "occupy_start": h["occupy_start"],
        "occupy_end": h["occupy_end"],
        "hold_status": h["hold_status"],
    })
    return out


def milestone_out(m):
    out = _common(m)
    out.update({
        "booking_id": m["booking_id"],
        "kind": m["kind"],
        "sequence": m["sequence"],
        "amount_due_cents": m["amount_due_cents"],
        "amount_allocated_cents": m["amount_allocated_cents"],
        "due_date": m["due_date"],
        "milestone_status": m["milestone_status"],
    })
    return out


def payment_out(p):
    # Payment is leaner: id + created_at only, no version/updated_at.
    out = _common(p, with_version=False)
    out.update({
        "booking_id": p["booking_id"],
        "direction": p["direction"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "status": p["status"],
        "posted_at": p["posted_at"],
    })
    return out


def vendor_out(v):
    out = _common(v)
    out.update({
        "booking_id": v["booking_id"],
        "company_name": v["company_name"],
        "vendor_role": v["vendor_role"],
        "coi_required": v["coi_required"],
        "coi_on_file": v["coi_on_file"],
        "coi_expires_on": v["coi_expires_on"],
        "vendor_status": v["vendor_status"],
    })
    return out


def guarantee_out(g):
    out = _common(g)
    out.update({
        "booking_id": g["booking_id"],
        "guaranteed_count": g["guaranteed_count"],
        "guarantee_deadline": g["guarantee_deadline"],
        "locked_at": g["locked_at"],
    })
    return out


def walkthrough_out(w):
    out = _common(w)
    out.update({
        "booking_id": w["booking_id"],
        "scheduled_start": w["scheduled_start"],
        "scheduled_end": w["scheduled_end"],
        "walkthrough_status": w["walkthrough_status"],
    })
    return out


def reschedule_out(r):
    out = _common(r)
    out.update({
        "booking_id": r["booking_id"],
        "supersedes_request_id": r["supersedes_request_id"],
        "reason_kind": r["reason_kind"],
        "proposed_event_date": r["proposed_event_date"],
        "proposed_ceremony_start": r["proposed_ceremony_start"],
        "proposed_ceremony_end": r["proposed_ceremony_end"],
        "proposed_reception_start": r["proposed_reception_start"],
        "proposed_reception_end": r["proposed_reception_end"],
        "request_status": r["request_status"],
    })
    return out
