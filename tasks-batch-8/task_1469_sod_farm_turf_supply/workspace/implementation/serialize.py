"""Entity -> public JSON serializers (computed fields resolved here)."""
from decimal import Decimal

import calc
import db
from util import D, fmt_ts, fmt_date, money_out, num_out

PRICE_CONFIG_FIELDS = [
    "name", "slab_sqft", "roll_sqft", "pallet_sqft_premium", "pallet_sqft_standard",
    "pallet_sqft_economy", "rate_premium", "rate_standard", "rate_economy",
    "zone1_rate", "zone2_rate", "zone3_rate", "freight_sqft_unit",
    "zone_truck_capacity", "delivery_window_hours", "delivery_earliest_start_hour",
    "delivery_latest_start_hour", "same_day_cutoff_hours", "future_day_cutoff_hour",
    "freshness_limit_hours", "card_fee_pct", "cash_discount_pct",
    "volume_t1_turf_min", "volume_t1_pre_min", "volume_t1_pct",
    "volume_t2_turf_min", "volume_t2_pre_min", "volume_t2_pct",
    "harvest_earliest_start_hour", "harvest_latest_end_hour",
]

# Fields stored internally as Decimal that serialize as plain numbers
_DECIMAL_ECHO_INT = {"freight_sqft_unit", "zone_truck_capacity", "delivery_window_hours",
                     "delivery_earliest_start_hour", "delivery_latest_start_hour",
                     "same_day_cutoff_hours", "future_day_cutoff_hour",
                     "harvest_earliest_start_hour", "harvest_latest_end_hour"}


