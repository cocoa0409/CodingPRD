"""Breeding records: open, get/list, and the cyclic transition machine."""
from flask import Blueprint, request

import errors
from db import db
from clock import clock
from middleware import authenticate, require_role
from response import object_response, array_response
from util import (get_json_body, as_str, as_enum, as_number, date_field,
                  parse_pagination, paginate)
from services.common import base_record, get_or_404, touch
from services import serializers as S
from services import domain
from datetime import timedelta

bp = Blueprint("breeding", __name__)

SEXES = {"MALE", "FEMALE", "STEER"}
GESTATION_DAYS = domain.GESTATION_DAYS


# ---------------------------------------------------------------- create
@bp.route("/breeding-records", methods=["POST"])
def create_breeding():
    role = authenticate()
    require_role(role, {"HerdManager"})
    body = get_json_body()

    dam_id = as_str(body, "dam_animal_id")
    dam = get_or_404(db.animals, dam_id)
    sire_id = as_str(body, "sire_animal_id", required=False, default=None)
    if sire_id is not None:
        get_or_404(db.animals, sire_id)

    bred_on = date_field(body, "bred_on")
    if bred_on > clock.today():
        raise errors.invalid_request("bred_on may not be in the future")

    # pedigree: dam must be FEMALE and ACTIVE; sire (if any) MALE
    if dam["sex"] != "FEMALE":
        raise errors.ApiError(errors.ERR_INVALID_PEDIGREE, 422,
                              "dam_animal_id must reference a FEMALE animal")
    if sire_id is not None and db.animals[sire_id]["sex"] != "MALE":
        raise errors.ApiError(errors.ERR_INVALID_PEDIGREE, 422,
                              "sire_animal_id must reference a MALE animal")
    if dam["life_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_ANIMAL_NOT_ACTIVE, 409,
                              "dam must be ACTIVE to open a breeding record")

    rec = base_record()
    rec.update({
        "dam_animal_id": dam_id,
        "sire_animal_id": sire_id,
        "bred_on": bred_on,
        "expected_calving_on": None,
        "calved_on": None,
        "calf_animal_id": None,
        "status": "OPEN",
    })
    db.breeding_records[rec["id"]] = rec
    return object_response(S.breeding_record_out(rec), 201)


@bp.route("/breeding-records/<bid>", methods=["GET"])
def get_breeding(bid):
    role = authenticate()
    require_role(role, {"HerdManager", "Veterinarian", "Auditor"})
    b = get_or_404(db.breeding_records, bid)
    return object_response(S.breeding_record_out(b), 200)


@bp.route("/breeding-records", methods=["GET"])
def list_breeding():
    role = authenticate()
    require_role(role, {"HerdManager", "Veterinarian", "Auditor"})
    limit, offset = parse_pagination()
    dam_id = request.args.get("dam_animal_id")
    sire_id = request.args.get("sire_animal_id")
    calf_id = request.args.get("calf_animal_id")
    items = list(db.breeding_records.values())
    if dam_id is not None:
        items = [b for b in items if b["dam_animal_id"] == dam_id]
    if sire_id is not None:
        items = [b for b in items if b.get("sire_animal_id") == sire_id]
    if calf_id is not None:
        items = [b for b in items if b.get("calf_animal_id") == calf_id]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.breeding_record_out(b) for b in window], limit, offset, total)


# ---------------------------------------------------------------- transition
@bp.route("/breeding-records/<bid>/transition", methods=["POST"])
def transition_breeding(bid):
    role = authenticate()
    require_role(role, {"HerdManager", "Veterinarian"})
    b = get_or_404(db.breeding_records, bid)
    body = get_json_body()
    to_status = as_enum(body, "to_status",
                        {"BRED", "CONFIRMED_PREGNANT", "OPEN", "CALVED", "FAILED"})
    cur = b["status"]

    if to_status == "BRED":
        if cur != "OPEN":
            raise errors.invalid_state("transition to BRED only from OPEN")
        dam = db.animals[b["dam_animal_id"]]
        if dam["sex"] != "FEMALE" or dam["life_status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_INVALID_PEDIGREE, 422,
                                  "dam must be ACTIVE and FEMALE")
        if b["bred_on"] > clock.today():
            raise errors.invalid_request("bred_on may not be in the future")
        herd = db.herds[dam["herd_id"]]
        gest = GESTATION_DAYS[herd["species"]]
        b["expected_calving_on"] = b["bred_on"] + timedelta(days=gest)
        b["status"] = "BRED"
        touch(b)

    elif to_status == "CONFIRMED_PREGNANT":
        # Veterinarian only
        if role != "Veterinarian":
            raise errors.forbidden()
        if cur != "BRED":
            raise errors.invalid_state("transition to CONFIRMED_PREGNANT only from BRED")
        b["status"] = "CONFIRMED_PREGNANT"
        touch(b)

    elif to_status == "OPEN":
        if role != "HerdManager":
            raise errors.forbidden()
        if cur not in ("BRED", "CONFIRMED_PREGNANT"):
            raise errors.invalid_state("transition to OPEN only from BRED or CONFIRMED_PREGNANT")
        b["expected_calving_on"] = None
        b["status"] = "OPEN"
        touch(b)

    elif to_status == "FAILED":
        if role != "HerdManager":
            raise errors.forbidden()
        if cur not in ("OPEN", "BRED"):
            raise errors.invalid_state("transition to FAILED only from OPEN or BRED")
        b["status"] = "FAILED"
        touch(b)

    else:  # CALVED
        if role != "HerdManager":
            raise errors.forbidden()
        if cur != "CONFIRMED_PREGNANT":
            raise errors.invalid_state("transition to CALVED only from CONFIRMED_PREGNANT")
        calved_on = date_field(body, "calved_on")
        calf_ear_tag = as_str(body, "calf_ear_tag", min_len=1, max_len=32)
        calf_bw = as_number(body, "calf_birth_weight_kg", gt=0)
        calf_sex = as_enum(body, "calf_sex", SEXES)
        if not (calved_on >= b["bred_on"]) or calved_on > clock.today():
            raise errors.invalid_request("calved_on must be on/after bred_on and not in the future")

        dam = db.animals[b["dam_animal_id"]]
        herd = db.herds[dam["herd_id"]]

        # duplicate ear_tag within calf's herd
        for a in db.animals.values():
            if a["herd_id"] == herd["id"] and a["ear_tag"] == calf_ear_tag:
                raise errors.ApiError(errors.ERR_DUPLICATE_IDENTIFIER, 409,
                                      "calf ear_tag must be unique within herd")

        calf = base_record()
        calf.update({
            "herd_id": herd["id"],
            "ear_tag": calf_ear_tag,
            "rfid": None,
            "sex": calf_sex,
            "birth_date": calved_on,
            "birth_weight_kg": calf_bw,
            "dam_animal_id": dam["id"],
            "sire_animal_id": None,
            "current_pasture_id": None,
            "latest_weight_kg": calf_bw,
            "lifetime_adg_kg": 0.0,
            "life_status": "ACTIVE",
            "meat_clearance_status": "CLEAR",
            "meat_clear_on": None,
        })
        db.animals[calf["id"]] = calf

        b["calved_on"] = calved_on
        b["calf_animal_id"] = calf["id"]
        b["status"] = "CALVED"
        touch(b)

        domain.recompute_herd_loads(herd)
        touch(herd)
        domain.append_trace(calf["id"], "BIRTH", "Animal", calf["id"], calved_on,
                            {"ear_tag": calf_ear_tag, "dam_animal_id": dam["id"]})

    return object_response(S.breeding_record_out(b), 200)
