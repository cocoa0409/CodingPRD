"""Ops endpoints: logical clock and the retention sweep (PRD 2.5, 3.7)."""
from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from services import core
from util import CLOCK, parse_dt, fmt_auto
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)

ADMIN = {"ProgramAdmin"}


@bp.post("/_clock/set_current_utc")
def set_clock():
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    authorized(ADMIN)
    new_dt = CLOCK.set(to_iso8601)
    return success_object({"current_utc": fmt_auto(new_dt)})


@bp.post("/_sweeps/retention")
def retention_sweep():
    authorized(ADMIN)
    now = CLOCK.now()
    transitioned = []
    for item in db["items"].values():
        if item["status"] not in ("STORED", "LISTED"):
            continue
        if parse_dt(item["retention_deadline"]) > now:
            continue
        policy = db["retention_policies"].get(item["retention_policy_id"])
        method = policy["disposal_method"] if policy is not None else "DESTRUCTION"
        if method == "AUCTION":
            item["status"] = "AUCTION_ELIGIBLE"
        else:
            item["status"] = "DISPOSAL_PENDING"
            item["pending_disposal_method"] = method
        core.touch(item)
        transitioned.append(item["id"])
    return success_object(
        {"transitioned_count": len(transitioned), "transitioned_item_ids": transitioned}
    )
