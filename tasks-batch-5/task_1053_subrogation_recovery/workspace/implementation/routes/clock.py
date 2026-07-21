"""Logical clock control and the statute-and-window sweep (§2.6, §3.9)."""
from flask import Blueprint, request

import validate as v
from auth import authorize
from cascade import withdraw_open_demands, withdraw_live_arbitrations
from envelope import success
from store import db, touch
from timeutil import parse_iso

bp = Blueprint("clock", __name__)

NON_TERMINAL_CLAIM = {"REFERRED", "LIABILITY_ASSESSED", "DEMAND_ISSUED", "ARBITRATION"}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize(request, {"System"})
    body = v.get_body(request)
    to_iso = v.req_datetime(body, "to_iso8601")
    now = parse_iso(to_iso)
    db.clock = now

    # Part 1: statute expiry for non-terminal claims (with declared cascades).
    for claim in db.claims.values():
        if claim["status"] not in NON_TERMINAL_CLAIM:
            continue
        if now >= parse_iso(claim["statute_deadline"]):
            prev = claim["status"]
            claim["status"] = "STATUTE_EXPIRED"
            touch(claim)
            if prev == "DEMAND_ISSUED":
                withdraw_open_demands(claim["id"])
            elif prev == "ARBITRATION":
                withdraw_live_arbitrations(claim["id"])

    # Part 2: demand response-window expiry for still-open ISSUED demands.
    for demand in db.demands.values():
        if demand["status"] == "ISSUED" and demand["outcome"] is None:
            if now >= demand["response_due_at"]:
                demand["status"] = "EXPIRED"
                touch(demand)

    return success({}, "object", 200)
