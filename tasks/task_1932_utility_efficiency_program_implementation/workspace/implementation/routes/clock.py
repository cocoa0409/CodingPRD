"""Logical clock endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
import errors
from middleware import require_roles
from response import success_object
from services import core

bp = Blueprint("clock", __name__)


@bp.post("/efficiency/_clock/set_current_utc")
def set_clock():
    require_roles({"ProgramManager"})
    from routes.common import get_body
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not to_iso:
        raise errors.ApiError(errors.ERR_INVALID_INSPECTION_PAYLOAD, "to_iso8601 is required", 400)
    try:
        new_clock = db.parse_dt(to_iso)
    except ValueError:
        raise errors.ApiError(errors.ERR_INVALID_INSPECTION_PAYLOAD, "to_iso8601 must be ISO-8601", 400)

    db.set_clock(new_clock)

    # Certification sweep: ACTIVE -> EXPIRED for expires_on <= new clock.
    expired_count = 0
    # Track affected contractors so we can apply cascade once per contractor.
    affected: set[str] = set()
    for cert in list(db.certifications.values()):
        if cert.get("status") != "ACTIVE":
            continue
        if db.parse_dt(cert["expires_on"]) <= new_clock:
            cert["status"] = "EXPIRED"
            db.touch(cert)
            expired_count += 1
            affected.add(cert["contractor_id"])

    for contractor_id in affected:
        contractor = db.contractors.get(contractor_id)
        if contractor is None:
            continue
        core.recompute_active_cert_count(contractor)
        db.touch(contractor)
        if contractor.get("active_certification_count", 0) == 0 and contractor.get("status") == "APPROVED":
            core.suspend_contractor(contractor)

    return success_object({
        "current_utc": db.format_dt(db.get_clock()),
        "certifications_expired": expired_count,
    })
