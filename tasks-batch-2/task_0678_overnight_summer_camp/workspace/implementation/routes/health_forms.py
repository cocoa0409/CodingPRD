"""Health forms and the infirmary review loop. PRD §3.3, §2.10."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize, recompute
from services.store import base_fields, require, touch, paginate, guardian_owns_camper

bp = Blueprint("health_forms", __name__)


def _camper_owner_chain(form):
    return db.campers.get(form["camper_id"])


@bp.route("/health-forms", methods=["POST"])
def create_health_form():
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    body = get_json_body()

    if "camper_id" not in body or not isinstance(body.get("camper_id"), str):
        raise validate.bad_request("camper_id is required.")
    camper = db.campers.get(body["camper_id"])
    if camper is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Camper not found.")
    guardian_owns_camper(uid, role, camper)

    allergy = validate.optional_bool(body, "has_life_threatening_allergy", False)
    epipen = validate.optional_bool(body, "epipen_on_file", False)
    med_count = validate.optional_int(body, "daily_medication_count", 0)
    if med_count < 0:
        raise validate.bad_request("daily_medication_count must be non-negative.")

    h = base_fields()
    h.update({
        "camper_id": camper["id"],
        "has_life_threatening_allergy": allergy,
        "epipen_on_file": epipen,
        "daily_medication_count": med_count,
        "status": "DRAFT",
        "review_note": "",
    })
    db.health_forms[h["id"]] = h
    return response.success(serialize.health_form(h), 201)


@bp.route("/health-forms", methods=["GET"])
def list_health_forms():
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    limit, offset = parse_pagination()

    camper_f = request.args.get("camper_id")
    status_f = request.args.get("status")

    items = list(db.health_forms.values())
    if role == "Guardian":
        owned = {c["id"] for c in db.campers.values() if c["guardian_user_id"] == uid}
        items = [h for h in items if h["camper_id"] in owned]
    if camper_f is not None:
        items = [h for h in items if h["camper_id"] == camper_f]
    if status_f is not None:
        items = [h for h in items if h["status"] == status_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.health_form(h) for h in page], limit, offset, total)


@bp.route("/health-forms/<hid>", methods=["GET"])
def get_health_form(hid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    h = require(db.health_forms, hid)
    camper = _camper_owner_chain(h)
    if camper is not None:
        guardian_owns_camper(uid, role, camper)
    return response.success(serialize.health_form(h), 200)


@bp.route("/health-forms/<hid>/submit", methods=["POST"])
def submit_health_form(hid):
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    h = require(db.health_forms, hid)
    camper = _camper_owner_chain(h)
    guardian_owns_camper(uid, role, camper)

    # State: DRAFT or FLAGGED -> SUBMITTED (PRD §3.3).
    if h["status"] not in ("DRAFT", "FLAGGED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Health form is not submittable.")
    # Anaphylaxis gate (ERR_EPIPEN_REQUIRED, p7).
    if h["has_life_threatening_allergy"] and not h["epipen_on_file"]:
        raise ApiError(errors.ERR_EPIPEN_REQUIRED, 422, "EpiPen required for life-threatening allergy.")

    h["status"] = "SUBMITTED"
    touch(h)
    recompute.recompute_camper_health_status(camper)
    touch(camper)
    return response.success(serialize.health_form(h), 200)


@bp.route("/health-forms/<hid>/clear", methods=["POST"])
def clear_health_form(hid):
    _uid, role = get_identity()
    require_role(role, {"InfirmaryNurse"})
    h = require(db.health_forms, hid)
    body = get_json_body()

    if h["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Health form is not SUBMITTED.")
    # Anaphylaxis gate re-applied on clear (ERR_EPIPEN_REQUIRED, p7).
    if h["has_life_threatening_allergy"] and not h["epipen_on_file"]:
        raise ApiError(errors.ERR_EPIPEN_REQUIRED, 422, "EpiPen required for life-threatening allergy.")

    note = validate.optional_str(body, "review_note", h["review_note"])
    h["status"] = "CLEARED"
    h["review_note"] = note
    touch(h)
    camper = _camper_owner_chain(h)
    if camper is not None:
        recompute.recompute_camper_health_status(camper)
        touch(camper)
    return response.success(serialize.health_form(h), 200)


@bp.route("/health-forms/<hid>/flag", methods=["POST"])
def flag_health_form(hid):
    _uid, role = get_identity()
    require_role(role, {"InfirmaryNurse"})
    h = require(db.health_forms, hid)
    body = get_json_body()

    if h["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Health form is not SUBMITTED.")

    note = validate.optional_str(body, "review_note", h["review_note"])
    h["status"] = "FLAGGED"
    h["review_note"] = note
    touch(h)
    camper = _camper_owner_chain(h)
    if camper is not None:
        recompute.recompute_camper_health_status(camper)
        touch(camper)
    return response.success(serialize.health_form(h), 200)
