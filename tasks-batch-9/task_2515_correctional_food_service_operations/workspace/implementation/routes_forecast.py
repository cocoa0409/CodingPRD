"""Population counts and meal forecasts (PRD 3.4)."""
from flask import Blueprint

from core import (
    ApiError, Field, ROLE_COMPLIANCE_AUDITOR, ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_CORRECTIONAL_OFFICER, ROLE_FOOD_SERVICE_SUPERVISOR,
    ROLE_REGISTERED_DIETITIAN, all_rows, authorize, base_row, body_json,
    filter_eq, insert, listing, now_logical, parse_date, public,
    respond_object, touch, validate_fields,
)
from calc import (
    expire_due_orders, facility_cycles, forecast_trays, roster_segments,
    rows_where, special_diet_trays_for,
)
from ops import (
    census_after_diet_change, need_facility, need_forecast,
    need_population_count, not_terminal,
)

bp = Blueprint("forecast", __name__, url_prefix="/cfs")

MEAL_SLOTS = ("BREAKFAST", "LUNCH", "DINNER")
COUNT_SOURCES = ("FORMAL_COUNT", "EMERGENCY_COUNT")
FORECAST_VARIANTS = ("COUNT_DRIVEN", "ROSTER_DRIVEN")
FORECAST_TERMINAL = ("LOCKED", "SUPERSEDED")
FORECAST_LIVE = ("DRAFT", "LOCKED")

COUNT_READ_ROLES = (ROLE_CORRECTIONAL_OFFICER, ROLE_FOOD_SERVICE_SUPERVISOR,
                    ROLE_COMPLIANCE_AUDITOR)
FORECAST_READ_ROLES = (ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_CONTRACT_ADMINISTRATOR,
                       ROLE_COMPLIANCE_AUDITOR, ROLE_REGISTERED_DIETITIAN)


# --------------------------------------------------------------------------
# Population counts (immutable ledger rows: no updated_at, no version)
# --------------------------------------------------------------------------
@bp.route("/population-counts", methods=["POST"])
def create_population_count():
    actor = authorize(ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [
        Field("facility_id", "string", required=True),
        Field("general_population", "integer", required=True, min_inclusive=0),
        Field("segregation_population", "integer", required=True, min_inclusive=0),
        Field("satellite_population", "integer", required=True, min_inclusive=0),
        Field("medical_population", "integer", required=True, min_inclusive=0),
        Field("source", "string", required=True, enum=COUNT_SOURCES),
    ])
    facility = need_facility(body["facility_id"])
    segments = [body["general_population"], body["segregation_population"],
                body["satellite_population"], body["medical_population"]]
    row = base_row(with_version=False)
    row.update({
        "facility_id": facility["id"],
        "general_population": segments[0],
        "segregation_population": segments[1],
        "satellite_population": segments[2],
        "medical_population": segments[3],
        "source": body["source"],
        "total_population": sum(segments),
        "count_at": now_logical(),
        "submitted_by_user_id": actor.user_id,
    })
    insert("population_counts", row)
    return respond_object(public(row), 201)


@bp.route("/population-counts/<row_id>", methods=["GET"])
def read_population_count(row_id):
    authorize(*COUNT_READ_ROLES)
    return respond_object(public(need_population_count(row_id)), 200)


@bp.route("/population-counts", methods=["GET"])
def list_population_counts():
    authorize(*COUNT_READ_ROLES)
    rows = filter_eq(all_rows("population_counts"), "facility_id")
    rows = filter_eq(rows, "source")
    return listing(rows)


# --------------------------------------------------------------------------
# Meal forecasts
# --------------------------------------------------------------------------
@bp.route("/meal-forecasts", methods=["POST"])
def create_forecast():
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("facility_id", "string", required=True),
        Field("population_count_id", "string", required=True),
        Field("service_date", "date", required=True),
        Field("meal_slot", "string", required=True, enum=MEAL_SLOTS),
        Field("forecast_variant", "string", required=True, enum=FORECAST_VARIANTS),
    ])
    facility = need_facility(body["facility_id"])
    count = need_population_count(body["population_count_id"])
    service_date = body["service_date"]
    meal_slot = body["meal_slot"]
    for existing in rows_where("meal_forecasts", facility_id=facility["id"]):
        if (existing["service_date"] == service_date
                and existing["meal_slot"] == meal_slot
                and existing["status"] in FORECAST_LIVE):
            raise ApiError("ERR_DUPLICATE_FORECAST")

    # The expiry sweep runs before a single special diet tray is counted.
    expired = expire_due_orders(facility["id"])
    if expired:
        inmates = [r for r in all_rows("inmates") if r["facility_id"] == facility["id"]]
        census_after_diet_change(inmates, [facility])

    variant = body["forecast_variant"]
    if variant == "COUNT_DRIVEN":
        segments = count
    else:
        segments = roster_segments(facility["id"])
    trays = forecast_trays(segments)

    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "population_count_id": count["id"],
        "service_date": service_date,
        "meal_slot": meal_slot,
        "forecast_variant": variant,
        "status": "DRAFT",
        "line_trays": trays["line_trays"],
        "waste_allowance_trays": trays["waste_allowance_trays"],
        "total_forecast_trays": trays["total_forecast_trays"],
        "forecast_special_diet_trays": special_diet_trays_for(facility["id"], service_date),
        "locked_at": None,
    })
    insert("meal_forecasts", row)
    return respond_object(public(row), 201)


@bp.route("/meal-forecasts/<row_id>", methods=["GET"])
def read_forecast(row_id):
    authorize(*FORECAST_READ_ROLES)
    return respond_object(public(need_forecast(row_id)), 200)


@bp.route("/meal-forecasts", methods=["GET"])
def list_forecasts():
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_CONTRACT_ADMINISTRATOR,
              ROLE_COMPLIANCE_AUDITOR)
    rows = filter_eq(all_rows("meal_forecasts"), "facility_id")
    rows = filter_eq(rows, "population_count_id")
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "service_date")
    return listing(rows)


@bp.route("/meal-forecasts/<row_id>/lock", methods=["POST"])
def lock_forecast(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    forecast = need_forecast(row_id)
    not_terminal(forecast, "status", FORECAST_TERMINAL)
    now = now_logical()
    service_day = parse_date(forecast["service_date"])
    if service_day is not None and service_day.date() < now.date():
        raise ApiError("ERR_FORECAST_DATE_PAST")
    if not any(c["status"] == "ACTIVE" for c in facility_cycles(forecast["facility_id"])):
        raise ApiError("ERR_NO_ACTIVE_MENU_CYCLE")
    forecast["status"] = "LOCKED"
    forecast["locked_at"] = now
    touch(forecast)
    return respond_object(public(forecast), 200)
