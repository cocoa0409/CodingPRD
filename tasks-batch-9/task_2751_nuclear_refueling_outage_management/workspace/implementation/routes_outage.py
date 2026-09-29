"""Outage lifecycle gates (PRD 3.2, 3.6, 3.9)."""
from flask import Blueprint

import calc
import lookup
import projections
from auth import ALL_ROLES, authorize, current_user_id
from calc import ZERO2, dec, q2
from clock import clock
from db import create_row, store, touch
from errors import api_error
from response import ok
from serializers import serialize
from validators import F, bad, body, no_body

bp = Blueprint("outage", __name__)

STATION_UNITS = ("UNIT_1", "UNIT_2")


@bp.route("/outages", methods=["POST"])
@authorize("StationAdmin", "OutageDirector")
def create_outage():
    payload = body([
        F("station_unit", "str", enum=STATION_UNITS),
        F("designation", "str", min_len=1, max_len=32),
        F("duration_target_hours", "num", gt=0),
        F("dose_budget_total_mrem", "num", gt=0),
        F("cost_budget_usd", "num", gt=0),
        F("scope_freeze_at", "iso"),
        F("required_training_modules", "int", required=False, default=4, ge=0),
        F("required_badged_workers", "int", required=False, default=0, ge=0),
    ])
    for existing in store.outages.values():
        if (existing["station_unit"] == payload["station_unit"]
                and existing["designation"] == payload["designation"]):
            raise bad("designation must be unique within the station_unit.")
    dose_total = q2(payload["dose_budget_total_mrem"])
    outage = create_row(store.outages, {
        "station_unit": payload["station_unit"],
        "designation": payload["designation"],
        "duration_target_hours": q2(payload["duration_target_hours"]),
        "dose_budget_total_mrem": dose_total,
        "cost_budget_usd": q2(payload["cost_budget_usd"]),
        "scope_freeze_at": payload["scope_freeze_at"],
        "required_training_modules": payload["required_training_modules"],
        "required_badged_workers": payload["required_badged_workers"],
        "status": "PLANNING",
        "schedule_posture": "ON_TRACK",
        "alara_posture": "NORMAL",
        "projected_duration_hours": ZERO2,
        "risk_adjusted_duration_hours": ZERO2,
        "critical_path_activity_id": None,
        "dose_committed_mrem": ZERO2,
        "dose_budget_remaining_mrem": dose_total,
        "approved_scope_cost_usd": ZERO2,
        "scope_contingency_usd": ZERO2,
        "total_scope_cost_usd": ZERO2,
        "approved_emergent_hours": ZERO2,
        "badged_worker_count": 0,
        "scope_locked_at": None,
        "actual_duration_hours": None,
        "actual_cost_usd": None,
        "review_notes": None,
        "duration_variance_pct": None,
        "adjusted_duration_variance_pct": None,
        "dose_variance_pct": None,
        "cost_variance_pct": None,
        "outage_performance_index": None,
        "adjusted_performance_index": None,
        "created_by_user_id": current_user_id(),
    })
    return ok(serialize(outage), 201)


