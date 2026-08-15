"""Bin endpoints (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok
from services import core
from util import as_bu, as_enum, as_str, body, required, resolve_path

bp = Blueprint("bins", __name__)


@bp.route("/grain/bins", methods=["POST"])
def create_bin():
    require_roles("SiteManager")
    data = body()
    name = as_str(required(data, "name"), "name")
    capacity = as_bu(required(data, "capacity_bu"), "capacity_bu")
    if capacity <= 0:
        raise ApiError("ERR_VALIDATION", 400, "capacity_bu must be > 0")
    crop = as_enum(required(data, "crop"), "crop", core.CROPS)

    rec = core.new_common()
    rec.update({
        "name": name,
        "capacity_bu": capacity,
        "crop": crop,
        "current_inventory_bu": Decimal("0.00"),
        "risk_score": Decimal("0.00"),
        "posture": "SOUND",
        "insect_activity": False,
        "last_reading_at": None,
    })
    db.bins[rec["id"]] = rec
    return ok(core.bin_view(rec), 201)


@bp.route("/grain/bins/<bid>", methods=["GET"])
def get_bin(bid):
    require_roles(*ALL_ROLES)
    return ok(core.bin_view(resolve_path(db.bins, bid, "bin")))
