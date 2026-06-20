"""Mortality records: record (cascade -> DEAD), get/list, void (-> ACTIVE)."""
from flask import Blueprint, request

import errors
from db import db
from clock import clock
from middleware import authenticate, require_role
from response import object_response, array_response
from util import (get_json_body, as_str, as_enum, date_field,
                  parse_pagination, paginate)
from services.common import base_record, get_or_404, touch
from services import serializers as S
from services import domain

bp = Blueprint("mortality", __name__)

CAUSES = {"DISEASE", "PREDATION", "ACCIDENT", "CALVING", "UNKNOWN"}
DISPOSALS = {"RENDERING", "BURIAL", "INCINERATION", "COMPOST"}
ACTIVE_STATES = ("ACTIVE", "SUSPENDED")


@bp.route("/mortality-records", methods=["POST"])
def create_mortality():
    role = authenticate()
    require_role(role, {"HerdManager"})
    body = get_json_body()

    animal_id = as_str(body, "animal_id")
    animal = get_or_404(db.animals, animal_id)
    died_on = date_field(body, "died_on")
    cause = as_enum(body, "cause", CAUSES)
    disposal = as_enum(body, "disposal_method", DISPOSALS, required=False, default="RENDERING")

    # date constraint: not future and on/after birth_date
    if died_on > clock.today() or died_on < animal["birth_date"]:
        raise errors.invalid_request("died_on must be on/after birth_date and not in the future")

    # animal must be ACTIVE or SUSPENDED
    if animal["life_status"] not in ACTIVE_STATES:
        raise errors.ApiError(errors.ERR_ANIMAL_NOT_ACTIVE, 409,
                              "animal must be ACTIVE or SUSPENDED to record a death")

    rec = base_record()
    rec.update({
        "animal_id": animal_id,
        "died_on": died_on,
        "cause": cause,
        "disposal_method": disposal,
        "status": "RECORDED",
    })
    db.mortality_records[rec["id"]] = rec

    # cascade animal -> DEAD
    old_pasture = animal.get("current_pasture_id")
    animal["life_status"] = "DEAD"
    touch(animal)
    herd = db.herds[animal["herd_id"]]
    domain.recompute_herd_loads(herd)
    if old_pasture:
        domain.recompute_pasture_by_id(old_pasture)
    domain.recompute_mortality_rate(herd)
    touch(herd)

    domain.append_trace(animal_id, "MORTALITY", "MortalityRecord", rec["id"], died_on,
                        {"cause": cause, "disposal_method": disposal})

    return object_response(S.mortality_record_out(rec), 201)


@bp.route("/mortality-records/<mid>", methods=["GET"])
def get_mortality(mid):
    role = authenticate()
    require_role(role, {"HerdManager", "Veterinarian", "Auditor"})
    m = get_or_404(db.mortality_records, mid)
    return object_response(S.mortality_record_out(m), 200)


@bp.route("/mortality-records", methods=["GET"])
def list_mortality():
    role = authenticate()
    require_role(role, {"HerdManager", "Veterinarian", "Auditor"})
    limit, offset = parse_pagination()
    animal_id = request.args.get("animal_id")
    items = list(db.mortality_records.values())
    if animal_id is not None:
        items = [m for m in items if m["animal_id"] == animal_id]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.mortality_record_out(m) for m in window], limit, offset, total)


@bp.route("/mortality-records/<mid>/void", methods=["POST"])
def void_mortality(mid):
    role = authenticate()
    require_role(role, {"HerdManager"})
    m = get_or_404(db.mortality_records, mid)

    if m["status"] != "RECORDED":
        raise errors.invalid_state("only RECORDED mortality records may be voided")

    animal = db.animals.get(m["animal_id"])
    # require the animal to be DEAD (cascade pre-state)
    if animal is None or animal["life_status"] != "DEAD":
        raise errors.invalid_state("the animal is not DEAD")

    m["status"] = "VOIDED"
    touch(m)

    # cascade: reactivate animal -> ACTIVE
    animal["life_status"] = "ACTIVE"
    touch(animal)
    herd = db.herds[animal["herd_id"]]
    domain.recompute_herd_loads(herd)
    if animal.get("current_pasture_id"):
        domain.recompute_pasture_by_id(animal["current_pasture_id"])
    domain.recompute_mortality_rate(herd)
    touch(herd)

    domain.append_trace(animal["id"], "REINSTATE", "MortalityRecord", m["id"],
                        clock.today())

    return object_response(S.mortality_record_out(m), 200)
