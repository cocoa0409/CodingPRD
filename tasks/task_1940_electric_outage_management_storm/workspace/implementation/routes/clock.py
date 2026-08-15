"""POST /om/_clock/set_current_utc — set the server logical clock (EmergencyDirector).

Advancing the clock sweeps CERTIFIED priority customers whose certified_through
lies strictly before the new now into SUSPENDED, and recomputes the affected
feeder's certified_priority_count plus has_priority_customers / priority_score
on every non-terminal outage on that feeder (all derived on read).
"""
from flask import Blueprint

from db import db, iso_ms
from middleware import require_roles
from response import success_object
from errors import raise_err, ERR_INVALID_REQUEST
from services.core import (
    get_body, req_datetime, recompute_outage_scores_for_feeder,
)

bp = Blueprint("clock", __name__)


@bp.route("/om/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(["EmergencyDirector"])
    body = get_body()
    new_now = req_datetime(body, "to_iso8601")
    db.set_now(new_now)

    # Certification sweep: CERTIFIED customers whose certified_through < now
    # become SUSPENDED.
    affected_feeders = set()
    for pc in db.priority_customers.values():
        if pc["certification_status"] != "CERTIFIED":
            continue
        ct = pc.get("certified_through")
        if ct is None:
            continue
        from db import parse_iso
        if parse_iso(ct) < new_now:
            pc["certification_status"] = "SUSPENDED"
            pc["updated_at"] = iso_ms(new_now)
            pc["version"] += 1
            affected_feeders.add(pc["feeder_id"])
    for fid in affected_feeders:
        recompute_outage_scores_for_feeder(fid)

    return success_object({"current_utc": iso_ms(new_now)}, status=200)
