"""Compound formulation, qualification and suspension (PRD 3.2)."""

from flask import Blueprint

import clock
import constants as C
import errors
import lookups
import response
import validation
from auth import require_auth
from db import db, new_record, touch
from serializers import view
from services import cascades
from util import D

bp = Blueprint("compounds", __name__)


@bp.route("/compounds", methods=["POST"])
def create_compound():
    require_auth("ProcessEngineer", "PlantAdmin")
    b = validation.body()
    compound_code = validation.f_str(b, "compound_code")
    layer_role = validation.f_enum(b, "layer_role", C.LAYER_ROLES)
    temp_rating_c = validation.f_int(b, "temp_rating_c", choices=C.TEMP_RATINGS)
    flame_test = validation.f_enum(b, "flame_test", C.FLAME_TESTS)
    max_voltage_v = validation.f_int(b, "max_voltage_v", choices=C.MAX_VOLTAGES)
    wet_rated = validation.f_bool(b, "wet_rated", default=False)
    filler_pct = validation.f_num(b, "filler_pct", required=False, default=D("0"), ge=0, le=40)

    rec = new_record()
    rec.update({
        "compound_code": compound_code,
        "layer_role": layer_role,
        "temp_rating_c": temp_rating_c,
        "flame_test": flame_test,
        "max_voltage_v": max_voltage_v,
        "wet_rated": wet_rated,
        "filler_pct": filler_pct,
        "qualification_date": None,
        "suspension_reason": None,
        "status": "DRAFT",
    })
    db.compounds[rec["id"]] = rec
    return response.created(view("compound", rec))


@bp.route("/compounds/<compound_id>", methods=["GET"])
def get_compound(compound_id):
    require_auth("ProcessEngineer", "QualityEngineer", "CertificationOfficer", "PlantAdmin")
    rec = lookups.compound(compound_id)
    return response.ok(view("compound", rec))


@bp.route("/compounds/<compound_id>/qualify", methods=["POST"])
def qualify_compound(compound_id):
    require_auth("ProcessEngineer", "PlantAdmin")
    validation.body()
    rec = lookups.compound(compound_id)
    if rec["status"] not in ("DRAFT", "SUSPENDED"):
        errors.fail(
            errors.ERR_INVALID_COMPOUND_STATE,
            "A compound at %s may not be qualified" % rec["status"],
        )
    rec["qualification_date"] = clock.today_str()
    rec["suspension_reason"] = None
    rec["status"] = "QUALIFIED"
    touch(rec)
    return response.ok(view("compound", rec))


@bp.route("/compounds/<compound_id>/suspend", methods=["POST"])
def suspend_compound(compound_id):
    require_auth("ProcessEngineer", "QualityEngineer", "PlantAdmin")
    b = validation.body()
    reason = validation.f_str(b, "suspension_reason")
    rec = lookups.compound(compound_id)
    if rec["status"] != "QUALIFIED":
        errors.fail(
            errors.ERR_INVALID_COMPOUND_STATE,
            "Only a QUALIFIED compound may be suspended (this one is %s)" % rec["status"],
        )
    rec["suspension_reason"] = reason
    rec["status"] = "SUSPENDED"
    touch(rec)
    cascades.compound_suspended(rec)
    return response.ok(view("compound", rec))
