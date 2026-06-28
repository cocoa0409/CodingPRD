"""Campers. PRD §3.3."""
from flask import Blueprint, request

import db
import response
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize
from services.store import base_fields, require, paginate, guardian_owns_camper

bp = Blueprint("campers", __name__)

GENDERS = {"BOY", "GIRL"}


@bp.route("/campers", methods=["POST"])
def create_camper():
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    body = get_json_body()

    full_name = validate.require_str(body, "full_name")
    age = validate.require_int(body, "age")
    if age < 0:
        raise validate.bad_request("age must be non-negative.")
    gender = validate.require_enum(body, "gender", GENDERS)

    c = base_fields()
    c.update({
        "guardian_user_id": uid,
        "full_name": full_name,
        "age": age,
        "gender": gender,
        "health_status": "NONE",
    })
    db.campers[c["id"]] = c
    return response.success(serialize.camper(c), 201)


@bp.route("/campers", methods=["GET"])
def list_campers():
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    limit, offset = parse_pagination()

    guardian_f = request.args.get("guardian_user_id")
    items = list(db.campers.values())
    # A Guardian sees only their own campers.
    if role == "Guardian":
        items = [c for c in items if c["guardian_user_id"] == uid]
    if guardian_f is not None:
        items = [c for c in items if c["guardian_user_id"] == guardian_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.camper(c) for c in page], limit, offset, total)


@bp.route("/campers/<cid>", methods=["GET"])
def get_camper(cid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    c = require(db.campers, cid)
    guardian_owns_camper(uid, role, c)
    return response.success(serialize.camper(c), 200)
