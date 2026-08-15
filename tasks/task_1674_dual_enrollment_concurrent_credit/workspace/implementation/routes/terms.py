"""AcademicTerm endpoints (PRD 2.4, 3.1). State machine: SCHEDULED -> OPEN -> CLOSED."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_TERM_INVALID_STATE,
    ERR_TERM_OVERLAP,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.core import new_record, public, touch
from services.transitions import close_registration_cascade
from validate import get_body, req_dt, req_enum, req_str, require_body_ref, require_path_resource

bp = Blueprint("terms", __name__)

INSTITUTION_TYPES = {"COLLEGE", "HIGH_SCHOOL"}
DATE_ORDERING_NOTE = (
    "start_date < add_deadline <= drop_deadline <= withdraw_deadline <= end_date"
)


@bp.post("/terms")
def create_term():
    authorized(["DualCreditAdmin"])
    body = get_body()
    # Priority 4: request shape, including the high_school_id presence rule and
    # the internal date ordering invariant.
    institution_type = req_enum(body, "institution_type", INSTITUTION_TYPES)
    name = req_str(body, "name")
    hs_raw = body.get("high_school_id")
    if institution_type == "HIGH_SCHOOL":
        if hs_raw is None or not isinstance(hs_raw, str) or hs_raw.strip() == "":
            raise_error(
                ERR_VALIDATION,
                "high_school_id is required for HIGH_SCHOOL terms",
            )
    else:  # COLLEGE terms must carry a null high_school_id
        if hs_raw is not None:
            raise_error(
                ERR_VALIDATION,
                "high_school_id must be null for COLLEGE terms",
            )
    start_raw, start = req_dt(body, "start_date")
    end_raw, end = req_dt(body, "end_date")
    add_raw, add = req_dt(body, "add_deadline")
    drop_raw, drop = req_dt(body, "drop_deadline")
    withdraw_raw, withdraw = req_dt(body, "withdraw_deadline")
    if not (start < add <= drop <= withdraw <= end):
        raise_error(ERR_VALIDATION, f"term date ordering violated: {DATE_ORDERING_NOTE}")

    # Priority 5: referenced high school exists.
    if institution_type == "HIGH_SCHOOL":
        require_body_ref("high_schools", hs_raw, "high_school_id")

    # Priority 8: HALF-OPEN [start_date, end_date) overlap with a sibling term
    # (same institution_type; same high_school_id for HIGH_SCHOOL). Adjacency
    # (end == start) is allowed.
    for t in db["terms"].values():
        if t["institution_type"] != institution_type:
            continue
        if institution_type == "HIGH_SCHOOL" and t["high_school_id"] != hs_raw:
            continue
        if start < t["_end_date"] and t["_start_date"] < end:
            raise_error(ERR_TERM_OVERLAP, "term overlaps an existing term on this calendar")

    rec = new_record(
        "terms",
        {
            "institution_type": institution_type,
            "high_school_id": hs_raw if institution_type == "HIGH_SCHOOL" else None,
            "name": name,
            "start_date": start_raw,
            "end_date": end_raw,
            "add_deadline": add_raw,
            "drop_deadline": drop_raw,
            "withdraw_deadline": withdraw_raw,
            "status": "SCHEDULED",
            "date_ordering": DATE_ORDERING_NOTE,
        },
    )
    rec["_start_date"] = start
    rec["_end_date"] = end
    rec["_add_deadline"] = add
    rec["_drop_deadline"] = drop
    rec["_withdraw_deadline"] = withdraw
    return success_object(public(rec), status=201)


@bp.get("/terms")
def list_terms():
    return list_response(
        "terms",
        {"institution_type": arg("institution_type"), "high_school_id": arg("high_school_id")},
    )


@bp.get("/terms/<rid>")
def get_term(rid):
    return get_one("terms", rid)


@bp.post("/terms/<rid>/open-registration")
def open_registration(rid):
    authorized(["DualCreditAdmin"])
    term = require_path_resource("terms", rid)
    if term["status"] != "SCHEDULED":
        raise_error(ERR_TERM_INVALID_STATE, "only a SCHEDULED term can open registration")
    term["status"] = "OPEN"
    touch(term)
    return success_object(public(term))


@bp.post("/terms/<rid>/close-registration")
def close_registration(rid):
    authorized(["DualCreditAdmin"])
    term = require_path_resource("terms", rid)
    if term["status"] != "OPEN":
        raise_error(ERR_TERM_INVALID_STATE, "only an OPEN term can close registration")
    term["status"] = "CLOSED"
    touch(term)
    close_registration_cascade(term)
    return success_object(public(term))