@bp.route("/outages/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_outage(row_id):
    return ok(serialize(lookup.outage(row_id)))


# ---------------------------------------------------------------------------
# PLANNING -> SCOPE_LOCKED
# ---------------------------------------------------------------------------
@bp.route("/outages/<row_id>/lock-scope", methods=["POST"])
@authorize("OutageDirector")
def lock_scope(row_id):
    outage = lookup.outage(row_id)
    no_body()
    if outage["status"] != "PLANNING":
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Scope lock requires the outage to be in PLANNING.")
    work_orders = projections.work_orders_of_outage(outage["id"])
    if not any(w["status"] == "APPROVED" for w in work_orders):
        raise api_error("ERR_WORK_ORDER_STATE_INVALID",
                        "The outage owns no APPROVED work order.")
    if not any(p["status"] == "APPROVED"
               for p in projections.patterns_of_outage(outage["id"])):
        raise api_error("ERR_CORE_LOAD_PATTERN_NOT_APPROVED",
                        "The outage owns no APPROVED core loading pattern.")

    outage["status"] = "SCOPE_LOCKED"
    outage["scope_locked_at"] = clock.now_iso()
    for work_order in work_orders:
        if work_order["status"] != "SCOPED":
            continue
        work_order["status"] = "DEFERRED"
        work_order["deferral_reason"] = "SCOPE_LOCK_AUTO_DEFERRAL"
        touch(work_order)
        projections.defer_work_order_cascade(work_order, False)

    projections.recompute_scope_cost(outage)
    projections.recompute_critical_path(outage)
    projections.recompute_schedule_posture(outage)
    touch(outage)
    return ok(serialize(outage))


# ---------------------------------------------------------------------------
# SCOPE_LOCKED -> EXECUTION
# ---------------------------------------------------------------------------
@bp.route("/outages/<row_id>/commence-execution", methods=["POST"])
@authorize("OutageDirector")
def commence_execution(row_id):
    outage = lookup.outage(row_id)
    no_body()
    if outage["status"] != "SCOPE_LOCKED":
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Breaker-open requires the outage to be in SCOPE_LOCKED.")
    if outage["badged_worker_count"] < outage["required_badged_workers"]:
        raise api_error("ERR_BADGED_WORKFORCE_INSUFFICIENT",
                        "The badged workforce has not reached required_badged_workers.")
    outage["status"] = "EXECUTION"
    touch(outage)
    return ok(serialize(outage))


# ---------------------------------------------------------------------------
# EXECUTION -> STARTUP
# ---------------------------------------------------------------------------
OPEN_WORK_ORDER_STATES = ("SCOPED", "PLANNED", "APPROVED", "EXECUTING")


@bp.route("/outages/<row_id>/authorize-startup", methods=["POST"])
@authorize("OutageDirector")
def authorize_startup(row_id):
    outage = lookup.outage(row_id)
    no_body()
    if outage["status"] != "EXECUTION":
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Startup authorization requires the outage to be in EXECUTION.")
    if not projections.startup_tests_of_outage(outage["id"]):
        raise api_error("ERR_STARTUP_SEQUENCE_EMPTY",
                        "The outage owns no startup test.")
    for work_order in projections.work_orders_of_outage(outage["id"]):
        if work_order["status"] in OPEN_WORK_ORDER_STATES:
            raise api_error("ERR_OPEN_WORK_ORDERS_REMAIN",
                            "A work order of the outage is still open.")
    for activity in projections.activities_of_outage(outage["id"]):
        if activity["oos_safety_function_id"] is None:
            continue
        if activity["execution_status"] not in ("COMPLETE", "CANCELLED"):
            raise api_error("ERR_ACTIVITY_STATE_INVALID",
                            "An out-of-service safety function has not been restored.")
    outage["status"] = "STARTUP"
    touch(outage)
    return ok(serialize(outage))


# ---------------------------------------------------------------------------
# ONLINE -> REVIEWED
# ---------------------------------------------------------------------------
@bp.route("/outages/<row_id>/post-outage-review", methods=["POST"])
@authorize("OutageDirector")
def post_outage_review(row_id):
    outage = lookup.outage(row_id)
    payload = body([
        F("actual_duration_hours", "num", gt=0),
        F("actual_cost_usd", "num", ge=0),
        F("review_notes", "str", required=False, nullable=True, max_len=2000),
    ])
    if outage["status"] != "ONLINE":
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "The post-outage review requires the outage to be in ONLINE.")

    actual_duration = q2(payload["actual_duration_hours"])
    actual_cost = q2(payload["actual_cost_usd"])
    outage["actual_duration_hours"] = actual_duration
    outage["actual_cost_usd"] = actual_cost
    outage["review_notes"] = payload["review_notes"]

    duration_pct = calc.variance_pct(actual_duration, outage["duration_target_hours"])
    dose_pct = calc.variance_pct(outage["dose_committed_mrem"],
                                 outage["dose_budget_total_mrem"])
    cost_pct = calc.variance_pct(actual_cost, outage["cost_budget_usd"])
    adjusted_hours = dec(actual_duration) - dec(outage["approved_emergent_hours"])
    adjusted_pct = calc.variance_pct(adjusted_hours, outage["duration_target_hours"])

    outage["duration_variance_pct"] = duration_pct
    outage["adjusted_duration_variance_pct"] = adjusted_pct
    outage["dose_variance_pct"] = dose_pct
    outage["cost_variance_pct"] = cost_pct
    outage["outage_performance_index"] = calc.performance_index(
        duration_pct, dose_pct, cost_pct)
    outage["adjusted_performance_index"] = calc.performance_index(
        adjusted_pct, dose_pct, cost_pct)

    outage["status"] = "REVIEWED"
    touch(outage)
    return ok(serialize(outage))
