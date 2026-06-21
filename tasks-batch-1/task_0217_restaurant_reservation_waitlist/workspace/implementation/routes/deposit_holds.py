"""DepositHold read/list/capture/release routes (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import err, ERR_INVALID_STATE
from middleware import require_roles
from response import object_response, array_response
from services.lookup import get_or_404
from validators import paginate

bp = Blueprint("deposit_holds", __name__)


@bp.get("/deposit-holds/<hid>")
def read_hold(hid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.deposit_holds, hid)
    return object_response(db.serialize(rec), 200)


@bp.get("/deposit-holds")
def list_holds():
    require_roles({"Manager", "Host", "Customer"})
    reservation_id = request.args.get("reservation_id")
    status = request.args.get("status")
    records = []
    for h in db.deposit_holds.values():
        if reservation_id is not None and h["reservation_id"] != reservation_id:
            continue
        if status is not None and h["status"] != status:
            continue
        records.append(h)
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)


@bp.post("/deposit-holds/<hid>/capture")
def capture_hold(hid):
    require_roles({"Manager"})
    rec = get_or_404(db.deposit_holds, hid)
    if rec["status"] != "HELD":
        raise err(ERR_INVALID_STATE, "hold is not HELD")
    res = db.reservations.get(rec["reservation_id"])
    if res is None or res["status"] not in ("NO_SHOW", "CANCELLED") \
            or res["cancellation_fee_cents"] <= 0:
        raise err(ERR_INVALID_STATE, "referenced reservation is not fee-bearing")
    rec["captured_cents"] = res["cancellation_fee_cents"]
    rec["status"] = "CAPTURED"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)


@bp.post("/deposit-holds/<hid>/release")
def release_hold(hid):
    require_roles({"Manager"})
    rec = get_or_404(db.deposit_holds, hid)
    if rec["status"] != "HELD":
        raise err(ERR_INVALID_STATE, "hold is not HELD")
    rec["captured_cents"] = 0
    rec["status"] = "RELEASED"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)
