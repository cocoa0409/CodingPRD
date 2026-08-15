"""E-file rejection follow-up (PRD §3.7)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import ok, paginate
from services.serialize import rejection_json
from validation import parse_body, require_entity

bp = Blueprint("rejections", __name__)

FOLLOW_UP_SCHEMA = {
    "outcome": {"kind": "enum", "required": True, "values": ["CONTACTED",
                                                             "RESOLVED"]},
    "resolution_note": {"kind": "string"},
}


@bp.get("/tax-returns/<return_id>/rejections")
def list_rejections(return_id):
    get_context()
    require_entity(store.tax_returns, return_id)
    rows = [r for r in store.efile_rejections.values()
            if r["tax_return_id"] == return_id]
    page = paginate(rows)
    return ok([rejection_json(r) for r in page], rtype="array",
              pagination=paginate)


@bp.post("/efile-rejections/<rejection_id>/follow-up")
def record_follow_up(rejection_id):
    get_context()
    require_roles(["QualityReviewer", "SiteCoordinator"])
    rej = require_entity(store.efile_rejections, rejection_id)
    body = parse_body(FOLLOW_UP_SCHEMA)
    outcome = body["outcome"]
    # Conditional field (tier 4): resolving requires a resolution note.
    if outcome == "RESOLVED" and "resolution_note" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "resolution_note is required when recording RESOLVED")

    current = rej["follow_up_status"]
    if current == "OPEN" and outcome == "CONTACTED":
        rej["follow_up_status"] = "CONTACTED"
        rej["contacted_at"] = db.logical_dt()
    elif current in ("OPEN", "CONTACTED") and outcome == "RESOLVED":
        rej["follow_up_status"] = "RESOLVED"
        rej["resolved_at"] = db.logical_dt()
        rej["resolution_note"] = body["resolution_note"]
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Cannot record %s on a %s rejection" % (outcome, current))
    db.touch(rej)
    return ok(rejection_json(rej))
