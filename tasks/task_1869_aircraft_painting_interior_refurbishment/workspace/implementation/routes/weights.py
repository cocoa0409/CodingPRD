"""WeightBalanceRecord endpoints (provisional/final variants, SoD sign-off)."""
from flask import Blueprint, request

import calc
from db import STORE
from domain import (new_entity, bump, get_or_404, by_created,
                    serialize_weight_record)
from errors import (ApiError, ref_integrity, invalid_state,
                    ERR_WEIGHT_DELTA_EXCEEDED, ERR_SEGREGATION_OF_DUTIES)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("weights", __name__)

VARIANTS = ("PROVISIONAL", "FINAL")


@bp.post("/weight-balance-records")
def create_weight_record():
    user_id, _ = auth("ShopTechnician")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    scheme_id = field(data, "scheme_id", "str")
    variant = field(data, "variant", "str", enum=VARIANTS)
    removal_weight_lbs = field(data, "removal_weight_lbs", "num")
    installed_weight_lbs = field(data, "installed_weight_lbs", "num")
    prog = STORE.programs.get(program_id)
    if prog is None:
        raise ref_integrity("program_id does not reference an existing program")
    if prog["status"] in ("DELIVERED", "CANCELLED"):
        raise invalid_state("Cannot prepare a weight record for a terminal program")
    scheme = STORE.paint_schemes.get(scheme_id)
    if scheme is None or prog["approved_scheme_id"] != scheme_id:
        raise ref_integrity(
            "scheme_id must equal the program's currently approved scheme")
    film = calc.compute_film_lbs(scheme, variant, calc.current_decision(program_id))
    delta = calc.compute_delta_lbs(removal_weight_lbs, installed_weight_lbs, film)
    rec = new_entity()
    rec.update({
        "program_id": program_id,
        "scheme_id": scheme_id,
        "variant": variant,
        "removal_weight_lbs": removal_weight_lbs,
        "installed_weight_lbs": installed_weight_lbs,
        "film_lbs": float(film),
        "delta_lbs": float(delta),
        "status": "PREPARED",
        "prepared_by_user_id": user_id,
    })
    STORE.weight_records[rec["id"]] = rec
    return success(serialize_weight_record(rec), status=201)


@bp.get("/weight-balance-records/<wid>")
def get_weight_record(wid):
    auth()
    rec = get_or_404(STORE.weight_records, wid, "WeightBalanceRecord")
    return success(serialize_weight_record(rec))


@bp.get("/weight-balance-records")
def list_weight_records():
    auth()
    items = by_created(list(STORE.weight_records.values()))
    for key in ("program_id", "scheme_id", "variant", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [w for w in items if w[key] == value]
    return paginate(items, serialize_weight_record)


@bp.post("/weight-balance-records/<wid>/sign-off")
def sign_off_weight_record(wid):
    user_id, _ = auth("QualityInspector")
    rec = get_or_404(STORE.weight_records, wid, "WeightBalanceRecord")
    if rec["status"] != "PREPARED":
        raise invalid_state("Only a PREPARED weight record can be signed off")
    # PRD §3.9: segregation of duties first, then the weight gate.
    if user_id == rec["prepared_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The signer must differ from the record's preparer")
    prog = STORE.programs[rec["program_id"]]
    aircraft = STORE.aircraft.get(prog["aircraft_id"])
    max_delta = aircraft["max_delta_lbs"] if aircraft else 0
    if abs(rec["delta_lbs"]) > max_delta:
        acked = any(co["kind"] == "WEIGHT_ACK" and co["status"] == "APPROVED"
                    and co["acknowledges_weight_record_id"] == rec["id"]
                    for co in calc.change_orders_of(prog["id"]))
        if not acked:
            raise ApiError(ERR_WEIGHT_DELTA_EXCEEDED, 409,
                           "|delta_lbs| exceeds aircraft.max_delta_lbs and no "
                           "APPROVED WEIGHT_ACK change order acknowledges it")
    # Compensating pair: at most one SIGNED_OFF record per (program, variant).
    for other in STORE.weight_records.values():
        if (other["program_id"] == rec["program_id"]
                and other["variant"] == rec["variant"]
                and other["status"] == "SIGNED_OFF"
                and other["id"] != rec["id"]):
            other["status"] = "SUPERSEDED"
            bump(other)
    rec["status"] = "SIGNED_OFF"
    bump(rec)
    return success(serialize_weight_record(rec))
