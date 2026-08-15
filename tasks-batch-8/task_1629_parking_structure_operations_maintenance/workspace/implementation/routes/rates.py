"""Rate schedule endpoints (PRD 3.2)."""
from flask import Blueprint, request

import db
from errors import err_invalid_state, err_stale_facility
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, require_int, optional_enum, require_datetime,
    parse_pagination, paginate, require_ref, optional_ref, get_schedule, public_view,
)

bp = Blueprint("rates", __name__)

CAP_MODES = {"CALENDAR_DAY", "ROLLING_24H"}


@bp.post("/ops/rate-schedules")
def create_schedule():
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    label = require_string(payload, "label")
    grace_minutes = require_int(payload, "grace_minutes", minimum=0)
    first_hour_cents = require_int(payload, "first_hour_cents", minimum=0)
    additional_hour_cents = require_int(payload, "additional_hour_cents", minimum=0)
    daily_max_cents = require_int(payload, "daily_max_cents", minimum=0, exclusive_min=True)
    event_flat_cents = require_int(payload, "event_flat_cents", minimum=0)
    lost_ticket_daily_cents = require_int(payload, "lost_ticket_daily_cents", minimum=0)
    effective_from = require_datetime(payload, "effective_from")
    cap_mode = optional_enum(payload, "cap_mode", CAP_MODES, default="CALENDAR_DAY")
    supersedes_ref = optional_ref(payload, db.rate_schedules, "supersedes_schedule_id")
    supersedes = supersedes_ref["id"] if supersedes_ref else None
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "label": label,
        "schedule_status": "DRAFT",
        "grace_minutes": grace_minutes,
        "first_hour_cents": first_hour_cents,
        "additional_hour_cents": additional_hour_cents,
        "daily_max_cents": daily_max_cents,
        "event_flat_cents": event_flat_cents,
        "lost_ticket_daily_cents": lost_ticket_daily_cents,
        "cap_mode": cap_mode,
        "effective_from": db.format_iso(effective_from),
        "supersedes_schedule_id": supersedes,
        "published_at": None,
    }
    db.stamp_new(ent)
    db.rate_schedules[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/rate-schedules/<rate_schedule_id>")
def get_schedule_route(rate_schedule_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_schedule(rate_schedule_id)))


@bp.get("/ops/rate-schedules")
def list_schedules():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.rate_schedules.values())
    facility_id = request.args.get("facility_id")
    schedule_status = request.args.get("schedule_status")
    supersedes = request.args.get("supersedes_schedule_id")
    if facility_id is not None:
        items = [s for s in items if s["facility_id"] == facility_id]
    if schedule_status is not None:
        items = [s for s in items if s["schedule_status"] == schedule_status]
    if supersedes is not None:
        items = [s for s in items if s.get("supersedes_schedule_id") == supersedes]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(s) for s in page], limit, offset, total)


@bp.post("/ops/rate-schedules/<rate_schedule_id>/publish")
def publish_schedule(rate_schedule_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    sched = get_schedule(rate_schedule_id)
    payload = body()
    expected = require_int(payload, "expected_facility_version")
    facility = db.facilities[sched["facility_id"]]
    # OCC (pipeline stage 8) precedes state legality (stage 9)
    if expected != facility["version"]:
        raise err_stale_facility()
    if sched["schedule_status"] != "DRAFT":
        raise err_invalid_state("only a DRAFT schedule may be published")
    for other in db.rate_schedules.values():
        if (other["facility_id"] == sched["facility_id"]
                and other["id"] != sched["id"]
                and other["schedule_status"] == "PUBLISHED"):
            other["schedule_status"] = "SUPERSEDED"
            db.touch(other)
    sched["schedule_status"] = "PUBLISHED"
    sched["published_at"] = db.now_iso()
    db.touch(sched)
    db.touch(facility)  # publish advances Facility.version by one
    return success_object(public_view(sched))


@bp.post("/ops/rate-schedules/<rate_schedule_id>/retire")
def retire_schedule(rate_schedule_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    sched = get_schedule(rate_schedule_id)
    if sched["schedule_status"] not in ("DRAFT", "PUBLISHED"):
        raise err_invalid_state("only a DRAFT or PUBLISHED schedule may be retired")
    sched["schedule_status"] = "RETIRED"
    db.touch(sched)
    return success_object(public_view(sched))
