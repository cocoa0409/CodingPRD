"""Program endpoints (PRD 3.1)."""
from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    check_int_range,
    get_or_404,
    list_response,
    new_record,
    opt_int,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("programs", __name__)

FIELDS = [
    "id",
    "season_id",
    "name",
    "category",
    "min_age",
    "max_age",
    "created_at",
    "updated_at",
    "version",
]


def program_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/programs", methods=["POST"])
def create_program():
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    season_id = req_str(body, "season_id")
    name = req_str(body, "name")
    category = req_str(body, "category")
    min_age = opt_int(body, "min_age", 0)
    max_age = opt_int(body, "max_age", 120)
    check_int_range(min_age, 0, None, "min_age")
    if max_age < min_age:
        raise_err("ERR_INVALID_REQUEST", "max_age must be at least min_age")
    season = get_or_404(store.seasons, season_id, "Season")
    if season["status"] == "CLOSED":
        raise_err("ERR_SEASON_CLOSED", "Season is CLOSED; new catalog content is rejected")
    rec = new_record()
    rec.update(
        season_id=season_id,
        name=name,
        category=category,
        min_age=min_age,
        max_age=max_age,
    )
    store.programs[rec["id"]] = rec
    return success_object(program_out(rec), 201)


@bp.route("/programs", methods=["GET"])
def list_programs():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    season_id = request.args.get("season_id")
    records = list(store.programs.values())
    if season_id is not None:
        records = [r for r in records if r["season_id"] == season_id]
    return list_response(records, program_out)


@bp.route("/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.programs, program_id, "Program")
    return success_object(program_out(rec), 200)
