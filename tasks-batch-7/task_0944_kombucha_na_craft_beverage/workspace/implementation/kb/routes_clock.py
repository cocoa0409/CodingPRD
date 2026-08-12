"""POST /_clock/set_current_utc -- the logical clock and its three sweeps."""

from flask import Blueprint

from .auth import authorize
from .calc import recompute_shipment_aging
from .envelope import raw_object_response
from .errors import ApiError
from .store import collection_sorted, db, touch
from .util import render_instant
from .validate import body_dict, field, parse_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize("PlatformAdmin")
    payload = body_dict()
    data = parse_body(payload, [field("to_iso8601", "datetime", required=True)])
    target = data["to_iso8601"]

    # rung 23 -- time never runs backwards; equal to the current clock is fine
    if target < db.clock:
        raise ApiError(
            "ERR_VALIDATION", "The logical clock may not be moved backwards."
        )

    db.clock = target

    expired_count = 0
    for lot in collection_sorted(
        db.ingredient_lots,
        lambda l: l["status"] in ("AVAILABLE", "PARTIALLY_CONSUMED"),
    ):
        if lot["expiry_date"] is not None and lot["expiry_date"] < target:
            lot["status"] = "EXPIRED"
            touch(lot)
            expired_count += 1

    overdue_count = 0
    for notice in collection_sorted(
        db.recall_notices, lambda n: n["status"] == "PENDING"
    ):
        if notice["ack_deadline_at"] is not None and notice["ack_deadline_at"] < target:
            notice["status"] = "OVERDUE"
            touch(notice)
            overdue_count += 1

    for shipment in collection_sorted(
        db.shipments, lambda s: s["status"] == "DELIVERED"
    ):
        recompute_shipment_aging(shipment)

    return raw_object_response(
        {
            "current_utc": render_instant(db.clock),
            "expired_ingredient_lot_count": expired_count,
            "overdue_recall_notice_count": overdue_count,
        }
    )
