"""Release planning, the bridge supply and the statutory mortality review."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers
import store
from constants import (
    BRIDGE_SUPPLY_LEAD_DAYS, MORTALITY_CORRECTIVE_ACTION_MIN, RELEASE_TYPE,
)
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx

bp = Blueprint("release", __name__)


@bp.post("/inmates/<inmate_id>/release-plans")
def open_plan(inmate_id):
    # Release-plan work is deliberately exempt from the records freeze (PRD 2.6).
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.path_inmate(inmate_id)
    ctx.require("release_type", "planned_release_at")
    ctx.check_type("planned_release_at", "datetime")
    ctx.enum("release_type", RELEASE_TYPE)

    def lead_time():
        if ctx.body.get("release_type") != "SCHEDULED":
            return                      # UNEXPECTED plans are exempt entirely
        planned = ctx.dt_field("planned_release_at")
        floor = store.clock_dt() + timedelta(days=BRIDGE_SUPPLY_LEAD_DAYS)
        if planned.dt < floor:          # exact equality is accepted
            raise ApiError("ERR_RELEASE_PLAN_LEAD_TIME",
                           "a SCHEDULED plan needs at least 7 days of runway")
    ctx.temporal(lead_time)
    ctx.run()

    planned = ctx.dt_field("planned_release_at")
    lines, total, reentry = calc.bridge_supply(inmate_id, ctx.body["release_type"], planned)
    row = store.base_row()
    row.update({
        "inmate_id": inmate_id,
        "release_type": ctx.body["release_type"],
        "planned_release_at": planned,
        "bridge_supply_total_days": total,
        "bridge_supply_lines": lines,
        "reentry_referral_required": reentry,
        "records_packet_ready": False,
        "status": "DRAFT",
    })
    store.release_plans[row["id"]] = row
    return created(serializers.release_plan(row))


@bp.get("/inmates/<inmate_id>/release-plans")
def list_plans(inmate_id):
    ctx = Ctx(roles=("HealthServicesAdmin", "Inmate"))
    ctx.path_inmate(inmate_id)
    ctx.run()

    limit, offset = page_params(request.args)
    rows = [p for p in store.release_plans.values() if p["inmate_id"] == inmate_id]
    if request.args.get("status"):
        rows = [p for p in rows if p["status"] == request.args["status"]]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.release_plan, rows), limit, offset)


@bp.post("/release-plans/<plan_id>/finalize")
def finalize(plan_id):
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.need("plan", store.release_plans, plan_id, "ERR_RECORD_NOT_FOUND")
    ctx.status_in(lambda: ctx.row("plan"), ("DRAFT",))
    ctx.run()

    row = ctx.row("plan")
    lines, total, reentry = calc.bridge_supply(row["inmate_id"], row["release_type"],
                                               row["planned_release_at"])
    row["status"] = "FINALIZED"
    row["bridge_supply_lines"] = lines
    row["bridge_supply_total_days"] = total
    row["reentry_referral_required"] = reentry
    store.touch(row)
    return ok(serializers.release_plan(row))


@bp.get("/inmates/<inmate_id>/mortality-reviews")
def list_reviews(inmate_id):
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.path_inmate(inmate_id)
    ctx.run()

    limit, offset = page_params(request.args)
    rows = [m for m in store.mortality_reviews.values() if m["inmate_id"] == inmate_id]
    if request.args.get("status"):
        rows = [m for m in rows if m["status"] == request.args["status"]]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.mortality_review, rows), limit, offset)


@bp.post("/mortality-reviews/<review_id>/corrective-actions")
def add_corrective_action(review_id):
    # Mortality-review work is deliberately exempt from the records freeze.
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.need("review", store.mortality_reviews, review_id, "ERR_RECORD_NOT_FOUND")
    ctx.require("action_text")
    ctx.check_type("action_text", "string")
    ctx.status_in(lambda: ctx.row("review"), ("OPEN", "CORRECTIVE_ACTIONS_ISSUED"))
    ctx.run()

    row = ctx.row("review")
    row["corrective_actions"].append({
        "action_text": ctx.body["action_text"],
        "recorded_at": store.now(),
    })
    row["corrective_actions"].sort(key=lambda a: a["recorded_at"].dt)
    row["corrective_action_count"] += 1
    row["status"] = "CORRECTIVE_ACTIONS_ISSUED"
    store.touch(row)
    return ok(serializers.mortality_review(row))


@bp.post("/mortality-reviews/<review_id>/close")
def close_review(review_id):
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.need("review", store.mortality_reviews, review_id, "ERR_RECORD_NOT_FOUND")

    def complete_enough():
        row = ctx.row("review")
        if row["corrective_action_count"] < MORTALITY_CORRECTIVE_ACTION_MIN:
            raise ApiError("ERR_MORTALITY_REVIEW_INCOMPLETE",
                           "at least one corrective action is required before closing")
    ctx.state(complete_enough, sub=0)
    ctx.status_in(lambda: ctx.row("review"), ("CORRECTIVE_ACTIONS_ISSUED",), sub=1)
    ctx.run()

    row = ctx.row("review")
    closed_at = store.now()
    row["status"] = "CLOSED"
    row["closed_at"] = closed_at
    row["closed_late"] = closed_at.dt > row["due_at"].dt
    store.touch(row)
    return ok(serializers.mortality_review(row))
