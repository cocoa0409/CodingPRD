"""Movement records: plan, get/list, apply (OCC + rest + capacity), revert."""
from flask import Blueprint, request
from datetime import timedelta

import errors
from db import db
from clock import clock
from middleware import authenticate, require_role
from response import object_response, array_response
from util import (get_json_body, as_str, as_int, datetime_field,
                  parse_pagination, paginate)
from services.common import base_record, get_or_404, touch
from services import serializers as S
from services import domain

bp = Blueprint("movements", __name__)

ACTIVE_STATES = ("ACTIVE", "SUSPENDED")


@bp.route("/movement-records", methods=["POST"])
def plan_movement():
    role = authenticate()
    require_role(role, {"HerdManager"})
    body = get_json_body()

    animal_id = as_str(body, "animal_id")
    get_or_404(db.animals, animal_id)
    to_pasture_id = as_str(body, "to_pasture_id")
    get_or_404(db.pastures, to_pasture_id)

    effective_from = datetime_field(body, "effective_from")
    if effective_from > clock.now():
        raise errors.invalid_request("effective_from may not be in the future")
    effective_to = datetime_field(body, "effective_to", required=False, default=None)
    if effective_to is not None and not (effective_to > effective_from):
        raise errors.invalid_request("effective_to must be strictly after effective_from")

    rec = base_record()
    rec.update({
        "animal_id": animal_id,
        "to_pasture_id": to_pasture_id,
        "from_pasture_id": None,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "PLANNED",
    })
    db.movement_records[rec["id"]] = rec
    return object_response(S.movement_record_out(rec), 201)


@bp.route("/movement-records/<mid>", methods=["GET"])
def get_movement(mid):
    role = authenticate()
    require_role(role, {"HerdManager", "Auditor"})
    m = get_or_404(db.movement_records, mid)
    return object_response(S.movement_record_out(m), 200)


@bp.route("/movement-records", methods=["GET"])
def list_movements():
    role = authenticate()
    require_role(role, {"HerdManager", "Auditor"})
    limit, offset = parse_pagination()
    animal_id = request.args.get("animal_id")
    to_pasture_id = request.args.get("to_pasture_id")
    from_pasture_id = request.args.get("from_pasture_id")
    items = list(db.movement_records.values())
    if animal_id is not None:
        items = [m for m in items if m["animal_id"] == animal_id]
    if to_pasture_id is not None:
        items = [m for m in items if m["to_pasture_id"] == to_pasture_id]
    if from_pasture_id is not None:
        items = [m for m in items if m.get("from_pasture_id") == from_pasture_id]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.movement_record_out(m) for m in window], limit, offset, total)


