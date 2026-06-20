"""Animal registration, retrieval/listing, life-status transitions, weights,
and the trace chain."""
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

bp = Blueprint("animals", __name__)

SEXES = {"MALE", "FEMALE", "STEER"}
WEIGHT_SOURCES = {"SCALE", "TAPE", "ESTIMATE"}
ALL_ROLES = {"HerdManager", "Veterinarian", "SaleClerk", "FeedlotOperator", "Auditor"}
ACTIVE_STATES = ("ACTIVE", "SUSPENDED")


def _check_pedigree(dam_id, sire_id):
    """ERR_INVALID_PEDIGREE if dam not FEMALE or sire not MALE. Assumes the
    referenced animals already passed the existence (404) check."""
    if dam_id is not None:
        dam = db.animals[dam_id]
        if dam["sex"] != "FEMALE":
            raise errors.ApiError(errors.ERR_INVALID_PEDIGREE, 422,
                                  "dam_animal_id must reference a FEMALE animal")
    if sire_id is not None:
        sire = db.animals[sire_id]
        if sire["sex"] != "MALE":
            raise errors.ApiError(errors.ERR_INVALID_PEDIGREE, 422,
                                  "sire_animal_id must reference a MALE animal")


# ---------------------------------------------------------------- create
@bp.route("/animals", methods=["POST"])
def create_animal():
    role = authenticate()
    require_role(role, {"HerdManager"})
    body = get_json_body()

    # existence of FK references first (left-to-right: herd, then dam, then sire)
    herd_id = as_str(body, "herd_id")
    get_or_404(db.herds, herd_id)
    dam_id = as_str(body, "dam_animal_id", required=False, default=None)
    if dam_id is not None:
        get_or_404(db.animals, dam_id)
    sire_id = as_str(body, "sire_animal_id", required=False, default=None)
    if sire_id is not None:
        get_or_404(db.animals, sire_id)

    # shape validation
    ear_tag = as_str(body, "ear_tag", min_len=1, max_len=32)
    rfid = as_str(body, "rfid", required=False, default=None)
    sex = as_enum(body, "sex", SEXES)
    birth_date = date_field(body, "birth_date")
    if birth_date > clock.today():
        raise errors.invalid_request("birth_date may not be after the current clock date")
    birth_weight = as_number(body, "birth_weight_kg", gt=0)

    # pedigree (priority 6)
    _check_pedigree(dam_id, sire_id)

    # duplicate identifiers (priority 7)
    for a in db.animals.values():
        if a["herd_id"] == herd_id and a["ear_tag"] == ear_tag:
            raise errors.ApiError(errors.ERR_DUPLICATE_IDENTIFIER, 409,
                                  "ear_tag must be unique within herd")
    if rfid is not None:
        for a in db.animals.values():
            if a.get("rfid") == rfid:
                raise errors.ApiError(errors.ERR_DUPLICATE_IDENTIFIER, 409,
                                      "rfid must be globally unique")

    rec = base_record()
    rec.update({
        "herd_id": herd_id,
        "ear_tag": ear_tag,
        "rfid": rfid,
        "sex": sex,
        "birth_date": birth_date,
        "birth_weight_kg": birth_weight,
        "dam_animal_id": dam_id,
        "sire_animal_id": sire_id,
        "current_pasture_id": None,
        "latest_weight_kg": birth_weight,
        "lifetime_adg_kg": 0.0,
        "life_status": "ACTIVE",
        "meat_clearance_status": "CLEAR",
        "meat_clear_on": None,
    })
    db.animals[rec["id"]] = rec

    # herd inventory: +1 count, + AU
    herd = db.herds[herd_id]
    domain.recompute_herd_loads(herd)
    touch(herd)

    # BIRTH trace event
    domain.append_trace(rec["id"], "BIRTH", "Animal", rec["id"], birth_date,
                        {"ear_tag": ear_tag, "herd_id": herd_id})

    return object_response(S.animal_out(rec), 201)


# ---------------------------------------------------------------- get / list
@bp.route("/animals/<aid>", methods=["GET"])
def get_animal(aid):
    role = authenticate()
    require_role(role, ALL_ROLES)
    a = get_or_404(db.animals, aid)
    return object_response(S.animal_out(a), 200)


@bp.route("/animals", methods=["GET"])
def list_animals():
    role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    herd_id = request.args.get("herd_id")
    dam_id = request.args.get("dam_animal_id")
    sire_id = request.args.get("sire_animal_id")
    pasture_id = request.args.get("current_pasture_id")

    items = list(db.animals.values())
    if herd_id is not None:
        items = [a for a in items if a["herd_id"] == herd_id]
    if dam_id is not None:
        items = [a for a in items if a.get("dam_animal_id") == dam_id]
    if sire_id is not None:
        items = [a for a in items if a.get("sire_animal_id") == sire_id]
    if pasture_id is not None:
        items = [a for a in items if a.get("current_pasture_id") == pasture_id]

    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.animal_out(a) for a in window], limit, offset, total)


