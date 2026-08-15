"""Entity construction, mutation bookkeeping, and serialization."""
from datetime import datetime, date

import db


def new_entity(store_name, fields):
    ent = dict(fields)
    ent["id"] = db.new_id()
    now = db.clock_now()
    ent["created_at"] = now
    ent["updated_at"] = now
    ent["version"] = 1
    ent["_seq"] = db.next_seq()
    db.STORES[store_name][ent["id"]] = ent
    return ent


def touch(ent):
    """Every mutation refreshes updated_at and increments version by one."""
    ent["updated_at"] = db.clock_now()
    ent["version"] += 1


def get(store_name, ent_id):
    return db.STORES[store_name].get(ent_id)


def all_of(store_name):
    return db.STORES[store_name].values()


# --------------------------------------------------------------------------
# Serializers (internal keys stripped; computed fields resolved by callers)
# --------------------------------------------------------------------------
def _base(ent):
    return {
        "id": ent["id"],
        "created_at": db.fmt_ts(ent["created_at"]),
        "updated_at": db.fmt_ts(ent["updated_at"]),
        "version": ent["version"],
    }


def _date_str(d):
    return d.isoformat() if isinstance(d, (date, datetime)) else d


def serialize_site(site, posture):
    out = _base(site)
    out.update({
        "name": site["name"],
        "base_nightly_rate_cents": site["base_nightly_rate_cents"],
        "no_show_grace_minutes": site["no_show_grace_minutes"],
        "overstay_grace_minutes": site["overstay_grace_minutes"],
        "cancellation_free_window_hours": site["cancellation_free_window_hours"],
        "posture": posture,
        "ops_run_index": site["ops_run_index"],
    })
    return out


def serialize_stall(s):
    out = _base(s)
    out.update({
        "site_id": s["site_id"],
        "stall_number": s["stall_number"],
        "stall_class": s["stall_class"],
        "is_reservable": s["is_reservable"],
        "status": s["status"],
    })
    return out


def serialize_rate_plan(p):
    out = _base(p)
    out.update({
        "site_id": p["site_id"],
        "tier2_pct": p["tier2_pct"],
        "tier3_pct": p["tier3_pct"],
        "tier4_pct": p["tier4_pct"],
        "mult_low": p["mult_low"],
        "mult_mid": p["mult_mid"],
        "mult_high": p["mult_high"],
        "mult_max": p["mult_max"],
        "peak_multiplier": p["peak_multiplier"],
        "peak_days": list(p["peak_days"]),
        "status": p["status"],
    })
    return out


def serialize_amenity_product(p):
    out = _base(p)
    out.update({
        "site_id": p["site_id"],
        "code": p["code"],
        "name": p["name"],
        "price_cents": p["price_cents"],
        "nightly_capacity": p["nightly_capacity"],
        "status": p["status"],
    })
    return out


def serialize_driver(d, computed):
    out = _base(d)
    out.update({
        "cdl_number": d["cdl_number"],
        "full_name": d["full_name"],
        "strike_events": [
            {"at": db.fmt_dt(e["at"]), "kind": e["kind"], "booking_id": e["booking_id"]}
            for e in d["strike_events"]
        ],
        "strikes_90d": computed["strikes_90d"],
        "standing": computed["standing"],
        "settled_nights_90d": computed["settled_nights_90d"],
        "loyalty_tier": computed["loyalty_tier"],
        "loyalty_points_balance": d["loyalty_points_balance"],
    })
    return out


def serialize_fleet(f, current_balance):
    out = _base(f)
    out.update({
        "company_name": f["company_name"],
        "credit_limit_cents": f["credit_limit_cents"],
        "payment_terms_days": f["payment_terms_days"],
        "status": f["status"],
        "auto_suspended": f["auto_suspended"],
        "current_balance_cents": current_balance,
        "credit_cents": f["credit_cents"],
    })
    return out


