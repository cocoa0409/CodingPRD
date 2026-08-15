"""DeliveryLoad and Bundle endpoints: planning, bundle maps, dispatch gates,
return/reschedule loop, final-freight and storage settlement at close."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_LOAD_INVALID_TRANSITION,
    ERR_OUTSIDE_DELIVERY_WINDOW,
    ERR_DROPS_PER_DAY_EXCEEDED,
    ERR_CREDIT_HOLD,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_BUNDLE_OVERWEIGHT,
    ERR_STACK_POSITION_CONFLICT,
    ERR_BUNDLE_JOB_MISMATCH,
)
from middleware import authenticate, require_role, require_ownership, get_or_404, ALL_ROLES
from response import success, success_list
from services import cascade, serializers
from services.derive import credit_used_cents, load_actual_weight, OPEN_CLAIM_STATUSES, \
    job_invoiced_cents as derive_job_invoiced
from services.cascade import (
    FREIGHT_BASE_CENTS,
    PROVISIONAL_CENTS_PER_LB,
    JOBSITE_CRANE_FLAT_CENTS,
    OVERWEIGHT_THRESHOLD_LBS,
    OVERWEIGHT_CENTS_PER_LB,
    job_completion_check,
)
from util import as_dt, as_int, as_num, as_fk, as_enum, body, paginate, dec, round_cents

bp = Blueprint("loads", __name__)

LOAD_STATES = {"PLANNED", "STAGED", "LOADING", "DISPATCHED", "DELIVERED", "RETURNED",
               "RESCHEDULED", "CLAIM_HOLD", "CLOSED", "CANCELLED"}


def _provisional_freight(job, planned_weight_est_lbs):
    return (
        FREIGHT_BASE_CENTS
        + round_cents(dec(planned_weight_est_lbs) * PROVISIONAL_CENTS_PER_LB)
        + (JOBSITE_CRANE_FLAT_CENTS if job["crane_required_at_jobsite"] else 0)
    )


def _date_in_window(job, when):
    return job["delivery_window_start"].date() <= when.date() <= job["delivery_window_end"].date()


def _drops_count(job, date_value, exclude_load_id=None):
    count = 0
    for l in db.delivery_loads.values():
        if l["job_id"] != job["id"] or l["status"] == "CANCELLED" or l["id"] == exclude_load_id:
            continue
        if l["scheduled_date"].date() == date_value.date():
            count += 1
    return count


def _check_window(job, when):
    if not _date_in_window(job, when):
        raise ApiError(ERR_OUTSIDE_DELIVERY_WINDOW, 422,
                       "scheduled_date is outside the job's closed delivery window")


def _check_drops(job, when, exclude_load_id=None):
    customer = db.customers[job["customer_id"]]
    if _drops_count(job, when, exclude_load_id) >= customer["max_drops_per_day"]:
        raise ApiError(ERR_DROPS_PER_DAY_EXCEEDED, 422,
                       "aggregate daily drops capacity for the job would be exceeded on that date")


def _check_credit_limit(customer, provisional_freight_cents):
    if credit_used_cents(customer["id"]) + provisional_freight_cents > customer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402,
                       "credit_used_cents plus this load's provisional freight exceeds the credit limit")


def _dispatch_guards(load, job):
    """Temporal first (31), then fiscal: credit hold (37) then limit (38)."""
    if not _date_in_window(job, load["scheduled_date"]) or db.get_clock() > job["delivery_window_end"]:
        raise ApiError(ERR_OUTSIDE_DELIVERY_WINDOW, 422,
                       "scheduled_date outside the window or the delivery window has closed")
    customer = db.customers[job["customer_id"]]
    if customer["credit_hold"]:
        raise ApiError(ERR_CREDIT_HOLD, 402, "dispatch blocked: customer is on credit hold")
    _check_credit_limit(customer, load["provisional_freight_cents"])


def _bundles_of(load_id):
    return sorted((b for b in db.bundles.values() if b["delivery_load_id"] == load_id),
                  key=lambda b: b["_seq"])


def _referenced_batch_ids(load_id):
    return {b["production_batch_id"] for b in _bundles_of(load_id)}


def _load_pick_slots(load_id, statuses=("BOOKED", "COMPLETED")):
    return sorted(
        (s for s in db.crane_slots.values()
         if s["delivery_load_id"] == load_id and s["purpose"] == "LOAD_PICK"
         and s["status"] in statuses),
        key=lambda s: (s["start_at"], s["_seq"]),
    )


# ---------------------------------------------------------------------------
# Load create / reads
# ---------------------------------------------------------------------------

@bp.route("/plant/jobs/<job_id>/loads", methods=["POST"])
def create_load(job_id):
    _uid, role = authenticate()
    require_role(role, ["ShippingCoordinator"])
    job = get_or_404(db.jobs, job_id, "job")
    data = body()
    scheduled_date = as_dt(data.get("scheduled_date"), "scheduled_date", required=True)
    planned_weight = as_num(data.get("planned_weight_est_lbs"), "planned_weight_est_lbs", required=True)
    # Gate order after the universal checks (section 3.7): window (31),
    # drops-per-day (32), then credit limit (38).
    _check_window(job, scheduled_date)
    _check_drops(job, scheduled_date)
    provisional = _provisional_freight(job, planned_weight)
    _check_credit_limit(db.customers[job["customer_id"]], provisional)
    rec = db.new_record({
        "job_id": job["id"],
        "scheduled_date": scheduled_date,
        "planned_weight_est_lbs": planned_weight,
        "provisional_freight_cents": provisional,
        "final_freight_cents": None,
        "crane_hours_actual": None,
        "staged_at": None,
        "last_dispatched_at": None,
        "storage_fee_cents": None,
        "status": "PLANNED",
    })
    db.delivery_loads[rec["id"]] = rec
    return success(serializers.delivery_load(rec), status=201)


@bp.route("/plant/loads/<lid>", methods=["GET"])
def get_load(lid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.delivery_loads, lid, "delivery load")
    require_ownership(role, uid, db.jobs[rec["job_id"]]["customer_id"])
    return success(serializers.delivery_load(rec))


@bp.route("/plant/loads", methods=["GET"])
def list_loads():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    records = list(db.delivery_loads.values())
    if role == "CustomerContact":
        records = [l for l in records if db.jobs[l["job_id"]]["customer_id"] == uid]
    for field in ("job_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            records = [l for l in records if l[field] == raw]
    raw = request.args.get("scheduled_date")
    if raw is not None:
        from util import fmt_dt
        records = [l for l in records if fmt_dt(l["scheduled_date"]) == raw]
    page, meta = paginate(records)
    return success_list([serializers.delivery_load(l) for l in page], meta)


# ---------------------------------------------------------------------------
# Load lifecycle
# ---------------------------------------------------------------------------

@bp.route("/plant/loads/<lid>/transition", methods=["POST"])
def load_transition(lid):
    _uid, role = authenticate()
    require_role(role, ["ShippingCoordinator"])
    rec = get_or_404(db.delivery_loads, lid, "delivery load")
    data = body()
    to_state = as_enum(data.get("to_state"), "to_state", LOAD_STATES, required=True)
    # Conditional inputs (schema layer, section 2.7).
    rescheduled_date = None
    crane_hours_actual = None
    if to_state == "RESCHEDULED":
        rescheduled_date = as_dt(data.get("rescheduled_date"), "rescheduled_date", required=True)
    if to_state == "CLOSED":
        crane_hours_actual = as_num(data.get("crane_hours_actual"), "crane_hours_actual", required=True)

    current = rec["status"]
    job = db.jobs[rec["job_id"]]

    def invalid(msg):
        return ApiError(ERR_LOAD_INVALID_TRANSITION, 409, msg)

    if to_state == "STAGED":
        if current != "PLANNED":
            raise invalid(f"load transition {current} -> STAGED is not declared")
        if not any(b["status"] == "PACKED" for b in _bundles_of(rec["id"])):
            raise invalid("staging requires at least one bundle of this load in PACKED")
        rec["staged_at"] = db.get_clock()  # storage anchor
    elif to_state == "LOADING":
        if current != "STAGED":
            raise invalid(f"load transition {current} -> LOADING is not declared")
        if not _load_pick_slots(rec["id"], statuses=("COMPLETED",)):
            raise invalid("loading requires a COMPLETED LOAD_PICK crane slot for this load")
        non_superseded = [b for b in _bundles_of(rec["id"]) if b["status"] != "SUPERSEDED"]
        if not non_superseded or any(b["status"] != "PACKED" for b in non_superseded):
            raise invalid("every non-SUPERSEDED bundle of this load must be in PACKED")
        for b in non_superseded:
            b["status"] = "LOADED"
            db.touch(b)
        for batch_id in _referenced_batch_ids(rec["id"]):
            batch = db.production_batches[batch_id]
            if batch["status"] == "STAGED":
                batch["status"] = "LOADED"
                db.touch(batch)
    elif to_state == "DISPATCHED":
        if current not in ("LOADING", "RESCHEDULED"):
            raise invalid(f"load transition {current} -> DISPATCHED is not declared")
        _dispatch_guards(rec, job)
        rec["last_dispatched_at"] = db.get_clock()
        if current == "RESCHEDULED":
            for b in _bundles_of(rec["id"]):
                if b["status"] == "RETURNED":
                    b["status"] = "LOADED"
                    db.touch(b)
            for batch_id in _referenced_batch_ids(rec["id"]):
                batch = db.production_batches[batch_id]
                if batch["status"] == "STAGED":
                    batch["status"] = "LOADED"
                    db.touch(batch)
        if job["status"] == "IN_PRODUCTION":
            # First DISPATCHED load advances the job to SHIPPING.
            job["status"] = "SHIPPING"
            db.touch(job)
    elif to_state == "DELIVERED":
        if current != "DISPATCHED":
            raise invalid(f"load transition {current} -> DELIVERED is not declared")
        for b in _bundles_of(rec["id"]):
            if b["status"] == "LOADED":
                b["status"] = "DELIVERED"
                db.touch(b)
    elif to_state == "RETURNED":
        if current != "DISPATCHED":
            raise invalid(f"load transition {current} -> RETURNED is not declared")
        for b in _bundles_of(rec["id"]):
            if b["status"] == "LOADED":
                b["status"] = "RETURNED"
                db.touch(b)
        for batch_id in _referenced_batch_ids(rec["id"]):
            batch = db.production_batches[batch_id]
            if batch["status"] == "LOADED":
                batch["status"] = "STAGED"
                db.touch(batch)
    elif to_state == "RESCHEDULED":
        if current != "RETURNED":
            raise invalid(f"load transition {current} -> RESCHEDULED is not declared")
        _check_window(job, rescheduled_date)
        _check_drops(job, rescheduled_date, exclude_load_id=rec["id"])
        rec["scheduled_date"] = rescheduled_date
    elif to_state == "CLOSED":
        if current not in ("DELIVERED", "CLAIM_HOLD"):
            raise invalid(f"load transition {current} -> CLOSED is not declared")
        if current == "CLAIM_HOLD":
            for c in db.damage_claims.values():
                if c["delivery_load_id"] == rec["id"] and c["status"] in OPEN_CLAIM_STATUSES:
                    raise invalid("load has open claims and cannot close")
        _close_load(rec, job, crane_hours_actual)
    else:  # CANCELLED / CLAIM_HOLD are system-only
        raise invalid(f"load transition to {to_state} is system-only")

    rec["status"] = to_state
    db.touch(rec)
    if to_state == "CLOSED":
        # Closing recomputes the job's invoiced_cents (now counting this load's
        # final freight) and runs the completion check.
        new_invoiced = derive_job_invoiced(job)
        if new_invoiced != job["invoiced_cents"]:
            job["invoiced_cents"] = new_invoiced
            db.touch(job)
        job_completion_check(job)
    return success(serializers.delivery_load(rec))


def _close_load(load, job, crane_hours_actual):
    """Final freight in pinned evaluation order (calculation load_freight_final)."""
    customer = db.customers[job["customer_id"]]
    # (1) measured weight over non-SUPERSEDED bundles.
    actual_weight = load_actual_weight(load)
    # (2) crane cost from the earliest-start BOOKED/COMPLETED LOAD_PICK slot.
    slots = _load_pick_slots(load["id"])
    crane_cost = 0
    if slots:
        crane = db.cranes[slots[0]["crane_id"]]
        crane_cost = round_cents(dec(crane_hours_actual) * crane["hourly_rate_cents"])
    # (3) overweight surcharge: strictly above 20000 lbs triggers.
    surcharge = 0
    if actual_weight > OVERWEIGHT_THRESHOLD_LBS:
        surcharge = round_cents((actual_weight - OVERWEIGHT_THRESHOLD_LBS) * OVERWEIGHT_CENTS_PER_LB)
    # (4) storage accrual (whole calendar days between the UTC date parts).
    days_stored = (load["last_dispatched_at"].date() - load["staged_at"].date()).days
    billable_days = max(0, days_stored - customer["storage_free_days"])
    storage_fee = min(billable_days * customer["storage_daily_fee_cents"],
                      customer["storage_fee_cap_cents"])
    # (5) final freight.
    load["crane_hours_actual"] = crane_hours_actual
    load["storage_fee_cents"] = storage_fee
    load["final_freight_cents"] = (
        FREIGHT_BASE_CENTS
        + round_cents(actual_weight * PROVISIONAL_CENTS_PER_LB)
        + surcharge
        + crane_cost
        + storage_fee
    )


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------

@bp.route("/plant/loads/<load_id>/bundles", methods=["POST"])
def create_bundle(load_id):
    _uid, role = authenticate()
    require_role(role, ["ShippingCoordinator"])
    load = get_or_404(db.delivery_loads, load_id, "delivery load")
    data = body()
    batch = as_fk(data.get("production_batch_id"), "production_batch_id",
                  db.production_batches, "production batch")
    split_from = as_fk(data.get("split_from_bundle_id"), "split_from_bundle_id",
                       db.bundles, "bundle")
    if batch is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: production_batch_id")
    stack_position = as_int(data.get("stack_position"), "stack_position", required=True)
    weight_lbs = as_num(data.get("weight_lbs"), "weight_lbs", required=True)
    # Constraint checks precede the referential check (section 3.7):
    # (23) weight against the booked load-pick crane's capacity, then
    # (24) stack-position uniqueness, then (34) referential.
    slots = _load_pick_slots(load_id)
    if slots:
        crane = db.cranes[slots[0]["crane_id"]]
        if weight_lbs > crane["capacity_lbs"]:
            raise ApiError(ERR_BUNDLE_OVERWEIGHT, 422,
                           "bundle weight exceeds the booked load-pick crane capacity")
    if any(b["stack_position"] == stack_position and b["status"] != "SUPERSEDED"
           for b in _bundles_of(load_id)):
        raise ApiError(ERR_STACK_POSITION_CONFLICT, 409,
                       "stack_position already used by a non-SUPERSEDED bundle of this load")
    if (
        load["status"] not in ("PLANNED", "STAGED", "LOADING")
        or batch["status"] != "STAGED"
        or batch["job_id"] != load["job_id"]
        or not slots
    ):
        raise ApiError(ERR_BUNDLE_JOB_MISMATCH, 422,
                       "load not accepting bundles, batch not STAGED, batch belongs to another job, or no load-pick slot booked")
    rec = db.new_record({
        "delivery_load_id": load["id"],
        "production_batch_id": batch["id"],
        "stack_position": stack_position,
        "weight_lbs": weight_lbs,
        "split_from_bundle_id": split_from["id"] if split_from else None,
        "status": "PACKED",
    })
    db.bundles[rec["id"]] = rec
    return success(serializers.bundle(rec), status=201)


@bp.route("/plant/bundles/<bid>", methods=["GET"])
def get_bundle(bid):
    _uid, role = authenticate()
    require_role(role, [r for r in ALL_ROLES if r != "CustomerContact"])
    return success(serializers.bundle(get_or_404(db.bundles, bid, "bundle")))


@bp.route("/plant/bundles", methods=["GET"])
def list_bundles():
    _uid, role = authenticate()
    require_role(role, [r for r in ALL_ROLES if r != "CustomerContact"])
    records = list(db.bundles.values())
    for field in ("delivery_load_id", "production_batch_id", "split_from_bundle_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            records = [b for b in records if b[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.bundle(b) for b in page], meta)
