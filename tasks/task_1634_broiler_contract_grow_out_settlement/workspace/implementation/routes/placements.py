"""ChickPlacement confirm/cancel — the placement workflow pivot (PRD §3.3)."""
from flask import Blueprint

import db
import utils
from errors import ApiError
from helpers import get_or_404
from middleware import require_roles
from response import ok
from services import domain

bp = Blueprint("placements", __name__)

ADMIN = "IntegratorAdmin"


@bp.route("/api/placements/<pid>/confirm", methods=["POST"])
@require_roles(ADMIN)
def confirm_placement(pid):
    rec = get_or_404(db.placements, pid, "ChickPlacement")
    # Priority 5: transition legality (placement and its flock).
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SCHEDULED placement can be confirmed (current: %s)." % rec["status"],
            409,
        )
    flock = db.flocks.get(rec["flock_id"])
    if flock is None or flock["status"] != "PLANNED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Confirmation requires the flock to be PLANNED (current: %s)."
            % (flock["status"] if flock else "missing"),
            409,
        )
    # Priority 7: house safety at confirmation (same guard as scheduling).
    house = domain.house_of_flock(flock)
    if house["house_status"] == "QUARANTINED":
        raise ApiError(
            "ERR_HOUSE_IN_DOWNTIME",
            "House is QUARANTINED and cannot receive a placement.",
            409,
        )
    if house["downtime_until"] is not None and not (
        rec["scheduled_date"] > house["downtime_until"]
    ):
        raise ApiError(
            "ERR_HOUSE_IN_DOWNTIME",
            "House is in downtime until %s; scheduled_date %s does not clear it."
            % (house["downtime_until"], rec["scheduled_date"]),
            409,
        )
    domain.confirm_placement(rec)
    return ok(utils.pub(rec))


@bp.route("/api/placements/<pid>/cancel", methods=["POST"])
@require_roles(ADMIN)
def cancel_placement(pid):
    rec = get_or_404(db.placements, pid, "ChickPlacement")
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SCHEDULED placement can be cancelled (current: %s)." % rec["status"],
            409,
        )
    rec["status"] = "CANCELLED"
    domain.bump(rec)
    return ok(utils.pub(rec))
