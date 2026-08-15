"""Win-rate analytics (PRD 3.9): decided representments only; PARTIAL_WON = half a win."""

from flask import Blueprint, g, request

from db import db
from middleware import is_merchant_user
from response import ok_object
from routes.common import ALL_ROLES, authenticate
from util import NETWORKS, filter_enum, rhu

bp = Blueprint("analytics", __name__)


@bp.get("/acquirer/analytics/win-rate")
def win_rate():
    authenticate(ALL_ROLES)
    merchant_id = request.args.get("merchant_id")
    reason_code = request.args.get("reason_code")
    network = filter_enum(request.args, "network", NETWORKS)
    if is_merchant_user():
        merchant_id = g.uid  # force-scoped to the caller's own merchant

    decided = []
    for rep in db.representments.values():
        if rep["status"] not in ("WON", "PARTIAL_WON", "LOST"):
            continue
        cb = db.chargebacks.get(rep["chargeback_id"])
        if cb is None:
            continue
        if merchant_id is not None and cb["merchant_id"] != merchant_id:
            continue
        if reason_code is not None and cb["reason_code"] != reason_code:
            continue
        if network is not None and cb["network"] != network:
            continue
        decided.append(rep)

    won = sum(1 for r in decided if r["status"] == "WON")
    partial = sum(1 for r in decided if r["status"] == "PARTIAL_WON")
    lost = sum(1 for r in decided if r["status"] == "LOST")
    total = len(decided)
    rate = None if total == 0 else rhu(10000 * (2 * won + partial), 2 * total)
    return ok_object({
        "decided_count": total,
        "won_count": won,
        "partial_win_count": partial,
        "lost_count": lost,
        "win_rate_bps": rate,
    })
