"""Driver registration, reads, wallet funding, and driver violations list."""
from flask import Blueprint, request

from db import db, make_versioned, touch
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_auth, require_role
from response import success, success_list
from serialize import driver_view, violation_view
from util import require_body, require_str, require_int, parse_pagination, paginate

bp = Blueprint("drivers", __name__)


@bp.post("/drivers")
def create_driver():
    # Anonymous (open registration) — no auth required.
    data = require_body(request.get_json(silent=True))
    email = require_str(data, "email")
    display_name = require_str(data, "display_name")
    for d in db.drivers.values():
        if d["email"] == email:
            raise err(ERR_INVALID_REQUEST, "email must be unique across drivers.")

    rec = make_versioned(
        {
            "email": email,
            "display_name": display_name,
            "wallet_balance_cents": 0,
            "violation_points": 0,
            "provisional_violation_points": 0,
            "standing_tier": "GOOD",
        }
    )
    db.drivers[rec["id"]] = rec
    return success(driver_view(rec), status=201)


@bp.get("/drivers/<driver_id>")
def get_driver(driver_id):
    caller = require_auth()
    require_role(caller, "Driver", "PlatformAdmin")
    rec = db.drivers.get(driver_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Driver not found.")
    return success(driver_view(rec))


@bp.post("/drivers/<driver_id>/wallet/topup")
def wallet_topup(driver_id):
    caller = require_auth()
    require_role(caller, "Driver", "PlatformAdmin")
    rec = db.drivers.get(driver_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Driver not found.")
    data = require_body(request.get_json(silent=True))
    amount = require_int(data, "amount_cents")
    if amount <= 0:
        raise err(ERR_INVALID_REQUEST, "amount_cents must be a positive integer.")
    rec["wallet_balance_cents"] += amount
    touch(rec)
    return success(driver_view(rec))


@bp.get("/drivers/<driver_id>/violations")
def list_driver_violations(driver_id):
    caller = require_auth()
    require_role(caller, "Driver", "PlatformAdmin")
    driver = db.drivers.get(driver_id)
    if driver is None:
        raise err(ERR_NOT_FOUND, "Driver not found.")
    limit, offset = parse_pagination(request.args)
    items = [v for v in db.violations.values() if v["driver_id"] == driver_id]
    items.sort(key=lambda v: v["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([violation_view(v) for v in page], limit, offset, total)
