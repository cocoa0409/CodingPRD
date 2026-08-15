"""AccountingPeriod endpoints (PRD 3.2, 3.9)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_PERIOD_ALREADY_OPEN,
    ERR_PERIOD_NOT_ADJACENT, ERR_PERIOD_REOPEN_NOT_LATEST,
)
from middleware import authorized
from response import success_object
from services.core import new_record, serialize_period, current_open_period, latest_period
from services.period_close import close_period, reopen_period
from util import parse_date
from validate import get_body, req_int, req_date, require_path_resource
from routes.helpers import list_response, get_one

bp = Blueprint("accounting_periods", __name__)


@bp.route("/ucp/accounting-periods", methods=["POST"])
def create_period():
    authorized(["SystemAdmin"])
    body = get_body()
    # Priority 4 — shape.
    fiscal_year = req_int(body, "fiscal_year")
    period_no = req_int(body, "period_no", minimum=1)
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    start_d = parse_date(start_date)
    end_d = parse_date(end_date)
    if end_d < start_d:
        raise_error(ERR_VALIDATION, "end_date precedes start_date")
    # Priority 7 — at most one period in OPEN or REOPENED at any time:
    # creation requires every existing period already CLOSED.
    if current_open_period() is not None:
        raise_error(ERR_PERIOD_ALREADY_OPEN, "another period is OPEN or REOPENED")
    # Priority 9 — strict adjacency to the latest existing period
    # (first period may begin on any date).
    latest = latest_period()
    if latest is not None and start_d != latest["_end"] + timedelta(days=1):
        raise_error(
            ERR_PERIOD_NOT_ADJACENT,
            "start_date must equal the latest period's end_date + 1 day",
        )

    rec = new_record()
    rec.update({
        "fiscal_year": fiscal_year,
        "period_no": period_no,
        "start_date": start_date,
        "end_date": end_date,
        "status": "OPEN",
        "closed_at": None,
        "_start": start_d,
        "_end": end_d,
    })
    db["accounting_periods"][rec["id"]] = rec
    return success_object(serialize_period(rec), status=201)


@bp.route("/ucp/accounting-periods/<period_id>", methods=["GET"])
def get_period(period_id):
    return get_one("accounting_periods", serialize_period, period_id)


@bp.route("/ucp/accounting-periods", methods=["GET"])
def list_periods():
    filters = {
        "fiscal_year": request.args.get("fiscal_year"),
        "status": request.args.get("status"),
    }
    return list_response("accounting_periods", serialize_period, filters)


@bp.route("/ucp/accounting-periods/<period_id>/close", methods=["POST"])
def close_period_endpoint(period_id):
    authorized(["Controller"])
    period = require_path_resource("accounting_periods", period_id)
    # Valid from OPEN or REOPENED; re-close recomputes all accruals fresh.
    if period["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_INVALID_STATE, "period is not OPEN or REOPENED")
    close_period(period)
    return success_object(serialize_period(period))


@bp.route("/ucp/accounting-periods/<period_id>/reopen", methods=["POST"])
def reopen_period_endpoint(period_id):
    authorized(["Controller"])
    period = require_path_resource("accounting_periods", period_id)
    # Guard 1 — no period may currently stand OPEN or REOPENED.
    if current_open_period() is not None:
        raise_error(ERR_PERIOD_ALREADY_OPEN, "another period is OPEN or REOPENED")
    # Guard 2 — target must be the most recently created CLOSED period.
    latest = latest_period()
    if period["status"] != "CLOSED" or latest is None or latest["id"] != period["id"]:
        raise_error(ERR_PERIOD_REOPEN_NOT_LATEST, "only the most recently created CLOSED period may be reopened")
    reopen_period(period)
    return success_object(serialize_period(period))