# ---------------------------------------------------------------- life-status
@bp.route("/animals/<aid>/life-status", methods=["POST"])
def life_status(aid):
    role = authenticate()
    require_role(role, {"HerdManager"})
    a = get_or_404(db.animals, aid)
    body = get_json_body()
    to_status = as_enum(body, "to_status", {"SUSPENDED", "ACTIVE", "CULLED"})

    cur = a["life_status"]
    if to_status == "SUSPENDED":
        if cur != "ACTIVE":
            raise errors.invalid_state("Animal must be ACTIVE to suspend")
        a["life_status"] = "SUSPENDED"
        # active_animal_count deliberately unchanged (SUSPENDED counts as inventory)
        touch(a)
        domain.append_trace(a["id"], "SUSPEND", "Animal", a["id"], clock.today())
    elif to_status == "ACTIVE":
        if cur != "SUSPENDED":
            raise errors.invalid_state("Animal must be SUSPENDED to reinstate")
        a["life_status"] = "ACTIVE"
        touch(a)
        domain.append_trace(a["id"], "REINSTATE", "Animal", a["id"], clock.today())
    else:  # CULLED
        if cur != "ACTIVE":
            raise errors.invalid_state("Animal must be ACTIVE to cull")
        # residue safety gate (priority 8)
        if a["meat_clearance_status"] == "WITHHELD":
            raise errors.ApiError(errors.ERR_WITHDRAWAL_NOT_CLEARED, 409,
                                  "Cannot cull an animal under meat withdrawal")
        old_pasture = a.get("current_pasture_id")
        a["life_status"] = "CULLED"
        touch(a)
        herd = db.herds[a["herd_id"]]
        domain.recompute_herd_loads(herd)
        touch(herd)
        if old_pasture:
            domain.recompute_pasture_by_id(old_pasture)
        domain.append_trace(a["id"], "CULL", "Animal", a["id"], clock.today())

    return object_response(S.animal_out(a), 200)


# ---------------------------------------------------------------- weights
@bp.route("/animals/<aid>/weights", methods=["POST"])
def add_weight(aid):
    role = authenticate()
    require_role(role, {"HerdManager", "FeedlotOperator"})
    a = get_or_404(db.animals, aid)
    body = get_json_body()
    weighed_at = date_field(body, "weighed_at")
    weight_kg = as_number(body, "weight_kg", gt=0)
    source = as_enum(body, "source", WEIGHT_SOURCES, required=False, default="SCALE")

    # weighed_at strictly after birth_date and not in the future (priority 14)
    if not (weighed_at > a["birth_date"]) or weighed_at > clock.today():
        raise errors.ApiError(errors.ERR_WEIGH_DATE_INVALID, 422,
                              "weighed_at must be after birth_date and not in the future")

    rec = base_record(common_fields=False)  # WeightRecord: id + created_at only
    rec.update({
        "animal_id": aid,
        "weighed_at": weighed_at,
        "weight_kg": weight_kg,
        "source": source,
        "interval_adg_kg": None,
    })
    db.weight_records[rec["id"]] = rec
    rec["interval_adg_kg"] = domain.compute_interval_adg(aid, rec)

    # update animal derived weight fields (latest_weight_kg / lifetime_adg_kg)
    domain.recompute_animal_weight_derived(a)
    touch(a)

    # AU loads (herd + current pasture) shift with latest weight
    herd = db.herds[a["herd_id"]]
    domain.recompute_herd_loads(herd)
    touch(herd)
    if a.get("current_pasture_id"):
        domain.recompute_pasture_by_id(a["current_pasture_id"])

    return object_response(S.weight_record_out(rec), 201)


@bp.route("/animals/<aid>/weights", methods=["GET"])
def list_weights(aid):
    role = authenticate()
    require_role(role, {"HerdManager", "FeedlotOperator", "Veterinarian", "Auditor"})
    get_or_404(db.animals, aid)
    limit, offset = parse_pagination()
    items = [w for w in db.weight_records.values() if w["animal_id"] == aid]
    items.sort(key=lambda w: (w["created_at"], w["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.weight_record_out(w) for w in window], limit, offset, total)


# ---------------------------------------------------------------- trace
@bp.route("/animals/<aid>/trace", methods=["GET"])
def get_trace(aid):
    role = authenticate()
    require_role(role, ALL_ROLES)
    get_or_404(db.animals, aid)
    limit, offset = parse_pagination()
    items = [e for e in db.trace_events.values() if e["animal_id"] == aid]
    # ordered by occurred_on ASC then created_at ASC (PRD §3.12)
    items.sort(key=lambda e: (e["occurred_on"], e["created_at"], e["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.trace_event_out(e) for e in window], limit, offset, total)
