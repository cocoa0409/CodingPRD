"""Logical clock test-driving endpoint."""
from flask import Blueprint

import db
from middleware import get_actor, require_roles
from response import success_object
from errors import err_validation
from services.common import body, parse_datetime_field
from services.calculations import compute_certification_status

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    payload = body()
    target = parse_datetime_field(payload, "to_iso8601", required=True)
    db.clock.set(db._format_iso(target))

    # Reopen DEFERRED defects whose deferred_until <= clock
    now = db.now_dt()
    for defect in db.defects.values():
        if defect["status"] == "DEFERRED" and defect.get("deferred_until"):
            deferred_until = db._parse_iso(defect["deferred_until"])
            if now >= deferred_until:
                defect["status"] = "OPEN"
                defect["deferred_until"] = None
                db.touch(defect)

    # Recompute all certification statuses
    for cert in db.technician_certifications.values():
        cert["status"] = compute_certification_status(cert)

    return success_object({"current_utc": db.now_iso()})
