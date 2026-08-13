"""Variance record endpoints: list per estimate, review (PRD 3.9)."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from util import get_body, paginate, serialize, touch

bp = Blueprint("variance", __name__)


@bp.get("/clearance/estimates/<eid>/variance-records")
def list_variance_records(eid):
    authenticate(ALL_ROLES)
    if eid not in db.estimates:
        raise not_found("estimate not found")
    items = [v for v in db.variance_records.values() if v["estimate_id"] == eid]
    page, meta = paginate(items)
    return ok_list([serialize(v) for v in page], meta)


@bp.post("/clearance/variance-records/<vid>/review")
def review_variance(vid):
    authenticate(["ClearanceSupervisor"])
    rec = db.variance_records.get(vid)
    if rec is None:
        raise not_found("variance record not found")
    b = get_body()
    root_cause = b.get("root_cause")
    if not isinstance(root_cause, str) or root_cause == "":
        raise ApiError(ERR_INVALID_REQUEST, "root_cause must be a non-empty string", 400)
    if rec["status"] != "UNREVIEWED":
        raise invalid_state("variance record has already been reviewed")
    rec["root_cause"] = root_cause
    rec["status"] = "REVIEWED"
    touch(rec)
    return ok_object(serialize(rec))
