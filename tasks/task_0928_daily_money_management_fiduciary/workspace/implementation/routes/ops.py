"""The logical clock control endpoint and the periodic checkpoint sweep."""

from flask import Blueprint

from core import serialize  # noqa: F401  (kept for symmetry of the route modules)
from core.clock import parse_date, parse_instant, render_instant
from core.envelope import object_response
from core.errors import fail
from core.pipeline import audited, authorize
from core.store import bump, db

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
@audited("System")
def set_clock():
    ctx = authorize("PlatformAdmin")                           # rungs 1-2
    ctx.check_shape([("to_iso8601", str, True)])               # rung 4
    moment = parse_instant(ctx.body["to_iso8601"])
    if moment is None:
        fail("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 instant.")
    db.now = moment
    # The server renders its own reading rather than echoing the caller.
    return object_response({"current_utc": render_instant(db.now)}, 200)


@bp.post("/dmm/ops/checkpoint")
@audited("System")
def checkpoint():
    authorize("PlatformAdmin")                                 # rungs 1-2

    authorizations_expired = 0
    today = db.now.date()
    for auth in db.ordered("authorizations"):
        if auth["status"] != "ACTIVE":
            continue
        expiry = parse_date(auth["expiry_date"])
        if expiry is not None and expiry < today:
            auth["status"] = "EXPIRED"
            bump(auth)
            authorizations_expired += 1

    alerts_escalated = 0
    for alert in db.ordered("fraud_alerts"):
        if alert["status"] != "NEW":
            continue
        if alert["ack_due_at"] is not None and alert["ack_due_at"] <= db.now:
            alert["status"] = "ESCALATED"
            bump(alert)
            alerts_escalated += 1

    coordination_requests_escalated = 0
    for req in db.ordered("coordination_requests"):
        if req["status"] != "OPEN":
            continue
        if req["ack_due_at"] is not None and req["ack_due_at"] <= db.now:
            req["status"] = "ESCALATED"
            bump(req)
            coordination_requests_escalated += 1

    return object_response({
        "authorizations_expired": authorizations_expired,
        "alerts_escalated": alerts_escalated,
        "coordination_requests_escalated": coordination_requests_escalated,
    }, 200)