def _base(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def _echo(v):
    if isinstance(v, Decimal):
        return num_out(v)
    return v


def pub_price_config(c):
    out = _base(c)
    for f in PRICE_CONFIG_FIELDS:
        out[f] = _echo(c[f])
    out["is_current"] = c["is_current"]
    return out


def pub_variety(v):
    out = _base(v)
    for f in ("name", "germination_max_days", "growing_max_days", "ready_max_days",
              "mature_max_days", "seed_lbs_per_1000_sqft"):
        out[f] = _echo(v[f])
    return out


def pub_field(f):
    out = _base(f)
    age_days, maturity = calc.compute_maturity(f)
    out.update({
        "name": f["name"],
        "variety_id": f["variety_id"],
        "field_sqft": _echo(f["field_sqft"]),
        "last_planted_at": fmt_ts(f["last_planted_at"]),
        "mow_count": f["mow_count"],
        "last_mowed_at": fmt_ts(f["last_mowed_at"]),
        "soil_moisture_pct": _echo(f["soil_moisture_pct"]),
        "health_score": _echo(f["health_score"]),
        "maturity_state": maturity,
        "age_days": age_days,
        "remaining_sqft": _echo(f["remaining_sqft"]),
        "status": f["status"],
    })
    return out


def pub_reseed_plan(p):
    out = _base(p)
    out.update({
        "field_id": p["field_id"],
        "planned_date": fmt_ts(p["planned_date"]),
        "target_seed_lbs": _echo(p["target_seed_lbs"]),
        "actual_seed_lbs": _echo(p["actual_seed_lbs"]) if p["actual_seed_lbs"] is not None else None,
        "status": p["status"],
        "completed_at": fmt_ts(p["completed_at"]),
    })
    return out


def pub_batch(b):
    out = _base(b)
    out.update({
        "field_id": b["field_id"],
        "variety_id": b["variety_id"],
        "grade": b["grade"],
        "pallet_count": b["pallet_count"],
        "shortfall_slabs": b["shortfall_slabs"],
        "shortfall_rolls": b["shortfall_rolls"],
        "full_sqft": _echo(b["full_sqft"]),
        "yield_sqft": _echo(b["yield_sqft"]),
        "sellable_sqft": _echo(b["sellable_sqft"]),
        "scheduled_date": fmt_date(b["scheduled_date"]),
        "actual_harvest_start": fmt_ts(b["actual_harvest_start"]),
        "actual_harvest_end": fmt_ts(b["actual_harvest_end"]),
        "status": b["status"],
        "order_id": b["order_id"],
    })
    return out


def pub_customer(c):
    out = _base(c)
    out.update({
        "full_name": c["full_name"],
        "email": c["email"],
        "phone": c["phone"],
        "freight_zone": c["freight_zone"],
        "address": c["address"],
    })
    return out


def pub_crew(c):
    out = _base(c)
    out.update({
        "name": c["name"],
        "service_zones": list(c["service_zones"]),
        "active": c["active"],
    })
    return out


def pub_quote(q):
    out = _base(q)
    out.update({
        "customer_id": q["customer_id"],
        "price_config_id": q["price_config_id"],
        "delivery_date": fmt_date(q["delivery_date"]),
        "settlement_method": q["settlement_method"],
        "z1_pallets": q["z1_pallets"],
        "z2_pallets": q["z2_pallets"],
        "z3_pallets": q["z3_pallets"],
        "lines": q["lines"],
        "total_pallets": q["total_pallets"],
        "capacity_zone": q["capacity_zone"],
        "turf_sqft": money_out(q["turf_sqft"]),
        "freight_amount": money_out(q["freight_amount"]),
        "pre_discount_subtotal": money_out(q["pre_discount_subtotal"]),
        "volume_tier": q["volume_tier"],
        "volume_discount": money_out(q["volume_discount"]),
        "card_fee": money_out(q["card_fee"]),
        "total_price": money_out(q["total_price"]),
        "additive_total": money_out(q["additive_total"]),
        "cash_price": money_out(q["cash_price"]),
        "status": q["status"],
        "superseded_by_id": q["superseded_by_id"],
    })
    return out


def order_total_paid(order):
    total = Decimal("0")
    for p in db.store.payments.values():
        if p["order_id"] == order["id"]:
            total += D(p["amount"])
    return total


def order_allocated_sqft(order):
    total = Decimal("0")
    for b in db.store.harvest_batches.values():
        if b["order_id"] == order["id"] and b["status"] != "CANCELLED":
            total += D(b["sellable_sqft"])
    return total


def pub_order(o):
    out = _base(o)
    total_paid = order_total_paid(o)
    chargeable = D(o["chargeable_amount"])
    amount_due = max(Decimal("0"), chargeable - total_paid)
    credit_balance = max(Decimal("0"), total_paid - chargeable)
    out.update({
        "quote_id": o["quote_id"],
        "customer_id": o["customer_id"],
        "price_config_id": o["price_config_id"],
        "delivery_date": fmt_date(o["delivery_date"]),
        "settlement_method": o["settlement_method"],
        "freight_zone": o["freight_zone"],
        "capacity_zone": o["capacity_zone"],
        "turf_sqft": money_out(o["turf_sqft"]),
        "freight_amount": money_out(o["freight_amount"]),
        "pre_discount_subtotal": money_out(o["pre_discount_subtotal"]),
        "volume_tier": o["volume_tier"],
        "volume_discount": money_out(o["volume_discount"]),
        "card_fee": money_out(o["card_fee"]),
        "total_price": money_out(o["total_price"]),
        "total_pallets": o["total_pallets"],
        "delivery_window_start": fmt_ts(o["delivery_window_start"]),
        "delivery_window_end": fmt_ts(o["delivery_window_end"]),
        "status": o["status"],
        "payment_status": o["payment_status"],
        "crew_referral_status": o["crew_referral_status"],
        "allocated_sqft": num_out(order_allocated_sqft(o)),
        "delivered_sqft": num_out(o["delivered_sqft"]),
        "actual_delivered_at": fmt_ts(o["actual_delivered_at"]),
        "freshness_hours": float(o["freshness_hours"]) if o["freshness_hours"] is not None else None,
        "install_started_at": fmt_ts(o["install_started_at"]),
        "installed_at": fmt_ts(o["installed_at"]),
        "chargeable_amount": money_out(chargeable),
        "total_paid": money_out(total_paid),
        "amount_due": money_out(amount_due),
        "credit_balance": money_out(credit_balance),
        "delivery_flagged": o["delivery_flagged"],
    })
    return out


def pub_payment(p):
    return {
        "id": p["id"],
        "order_id": p["order_id"],
        "amount": money_out(p["amount"]),
        "method": p["method"],
        "received_at": fmt_ts(p["received_at"]),
        "created_at": fmt_ts(p["created_at"]),
    }


def pub_delivery_check(c):
    return {
        "id": c["id"],
        "order_id": c["order_id"],
        "check_index": c["check_index"],
        "promised_sqft": money_out(c["promised_sqft"]),
        "delivered_cumulative": num_out(c["delivered_cumulative"]),
        "prior_payments": money_out(c["prior_payments"]),
        "baseline_sqft": money_out(c["baseline_sqft"]),
        "window_size": money_out(c["window_size"]),
        "in_window": c["in_window"],
        "strict_in_window": c["strict_in_window"],
        "shortfall_sqft": num_out(c["shortfall_sqft"]),
        "blended_rate": float(c["blended_rate"]),
        "shortfall_credit": money_out(c["shortfall_credit"]),
        "chargeable_after": money_out(c["chargeable_after"]),
        "created_at": fmt_ts(c["created_at"]),
    }


def pub_referral(r):
    out = _base(r)
    out.update({
        "order_id": r["order_id"],
        "crew_id": r["crew_id"],
        "status": r["status"],
        "scheduled_date": fmt_date(r["scheduled_date"]),
    })
    return out


def pub_claim(c):
    out = _base(c)
    out.update({
        "order_id": c["order_id"],
        "customer_id": c["customer_id"],
        "weather_case": c["weather_case"],
        "eligible_turf_sqft": num_out(c["eligible_turf_sqft"]),
        "target_credits": c["target_credits"],
        "total_credits": c["total_credits"],
        "status": c["status"],
        "resolution": c["resolution"],
        "credit_amount": money_out(c["credit_amount"]),
        "evaluated_at": fmt_ts(c["evaluated_at"]),
    })
    return out


def pub_watering_log(w):
    return {
        "id": w["id"],
        "claim_id": w["claim_id"],
        "log_date": fmt_date(w["log_date"]),
        "moisture_reading": _echo(w["moisture_reading"]),
        "credits_awarded": w["credits_awarded"],
        "created_at": fmt_ts(w["created_at"]),
    }


def pub_truck_block(t):
    out = _base(t)
    out.update({
        "freight_zone": t["freight_zone"],
        "window_start": fmt_ts(t["window_start"]),
        "window_end": fmt_ts(t["window_end"]),
        "reason": t["reason"],
    })
    return out
