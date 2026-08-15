"""FundingCycle endpoints (PRD 3.1)."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, check_role
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record
from util import parse_date
from validate import (
    get_body, check_allowed, req_str, req_date,
)

bp = Blueprint("funding_cycles", __name__, url_prefix="/erate")


@bp.post("/funding-cycles")
def create_cycle():
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, {"label", "window_open_date", "window_close_date",
                         "service_delivery_deadline"})
    label = req_str(body, "label")
    window_open = req_date(body, "window_open_date")
    window_close = req_date(body, "window_close_date")
    deadline = req_date(body, "service_delivery_deadline")
    if parse_date(window_close) < parse_date(window_open):
        raise_error(ERR_INVALID_REQUEST,
                    "window_close_date precedes window_open_date")
    rec = new_record("funding_cycles", {
        "label": label,
        "window_open_date": window_open,
        "window_close_date": window_close,
        "service_delivery_deadline": deadline,
    })
    return success_object(public(rec), 201)


@bp.get("/funding-cycles")
def list_cycles():
    return list_collection("funding_cycles")


@bp.get("/funding-cycles/<rid>")
def get_cycle(rid):
    return get_one("funding_cycles", rid)
