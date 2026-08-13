"""Treatment interruptions and compensation strategies (PRD 3.8)."""
from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INTERRUPTION_NOT_OPEN, ERR_COURSE_NOT_ON_TREATMENT,
                    ERR_NO_REMAINING_FRACTIONS)
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import interruption_json
from services import calc
from timeutil import new_id
from validate import req_enum, req_int, req_date

bp = Blueprint("interruptions", __name__)

REASONS = {"MACHINE_DOWN", "PATIENT_ILLNESS", "OTHER"}
STRATEGIES = {"ADD_FRACTIONS", "DOSE_PER_FRACTION_INCREASE", "WEEKEND_MAKEUP"}


def active_plan(course_id):
    for p in store.plans.values():
        if p["course_id"] == course_id and p["status"] == "ACTIVE":
            return p
    return None


@bp.post("/oncology/treatment-courses/<cid>/interruptions")
@require_roles("RadiationOncologist", "RadiationTherapist")
def create_interruption(cid, user_id):
    course = store.courses.get(cid)
    if course is None:
        err(ERR_NOT_FOUND, "treatment course not found")
    body = get_body()
    reason = req_enum(body, "reason", REASONS)
    missed = req_int(body, "missed_count", minimum=1)
    start_raw, start_d = req_date(body, "start_date")
    end_raw, end_d = req_date(body, "end_date")
    if end_d < start_d:
        err(ERR_INVALID_REQUEST, "end_date must be on or after start_date")
    intr = new_entity()
    intr.update({
        "id": new_id(), "course_id": cid, "reason": reason,
        "missed_count": missed, "start_date": start_raw, "end_date": end_raw,
        "gap_days": (end_d - start_d).days + 1,
        "applied_strategy": None, "status": "OPEN",
    })
    store.interruptions[intr["id"]] = intr
    course["open_interruption_count"] += 1
    touch(course)
    return success(interruption_json(intr), 201)


@bp.get("/oncology/treatment-courses/<cid>/interruptions")
@require_roles(*ALL_ROLES)
def list_interruptions(cid, user_id):
    if cid not in store.courses:
        err(ERR_NOT_FOUND, "treatment course not found")
    items = sorted_all(i for i in store.interruptions.values()
                       if i["course_id"] == cid)
    page, meta = paginate(items)
    return success([interruption_json(i) for i in page], 200, pagination=meta)


@bp.post("/oncology/interruptions/<iid>/compensate")
@require_roles("RadiationOncologist")
def compensate(iid, user_id):
    intr = store.interruptions.get(iid)
    if intr is None:
        err(ERR_NOT_FOUND, "interruption not found")
    body = get_body()
    strategy = req_enum(body, "strategy", STRATEGIES)
    if intr["status"] != "OPEN":
        err(ERR_INTERRUPTION_NOT_OPEN, "Compensate requires interruption OPEN")
    course = store.courses[intr["course_id"]]
    if course["status"] != "ON_TREATMENT":
        err(ERR_COURSE_NOT_ON_TREATMENT,
            "Compensation requires course ON_TREATMENT")
    plan = active_plan(course["id"])
    if strategy == "DOSE_PER_FRACTION_INCREASE":
        delivered_count = delivered_dose = 0
        if plan is not None:
            delivered_count, delivered_dose = calc.delivered_under_plan(plan["id"])
        remaining = (plan["planned_fractions"] - delivered_count) if plan else 0
        if remaining <= 0:
            err(ERR_NO_REMAINING_FRACTIONS,
                "No undelivered fractions remain on the ACTIVE plan")
        # rerun fraction_dose_allocation over the plan's remainder
        remaining_dose = plan["target_total_dose_cGy"] - delivered_dose
        new_base = calc.alloc_base(remaining_dose, remaining)
        plan["dose_per_fraction_cGy"] = new_base
        touch(plan)
        course["dose_per_fraction_cGy"] = new_base
    elif strategy == "ADD_FRACTIONS":
        course["planned_fractions"] += intr["missed_count"]
        if plan is not None:
            plan["planned_fractions"] += intr["missed_count"]
            touch(plan)
        # dose per fraction unchanged
    else:  # WEEKEND_MAKEUP
        course["weekend_makeup_allowance"] += intr["missed_count"]
    intr["applied_strategy"] = strategy
    intr["status"] = "COMPENSATED"
    touch(intr)
    course["open_interruption_count"] -= 1
    touch(course)
    return success(interruption_json(intr), 200)
