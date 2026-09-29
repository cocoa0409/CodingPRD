"""Environmental clearance: circulation, certification and recirculation
(PRD 3.8).  Circulation intervals are CLOSED, so a shared endpoint day is an
overlap.
"""

from flask import Blueprint

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import AGENCY_REP, CLERK, MONITOR, RPO, SYSADMIN, authorize
from services import calc, derive

bp = Blueprint("env_reviews", __name__)

DETERMINATION_CLASSES = ("EXEMPT", "NEGATIVE_DECLARATION", "MITIGATED_NEG_DEC", "FULL_EIR")
ENV_STATUSES = ("CIRCULATING", "RECIRCULATION_REQUIRED", "CERTIFIED")
READ_ROLES = (RPO, CLERK, MONITOR, AGENCY_REP, SYSADMIN)


@bp.post("/declarations/<row_id>/environmental-reviews")
@authorize(RPO)
def open_review(row_id):
    payload = shape.body()
    determination_class = shape.req_enum(payload, "determination_class", DETERMINATION_CLASSES)
    start, start_raw = shape.opt_instant(payload, "circulation_start_on")
    end, end_raw = shape.opt_instant(payload, "circulation_end_on")
    if determination_class != "EXEMPT" and (start is None or end is None):
        fail("ERR_INVALID_REQUEST",
             "circulation_start_on and circulation_end_on are required for a %s review."
             % determination_class)
    declaration = lookup.must("declarations", row_id)

    if determination_class == "EXEMPT":
        # The supplied interval is ignored entirely: no length check, no overlap
        # check, and nothing stored.
        row = db.insert("environmental_reviews", {
            "declaration_id": declaration["id"],
            "determination_class": determination_class,
            "circulation_start_on": None,
            "circulation_end_on": None,
            "circulation_round": 1,
            "status": "CERTIFIED",
            "certified_at": clockmod.now(),
            "recirculation_reason": None,
        })
        return response.object_response(derive.env_review_out(row), 201)

    if not calc.circulation_long_enough(start, end):
        fail("ERR_CIRCULATION_TOO_SHORT",
             "A public circulation runs for at least %d whole days."
             % calc.ENV_CIRCULATION_MIN_DAYS)
    if calc.circulation_overlaps(declaration["id"], start, end):
        fail("ERR_CIRCULATION_WINDOW_OVERLAP",
             "Another review on this declaration already circulates over these days.")

    row = db.insert("environmental_reviews", {
        "declaration_id": declaration["id"],
        "determination_class": determination_class,
        "circulation_start_on": start,
        "circulation_end_on": end,
        "circulation_round": 1,
        "status": "CIRCULATING",
        "certified_at": None,
        "recirculation_reason": None,
    })
    db.set_raw(row, "circulation_start_on", start_raw)
    db.set_raw(row, "circulation_end_on", end_raw)
    return response.object_response(derive.env_review_out(row), 201)


@bp.get("/declarations/<row_id>/environmental-reviews")
@authorize(*READ_ROLES)
def list_declaration_reviews(row_id):
    limit, offset = listing.bounds()
    status = shape.query_enum("status", ENV_STATUSES)
    declaration = lookup.must("declarations", row_id)
    rows = [r for r in db.all_rows("environmental_reviews")
            if r["declaration_id"] == declaration["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing.respond(rows, derive.env_review_out, limit, offset, listing.by_created_at)


@bp.get("/environmental-reviews/<row_id>")
@authorize(*READ_ROLES)
def get_review(row_id):
    row = lookup.must("environmental_reviews", row_id)
    return response.object_response(derive.env_review_out(row))


@bp.post("/environmental-reviews/<row_id>/certify")
@authorize(RPO)
def certify_review(row_id):
    row = lookup.must("environmental_reviews", row_id)
    end = row.get("circulation_end_on")
    if row["status"] != "CIRCULATING" or end is None or clockmod.now() < end:
        fail("ERR_INVALID_ENV_REVIEW_STATE",
             "Certification requires a CIRCULATING review whose circulation has run out.")
    row["status"] = "CERTIFIED"
    row["certified_at"] = clockmod.now()
    db.touch(row)
    return response.object_response(derive.env_review_out(row))


@bp.post("/environmental-reviews/<row_id>/recirculate")
@authorize(RPO)
def recirculate_review(row_id):
    payload = shape.body()
    reason = shape.req_str(payload, "recirculation_reason", 1)
    start, start_raw = shape.req_instant(payload, "circulation_start_on")
    end, end_raw = shape.req_instant(payload, "circulation_end_on")
    row = lookup.must("environmental_reviews", row_id)

    if row["status"] != "CIRCULATING":
        fail("ERR_INVALID_ENV_REVIEW_STATE",
             "A review that is %s cannot be recirculated." % row["status"])
    if not calc.circulation_long_enough(start, end):
        fail("ERR_CIRCULATION_TOO_SHORT",
             "A public circulation runs for at least %d whole days."
             % calc.ENV_CIRCULATION_MIN_DAYS)
    prior_end = row.get("circulation_end_on")
    if prior_end is not None:
        earliest = clockmod.plus_days(prior_end, calc.RECIRCULATION_BUFFER_DAYS)
        if start < earliest:
            fail("ERR_RECIRCULATION_BUFFER_VIOLATION",
                 "A recirculation starts no earlier than %d days after the prior round's end."
                 % calc.RECIRCULATION_BUFFER_DAYS)
    if calc.circulation_overlaps(row["declaration_id"], start, end, exclude_id=row["id"]):
        fail("ERR_CIRCULATION_WINDOW_OVERLAP",
             "Another review on this declaration already circulates over these days.")

    # RECIRCULATION_REQUIRED is passed through and left immediately.
    row["status"] = "RECIRCULATION_REQUIRED"
    row["circulation_round"] += 1
    row["circulation_start_on"] = start
    row["circulation_end_on"] = end
    row["recirculation_reason"] = reason
    row["status"] = "CIRCULATING"
    db.set_raw(row, "circulation_start_on", start_raw)
    db.set_raw(row, "circulation_end_on", end_raw)
    db.touch(row)
    return response.object_response(derive.env_review_out(row))
