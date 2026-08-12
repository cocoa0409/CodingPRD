"""TrainingEvent endpoints (append-only)."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from middleware import authenticate, get_or_404, require_roles
from validation import (
    get_body,
    paginate,
    pagination_params,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("training_events", __name__)

ROLES = {"SystemAdmin", "ContractorOps", "HRRecruiter"}


def recompute_driver_aggregates(driver_id):
    driver = db.find("drivers", driver_id)
    if driver is None:
        return
    behind = 0
    classroom = 0
    for ev in db.all_of("training_events"):
        if ev["driver_id"] != driver_id:
            continue
        if ev["category"] == "BEHIND_WHEEL":
            behind += ev["minutes"]
        elif ev["category"] == "CLASSROOM":
            classroom += ev["minutes"]
    if driver["behind_wheel_minutes"] != behind or driver["classroom_minutes"] != classroom:
        driver["behind_wheel_minutes"] = behind
        driver["classroom_minutes"] = classroom
        db.touch(driver)


@bp.route("/busops/training-events", methods=["POST"])
def create_training_event():
    body = get_body()
    driver_id = req_str(body, "driver_id")
    category = req_enum(body, "category", ("CLASSROOM", "BEHIND_WHEEL", "SAFETY"))
    minutes = req_int(body, "minutes", minimum=1)
    occurred_on = req_date(body, "occurred_on")
    actor = authenticate()
    require_roles(actor, {"HRRecruiter"})
    get_or_404("drivers", driver_id, "Driver")

    rec = {
        "id": db.new_id(),
        "driver_id": driver_id,
        "category": category,
        "minutes": minutes,
        "occurred_on": occurred_on,
    }
    db.stamp_append_only(rec)
    db.STORES["training_events"][rec["id"]] = rec
    recompute_driver_aggregates(driver_id)
    return success_object(db.public(rec), status=201)


@bp.route("/busops/training-events", methods=["GET"])
def list_training_events():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, ROLES)
    items = list(db.all_of("training_events"))
    driver_id = request.args.get("driver_id")
    category = request.args.get("category")
    if driver_id is not None:
        items = [e for e in items if e["driver_id"] == driver_id]
    if category is not None:
        items = [e for e in items if e["category"] == category]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/training-events/<rid>", methods=["GET"])
def get_training_event(rid):
    actor = authenticate()
    require_roles(actor, ROLES)
    rec = get_or_404("training_events", rid, "TrainingEvent")
    return success_object(db.public(rec))
