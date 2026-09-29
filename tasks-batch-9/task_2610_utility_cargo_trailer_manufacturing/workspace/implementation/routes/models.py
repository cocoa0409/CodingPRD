"""Trailer model configuration and the GVWR certification loop (PRD 3.1)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import db, new_id, now_iso, clock_now, public, stamp_new, touch
from middleware import ALL_ROLES, actor, endpoint
from response import created, ok
from services import calc, rollups

bp = Blueprint("models", __name__)

DECISIONS = ("CERTIFIED", "REVISION_REQUESTED", "WITHDRAWN")


@bp.route("/trailer-models", methods=["POST"])
@endpoint(["PlantEngineer"])
def create_model():
    data = v.body()
    model_code = v.req_code(data, "model_code", 4, 16)
    description = v.req_str(data, "description")
    axle_count = v.req_int(data, "axle_count", 1, 3)
    axle_rating_lbs = v.req_int(data, "axle_rating_lbs", 1)
    design_braked = v.req_int(data, "design_braked_axle_count", 0)
    if design_braked > axle_count:
        raise errors.invalid("design_braked_axle_count may not exceed axle_count")
    tire_load_rating_lbs = v.req_int(data, "tire_load_rating_lbs", 1)
    frame_design_code = v.req_str(data, "frame_design_code", 2, 2, v.FRAME_RE)
    frame_design_rated_lbs = v.req_int(data, "frame_design_rated_lbs", 1)
    coupler_rating_lbs = v.req_int(data, "coupler_rating_lbs", 1)
    overall_width_in = v.req_num(data, "overall_width_in")
    if overall_width_in <= 0:
        raise errors.invalid("overall_width_in must be > 0")
    nominal_length_mm = v.req_int(data, "nominal_length_mm", 1)
    nominal_width_mm = v.req_int(data, "nominal_width_mm", 1)
    base_curb_weight_lbs = v.req_int(data, "base_curb_weight_lbs", 1)
    base_dealer_price_cents = v.req_int(data, "base_dealer_price_cents", 1)

    lookups.unique_or_409(db.models, "model_code", model_code)

    row = {
        "id": new_id(),
        "model_code": model_code,
        "description": description,
        "axle_count": axle_count,
        "axle_rating_lbs": axle_rating_lbs,
        "design_braked_axle_count": design_braked,
        "tire_load_rating_lbs": tire_load_rating_lbs,
        "frame_design_code": frame_design_code,
        "frame_design_rated_lbs": frame_design_rated_lbs,
        "coupler_rating_lbs": coupler_rating_lbs,
        "overall_width_in": calc.num(overall_width_in),
        "nominal_length_mm": nominal_length_mm,
        "nominal_width_mm": nominal_width_mm,
        "base_curb_weight_lbs": base_curb_weight_lbs,
        "base_dealer_price_cents": base_dealer_price_cents,
        "provisional_gvwr_lbs": None,
        "certified_gvwr_lbs": None,
        "certification_status": "DRAFT",
        "revision_round": 0,
        "certified_by_user_id": None,
        "certified_at": None,
        "active_unit_count": 0,
    }
    stamp_new(row)
    db.models[row["id"]] = row
    return created(public(row))


@bp.route("/trailer-models/<model_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_model(model_id):
    return ok(public(lookups.model_or_404(model_id)))


@bp.route("/trailer-models/<model_id>/certification-submission", methods=["POST"])
@endpoint(["PlantEngineer"])
def submit_model(model_id):
    model = lookups.model_or_404(model_id)
    data = v.body()
    v.req_str(data, "engineering_note")
    if model["certification_status"] not in ("DRAFT", "CERTIFIED"):
        raise errors.ApiError("ERR_MODEL_STATE_INVALID", 409,
                              "A model in %s may not be submitted for certification review"
                              % model["certification_status"])
    model["provisional_gvwr_lbs"] = calc.provisional_gvwr(model)
    model["certification_status"] = "IN_ENGINEERING_REVIEW"
    touch(model)
    return ok(public(model))


def _release_reservation(reservation, jigs_touched):
    if reservation["status"] != "RESERVED":
        return
    reservation["status"] = "RELEASED"
    touch(reservation)
    jigs_touched.add(reservation["jig_id"])


def _units_sorted(model_id):
    units = rollups.units_of_model(model_id)
    units.sort(key=lambda u: u["_seq"])
    return units


@bp.route("/trailer-models/<model_id>/certification-decision", methods=["POST"])
@endpoint(["CertificationOfficer"])
def decide_model(model_id):
    model = lookups.model_or_404(model_id)
    data = v.body()
    decision = v.req_enum(data, "decision", DECISIONS)
    v.req_str(data, "decision_note")
    if model["certification_status"] != "IN_ENGINEERING_REVIEW":
        raise errors.ApiError("ERR_MODEL_STATE_INVALID", 409,
                              "A model in %s may not receive a certification decision"
                              % model["certification_status"])

    jigs_touched = set()
    if decision == "CERTIFIED":
        model["certified_gvwr_lbs"] = calc.certified_gvwr(model)
        model["certified_by_user_id"] = actor()
        model["certified_at"] = now_iso()
        model["certification_status"] = "CERTIFIED"
        for unit in _units_sorted(model_id):
            if unit["build_status"] == "BUILD_HOLD":
                unit["build_status"] = "PLANNED"
                touch(unit)
    elif decision == "REVISION_REQUESTED":
        model["certification_status"] = "DRAFT"
        model["revision_round"] = model["revision_round"] + 1
        for unit in _units_sorted(model_id):
            if unit["build_status"] in ("PLANNED", "JIG_RESERVED", "FRAME_REWORK"):
                unit["build_status"] = "BUILD_HOLD"
                touch(unit)
                for res in rollups.reservations_of_unit(unit["id"]):
                    _release_reservation(res, jigs_touched)
    else:
        model["certification_status"] = "WITHDRAWN"
        for unit in _units_sorted(model_id):
            if unit["build_status"] in ("PLANNED", "BUILD_HOLD"):
                unit["build_status"] = "SCRAPPED"
                touch(unit)
                for res in rollups.reservations_of_unit(unit["id"]):
                    _release_reservation(res, jigs_touched)

    for jig_id in sorted(jigs_touched):
        rollups.recompute_jig_minutes(db.jigs.get(jig_id))
    rollups.recompute_model_active_unit_count(model)
    touch(model)
    return ok(public(model))
