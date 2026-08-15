"""CatchSchedule complete/cancel — the harvest event (PRD §3.5)."""
from flask import Blueprint

import db
import utils
from errors import ApiError
from helpers import get_or_404
from middleware import require_roles
from response import ok
from services import domain

bp = Blueprint("schedules", __name__)

HAUL = "LivehaulScheduler"


@bp.route("/api/catch-schedules/<sid>/complete", methods=["POST"])
@require_roles(HAUL)
def complete_catch(sid):
    rec = get_or_404(db.catch_schedules, sid, "CatchSchedule")
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SCHEDULED catch can be completed (current: %s)." % rec["status"],
            409,
        )
    has_ticket = any(t["flock_id"] == rec["flock_id"] for t in db.weight_tickets.values())
    if not has_ticket:
        raise ApiError(
            "ERR_INVALID_STATE",
            "Catch completion requires at least one weight ticket for the flock.",
            409,
        )
    domain.harvest_flock(rec)
    return ok(utils.pub(rec))


@bp.route("/api/catch-schedules/<sid>/cancel", methods=["POST"])
@require_roles(HAUL)
def cancel_catch(sid):
    rec = get_or_404(db.catch_schedules, sid, "CatchSchedule")
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SCHEDULED catch can be cancelled (current: %s)." % rec["status"],
            409,
        )
    rec["status"] = "CANCELLED"
    domain.bump(rec)
    flock = db.flocks.get(rec["flock_id"])
    if flock is not None and flock["status"] == "CATCH_SCHEDULED":
        flock["status"] = "GROWING"
        domain.bump(flock)
    return ok(utils.pub(rec))
