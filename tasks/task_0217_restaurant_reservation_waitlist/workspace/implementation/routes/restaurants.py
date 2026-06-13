"""Restaurant routes (PRD §3.1)."""
from flask import Blueprint

import db
from errors import err, ERR_INVALID_STATE
from middleware import require_roles
from response import object_response
from services.lookup import get_or_404
from validators import (
    get_body, require_str, opt_str, opt_int,
)

bp = Blueprint("restaurants", __name__)


def _serialize(r):
    return db.serialize(r)


@bp.post("/restaurants")
def create_restaurant():
    require_roles({"Manager"})
    body = get_body()
    name = require_str(body, "name")
    timezone = opt_str(body, "timezone", "America/New_York")
    default_turn = opt_int(body, "default_turn_time_minutes", 90, minimum=30, maximum=360)
    cleanup = opt_int(body, "cleanup_buffer_minutes", 15, minimum=0, maximum=60)
    late_cutoff = opt_int(body, "late_cancel_cutoff_hours", 24, minimum=0, maximum=168)
    strike_threshold = opt_int(body, "no_show_strike_block_threshold", 3, minimum=1)
    per_seat = opt_int(body, "per_seat_deposit_cents", 2500, minimum=0)
    deposit_threshold = opt_int(body, "deposit_required_party_threshold", 6, minimum=1)

    rec = db.base_fields()
    rec.update({
        "name": name,
        "timezone": timezone,
        "default_turn_time_minutes": default_turn,
        "cleanup_buffer_minutes": cleanup,
        "late_cancel_cutoff_hours": late_cutoff,
        "no_show_strike_block_threshold": strike_threshold,
        "per_seat_deposit_cents": per_seat,
        "deposit_required_party_threshold": deposit_threshold,
        "status": "OPEN",
    })
    db.restaurants[rec["id"]] = rec
    return object_response(_serialize(rec), 201)


@bp.get("/restaurants/<rid>")
def read_restaurant(rid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.restaurants, rid)
    return object_response(_serialize(rec), 200)


@bp.post("/restaurants/<rid>/close")
def close_restaurant(rid):
    require_roles({"Manager"})
    rec = get_or_404(db.restaurants, rid)
    rec["status"] = "CLOSED"
    db.touch(rec)
    return object_response(_serialize(rec), 200)


@bp.post("/restaurants/<rid>/open")
def open_restaurant(rid):
    require_roles({"Manager"})
    rec = get_or_404(db.restaurants, rid)
    rec["status"] = "OPEN"
    db.touch(rec)
    return object_response(_serialize(rec), 200)
