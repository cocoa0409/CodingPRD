"""Logical clock and daily ops cycle (PRD §2.5)."""
from datetime import timedelta

from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from services.core import jurisdiction_for_tenancy, recompute_tenancy_money, touch
from util import CLOCK, parse_datetime
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/pm/_clock/set_current_utc")
def set_current_utc():
    authorized(["ManagerAdmin"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    return success_object({"current_utc": CLOCK.now_iso()})


@bp.post("/pm/ops/run_daily_cycle")
def run_daily_cycle():
    authorized(["ManagerAdmin"])
    get_body()  # body, when present, must be a JSON object
    flipped = []
    now = CLOCK.now()
    for disb in list(db["disbursements"].values()):
        if disb["status"] != "SENT":
            continue
        tenancy = db["tenancies"].get(disb["tenancy_id"])
        jur = jurisdiction_for_tenancy(tenancy)
        threshold = parse_datetime(disb["sent_at"]) + timedelta(days=jur["stale_check_days"])
        # Strictly-before aging: equality alone does not stale-date a check.
        if threshold < now:
            disb["status"] = "STALE_DATED"
            touch(disb)
            flipped.append(disb["id"])
            recompute_tenancy_money(disb["tenancy_id"])
            touch(tenancy)
    return success_object({
        "stale_dated_count": len(flipped),
        "stale_dated_disbursement_ids": flipped,
    })
