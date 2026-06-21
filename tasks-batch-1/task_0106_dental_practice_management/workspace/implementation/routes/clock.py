"""Deterministic clock endpoint (PRD §3.9).

Setting the clock drives the time-based system transitions:
  * every recare recall whose next_due_date <= now flips ACTIVE -> DUE
  * every PENDING predetermination whose valid_until_date has passed flips to EXPIRED
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_VALIDATION
from middleware import ROLE_BILLING, ROLE_FRONT_DESK
from response import ok_object
from routes._helpers import guard
from services import calculations, clock, common

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set")
def set_clock():
    guard([ROLE_FRONT_DESK, ROLE_BILLING])
    body = common.get_json_body()
    common.require_fields(body, ["now_iso8601"])
    now_iso = common.require_string(body, "now_iso8601")
    try:
        clock.set_now(now_iso)
    except Exception:
        raise APIError(ERR_VALIDATION, 422, "now_iso8601 must be an ISO 8601 datetime")

    cur = clock.now().date()

    # Recare recalls: next_due_date <= now -> DUE (>= boundary, PRD §3.7, §3.9).
    for rec in db.recare_recalls.values():
        if rec["status"] == "ACTIVE":
            due = clock.parse_date(rec["next_due_date"])
            if cur >= due:
                rec["status"] = "DUE"
                common.touch(rec)

    # PENDING predeterminations past their validity date -> EXPIRED (PRD §3.5, §3.9).
    for pre in db.predeterminations.values():
        if pre["status"] == "PENDING" and pre.get("valid_until_date"):
            valid_until = clock.parse_date(pre["valid_until_date"])
            if cur > valid_until:
                pre["status"] = "EXPIRED"
                common.touch(pre)

    return ok_object({"now_iso8601": now_iso}, 200)
