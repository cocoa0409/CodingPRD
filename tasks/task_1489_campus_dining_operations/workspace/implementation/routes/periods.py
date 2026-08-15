"""MealPeriodService, SwipeEvent ingestion, forecast create, waste-log create."""
from decimal import Decimal

from flask import Blueprint

from db import DB, logical_now_str, new_id, next_seq, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_array
from services import (
    ENTRY_TYPES,
    FORECAST_VARIANTS,
    MEAL_PERIODS,
    WASTE_CATEGORIES,
    WASTE_DISPOSITIONS,
    _kg2,
    c1_base_covers,
    c1_forecast_portions,
    c8_reconcile,
    get_cycle,
    get_hall,
    get_period,
    get_recipe,
    get_swipe,
    ser,
    stamp,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_iso_date,
    as_list,
    as_num,
    as_str,
    body,
    parse_ymd,
    required,
)
from routes.common import list_endpoint

bp = Blueprint("periods", __name__)


@bp.post("/meal-periods")
def create_period():
    auth(["HallManager"])
    data = body()
    # Body FK existence in declared input order: dining_hall_id -> menu_cycle_id.
    dining_hall_id = required(data, "dining_hall_id")
    if isinstance(dining_hall_id, str):
        get_hall(dining_hall_id)
    menu_cycle_id = required(data, "menu_cycle_id")
    cycle = get_cycle(menu_cycle_id) if isinstance(menu_cycle_id, str) else None
    service_date = as_iso_date(required(data, "service_date"), "service_date")
    meal_period = as_enum(required(data, "meal_period"), "meal_period", MEAL_PERIODS)
    if not isinstance(dining_hall_id, str):
        raise ApiError("ERR_VALIDATION", 400, "dining_hall_id must be a string")
    if cycle is None:
        raise ApiError("ERR_VALIDATION", 400, "menu_cycle_id must be a string")
    # The named cycle must govern this hall, be PUBLISHED, and cover the date.
    if (
        cycle["dining_hall_id"] != dining_hall_id
        or cycle["status"] != "PUBLISHED"
        or not (
            parse_ymd(cycle["start_date"])
            <= parse_ymd(service_date)
            < parse_ymd(cycle["end_date"])
        )
    ):
        raise ApiError(
            "ERR_VALIDATION",
            400,
            "Menu cycle must be PUBLISHED and cover the service date",
        )
    rec = {
        "id": new_id(),
        "dining_hall_id": dining_hall_id,
        "menu_cycle_id": menu_cycle_id,
        "service_date": service_date,
        "meal_period": meal_period,
        "status": "SCHEDULED",
        "forecasted_covers": 0,
        "actual_board_swipes": 0,
        "actual_retail_sales_cents": 0,
        "actual_covers": 0,
        "forecast_variance_pct": None,
        "posted_waste_kg": 0,
        "landfill_waste_kg": 0,
        "diversion_rate": None,
        "sustainability_alert": False,
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["meal_periods"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/meal-periods")
def list_periods():
    return list_endpoint(
        "meal_periods",
        [
            ("dining_hall_id", "dining_hall_id"),
            ("menu_cycle_id", "menu_cycle_id"),
            ("service_date", "service_date"),
            ("meal_period", "meal_period"),
            ("status", "status"),
        ],
    )


@bp.get("/meal-periods/<pid>")
def get_one_period(pid):
    auth(ALL_ROLES)
    return ok(ser(get_period(pid)))


@bp.post("/meal-periods/<pid>/lock-forecast")
def lock_forecast(pid):
    auth(["HallManager"])
    period = get_period(pid)
    if period["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Period is not SCHEDULED")
    forecasts = [f for f in DB["forecasts"].values() if f["meal_period_id"] == pid]
    if not forecasts or any(f["status"] == "DRAFT" for f in forecasts):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Period needs at least one forecast and no DRAFT forecasts",
        )
    period["forecasted_covers"] = c1_base_covers(period, "BASE")
    period["status"] = "FORECAST_LOCKED"
    touch(period)
    return ok(ser(period))


@bp.post("/meal-periods/<pid>/open-service")
def open_service(pid):
    auth(["HallManager"])
    period = get_period(pid)
    if period["status"] != "FORECAST_LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Period is not FORECAST_LOCKED")
    hall = get_hall(period["dining_hall_id"])
    if hall["status"] != "ACTIVE":
        raise ApiError("ERR_HALL_SUSPENDED", 409, "Dining hall is not ACTIVE")
    period["status"] = "IN_SERVICE"
    touch(period)
    return ok(ser(period))


