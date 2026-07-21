"""Compliance reviews and holds (PRD 3.8)."""
from flask import Blueprint, request, g

import db
from auth import require, body
from validation import get_or_404, req_str, req_enum, opt_str
from responses import success, list_response
from serializers import serialize
from errors import ApiError
from constants import COMPLIANCE_REASONS
from services import terminate_agreements

bp = Blueprint("compliance", __name__)


@bp.post("/compliance-reviews")
@require("ComplianceOfficer")
def open_review():
    b = body()
    if b.get("guarantee_id") is not None:
        get_or_404(db.guarantees, b["guarantee_id"])
    guarantee_id = req_str(b, "guarantee_id")
    reason = req_enum(b, "reason", COMPLIANCE_REASONS)

    cr = {
        "guarantee_id": guarantee_id,
        "reason": reason,
        "opened_by_user_id": g.user_id,
        "resolution_note": None,
        "status": "OPEN",
    }
    db.stamp_common(cr)
    db.compliance_reviews[cr["id"]] = cr
    return success(serialize(cr), 201)


@bp.get("/compliance-reviews/<rid>")
@require("ComplianceOfficer", "PlatformAdmin")
def get_review(rid):
    cr = get_or_404(db.compliance_reviews, rid)
    return success(serialize(cr), 200)


@bp.get("/compliance-reviews")
@require("ComplianceOfficer", "PlatformAdmin")
def list_reviews():
    args = request.args
    items = list(db.compliance_reviews.values())
    for key in ("guarantee_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    return list_response(items, args)


@bp.post("/compliance-reviews/<rid>/clear")
@require("ComplianceOfficer")
def clear_review(rid):
    cr = get_or_404(db.compliance_reviews, rid)
    if g.user_id == cr["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if cr["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    b = body()
    note = opt_str(b, "resolution_note")
    if note is not None:
        cr["resolution_note"] = note
    cr["status"] = "CLEARED"
    db.touch(cr)
    return success(serialize(cr), 200)


@bp.post("/compliance-reviews/<rid>/uphold")
@require("ComplianceOfficer")
def uphold_review(rid):
    cr = get_or_404(db.compliance_reviews, rid)
    if g.user_id == cr["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if cr["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    b = body()
    note = opt_str(b, "resolution_note")
    if note is not None:
        cr["resolution_note"] = note
    cr["status"] = "UPHELD"
    db.touch(cr)

    # cascade: cancel a not-yet-active guarantee
    guarantee = db.guarantees.get(cr["guarantee_id"])
    if guarantee is not None and guarantee["status"] in ("QUOTED", "APPROVED"):
        was_approved = guarantee["status"] == "APPROVED"
        guarantee["status"] = "CANCELLED"
        db.touch(guarantee)
        if was_approved:
            terminate_agreements(guarantee["id"], {"SIGNED", "ACTIVE"})

    return success(serialize(cr), 200)
