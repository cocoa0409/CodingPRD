"""Test-driving logical clock (PRD 2.5): DistrictAdmin-only; forward jumps
apply lazy expiry of offers and clearances (with the suspension cascade)."""

from flask import Blueprint

import db
import domain
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import auth_context, require_role
from response import ok
from util import parse_datetime
from validate import body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth_context()
    data = body()
    raw = data.get("to_iso8601")
    if raw is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    target = parse_datetime(raw)
    if target is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 UTC instant")
    require_role(role, ["DistrictAdmin"])
    previous = db.STORE.clock
    db.STORE.clock = target
    if target > previous:
        # Forward jump: offers whose expiry instant was reached flip to
        # EXPIRED (with the re-dispatch cascade); stale clearances flip to
        # EXPIRED. Clearance detection here is not a batch/activation
        # detection point, so no suspension cascade runs (PRD 3.2).
        domain.expire_offers()
        domain.flip_stale_clearances()
    return ok({"current_utc": db.iso(db.STORE.clock)})
