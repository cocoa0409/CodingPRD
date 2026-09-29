"""Operational endpoints: the logical clock and the reminder / expiry sweep."""

from flask import Blueprint

import services as svc
import validate as v
from auth import authorise
from db import fmt_ts, parse_ts, store
from errors import ApiError
from response import object_response

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorise("SystemAdmin")
    data = v.body()
    raw = v.req_string(data, "current_utc")
    moment = parse_ts(raw)
    if moment is None:
        v.bad("current_utc", "must be an ISO-8601 UTC instant")
    if moment < store.clock:
        raise ApiError("ERR_CLOCK_REWIND")
    store.clock = moment
    return object_response({"current_utc": fmt_ts(store.clock)}, 200)


@bp.post("/_ops/run-reminder-sweep")
def run_reminder_sweep():
    authorise("SystemAdmin")
    data = v.body()
    journal_id = v.req_id(data, "journal_id")
    journal = store.journals.get(journal_id)
    if journal is None:
        raise ApiError("ERR_JOURNAL_NOT_FOUND")
    return object_response(svc.run_reminder_sweep(journal), 200)
