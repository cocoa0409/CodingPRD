"""Ops run-daily sweep and logical clock endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import services as svc
from errors import ApiError, ERR_CLOCK_REGRESSION, ERR_VALIDATION
from middleware import require_roles
from response import success_object
from routes_orders import create_order_record

bp = Blueprint("ops", __name__)


@bp.post("/jansan/_clock/set_current_utc")
def set_clock():
    require_roles("DistributorAdmin")
    body = request.get_json(silent=True) or {}
    raw = svc.require_field(body, "to_iso8601")
    target = clock.parse_iso(raw)
    if target is None:
        raise ApiError(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 datetime", 400)
    if target < clock.now():
        raise ApiError(ERR_CLOCK_REGRESSION, "Cannot set clock earlier than current logical time", 400)
    clock.set_now(target)
    return success_object({"current_utc": clock.iso_now()})


@bp.post("/jansan/ops/run-daily")
def run_daily():
    require_roles("DistributorAdmin")
    now = clock.now()

    expired_training_record_ids = []
    expired_bid_ids = []
    expired_trial_ids = []
    expired_proposal_ids = []
    generated_order_ids = []

    # Step 1: expire CERTIFIED training records past expires_at (strict)
    for t in list(db.training_records.values()):
        if t["status"] == "CERTIFIED" and t.get("expires_at"):
            if now > clock.parse_iso(t["expires_at"]):
                t["status"] = "EXPIRED"
                svc.touch(t)
                expired_training_record_ids.append(t["id"])

    # Step 2: expire AWARDED bids past protection_end (strict) + standing-order reprice
    for b in list(db.contract_bids.values()):
        if b["status"] == "AWARDED" and now > clock.parse_iso(b["protection_end"]):
            b["status"] = "EXPIRED"
            svc.touch(b)
            expired_bid_ids.append(b["id"])
            svc.cascade_bid_to_standing_orders(b)

    # Step 3: expire ACTIVE trials past trial_end (strict)
    for t in list(db.trial_programs.values()):
        if t["status"] == "ACTIVE" and now > clock.parse_iso(t["trial_end"]):
            t["status"] = "EXPIRED"
            svc.touch(t)
            expired_trial_ids.append(t["id"])

    # Step 4: expire PENDING proposals past expires_at (strict) — decline cascade
    for p in list(db.substitution_proposals.values()):
        if p["status"] == "PENDING" and now > clock.parse_iso(p["expires_at"]):
            line = db.order_lines.get(p["order_line_id"])
            order = db.orders.get(line["order_id"]) if line else None
            if line is not None and line["status"] == "SUBSTITUTION_PENDING":
                line["status"] = "CANCELLED"
                svc.touch(line)
            p["status"] = "EXPIRED"
            svc.touch(p)
            expired_proposal_ids.append(p["id"])
            if order:
                svc.auto_transition_order(order)

    # Step 5: generate orders from due ACTIVE standing orders
    for so in list(db.standing_orders.values()):
        if so["status"] != "ACTIVE":
            continue
        if clock.parse_iso(so["next_run_date"]) > now:
            continue
        # Build order priced with the standing order's fuel_index
        lines = [{"product_id": it["product_id"], "qty": it["qty"], "discount_pct": 0}
                 for it in so["items"]]
        order = create_order_record(
            so["facility_id"], lines,
            clock.parse_iso(so["next_run_date"]), so["fuel_index"],
            source="STANDING_ORDER", standing_order_id=so["id"],
        )
        generated_order_ids.append(order["id"])
        facility = db.facilities.get(so["facility_id"])
        # Attempt placement; on any validation failure order stays DRAFT
        if facility is not None and facility["status"] == "ACTIVE":
            try:
                svc.place_order(order)
            except ApiError:
                pass  # stays DRAFT
        # next_run_date advances regardless of placement success
        advance = svc.FREQUENCY_DAYS[so["frequency"]]
        next_run = clock.parse_iso(so["next_run_date"]) + timedelta(days=advance)
        so["next_run_date"] = clock.iso_format(next_run)
        svc.touch(so)

    return success_object({
        "generated_count": len(generated_order_ids),
        "generated_order_ids": generated_order_ids,
        "expired_training_record_ids": expired_training_record_ids,
        "expired_bid_ids": expired_bid_ids,
        "expired_trial_ids": expired_trial_ids,
        "expired_proposal_ids": expired_proposal_ids,
    })
