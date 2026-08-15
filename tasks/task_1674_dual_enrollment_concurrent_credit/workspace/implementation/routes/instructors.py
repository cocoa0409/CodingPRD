"""Instructor endpoints (PRD 3.3)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.core import new_record, public
from validate import get_body, req_str, require_body_ref

bp = Blueprint("instructors", __name__)


@bp.post("/instructors")
def create_instructor():
    authorized(["DualCreditAdmin"])
    body = get_body()
    full_name = req_str(body, "full_name")
    high_school_id = req_str(body, "high_school_id")
    require_body_ref("high_schools", high_school_id, "high_school_id")
    rec = new_record(
        "instructors",
        {"full_name": full_name, "high_school_id": high_school_id},
    )
    return success_object(public(rec), status=201)


@bp.get("/instructors")
def list_instructors():
    return list_response("instructors", {"high_school_id": arg("high_school_id")})


@bp.get("/instructors/<rid>")
def get_instructor(rid):
    return get_one("instructors", rid)