def serialize_authorization(a):
    out = _base(a)
    out.update({
        "driver_id": a["driver_id"],
        "fleet_account_id": a["fleet_account_id"],
        "spend_cap_per_night_cents": a["spend_cap_per_night_cents"],
        "status": a["status"],
        "auto_suspended": a["auto_suspended"],
    })
    return out


def serialize_booking(b):
    out = _base(b)
    out.update({
        "driver_id": b["driver_id"],
        "site_id": b["site_id"],
        "stall_id": b["stall_id"],
        "waitlist_entry_id": b["waitlist_entry_id"],
        "booking_kind": b["booking_kind"],
        "payment_mode": b["payment_mode"],
        "fleet_account_id": b["fleet_account_id"],
        "arrival_date": _date_str(b["arrival_date"]),
        "night_count": b["night_count"],
        "checkin_open_at": db.fmt_dt(b["checkin_open_at"]),
        "checkout_due_at": db.fmt_dt(b["checkout_due_at"]),
        "checked_in_at": db.fmt_dt(b["checked_in_at"]),
        "checked_out_at": db.fmt_dt(b["checked_out_at"]),
        "overstayed_at": db.fmt_dt(b["overstayed_at"]),
        "status": b["status"],
        "billing_status": b["billing_status"],
        "per_night_rates": [
            {"date": _date_str(r["date"]), "rate_cents": r["rate_cents"]}
            for r in b["per_night_rates"]
        ],
        "quoted_total_cents": b["quoted_total_cents"],
        "parking_subtotal_cents": b["parking_subtotal_cents"],
        "amenity_net_cents": b["amenity_net_cents"],
        "discount_cents": b["discount_cents"],
        "fee_cents": b["fee_cents"],
        "final_total_cents": b["final_total_cents"],
        "paid_cents": b["paid_cents"],
        "incident_escalated": b["incident_escalated"],
    })
    return out


def serialize_booking_amenity(line):
    out = _base(line)
    out.update({
        "booking_id": line["booking_id"],
        "amenity_product_id": line["amenity_product_id"],
        "quantity": line["quantity"],
        "unit_price_cents": line["unit_price_cents"],
        "status": line["status"],
    })
    return out


def serialize_waitlist_entry(e):
    out = _base(e)
    out.update({
        "site_id": e["site_id"],
        "driver_id": e["driver_id"],
        "arrival_date": _date_str(e["arrival_date"]),
        "night_count": e["night_count"],
        "stall_class": e["stall_class"],
        "payment_mode": e["payment_mode"],
        "fleet_account_id": e["fleet_account_id"],
        "status": e["status"],
        "offered_stall_id": e["offered_stall_id"],
        "offer_expires_at": db.fmt_dt(e["offer_expires_at"]),
    })
    return out


def serialize_incident(i):
    out = _base(i)
    out.update({
        "site_id": i["site_id"],
        "reporter_driver_id": i["reporter_driver_id"],
        "booking_id": i["booking_id"],
        "category": i["category"],
        "severity": i["severity"],
        "description": i["description"],
        "status": i["status"],
        "acknowledged_by_user_id": i["acknowledged_by_user_id"],
        "resolved_by_user_id": i["resolved_by_user_id"],
        "resolved_at": db.fmt_dt(i["resolved_at"]),
        "reopened_count": i["reopened_count"],
    })
    return out


def serialize_invoice(inv):
    out = _base(inv)
    out.update({
        "fleet_account_id": inv["fleet_account_id"],
        "period": inv["period"],
        "status": inv["status"],
        "gross_cents": inv["gross_cents"],
        "discount_pct": inv["discount_pct"],
        "discount_cents": inv["discount_cents"],
        "net_cents": inv["net_cents"],
        "paid_cents": inv["paid_cents"],
        "due_date": _date_str(inv["due_date"]),
        "booking_ids": list(inv["booking_ids"]),
    })
    return out
