"""Fraud flag endpoints: read/list, confirm, clear."""
from flask import Blueprint, request

from db import STORE
from errors import err, ERR_FRAUD_FLAG_NOT_FOUND, ERR_FLAG_NOT_OPEN
from middleware import require_roles
from response import success, paginate
from services.core import touch, serialize, sort_created, reject_claim

bp = Blueprint("fraud", __name__)

ROLES = ("BenefitsAdmin", "Auditor", "ClaimsReviewer")


def get_flag(fid):
    f = STORE.fraud_flags.get(fid)
    if f is None:
        raise err(ERR_FRAUD_FLAG_NOT_FOUND, 404, "fraud flag id does not resolve")
    return f


@bp.get("/api/fraud-flags/<fid>")
def read_flag(fid):
    require_roles(*ROLES)
    return success(serialize(get_flag(fid)))


@bp.get("/api/fraud-flags")
def list_flags():
    require_roles(*ROLES)
    items = sort_created(STORE.fraud_flags.values())
    visit_id = request.args.get("visit_id")
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    if visit_id is not None:
        items = [f for f in items if f.get("visit_id") == visit_id]
    if claim_id is not None:
        items = [f for f in items if f.get("claim_id") == claim_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return paginate([serialize(f) for f in items])


@bp.post("/api/fraud-flags/<fid>/confirm")
def confirm_flag(fid):
    require_roles("ClaimsReviewer")
    f = get_flag(fid)
    if f["status"] != "OPEN":
        raise err(ERR_FLAG_NOT_OPEN, 409, "confirm requires fraud flag OPEN")
    f["status"] = "CONFIRMED"
    touch(f)
    # visit-level confirm voids the flagged visit (bypasses ERR_VISIT_IN_USE) and
    # auto-rejects referencing open claims with reservation release
    vid = f.get("visit_id")
    if vid is not None:
        v = STORE.visits.get(vid)
        if v is not None and v["status"] == "VERIFIED":
            v["status"] = "VOIDED"
            touch(v)
        for c in STORE.claims.values():
            if vid in c.get("visit_ids", []) and c["review_status"] in (
                    "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
                reject_claim(c)
    return success(serialize(f))


@bp.post("/api/fraud-flags/<fid>/clear")
def clear_flag(fid):
    require_roles("ClaimsReviewer")
    f = get_flag(fid)
    if f["status"] != "OPEN":
        raise err(ERR_FLAG_NOT_OPEN, 409, "clear requires fraud flag OPEN")
    f["status"] = "CLEARED"
    touch(f)
    # referencing claims recompute fraud_hold (computed live at read/approve)
    return success(serialize(f))
