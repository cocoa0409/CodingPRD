"""Grade endpoints — immutable compensation bands (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize
from services.common import (
    get_body, require_string, require_int, base_immutable_fields, fetch, paginate,
)

bp = Blueprint("grades", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


@bp.post("/grades")
def create_grade():
    require_auth(["CompensationAnalyst"])
    body = get_body()
    code = require_string(body, "code")
    band_min = require_int(body, "band_min_cents", min_value=0)
    band_mid = require_int(body, "band_mid_cents", min_value=0)
    band_max = require_int(body, "band_max_cents", min_value=0)
    rank = require_int(body, "rank", min_value=1)

    # Ordering: mid >= min, max >= mid (PRD §3.1).
    if band_mid < band_min:
        raise err("ERR_INVALID_REQUEST", "band_mid_cents must be >= band_min_cents")
    if band_max < band_mid:
        raise err("ERR_INVALID_REQUEST", "band_max_cents must be >= band_mid_cents")

    # code and rank unique among grades (PRD §3.1).
    for g in db.grades.values():
        if g["code"] == code:
            raise err("ERR_INVALID_REQUEST", "code must be unique among grades")
        if g["rank"] == rank:
            raise err("ERR_INVALID_REQUEST", "rank must be unique among grades")

    rec = base_immutable_fields()
    rec.update({
        "code": code,
        "band_min_cents": band_min,
        "band_mid_cents": band_mid,
        "band_max_cents": band_max,
        "rank": rank,
    })
    db.grades[rec["id"]] = rec
    return success(serialize.grade_out(rec), status=201)


@bp.get("/grades/<grade_id>")
def get_grade(grade_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.grades, grade_id)
    return success(serialize.grade_out(rec))


@bp.get("/grades")
def list_grades():
    require_auth(ALL_ROLES)
    page, limit, offset, total = paginate(list(db.grades.values()))
    return list_success([serialize.grade_out(r) for r in page], limit, offset, total)
