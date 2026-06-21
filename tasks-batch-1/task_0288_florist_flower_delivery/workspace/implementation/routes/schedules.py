"""Recurring-schedule routes: create/emit/pause/resume/cancel (PRD §3.8)."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_auth, require_role
from helpers import (
    get_body, make_record, touch, public, parse_pagination, paginate,
    require_fields, as_int, as_str, as_number, as_enum,
)
from response import success, success_list
from services import clock

bp = Blueprint("schedules", __name__)

CADENCES = {"WEEKLY", "MONTHLY"}


def _check_schedule_owner(sched, user_id, role):
    if role == "Customer" and sched["customer_id"] != user_id:
        raise errors.not_resource_owner("Customer does not own this schedule")


@bp.route("/floral/recurring-schedules", methods=["POST"])
def create_schedule():
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    body = get_body()
    require_fields(body, ["customer_id", "arrangement_id", "zone_id", "cadence",
                          "next_delivery_date", "window_start_minute",
                          "window_end_minute", "occurrences_remaining"])
    customer_id = as_str(body, "customer_id")
    arrangement_id = as_str(body, "arrangement_id")
    zone_id = as_str(body, "zone_id")
    cadence = as_enum(body, "cadence", CADENCES)
    next_delivery_date = as_str(body, "next_delivery_date")
    window_start = as_int(body, "window_start_minute")
    window_end = as_int(body, "window_end_minute")
    occurrences_remaining = as_int(body, "occurrences_remaining")
    recurring_discount_pct = as_number(body, "recurring_discount_pct",
                                       required=False, default=0.05)

    if role == "Customer" and customer_id != user_id:
        raise errors.not_resource_owner("Customer may only subscribe for self")

    if customer_id not in store.customers:
        raise errors.not_found("customer_id not found")
    if arrangement_id not in store.arrangements:
        raise errors.not_found("arrangement_id not found")
    if zone_id not in store.zones:
        raise errors.not_found("zone_id not found")

    clock.parse_date(next_delivery_date)
    if window_start < 0 or window_start > 1439:
        raise errors.invalid_request("window_start_minute must be 0..1439")
    if window_end > 1440:
        raise errors.invalid_request("window_end_minute must be <= 1440")
    if not (window_start < window_end):
        raise errors.invalid_request(
            "window_start_minute must be < window_end_minute")
    if occurrences_remaining < 0:
        raise errors.invalid_request("occurrences_remaining must be >= 0")
    if recurring_discount_pct < 0 or recurring_discount_pct > 0.5:
        raise errors.validation_range("recurring_discount_pct must be 0..0.5")

    rec = make_record()
    rec.update({
        "customer_id": customer_id,
        "arrangement_id": arrangement_id,
        "zone_id": zone_id,
        "cadence": cadence,
        "next_delivery_date": next_delivery_date,
        "window_start_minute": window_start,
        "window_end_minute": window_end,
        "occurrences_remaining": occurrences_remaining,
        "status": "ACTIVE",
        "recurring_discount_pct": recurring_discount_pct,
    })
    store.recurring_schedules[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/recurring-schedules/<sid>", methods=["GET"])
def get_schedule(sid):
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "CatalogAdmin"})
    rec = store.recurring_schedules.get(sid)
    if rec is None:
        raise errors.not_found("Schedule not found")
    return success(public(rec))


@bp.route("/floral/recurring-schedules", methods=["GET"])
def list_schedules():
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "CatalogAdmin"})
    limit, offset = parse_pagination()
    rows = list(store.recurring_schedules.values())
    for field in ("customer_id", "arrangement_id", "zone_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/floral/recurring-schedules/<sid>/emit", methods=["POST"])
def emit_schedule(sid):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    sched = store.recurring_schedules.get(sid)
    if sched is None:
        raise errors.not_found("Schedule not found")
    # PRD §3.8: "an emit (or a resume) against a schedule whose
    # `occurrences_remaining` is 0 is rejected with `ERR_SCHEDULE_EXHAUSTED`."
    # The exhausted condition governs and takes precedence over the generic
    # state check: a schedule that reaches occurrences_remaining 0 auto-pauses,
    # so the exhausted-emit case always coincides with a PAUSED status, and the
    # PRD names a dedicated error for it.
    if sched["occurrences_remaining"] < 1:
        raise errors.ApiError(errors.ERR_SCHEDULE_EXHAUSTED, 409,
                              "Schedule is exhausted")
    if sched["status"] != "ACTIVE":
        raise errors.invalid_state("Emit is only defined while ACTIVE")

    # Create the emitted order.
    new_order = make_record()
    new_order.update({
        "customer_id": sched["customer_id"],
        "arrangement_id": sched["arrangement_id"],
        "zone_id": sched["zone_id"],
        "parent_recurrence_id": sched["id"],
        "source_order_id": None,
        "occasion": "GENERAL",
        "card_message": "",
        "delivery_date": sched["next_delivery_date"],
        "window_start_minute": sched["window_start_minute"],
        "window_end_minute": sched["window_end_minute"],
        "apply_wallet_credit": False,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "estimated_total_cents": 0,
        "final_total_cents": 0,
        "wallet_credit_applied_cents": 0,
        "is_same_day": False,
        "_authorized_amount_cents": 0,
    })
    store.orders[new_order["id"]] = new_order

    # Advance next_delivery_date by cadence.
    if sched["cadence"] == "WEEKLY":
        sched["next_delivery_date"] = clock.add_days(sched["next_delivery_date"], 7)
    else:
        sched["next_delivery_date"] = clock.add_one_month(sched["next_delivery_date"])

    sched["occurrences_remaining"] -= 1
    if sched["occurrences_remaining"] == 0:
        sched["status"] = "PAUSED"
    touch(sched)
    return success(public(sched))


@bp.route("/floral/recurring-schedules/<sid>/pause", methods=["POST"])
def pause_schedule(sid):
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    sched = store.recurring_schedules.get(sid)
    if sched is None:
        raise errors.not_found("Schedule not found")
    _check_schedule_owner(sched, user_id, role)
    if sched["status"] != "ACTIVE":
        raise errors.invalid_state("Pause is only defined from ACTIVE")
    sched["status"] = "PAUSED"
    touch(sched)
    return success(public(sched))


@bp.route("/floral/recurring-schedules/<sid>/resume", methods=["POST"])
def resume_schedule(sid):
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    sched = store.recurring_schedules.get(sid)
    if sched is None:
        raise errors.not_found("Schedule not found")
    _check_schedule_owner(sched, user_id, role)
    if sched["status"] != "PAUSED":
        raise errors.invalid_state("Resume is only defined from PAUSED")
    if sched["occurrences_remaining"] < 1:
        raise errors.ApiError(errors.ERR_SCHEDULE_EXHAUSTED, 409,
                              "Schedule is exhausted")
    sched["status"] = "ACTIVE"
    touch(sched)
    return success(public(sched))


@bp.route("/floral/recurring-schedules/<sid>/cancel", methods=["POST"])
def cancel_schedule(sid):
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    sched = store.recurring_schedules.get(sid)
    if sched is None:
        raise errors.not_found("Schedule not found")
    _check_schedule_owner(sched, user_id, role)
    if sched["status"] not in {"ACTIVE", "PAUSED"}:
        raise errors.invalid_state("Cancel is only defined from ACTIVE/PAUSED")
    sched["status"] = "CANCELLED"
    touch(sched)
    return success(public(sched))
