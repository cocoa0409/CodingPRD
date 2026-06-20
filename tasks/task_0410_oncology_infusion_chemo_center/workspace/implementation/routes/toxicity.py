"""ToxicityEvent endpoints with automatic high-grade cycle hold."""
from flask import Blueprint, request

import errors
from db import db
from errors import err
from middleware import get_auth, require_roles
from response import success, list_success
from services import place_on_hold
from store_helpers import (
    make_common, public, sort_by_created,
    get_toxicity_event, get_cycle, get_drug_order,
)
from validation import (
    get_body, require_str, require_int,
    get_pagination, paginate,
)

bp = Blueprint("toxicity", __name__)

ALL_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}


@bp.route("/toxicity-events", methods=["POST"])
def create_toxicity_event():
    _, role = get_auth()
    require_roles(role, {"Nurse", "Pharmacist"})
    body = get_body()
    # Existence: cycle, then optional drug_order, left-to-right.
    cycle_id = require_str(body, "treatment_cycle_id")
    cycle = get_cycle(cycle_id)
    drug_order_id = body.get("drug_order_id")
    if drug_order_id is not None:
        if not isinstance(drug_order_id, str):
            raise err(errors.ERR_INVALID_REQUEST, "drug_order_id must be a string")
        get_drug_order(drug_order_id)

    # Body well-formedness: ctcae_grade 1..5, description present.
    ctcae_grade = require_int(body, "ctcae_grade", ge=1, le=5)
    description = require_str(body, "description")

    with db.lock:
        entity = make_common()
        triggered_hold = False
        # Grade >= 3 on an ACTIVE cycle auto-places it ON_HOLD with the two-step cascade.
        if ctcae_grade >= 3 and cycle["status"] == "ACTIVE":
            place_on_hold(cycle)
            triggered_hold = True
        entity.update({
            "treatment_cycle_id": cycle_id,
            "drug_order_id": drug_order_id,
            "ctcae_grade": ctcae_grade,
            "description": description,
            "triggered_hold": triggered_hold,
        })
        db.toxicity_events[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/toxicity-events", methods=["GET"])
def list_toxicity_events():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    cycle_id = request.args.get("treatment_cycle_id")
    drug_order_id = request.args.get("drug_order_id")
    items = []
    for ev in db.toxicity_events.values():
        if cycle_id is not None and ev["treatment_cycle_id"] != cycle_id:
            continue
        if drug_order_id is not None and ev.get("drug_order_id") != drug_order_id:
            continue
        items.append(ev)
    items = sort_by_created(items)
    total = len(items)
    window = [public(ev) for ev in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/toxicity-events/<eid>", methods=["GET"])
def get_one_toxicity_event(eid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_toxicity_event(eid)
    return success(public(entity), status=200)
