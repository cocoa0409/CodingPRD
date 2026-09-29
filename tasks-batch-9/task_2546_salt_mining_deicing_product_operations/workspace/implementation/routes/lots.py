"""Stockpile lots: read paths and the quarantine dimension."""

from flask import Blueprint

import db
import response
from db import store, touch
from errors import ERR_LOT_STATE_INVALID, fail, invalid
from middleware import auth, require_depot_ownership
from services import derive, serialize
from util import body, boolean, filter_str, require, text

bp = Blueprint("lots", __name__)


@bp.get("/salt/stockpile-lots/<lot_id>")
@auth()
def read_lot(lot_id):
    return response.ok(serialize.lot_json(derive.get_lot(lot_id)))


@bp.get("/salt/stockpile-lots")
@auth()
def list_lots():
    rows = list(store.lots.values())
    for name in ("depot_id", "treatment_batch_id", "product_line", "lot_state"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.lot_json)


@bp.post("/salt/stockpile-lots/<lot_id>/quarantine-state")
@auth("QualityLab", "DepotManager")
def set_quarantine_state(lot_id):
    known = store.lots.get(lot_id)
    if known is not None:
        require_depot_ownership(known["depot_id"])

    payload = body()
    require(payload, ["quarantine"])
    quarantine = boolean(payload, "quarantine", required=True)
    reason = None
    if quarantine:
        require(payload, ["quarantine_reason"])
        reason = text(payload, "quarantine_reason", minlen=1, maxlen=500)

    lot = derive.get_lot(lot_id)
    if quarantine and lot["lot_state"] != "AVAILABLE":
        fail(ERR_LOT_STATE_INVALID,
             "lot_state %s cannot be quarantined" % lot["lot_state"])
    if not quarantine and lot["lot_state"] != "QUARANTINED":
        fail(ERR_LOT_STATE_INVALID,
             "lot_state %s cannot be cleared" % lot["lot_state"])

    if quarantine:
        lot["lot_state"] = "QUARANTINED"
        lot["quarantine_reason"] = reason
    else:
        lot["lot_state"] = "AVAILABLE"
        lot["quarantine_reason"] = None
    touch(lot)
    return response.ok(serialize.lot_json(lot))
