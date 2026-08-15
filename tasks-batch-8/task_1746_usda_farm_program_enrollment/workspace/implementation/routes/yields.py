"""Yield record and observation endpoints (PRD §3.5)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_YIELD_UPDATE_WINDOW_CLOSED, invalid_request, invalid_state,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.aph import compute_aph
from services.helpers import (
    get_farm_or_404, get_yield_record_or_404, active_membership,
)
from validation import body, require_string, require_int, optional_decimal

bp = Blueprint("yields", __name__)


@bp.post("/fsa/farms/<farm_id>/yield-records")
def create_yield_record(farm_id):
    require_roles(["CountySpecialist"])
    get_farm_or_404(farm_id)
    data = body()
    commodity = require_string(data, "commodity")

    record = db.common_fields()
    record.update({
        "farm_id": farm_id,
        "commodity": commodity,
        "aph_yield_bu_per_acre": 0.0,
        "yield_status": "PROVISIONAL",
        "update_window_open": True,
    })
    db.yield_records[record["id"]] = record
    compute_aph(record)
    return success_object(record, 201)


@bp.get("/fsa/yield-records/<record_id>")
def get_yield_record(record_id):
    require_roles(ALL_ROLES)
    return success_object(get_yield_record_or_404(record_id))


@bp.get("/fsa/yield-records/<record_id>/enrollments")
def list_record_enrollments(record_id):
    require_roles(ALL_ROLES)
    get_yield_record_or_404(record_id)
    items = [
        e for e in db.enrollments.values()
        if e.get("pinned_yield_record_id") == record_id
    ]
    items.sort(key=lambda e: e["created_at"])
    return paginate(items, request.args)


@bp.get("/fsa/farms/<farm_id>/yield-records")
def list_farm_yield_records(farm_id):
    require_roles(ALL_ROLES)
    get_farm_or_404(farm_id)
    commodity = request.args.get("commodity")
    items = [y for y in db.yield_records.values() if y["farm_id"] == farm_id]
    if commodity is not None:
        items = [y for y in items if y["commodity"] == commodity]
    items.sort(key=lambda y: y["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/yield-records/<record_id>/observations")
def add_observation(record_id):
    require_roles(["CountySpecialist"])
    record = get_yield_record_or_404(record_id)
    if record["yield_status"] == "LOCKED":
        raise invalid_state("YieldRecord is LOCKED and immutable")
    data = body()
    crop_year = require_int(data, "crop_year")
    actual = optional_decimal(data, "actual_yield_bu_per_acre", None)

    obs = db.observation_fields()
    obs.update({
        "yield_record_id": record_id,
        "crop_year": crop_year,
        "actual_yield_bu_per_acre": float(actual) if actual is not None else None,
        "is_disaster_substituted": False,
    })
    db.yield_observations[obs["id"]] = obs
    # APH recomputes on each observation append (PRD §3.5).
    compute_aph(record)
    db.touch(record)
    return success_object(obs, 201)


@bp.get("/fsa/yield-records/<record_id>/observations")
def list_observations(record_id):
    require_roles(ALL_ROLES)
    get_yield_record_or_404(record_id)
    items = [
        o for o in db.yield_observations.values()
        if o["yield_record_id"] == record_id
    ]
    items.sort(key=lambda o: o["crop_year"])
    return paginate(items, request.args)


@bp.post("/fsa/yield-records/<record_id>/updates")
def trigger_update(record_id):
    user_id, _ = require_roles(["Producer"])
    record = get_yield_record_or_404(record_id)
    if record["yield_status"] not in ("PROVISIONAL", "CERTIFIED", "UPDATED"):
        raise invalid_state("YieldRecord cannot be updated from its current state")
    # One-time update window (priority 19). PRD §3.5: once the window has
    # been consumed, any further update attempt is rejected with
    # ERR_YIELD_UPDATE_WINDOW_CLOSED.
    if not record["update_window_open"]:
        raise ApiError(
            ERR_YIELD_UPDATE_WINDOW_CLOSED,
            "APH one-time update window already consumed",
            422,
        )
    if record["yield_status"] == "UPDATED":
        raise invalid_state("YieldRecord already UPDATED")
    if active_membership(record["farm_id"], user_id) is None:
        raise invalid_request("Producer does not hold an ACTIVE membership on this farm")

    compute_aph(record)
    record["yield_status"] = "UPDATED"
    record["update_window_open"] = False
    db.touch(record)
    return success_object(record)


@bp.post("/fsa/yield-records/<record_id>/certify")
def certify_yield_record(record_id):
    require_roles(["CountySpecialist"])
    record = get_yield_record_or_404(record_id)
    if record["yield_status"] != "UPDATED":
        raise invalid_state("YieldRecord is not UPDATED")
    record["yield_status"] = "CERTIFIED"
    db.touch(record)
    return success_object(record)
