"""Logical clock endpoint and its three deterministic sweeps (PRD 2.5)."""

from flask import Blueprint

import db
import middleware as mw
import response
import validate
from db import touch, sort_rows
from errors import ApiError
from services import calc

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # The only endpoint exempt from authentication and role authorisation.
    values = validate.parse(
        mw.body(), {"current_utc": {"type": "instant", "required": True}}
    )
    proposed = db.parse_instant(values["current_utc"])
    if proposed <= db.db.clock:
        raise ApiError(
            "ERR_CLOCK_NOT_MONOTONIC",
            "current_utc must be strictly later than the stored clock",
        )
    db.db.clock = proposed
    today = db.today()

    expired_offer_count = 0
    for offer in sort_rows(list(db.db.offers.values())):
        if offer["status"] != "ACTIVE":
            continue
        if db.parse_date(offer["expiration_date"]) < today:
            offer["status"] = "EXPIRED"
            touch(offer)
            expired_offer_count += 1

    expired_clip_count = 0
    for clip in sort_rows(list(db.db.clips.values())):
        if clip["status"] != "CLIPPED":
            continue
        if db.parse_date(clip["clip_expires_at"]) < today:
            clip["status"] = "EXPIRED_UNUSED"
            touch(clip)
            expired_clip_count += 1

    withdrawn_dispute_count = 0
    for dispute in sort_rows(list(db.db.disputes.values())):
        if dispute["status"] not in ("UNDER_REVIEW", "INFO_REQUESTED"):
            continue
        filed = db.parse_instant(dispute["filed_at"])
        if filed is None:
            continue
        if db.add_days(filed.date(), calc.DISPUTE_SLA_DAYS) < today:
            dispute["status"] = "WITHDRAWN"
            touch(dispute)
            lot = db.db.lots.get(dispute["lot_id"])
            if lot is not None and lot["status"] == "DISPUTED":
                lot["status"] = "LOT_REJECTED"
                lot["reject_reason"] = "DISPUTE_UPHELD"
                touch(lot)
            withdrawn_dispute_count += 1

    return response.object_response(
        {
            "current_utc": db.now_iso(),
            "expired_offer_count": expired_offer_count,
            "expired_clip_count": expired_clip_count,
            "withdrawn_dispute_count": withdrawn_dispute_count,
        }
    )
