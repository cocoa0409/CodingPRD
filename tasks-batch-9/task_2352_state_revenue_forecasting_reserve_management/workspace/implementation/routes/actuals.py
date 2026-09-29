"""Posted actual collections and the rolling forecast-error window."""

from flask import Blueprint

from db import db, make_record, now_dt, ordered, touch
from errors import fail
from middleware import authorize, body, req_int, validation
from response import object_response
from routes.helpers import actual_or_404, listing, source_or_404
from services import calc
from util import BPS_SCALE, fy_last_day, rhu

bp = Blueprint("actuals", __name__)

READ_ROLES = ("ForecastDirector", "ExecutiveEconomist", "LegislativeEconomist", "RatingAnalyst")


@bp.get("/actual-collections")
@authorize(*READ_ROLES)
def list_actuals():
    return listing(
        ordered(db.actuals),
        {
            "source_id": ("source_id", str),
            "fiscal_year": ("fiscal_year", int),
            "matched_cycle_id": ("matched_cycle_id", str),
            "error_direction": ("error_direction", str),
        },
    )


@bp.get("/actual-collections/<actual_id>")
@authorize(*READ_ROLES)
def get_actual(actual_id):
    return object_response(actual_or_404(actual_id))


@bp.post("/actual-collections")
@authorize("ForecastDirector", "ExecutiveEconomist")
def create_actual():
    data = body()

    source = None
    if data.get("source_id") is not None:
        if not isinstance(data["source_id"], str):
            validation("source_id must be a string")
        source = source_or_404(data["source_id"])
    if source is None:
        validation("source_id is required")
    fiscal_year = req_int(data, "fiscal_year", minimum=2000, maximum=2100)
    actual_amount = req_int(data, "actual_amount_cents", minimum=0)

    if now_dt().date() <= fy_last_day(fiscal_year):
        fail("ERR_FISCAL_YEAR_NOT_CLOSED",
             "fiscal year %d has not closed yet" % fiscal_year)
    if source["status"] != "ACTIVE":
        fail("ERR_SOURCE_RETIRED", "a RETIRED source may not receive actual collections")

    cycle = calc.matched_cycle_for(fiscal_year)
    forecast = None
    if cycle is not None:
        ratified = db.rounds.get(cycle.get("ratified_round_id"))
        if ratified is not None:
            forecast = calc.reconciled_for_source(ratified, source["id"])
    if cycle is None or forecast is None:
        fail("ERR_NO_CERTIFIED_FORECAST",
             "no certified forecast of fiscal year %d covers this source" % fiscal_year)

    for existing in calc.actuals_of_source(source["id"]):
        if existing["fiscal_year"] == fiscal_year:
            fail("ERR_DUPLICATE_ACTUAL",
                 "an actual collection already exists for that source and fiscal year")

    if forecast == 0:
        error_bps = 0
    else:
        error_bps = rhu(abs(actual_amount - forecast) * BPS_SCALE, forecast)
    if actual_amount < forecast:
        direction = "OVER_FORECAST"
    elif actual_amount > forecast:
        direction = "UNDER_FORECAST"
    else:
        direction = "EXACT"

    rec = make_record(
        {
            "source_id": source["id"],
            "fiscal_year": fiscal_year,
            "actual_amount_cents": actual_amount,
            "matched_cycle_id": cycle["id"],
            "matched_forecast_cents": forecast,
            "abs_pct_error_bps": error_bps,
            "error_direction": direction,
        }
    )
    db.actuals[rec["id"]] = rec

    source["posted_actual_count"] = source["posted_actual_count"] + 1
    source["mape_bps"] = calc.mape_for(source["id"])
    source["methodology_flag"] = source["mape_bps"] >= calc.METHODOLOGY_FLAG_BPS
    touch(source)
    return object_response(rec, 201)
