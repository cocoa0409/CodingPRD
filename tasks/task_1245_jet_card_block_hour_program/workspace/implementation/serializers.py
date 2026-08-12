"""Resource serializers: strip internal fields, format timestamps/hours."""

from util import fmt_ts, hours_json


def _common(r):
    return {
        "id": r["id"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def program_json(p):
    out = _common(p)
    out.update({
        "program_code": p["program_code"],
        "aircraft_category": p["aircraft_category"],
        "hours_purchased": p["hours_purchased"],
        "purchase_price_cents": p["purchase_price_cents"],
        "swap_ratio_to_lower": p["swap_ratio_to_lower"],
        "swap_ratio_to_higher": p["swap_ratio_to_higher"],
        "expiry_months": p["expiry_months"],
        "taxi_minutes_per_leg": p["taxi_minutes_per_leg"],
        "min_billable_minutes_per_leg": p["min_billable_minutes_per_leg"],
        "peak_surcharge_pct": p["peak_surcharge_pct"],
        "availability_window_hours": p["availability_window_hours"],
        "round_trip_discount_pct": p["round_trip_discount_pct"],
        "early_termination_penalty_pct": p["early_termination_penalty_pct"],
        "fractional_upgrade_ratio": p["fractional_upgrade_ratio"],
    })
    return out


def member_json(m):
    out = _common(m)
    out.update({
        "email": m["email"],
        "full_name": m["full_name"],
        "member_status": m["member_status"],
        "tier": m["tier"],
        "home_base_icao": m["home_base_icao"],
    })
    return out


def card_json(c, hours_remaining_override=None):
    out = _common(c)
    hrs = c["hours_remaining"] if hours_remaining_override is None \
        else hours_remaining_override
    out.update({
        "member_id": c["member_id"],
        "program_id": c["program_id"],
        "card_status": c["card_status"],
        "purchased_at": fmt_ts(c["purchased_at"]),
        "expires_at": fmt_ts(c["expires_at"]),
        "hours_total": c["hours_total"],
        "hours_remaining": hours_json(hrs),
        "hours_consumed": hours_json(c["hours_consumed"]),
        "hours_expired": hours_json(c["hours_expired"]),
        "escrow_balance_cents": c["escrow_balance_cents"],
        "peak_hours_used": hours_json(c["peak_hours_used"]),
    })
    return out


def ledger_json(e):
    # HourBankLedger is append-only: only id + created_at, no updated_at/version.
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "card_id": e["card_id"],
        "entry_kind": e["entry_kind"],
        "hours_delta": hours_json(e["hours_delta"]),
        "effective_at": fmt_ts(e["effective_at"]),
        "trip_id": e["trip_id"],
        "note": e["note"],
    }


def aircraft_json(a):
    out = _common(a)
    out.update({
        "tail_number": a["tail_number"],
        "category": a["category"],
        "home_base_icao": a["home_base_icao"],
        "seats": a["seats"],
        "aircraft_status": a["aircraft_status"],
        "reposition_rate_cents_per_nm": a["reposition_rate_cents_per_nm"],
    })
    return out


def trip_json(t):
    out = _common(t)
    out.update({
        "card_id": t["card_id"],
        "trip_kind": t["trip_kind"],
        "departure_icao": t["departure_icao"],
        "arrival_icao": t["arrival_icao"],
        "requested_departure_utc": fmt_ts(t["requested_departure_utc"]),
        "requested_return_utc": fmt_ts(t["requested_return_utc"]),
        "pax_count": t["pax_count"],
        "requested_category": t["requested_category"],
        "swap_applied": t["swap_applied"],
        "dispatched_aircraft_id": t["dispatched_aircraft_id"],
        "trip_status": t["trip_status"],
        "denial_reason": t["denial_reason"],
        "is_peak_period": t["is_peak_period"],
        "quoted_hours": hours_json(t["quoted_hours"]),
        "final_hours": hours_json(t["final_hours"]),
        "sla_met": t["sla_met"],
    })
    return out


def leg_json(lg):
    out = _common(lg)
    out.update({
        "trip_id": lg["trip_id"],
        "leg_seq": lg["leg_seq"],
        "departure_icao": lg["departure_icao"],
        "arrival_icao": lg["arrival_icao"],
        "scheduled_departure_utc": fmt_ts(lg["scheduled_departure_utc"]),
        "actual_block_minutes": lg["actual_block_minutes"],
        "billable_minutes": lg["billable_minutes"],
        "billable_hours": hours_json(lg["billable_hours"]),
        "swap_multiplier": (None if lg["swap_multiplier"] is None
                            else float(lg["swap_multiplier"])),
        "debited_hours": hours_json(lg["debited_hours"]),
        "leg_status": lg["leg_status"],
    })
    return out


def invoice_json(inv):
    out = _common(inv)
    out.update({
        "trip_id": inv["trip_id"],
        "invoice_status": inv["invoice_status"],
        "subtotal_cents": inv["subtotal_cents"],
        "peak_surcharge_cents": inv["peak_surcharge_cents"],
        "round_trip_discount_cents": inv["round_trip_discount_cents"],
        "total_cents": inv["total_cents"],
        "issued_at": fmt_ts(inv["issued_at"]),
    })
    return out


def peak_window_json(w):
    out = _common(w)
    out.update({
        "program_id": w["program_id"],
        "window_start_utc": fmt_ts(w["window_start_utc"]),
        "window_end_utc": fmt_ts(w["window_end_utc"]),
        "label": w["label"],
    })
    return out


def blackout_window_json(w):
    out = _common(w)
    out.update({
        "program_id": w["program_id"],
        "window_start_utc": fmt_ts(w["window_start_utc"]),
        "window_end_utc": fmt_ts(w["window_end_utc"]),
        "applies_to_category": w["applies_to_category"],
        "reason": w["reason"],
    })
    return out


def escrow_json(e):
    out = _common(e)
    out.update({
        "card_id": e["card_id"],
        "principal_cents": e["principal_cents"],
        "available_cents": e["available_cents"],
        "released_cents": e["released_cents"],
        "forfeited_cents": e["forfeited_cents"],
    })
    return out


def refund_json(r):
    out = _common(r)
    out.update({
        "card_id": r["card_id"],
        "refund_status": r["refund_status"],
        "hours_at_request": hours_json(r["hours_at_request"]),
        "gross_refund_cents": r["gross_refund_cents"],
        "penalty_cents": r["penalty_cents"],
        "net_refund_cents": r["net_refund_cents"],
        "requested_at": fmt_ts(r["requested_at"]),
        "denial_reason": r["denial_reason"],
    })
    return out


def upgrade_json(u):
    out = _common(u)
    out.update({
        "card_id": u["card_id"],
        "hours_converted": hours_json(u["hours_converted"]),
        "share_fraction": u["share_fraction"],
        "upgrade_status": u["upgrade_status"],
        "applied_at": fmt_ts(u["applied_at"]),
    })
    return out
