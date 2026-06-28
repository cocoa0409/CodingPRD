"""Shared business logic: ownership resolution, compliance bubble-up, pagination."""
import db
import errors
from errors import err


# --- pagination (PRD §2.3) ---
def parse_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """Sort by created_at ASC, then apply limit/offset. Returns (page, total)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# --- ownership resolution (PRD §2.1) ---
def homeowner_owns_job(user_id, job):
    prop = db.properties.get(job["property_id"])
    if prop is None:
        return False
    return prop["homeowner_id"] == user_id


def homeowner_owns_property(user_id, prop):
    return prop["homeowner_id"] == user_id


# --- compliance bubble-up (PRD §2.9) ---
def reevaluate_clearance(job):
    """If job is PERMIT_PENDING and both an APPROVED permit and APPROVED
    interconnection exist on it, bubble compliance_status up to CLEARED.

    Server-initiated mutation: refreshes updated_at and increments version.
    """
    if job["compliance_status"] != "PERMIT_PENDING":
        return
    has_permit = any(
        p["install_job_id"] == job["id"] and p["status"] == "APPROVED"
        for p in db.permit_applications.values()
    )
    if not has_permit:
        return
    has_inter = any(
        r["install_job_id"] == job["id"] and r["status"] == "APPROVED"
        for r in db.interconnection_requests.values()
    )
    if not has_inter:
        return
    job["compliance_status"] = "CLEARED"
    db.touch(job)
