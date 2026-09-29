"""The individualized overall plan of care (PRD §3.5)."""

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import enum_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import (DISCIPLINES, THREE_HOUR_MODES, active_plan, by_seq,
                      poc_signed_within_deadline, require, stamp_new, touch)
from util import Body, iso, serialize

bp = Blueprint("plans", __name__)


@bp.post("/plans-of-care")
def create_plan():
    user_id, _ = authenticate(("RehabPhysician",))
    body = Body(request.get_json(silent=True))

    admission_id = body.id_field("admission_id")
    expected_version = body.int_field("expected_admission_version", minimum=0)
    target_los_days = body.int_field("target_los_days", minimum=1, maximum=120)
    weekly_minutes_target = body.int_field("weekly_minutes_target", minimum=60, maximum=2400)
    disciplines = body.enum_list_field("disciplines", DISCIPLINES, min_len=1, max_len=3)
    mode = body.enum_field("three_hour_rule_mode", THREE_HOUR_MODES, required=False,
                           default="DAILY_3HR")

    # ladder rank 10 — body identifier existence
    admission = require(store.admissions, admission_id)

    # ladder rank 13 — the signing physician must belong to the admission's facility
    author = store.clinicians.get(user_id)
    if author is None or author["facility_id"] != admission["facility_id"]:
        raise ApiError("ERR_CROSS_FACILITY_MISMATCH")

    # ladder rank 15 — optimistic concurrency on the admission
    if expected_version != admission["version"]:
        raise ApiError("ERR_STALE_ADMISSION_VERSION")

    # ladder rank 17 — the stay must be active
    if admission["stay_status"] != "ADMITTED":
        raise ApiError("ERR_ADMISSION_NOT_ACTIVE")

    previous = active_plan(admission_id)

    plan = stamp_new({
        "admission_id": admission_id,
        "authored_by_clinician_id": user_id,
        "target_los_days": target_los_days,
        "weekly_minutes_target": weekly_minutes_target,
        "disciplines": list(disciplines),
        "three_hour_rule_mode": mode,
        "signed_at": iso(store.clock),
        "status": "ACTIVE",
    })
    store.plans[plan["id"]] = plan

    if previous is not None:
        previous["status"] = "SUPERSEDED"
        touch(previous)

    # the admission advances exactly once (PRD §3.5)
    if admission["documentation_status"] == "INCOMPLETE":
        admission["documentation_status"] = "POC_SIGNED"
    admission["poc_signed_within_deadline"] = poc_signed_within_deadline(admission)
    touch(admission)

    return envelope(serialize(plan), 201)


@bp.get("/plans-of-care/<plan_id>")
def get_plan(plan_id):
    authenticate(ALL_ROLES)
    plan = require(store.plans, plan_id)
    return envelope(serialize(plan), 200)


@bp.get("/plans-of-care")
def list_plans():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "admission_id": str_arg("admission_id"),
        "authored_by_clinician_id": str_arg("authored_by_clinician_id"),
        "status": enum_arg("status", ("ACTIVE", "SUPERSEDED")),
    }
    items = [p for p in by_seq(list(store.plans.values())) if matches(p, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(p) for p in page], 200, pagination)