def _overlaps(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap. None to means open-ended (+inf)."""
    if a_to is None:
        a_to_inf = True
    else:
        a_to_inf = False
    if b_to is None:
        b_to_inf = True
    else:
        b_to_inf = False
    # a starts before b ends  AND  b starts before a ends
    cond1 = b_to_inf or (a_from < b_to)
    cond2 = a_to_inf or (b_from < a_to)
    return cond1 and cond2


@bp.route("/movement-records/<mid>/apply", methods=["POST"])
def apply_movement(mid):
    role = authenticate()
    require_role(role, {"HerdManager"})
    m = get_or_404(db.movement_records, mid)
    body = get_json_body()

    # request shape (priority 4): expected_animal_version required
    expected_version = as_int(body, "expected_animal_version", required=True)

    animal = db.animals.get(m["animal_id"])
    if animal is None:
        raise errors.not_found("animal not found")

    # state (priority 5): movement must be PLANNED
    if m["status"] != "PLANNED":
        raise errors.invalid_state("only PLANNED movements may be applied")

    # animal life_status gate
    if animal["life_status"] not in ACTIVE_STATES:
        raise errors.ApiError(errors.ERR_ANIMAL_NOT_ACTIVE, 409,
                              "animal must be ACTIVE or SUSPENDED to apply a movement")

    dest = db.pastures.get(m["to_pasture_id"])
    if dest is None:
        raise errors.not_found("destination pasture not found")

    # rest period (priority 11) — PASTURE kind only
    if dest["kind"] == "PASTURE" and dest["rest_days"] and dest["rest_days"] > 0:
        gap = timedelta(days=dest["rest_days"])
        for other in db.movement_records.values():
            if other["id"] == m["id"]:
                continue
            if other["status"] != "APPLIED":
                continue
            if other["to_pasture_id"] != dest["id"]:
                continue
            prior_to = other.get("effective_to")
            if prior_to is None:
                # open-ended prior occupancy: any later start violates the rest gap
                if m["effective_from"] < (other["effective_from"] + gap):
                    raise errors.ApiError(errors.ERR_REST_PERIOD_VIOLATION, 409,
                                          "rest period not satisfied")
                continue
            # new occupancy must start at least rest_days after the prior end
            if prior_to <= m["effective_from"] and m["effective_from"] < (prior_to + gap):
                raise errors.ApiError(errors.ERR_REST_PERIOD_VIOLATION, 409,
                                      "rest period not satisfied")

    # capacity gate (priority 12) — unrounded projected aggregate over overlap window
    mover_au = domain.animal_au(animal)
    projected = mover_au
    for other in db.movement_records.values():
        if other["id"] == m["id"]:
            continue
        if other["status"] != "APPLIED":
            continue
        if other["to_pasture_id"] != dest["id"]:
            continue
        occ_animal = db.animals.get(other["animal_id"])
        if occ_animal is None or occ_animal["life_status"] not in ACTIVE_STATES:
            continue
        # only animals still located at dest (not subsequently moved away)
        if occ_animal.get("current_pasture_id") != dest["id"]:
            continue
        if _overlaps(m["effective_from"], m["effective_to"],
                     other["effective_from"], other.get("effective_to")):
            projected += domain.animal_au(occ_animal)
    if projected > dest["capacity_au"]:
        raise errors.ApiError(errors.ERR_PASTURE_OVER_CAPACITY, 409,
                              "destination pasture over capacity")

    # OCC (priority 16): expected_animal_version must equal current animal version
    if expected_version != animal["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "animal version is stale")

    # ---- apply ----
    from_pasture_id = animal.get("current_pasture_id")
    m["from_pasture_id"] = from_pasture_id
    m["status"] = "APPLIED"
    touch(m)

    animal["current_pasture_id"] = m["to_pasture_id"]
    touch(animal)  # bumps Animal.version by 1

    if from_pasture_id:
        domain.recompute_pasture_by_id(from_pasture_id)
    domain.recompute_pasture_by_id(m["to_pasture_id"])

    domain.append_trace(animal["id"], "MOVEMENT", "MovementRecord", m["id"],
                        m["effective_from"].date(),
                        {"from_pasture_id": from_pasture_id,
                         "to_pasture_id": m["to_pasture_id"]})

    return object_response(S.movement_record_out(m), 200)


@bp.route("/movement-records/<mid>/revert", methods=["POST"])
def revert_movement(mid):
    role = authenticate()
    require_role(role, {"HerdManager"})
    m = get_or_404(db.movement_records, mid)

    if m["status"] != "APPLIED":
        raise errors.invalid_state("only APPLIED movements may be reverted")

    # must be the animal's most recently APPLIED movement (priority 18)
    for other in db.movement_records.values():
        if other["id"] == m["id"]:
            continue
        if other["animal_id"] != m["animal_id"]:
            continue
        if other["status"] != "APPLIED":
            continue
        if (other["_seq"]) > (m["_seq"]):
            raise errors.ApiError(errors.ERR_NOT_LATEST_MOVEMENT, 409,
                                  "not the animal's most recent applied movement")

    animal = db.animals.get(m["animal_id"])
    to_pasture_id = m["to_pasture_id"]
    from_pasture_id = m.get("from_pasture_id")

    m["status"] = "REVERTED"
    touch(m)

    if animal is not None:
        animal["current_pasture_id"] = from_pasture_id
        touch(animal)

    domain.recompute_pasture_by_id(to_pasture_id)
    if from_pasture_id:
        domain.recompute_pasture_by_id(from_pasture_id)

    return object_response(S.movement_record_out(m), 200)