@bp.post("/meal-periods/<pid>/reconcile")
def reconcile(pid):
    auth(["HallManager"])
    period = get_period(pid)
    if period["status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409, "Period is not IN_SERVICE")
    c8_reconcile(period)
    period["status"] = "RECONCILED"
    touch(period)
    return ok(ser(period))


@bp.post("/meal-periods/<pid>/close")
def close_period(pid):
    auth(["DiningAdmin"])
    period = get_period(pid)
    if period["status"] != "RECONCILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Period is not RECONCILED")
    for w in DB["waste_logs"].values():
        if w["meal_period_id"] == pid and w["status"] in ("RECORDED", "VERIFIED"):
            raise ApiError(
                "ERR_PENDING_WASTE_LOGS",
                409,
                "Period still has RECORDED or VERIFIED waste logs",
            )
    period["status"] = "CLOSED"
    touch(period)
    return ok(ser(period))


# ---------------------------------------------------------------------------
# SwipeEvent bulk ingestion
# ---------------------------------------------------------------------------

@bp.post("/meal-periods/<pid>/swipes")
def ingest_swipes(pid):
    auth(["HallManager"])
    period = get_period(pid)
    if period["status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409, "Period is not IN_SERVICE")
    data = body()
    events = as_list(required(data, "events"), "events")
    # All-or-nothing: validate every element before persisting anything.
    expanded = []
    for el in events:
        if not isinstance(el, dict):
            raise ApiError("ERR_VALIDATION", 400, "Each event must be an object")
        entry_type = as_enum(required(el, "entry_type"), "entry_type", ENTRY_TYPES)
        amount = as_int(required(el, "amount_cents"), "amount_cents")
        if entry_type == "RETAIL_SALE" and amount <= 0:
            raise ApiError(
                "ERR_VALIDATION", 400, "RETAIL_SALE amount_cents must be > 0"
            )
        if entry_type == "BOARD_SWIPE" and amount != 0:
            raise ApiError(
                "ERR_VALIDATION", 400, "BOARD_SWIPE amount_cents must be 0"
            )
        count = el.get("count", 1)
        if count is None:
            count = 1
        count = as_int(count, "count")
        if count < 1:
            raise ApiError("ERR_VALIDATION", 400, "count must be >= 1")
        expanded.append((entry_type, amount, count))
    created = []
    for entry_type, amount, count in expanded:
        for _ in range(count):
            rec = {
                "id": new_id(),
                "meal_period_id": pid,
                "entry_type": entry_type,
                "amount_cents": amount,
                "recorded_at": logical_now_str(),
                "created_at": now_iso(),
                "_seq": next_seq(),
            }
            DB["swipe_events"][rec["id"]] = rec
            created.append(ser(rec))
    return ok_array(created, status=201)


@bp.get("/swipe-events")
def list_swipes():
    return list_endpoint(
        "swipe_events",
        [("meal_period_id", "meal_period_id"), ("entry_type", "entry_type")],
    )


@bp.get("/swipe-events/<sid>")
def get_one_swipe(sid):
    auth(ALL_ROLES)
    return ok(ser(get_swipe(sid)))


# ---------------------------------------------------------------------------
# ProductionForecast creation (nested under the period)
# ---------------------------------------------------------------------------

@bp.post("/meal-periods/<pid>/forecasts")
def create_forecast(pid):
    auth(["KitchenLead"])
    period = get_period(pid)
    data = body()
    recipe_id = required(data, "recipe_id")
    recipe = get_recipe(recipe_id) if isinstance(recipe_id, str) else None
    # Tier 4 state gate: parent period must still be SCHEDULED.
    if period["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_FORECAST_LOCKED_PERIOD", 409, "Period is no longer SCHEDULED"
        )
    # OCC: expected_meal_period_version, checked immediately after from-state.
    expected = required(data, "expected_meal_period_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(
            "ERR_VALIDATION", 400, "expected_meal_period_version must be an integer"
        )
    if expected != period["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_meal_period_version does not match the period version",
        )
    if recipe is None:
        raise ApiError("ERR_VALIDATION", 400, "recipe_id must be a string")
    # Tier 7: at most one DRAFT forecast per (meal_period_id, recipe_id).
    for f in DB["forecasts"].values():
        if (
            f["meal_period_id"] == pid
            and f["recipe_id"] == recipe_id
            and f["status"] == "DRAFT"
        ):
            raise ApiError(
                "ERR_DUPLICATE_FORECAST",
                409,
                "A DRAFT forecast already exists for this period and recipe",
            )
    # The recipe must be ACTIVE and belong to the period's hall.
    if recipe["status"] != "ACTIVE" or recipe["dining_hall_id"] != period["dining_hall_id"]:
        raise ApiError(
            "ERR_VALIDATION",
            400,
            "Recipe must be ACTIVE and belong to the period's hall",
        )
    variant = as_enum(required(data, "variant"), "variant", FORECAST_VARIANTS)
    # C1 (tier 8 raises ERR_INSUFFICIENT_HISTORY for TREND with < 2 occurrences).
    base_covers, portions = c1_forecast_portions(period, recipe, variant)
    # Supersede the pair's prior LOCKED forecast (INV-2).
    for f in DB["forecasts"].values():
        if (
            f["meal_period_id"] == pid
            and f["recipe_id"] == recipe_id
            and f["status"] == "LOCKED"
        ):
            f["status"] = "SUPERSEDED"
            touch(f)
    rec = {
        "id": new_id(),
        "meal_period_id": pid,
        "recipe_id": recipe_id,
        "variant": variant,
        "forecasted_portions": portions,
        "base_covers": base_covers,
        "status": "DRAFT",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["forecasts"][rec["id"]] = rec
    touch(period)
    return ok(ser(rec), status=201)


# ---------------------------------------------------------------------------
# WasteLog creation (nested under the period)
# ---------------------------------------------------------------------------

@bp.post("/meal-periods/<pid>/waste-logs")
def create_waste_log(pid):
    user_id, _ = auth(["KitchenLead"])
    period = get_period(pid)
    if period["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError(
            "ERR_WASTE_WINDOW_CLOSED", 422, "The period's waste window has closed"
        )
    if period["status"] not in ("IN_SERVICE", "RECONCILED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Period is not IN_SERVICE or RECONCILED"
        )
    data = body()
    category = as_enum(required(data, "category"), "category", WASTE_CATEGORIES)
    disposition = as_enum(
        required(data, "disposition"), "disposition", WASTE_DISPOSITIONS
    )
    weight = as_num(required(data, "weight_kg"), "weight_kg")
    if weight <= 0:
        raise ApiError("ERR_VALIDATION", 400, "weight_kg must be > 0")
    rec = {
        "id": new_id(),
        "meal_period_id": pid,
        "category": category,
        "disposition": disposition,
        "weight_kg": _kg2(Decimal(str(weight))),
        "recorded_by_user_id": user_id,
        "verified_by_user_id": None,
        "status": "RECORDED",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["waste_logs"][rec["id"]] = rec
    return ok(ser(rec), status=201)
