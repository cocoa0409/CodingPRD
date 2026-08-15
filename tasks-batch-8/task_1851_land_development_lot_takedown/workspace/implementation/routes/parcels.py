"""Parcel endpoints (PRD 3.1): acquisition under entitlement contingency."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_CONTINGENCY_EXTENSION,
    ERR_PARCEL_INVALID_STATE,
    ERR_CONTINGENCY_EXPIRED,
    ERR_STALE_PARCEL_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch
from util import CLOCK, parse_dt
from validate import get_body, opt_enum, opt_int, req_datetime, req_int, req_str, require_path

bp = Blueprint("parcels", __name__)

ABSORPTION_METHODS = {"STRAIGHT_LINE", "TRAILING_WEIGHTED"}


@bp.post("/parcels")
def create_parcel():
    authorized(["DeveloperOperator"])
    body = get_body()
    rec = new_record("parcels", {
        "parcel_name": req_str(body, "parcel_name"),
        "county": req_str(body, "county"),
        "earnest_money_cents": req_int(body, "earnest_money_cents", non_negative=True),
        "planned_sellout_months": opt_int(body, "planned_sellout_months", 24, non_negative=True),
        "absorption_method": opt_enum(body, "absorption_method", ABSORPTION_METHODS, "STRAIGHT_LINE"),
        "status": "DRAFT",
        "contingency_end_date": None,
        "acquisition_close_date": None,
        "earnest_money_refunded": False,
        "total_lots_planned": 0,
        "lots_closed_count": 0,
        "lots_available_count": 0,
        "closed_pct": 0.0,
        "straight_line_pace_pm": 0.0,
        "trailing_weighted_pace_pm": 0.0,
        "selected_pace_pm": 0.0,
        "projected_months_to_sellout": None,
        "next_phase_release_eligible": False,
    })
    return success_object(public(rec), status=201)


@bp.get("/parcels")
def list_parcels():
    return list_response("parcels", {"status": request.args.get("status")})


@bp.get("/parcels/<rid>")
def get_parcel(rid):
    return get_one("parcels", rid)


@bp.post("/parcels/<rid>/open-contingency")
def open_contingency(rid):
    authorized(["DeveloperOperator"])
    parcel = require_path("parcels", rid)
    body = get_body()
    # Priority 4 (shape): the deadline must fall strictly after the current clock
    end_date = req_datetime(body, "contingency_end_date")
    if parse_dt(end_date) <= CLOCK.now():
        raise_error(ERR_INVALID_REQUEST, "contingency_end_date must be strictly in the future")
    # Priority 6 (state)
    if parcel["status"] != "DRAFT":
        raise_error(ERR_PARCEL_INVALID_STATE, "open-contingency requires DRAFT")
    parcel["status"] = "CONTINGENCY_ACTIVE"
    parcel["contingency_end_date"] = end_date
    touch(parcel)
    return success_object(public(parcel))


@bp.post("/parcels/<rid>/extend-contingency")
def extend_contingency(rid):
    authorized(["DeveloperOperator"])
    parcel = require_path("parcels", rid)
    body = get_body()
    # Priority 4 (shape): both fields are non-optional (PRD 2.7)
    new_end = req_datetime(body, "new_contingency_end_date")
    expected = req_int(body, "expected_parcel_version")
    if (parcel["contingency_end_date"] is not None
            and parse_dt(new_end) <= parse_dt(parcel["contingency_end_date"])):
        raise_error(ERR_INVALID_CONTINGENCY_EXTENSION,
                    "new_contingency_end_date must be strictly later than the current deadline")
    # Priority 5 (OCC) — before the state check (PRD 2.8)
    if expected != parcel["version"]:
        raise_error(ERR_STALE_PARCEL_VERSION, "expected_parcel_version does not match Parcel.version")
    # Priority 6 (state)
    if parcel["status"] != "CONTINGENCY_ACTIVE":
        raise_error(ERR_PARCEL_INVALID_STATE, "extend-contingency requires CONTINGENCY_ACTIVE")
    parcel["contingency_end_date"] = new_end
    touch(parcel)
    return success_object(public(parcel))


@bp.post("/parcels/<rid>/clear-contingency")
def clear_contingency(rid):
    authorized(["DeveloperOperator"])
    parcel = require_path("parcels", rid)
    # Priority 6 (state)
    if parcel["status"] != "CONTINGENCY_ACTIVE":
        raise_error(ERR_PARCEL_INVALID_STATE, "clear-contingency requires CONTINGENCY_ACTIVE")
    # Priority 8 (temporal): the deadline is inclusive
    if CLOCK.now() > parse_dt(parcel["contingency_end_date"]):
        raise_error(ERR_CONTINGENCY_EXPIRED, "contingency deadline has passed")
    parcel["status"] = "ACQUIRED"
    parcel["acquisition_close_date"] = CLOCK.now_iso()
    touch(parcel)
    return success_object(public(parcel))


@bp.post("/parcels/<rid>/terminate-contingency")
def terminate_contingency(rid):
    authorized(["DeveloperOperator"])
    parcel = require_path("parcels", rid)
    # Priority 6 (state): an auto-expired parcel is TERMINATED, so a late manual
    # termination surfaces ERR_PARCEL_INVALID_STATE (PRD 3.1)
    if parcel["status"] != "CONTINGENCY_ACTIVE":
        raise_error(ERR_PARCEL_INVALID_STATE, "terminate-contingency requires CONTINGENCY_ACTIVE")
    parcel["status"] = "TERMINATED"
    parcel["earnest_money_refunded"] = True
    touch(parcel)
    return success_object(public(parcel))
