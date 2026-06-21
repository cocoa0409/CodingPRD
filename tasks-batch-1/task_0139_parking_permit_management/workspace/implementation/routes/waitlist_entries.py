"""Standalone waitlist-entry endpoints: read, cancel."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_STATE
from middleware import require_auth
from response import ok_object
from services.common import lookup, require_owner_motorist
from services.serialize import public

bp = Blueprint("waitlist_entries", __name__)


@bp.get("/parking/waitlist-entries/<wid>")
def read_waitlist_entry(wid):
    require_auth(["FacilityAdmin", "Motorist"])()
    w = lookup(db.waitlist_entries, wid)
    return ok_object(public(w), 200)


@bp.post("/parking/waitlist-entries/<wid>/cancel")
def cancel_waitlist_entry(wid):
    require_auth(["Motorist"])()
    w = lookup(db.waitlist_entries, wid)

    # state (priority 4) before ownership (priority 5) per PRD §2.9.
    if w["status"] != "WAITING":
        raise APIError(ERR_INVALID_STATE, 409, "Waitlist entry is not WAITING")
    require_owner_motorist(w["motorist_id"])

    w["status"] = "CANCELLED"
    db.bump(w)
    return ok_object(public(w), 200)
