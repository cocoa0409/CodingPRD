"""AccountingPeriod endpoints (§3.2, §3.8)."""

from flask import Blueprint

import lookup
import serializers
import validation
from constants import (
    API_PREFIX,
    CLAIM_WINDOW_DAYS,
    OPEN_REGISTRATION_STATES,
    ROLE_ROYALTY_ADMIN,
)
from db import date_plus_days, db, fmt_dt, now, parse_date, parse_dt, stamp_new, touch
from errors import ApiError
from middleware import require
from response import created_response, object_response
from services import derive

bp = Blueprint("periods", __name__, url_prefix=API_PREFIX)


@bp.post("/periods")
@require(ROLE_ROYALTY_ADMIN)
def create_period():
    data = validation.body()
    label = validation.get_string(data, "label")
    usage_start = validation.get_date(data, "usage_start")
    usage_end = validation.get_date(data, "usage_end")

    for existing in db.periods.values():
        if existing["label"] == label:
            raise ApiError("ERR_DUPLICATE_PERIOD_LABEL")

    if parse_date(usage_end) < parse_date(usage_start):
        raise ApiError("ERR_INVALID_EFFECTIVE_PERIOD")

    closes_at = date_plus_days(usage_end, CLAIM_WINDOW_DAYS)
    record = {
        "label": label,
        "usage_start": usage_start,
        "usage_end": usage_end,
        "claim_window_closes_at": fmt_dt(closes_at),
        "status": "OPEN",
    }
    stamp_new(record)
    db.periods[record["id"]] = record
    return created_response(serializers.accounting_period(record))


@bp.get("/periods/<period_id>")
@require()
def read_period(period_id):
    period = lookup.period(period_id)
    return object_response(serializers.accounting_period(period))


@bp.post("/periods/<period_id>/close")
@require(ROLE_ROYALTY_ADMIN)
def close_period(period_id):
    period = lookup.period(period_id)

    if period["status"] != "DISTRIBUTED":
        raise ApiError("ERR_INVALID_PERIOD_STATE")

    if derive.period_total_holding_cents(period["id"]) != 0:
        raise ApiError("ERR_HOLDING_UNRESOLVED")

    work_ids = set()
    for line in derive.lines_of_period(period["id"]):
        if line["work_id"] is None:
            continue
        work_ids.add(line["work_id"])
        work = db.works.get(line["work_id"])
        if work is not None and work["linked_work_id"]:
            work_ids.add(work["linked_work_id"])
    for registration in db.registrations.values():
        if registration["work_id"] in work_ids \
                and registration["status"] in OPEN_REGISTRATION_STATES:
            raise ApiError("ERR_UNRESOLVED_REGISTRATIONS")

    closes = parse_dt(period["claim_window_closes_at"])
    if closes is not None and now() <= closes:
        raise ApiError(
            "ERR_INVALID_PERIOD_STATE",
            "The claim window of this period has not closed yet.",
        )

    period["status"] = "CLOSED"
    touch(period)
    return object_response(serializers.accounting_period(period))
