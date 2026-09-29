"""Forecasting the day and sizing the team -- PRD 3.2."""

from decimal import Decimal

from flask import Blueprint, request

import derive
from auth import HOUSEKEEPING_DIRECTOR, authenticate
from envelope import created, filtered, ok, paginate
from errors import ApiError
from serialize import forecast_day_out
from store import STORE, base_record, touch
from timeutil import format_iso_date
from validate import read_body, vdate, vint, vstr

bp = Blueprint("forecast", __name__)


@bp.post("/housekeeping/forecast-days")
def create_forecast_day():
    authenticate((HOUSEKEEPING_DIRECTOR,))
    body = read_body()
    property_id = vstr(body, "property_id", 1, None)
    business_date = vdate(body, "business_date")
    forecast_occupied_rooms = vint(body, "forecast_occupied_rooms", 0, 5000)
    forecast_arrivals = vint(body, "forecast_arrivals", 0, 5000)
    forecast_departures = vint(body, "forecast_departures", 0, 5000)
    planned_deep_clean_rooms = vint(
        body, "planned_deep_clean_rooms", 0, 5000, required=False, default=0
    )
    if forecast_arrivals > forecast_occupied_rooms:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "forecast_arrivals must not exceed forecast_occupied_rooms.",
        )

    prop = derive.get_property(STORE, property_id)

    for existing in STORE.forecast_days.values():
        if existing["property_id"] == prop["id"] and existing["business_date"] == business_date:
            raise ApiError(
                "ERR_FORECAST_DAY_DUPLICATE",
                "A forecast day already exists for %s at this property."
                % format_iso_date(business_date),
            )

    # PRD 3.2: the business date must not be earlier than the property's own
    # creation date.
    if business_date < prop["created_at"].date():
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "business_date is earlier than the property's creation date.",
        )

    row = base_record(STORE)
    row.update({
        "property_id": prop["id"],
        "business_date": business_date,
        "forecast_occupied_rooms": forecast_occupied_rooms,
        "forecast_arrivals": forecast_arrivals,
        "forecast_departures": forecast_departures,
        "planned_deep_clean_rooms": planned_deep_clean_rooms,
        "status": "DRAFT",
        "projected_required_credits": Decimal("0.00"),
        "required_attendants": 0,
        "allocated_credits_total": Decimal("0.00"),
        "actual_reconciled_credits": None,
        "credit_variance_pct": None,
    })
    projected = derive.projected_required_credits(STORE, prop, row)
    row["projected_required_credits"] = projected
    row["required_attendants"] = derive.required_attendant_headcount(prop, projected)
    STORE.forecast_days[row["id"]] = row
    return created(forecast_day_out(STORE, row))


@bp.get("/housekeeping/forecast-days/<fid>")
def read_forecast_day(fid):
    authenticate(None)
    row = derive.get_forecast_day(STORE, fid)
    return ok(forecast_day_out(STORE, row))


@bp.get("/housekeeping/forecast-days")
def list_forecast_days():
    authenticate(None)
    rows = filtered(
        list(STORE.forecast_days.values()),
        request.args,
        {
            "property_id": ("property_id", None),
            "status": ("status", None),
            "business_date": ("business_date", format_iso_date),
        },
    )
    return paginate(rows, request.args, lambda r: forecast_day_out(STORE, r))


@bp.post("/housekeeping/forecast-days/<fid>/publish")
def publish_forecast_day(fid):
    authenticate((HOUSEKEEPING_DIRECTOR,))
    day = derive.get_forecast_day(STORE, fid)
    if day["status"] == "CLOSED":
        raise ApiError("ERR_FORECAST_ALREADY_CLOSED", "Forecast day is already closed.")
    if day["status"] != "DRAFT":
        raise ApiError("ERR_FORECAST_NOT_DRAFT", "Forecast day is not in DRAFT.")

    prop = STORE.properties[day["property_id"]]
    # Publishing re-runs the projection against the CURRENT room inventory, so rooms
    # and room types added after the day was drafted are included.
    projected = derive.projected_required_credits(STORE, prop, day)
    day["projected_required_credits"] = projected
    day["required_attendants"] = derive.required_attendant_headcount(prop, projected)
    day["status"] = "PUBLISHED"
    touch(STORE, day)
    return ok(forecast_day_out(STORE, day))


@bp.post("/housekeeping/forecast-days/<fid>/close")
def close_forecast_day(fid):
    authenticate((HOUSEKEEPING_DIRECTOR,))
    day = derive.get_forecast_day(STORE, fid)
    if day["status"] == "CLOSED":
        raise ApiError("ERR_FORECAST_ALREADY_CLOSED", "Forecast day is already closed.")
    if day["status"] != "PUBLISHED":
        raise ApiError("ERR_FORECAST_NOT_PUBLISHED", "Forecast day is not PUBLISHED.")

    for roster in derive.rosters_of_forecast_day(STORE, day["id"]):
        if roster["status"] in ("PLANNED", "CLOCKED_IN"):
            raise ApiError(
                "ERR_ROSTER_STILL_OPEN",
                "Roster %s has not been closed yet." % roster["id"],
            )

    actual = derive.actual_reconciled_credits(STORE, day)
    day["actual_reconciled_credits"] = actual
    day["credit_variance_pct"] = derive.credit_variance_pct(
        day["projected_required_credits"], actual
    )
    day["status"] = "CLOSED"
    touch(STORE, day)
    return ok(forecast_day_out(STORE, day))
