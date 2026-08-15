"""Holiday calendar endpoints (PRD §2.5/§3.1).

HolidayCalendarEntry carries only id and created_at — no updated_at, no version
(common_fields: false); entries are never modified after registration.
"""
from flask import Blueprint

from db import db, next_insertion_seq
from errors import raise_error, ERR_DUPLICATE
from middleware import authorize
from response import success_object
from services.core import list_response, serialize_holiday
from util import CLOCK, fmt_dt, fmt_dt_ms, new_id
from validate import Payload

bp = Blueprint("holidays", __name__)


@bp.post("/er/holiday-calendar")
def create_holiday():
    authorize({"ERManager"})
    from flask import request
    p = Payload(request.get_json(silent=True))
    holiday_dt = p.get_dt("holiday_date", required=True)
    label = p.get_str("label", required=True)

    # priority 15 — holiday_date unique (point equality on the calendar date)
    if holiday_dt is not None:
        for h in db["holidays"].values():
            if h["_date"] == holiday_dt.date():
                raise_error(ERR_DUPLICATE,
                            f"holiday_date {fmt_dt(holiday_dt)} already registered")

    # priority 24
    p.raise_if_errors()

    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "holiday_date": fmt_dt(holiday_dt),
        "label": label,
        "created_at": fmt_dt_ms(now),
        "_created_dt": now,
        "_seq": next_insertion_seq(),
        "_date": holiday_dt.date(),
    }
    db["holidays"][rec["id"]] = rec
    return success_object(serialize_holiday(rec), status=201)


@bp.get("/er/holiday-calendar")
def list_holidays():
    authorize({"ERManager", "Investigator", "LegalCounsel", "HRAnalyst"})
    return list_response(list(db["holidays"].values()), serialize_holiday)
