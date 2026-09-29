"""Service days, meal count entries and holding logs (PRD sec 3.6)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.common import require_owner, require_state
from services import cascades
from services import calculations as calc
from services import lookup
from services import serializers as ser

bp = Blueprint("days", __name__)

REVIEWER = mw.ROLE_STATE_AGENCY_REVIEWER
SPONSOR_ADMIN = mw.ROLE_SPONSOR_ADMIN
SUPERVISOR = mw.ROLE_SITE_SUPERVISOR
ALL = mw.ALL_ROLES

DAY_STATUSES = ("PLANNED", "OPEN", "CLOSED", "FINALIZED", "VOIDED")
SAFETY_STATUSES = ("OK", "BREACH")
ENTRY_KINDS = ("ORIGINAL", "REVERSAL")


def _site_of(day):
    return db.store.sites[day["site_id"]]


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------
@bp.post("/sfsp/meal-service-days")
@mw.endpoint([SUPERVISOR])
def plan_day():
    body = mw.json_body()
    site_id = mw.field_str(body, "site_id")
    service_date = mw.field_date(body, "service_date")
    services = mw.field_list(body, "meal_services")

    if len(services) == 0:
        mw.bad_request("Field 'meal_services' must not be empty.")
    declared = []
    windows = []
    for element in services:
        if not isinstance(element, dict):
            mw.bad_request("Each 'meal_services' element must be an object.")
        meal_type = mw.field_enum(element, "meal_type", calc.MEAL_TYPES)
        planned_meals = mw.field_int(element, "planned_meals", minimum=0)
        start_minutes = mw.field_time(element, "service_start")
        end_minutes = mw.field_time(element, "service_end")
        if start_minutes >= end_minutes:
            mw.bad_request("'service_start' must be strictly before 'service_end'.")
        if meal_type in [service["meal_type"] for service in declared]:
            mw.bad_request("A meal type may not appear twice in 'meal_services'.")
        declared.append(
            {
                "meal_type": meal_type,
                "planned_meals": planned_meals,
                "service_start": element["service_start"],
                "service_end": element["service_end"],
            }
        )
        windows.append((start_minutes, end_minutes))

    site = lookup.require_site(site_id)
    require_owner(site["id"])

    for service in declared:
        if service["meal_type"] not in site["approved_meal_types"]:
            raise ApiError("ERR_MEAL_TYPE_NOT_APPROVED")

    service_date_iso = db.date_iso(service_date)
    for existing in lookup.site_days(site["id"]):
        if existing["service_date"] == service_date_iso and existing["status"] != "VOIDED":
            raise ApiError("ERR_DUPLICATE_SERVICE_DAY")

    start_date = db.parse_date(site["operating_start_date"])
    end_date = db.parse_date(site["operating_end_date"])
    if service_date < start_date or service_date > end_date:
        raise ApiError("ERR_SERVICE_DATE_OUTSIDE_SEASON")

    windows.sort()
    for index in range(1, len(windows)):
        if windows[index][0] - windows[index - 1][1] < calc.MEAL_SERVICE_GAP_MINUTES:
            raise ApiError("ERR_MEAL_SERVICE_WINDOW_CONFLICT")

    day = db.new_row(
        {
            "site_id": site["id"],
            "service_date": service_date_iso,
            "meal_services": declared,
            "production_mode": site["production_mode"],
            "production_counts": None,
            "food_received_at": None,
            "status": "PLANNED",
            "food_safety_status": "OK",
            "breach_at": None,
            "counted_first_meals": 0,
            "counted_second_meals": 0,
            "counted_adult_meals": 0,
            "reimbursable_meals": 0,
            "non_reimbursable_meals": 0,
            "discarded_meals": 0,
            "leftover_meals": 0,
            "void_reason": None,
        }
    )
    db.store.days[day["id"]] = day
    return response.created_response(ser.service_day(day))


@bp.get("/sfsp/meal-service-days/<day_id>")
@mw.endpoint(ALL)
def get_day(day_id):
    day = lookup.require_day(day_id)
    return response.object_response(ser.service_day(day))


@bp.get("/sfsp/meal-service-days")
@mw.endpoint(ALL)
def list_days():
    limit, offset = mw.pagination()
    site_id = mw.query_value("site_id")
    service_date = mw.query_date("service_date")
    status = mw.query_enum("status", DAY_STATUSES)
    safety_status = mw.query_enum("food_safety_status", SAFETY_STATUSES)

    rows = []
    for day in db.store.days.values():
        if site_id is not None and day["site_id"] != site_id:
            continue
        if service_date is not None and day["service_date"] != db.date_iso(service_date):
            continue
        if status is not None and day["status"] != status:
            continue
        if safety_status is not None and day["food_safety_status"] != safety_status:
            continue
        rows.append(day)
    return response.paginate(rows, limit, offset, ser.service_day)


# --------------------------------------------------------------------------
# Day lifecycle
# --------------------------------------------------------------------------
@bp.post("/sfsp/meal-service-days/<day_id>/open")
@mw.endpoint([SUPERVISOR])
def open_day(day_id):
    body = mw.json_body()
    production_counts = mw.field_object(body, "production_counts")
    food_received_at = mw.field_datetime(body, "food_received_at")
    normalized = {}
    for key, value in production_counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            mw.bad_request("Each 'production_counts' value must be a non-negative integer.")
        normalized[key] = value

    day = lookup.require_day(day_id)
    declared = [service["meal_type"] for service in day["meal_services"]]
    if set(normalized.keys()) != set(declared):
        mw.bad_request(
            "'production_counts' keys must be exactly the day's declared meal types."
        )

    require_owner(day["site_id"])
    require_state(day["status"] == "PLANNED", "ERR_SERVICE_DAY_STATE_INVALID")

    site = _site_of(day)
    require_state(
        site["approval_status"] not in ("PENDING_REVIEW", "DENIED"),
        "ERR_SITE_NOT_APPROVED",
    )
    require_state(site["approval_status"] != "SUSPENDED", "ERR_SITE_SUSPENDED")
    require_state(site["operating_status"] == "OPERATING", "ERR_SITE_NOT_OPERATING")

    day["status"] = "OPEN"
    day["production_counts"] = {key: normalized[key] for key in declared}
    day["food_received_at"] = db.to_iso(food_received_at)
    result = calc.classify_day(day, site)
    day["counted_first_meals"] = result["counted_first_meals"]
    day["counted_second_meals"] = result["counted_second_meals"]
    day["counted_adult_meals"] = result["counted_adult_meals"]
    day["reimbursable_meals"] = result["reimbursable_meals"]
    day["non_reimbursable_meals"] = result["non_reimbursable_meals"]
    day["leftover_meals"] = result["leftover_meals"]
    db.touch(day)

    # first_operating_date is written when service actually begins.
    existing_first = db.parse_date(site["first_operating_date"])
    this_date = db.parse_date(day["service_date"])
    if existing_first is None or this_date < existing_first:
        site["first_operating_date"] = day["service_date"]
        db.touch(site)
    cascades.recompute_visit_deadlines(site)

    return response.object_response(ser.service_day(day))


@bp.post("/sfsp/meal-service-days/<day_id>/close")
@mw.endpoint([SUPERVISOR])
def close_day(day_id):
    day = lookup.require_day(day_id)
    require_owner(day["site_id"])
    require_state(day["status"] == "OPEN", "ERR_SERVICE_DAY_STATE_INVALID")

    site = _site_of(day)
    result = calc.classify_day(day, site)
    day["status"] = "CLOSED"
    day["counted_first_meals"] = result["counted_first_meals"]
    day["counted_second_meals"] = result["counted_second_meals"]
    day["counted_adult_meals"] = result["counted_adult_meals"]
    day["reimbursable_meals"] = result["reimbursable_meals"]
    day["non_reimbursable_meals"] = result["non_reimbursable_meals"]
    day["leftover_meals"] = result["leftover_meals"]
    db.touch(day)
    return response.object_response(ser.service_day(day))


@bp.post("/sfsp/meal-service-days/<day_id>/finalize")
@mw.endpoint([SPONSOR_ADMIN])
def finalize_day(day_id):
    day = lookup.require_day(day_id)
    site = _site_of(day)
    require_owner(site["sponsor_id"])
    require_state(day["status"] == "CLOSED", "ERR_SERVICE_DAY_STATE_INVALID")
    require_state(not site["claim_hold"], "ERR_SITE_SUSPENDED")

    day["status"] = "FINALIZED"
    db.touch(day)
    return response.object_response(ser.service_day(day))


@bp.post("/sfsp/meal-service-days/<day_id>/void")
@mw.endpoint([SPONSOR_ADMIN])
def void_day(day_id):
    body = mw.json_body()
    reason = mw.field_str(body, "reason")

    day = lookup.require_day(day_id)
    site = _site_of(day)
    require_owner(site["sponsor_id"])
    require_state(
        day["status"] in ("PLANNED", "OPEN", "CLOSED"), "ERR_SERVICE_DAY_STATE_INVALID"
    )

    cascades.void_day(day, reason)
    site["voided_day_count"] = (site["voided_day_count"] or 0) + 1
    db.touch(site)
    return response.object_response(ser.service_day(day))


# --------------------------------------------------------------------------
# Meal count entries
# --------------------------------------------------------------------------
@bp.post("/sfsp/meal-service-days/<day_id>/meal-counts")
@mw.endpoint([SUPERVISOR])
def post_meal_count(day_id):
    body = mw.json_body()
    meal_type = mw.field_enum(body, "meal_type", calc.MEAL_TYPES)
    first_meals = mw.field_int(body, "first_meals", minimum=0)
    second_meals = mw.field_int(body, "second_meals", minimum=0)
    adult_meals = mw.field_int(body, "adult_meals", minimum=0)
    reversal_of = mw.field_str(body, "reversal_of_entry_id", required=False)

    day = lookup.require_day(day_id)
    target = None
    if reversal_of is not None:
        target = lookup.require_count_entry(reversal_of)

    require_owner(day["site_id"])
    require_state(day["status"] == "OPEN", "ERR_SERVICE_DAY_STATE_INVALID")
    require_state(day["food_safety_status"] == "OK", "ERR_FOOD_SAFETY_BREACH")

    site = _site_of(day)
    if meal_type not in site["approved_meal_types"]:
        raise ApiError("ERR_MEAL_TYPE_NOT_APPROVED")

    if target is not None:
        already_reversed = any(
            entry["reversal_of_entry_id"] == target["id"]
            for entry in db.store.count_entries.values()
        )
        if (
            target["meal_service_day_id"] != day["id"]
            or target["entry_kind"] != "ORIGINAL"
            or target["meal_type"] != meal_type
            or already_reversed
            or target["first_meals"] != first_meals
            or target["second_meals"] != second_meals
            or target["adult_meals"] != adult_meals
        ):
            raise ApiError("ERR_REVERSAL_TARGET_INVALID")

    before = calc.classify_day(day, site)
    entry = db.new_row(
        {
            "meal_service_day_id": day["id"],
            "reversal_of_entry_id": target["id"] if target else None,
            "meal_type": meal_type,
            "first_meals": first_meals,
            "second_meals": second_meals,
            "adult_meals": adult_meals,
            "entry_kind": "REVERSAL" if target else "ORIGINAL",
            "reimbursable_first_meals": 0,
            "reimbursable_second_meals": 0,
            "non_reimbursable_meals": 0,
            "recorded_at": db.clock.now_iso(),
            "recorded_by_user_id": mw.acting_user_id(),
        },
        versioned=False,
    )
    db.store.count_entries[entry["id"]] = entry

    after = calc.classify_day(day, site)
    first_delta = _reimbursable_first(after) - _reimbursable_first(before)
    second_delta = _reimbursable_second(after) - _reimbursable_second(before)
    entry["reimbursable_first_meals"] = first_delta
    entry["reimbursable_second_meals"] = second_delta
    entry["non_reimbursable_meals"] = (
        first_meals + second_meals + adult_meals - first_delta - second_delta
    )

    day["counted_first_meals"] = after["counted_first_meals"]
    day["counted_second_meals"] = after["counted_second_meals"]
    day["counted_adult_meals"] = after["counted_adult_meals"]
    day["reimbursable_meals"] = after["reimbursable_meals"]
    day["non_reimbursable_meals"] = after["non_reimbursable_meals"]
    day["leftover_meals"] = after["leftover_meals"]
    db.touch(day)

    return response.created_response(ser.count_entry(entry))


def _reimbursable_first(result):
    return sum(first for first, _ in result["per_type"].values())


def _reimbursable_second(result):
    return sum(second for _, second in result["per_type"].values())


@bp.get("/sfsp/meal-count-entries/<entry_id>")
@mw.endpoint(ALL)
def get_count_entry(entry_id):
    entry = lookup.require_count_entry(entry_id)
    return response.object_response(ser.count_entry(entry))


@bp.get("/sfsp/meal-count-entries")
@mw.endpoint(ALL)
def list_count_entries():
    limit, offset = mw.pagination()
    day_id = mw.query_value("meal_service_day_id")
    reversal_of = mw.query_value("reversal_of_entry_id")
    meal_type = mw.query_enum("meal_type", calc.MEAL_TYPES)
    entry_kind = mw.query_enum("entry_kind", ENTRY_KINDS)

    rows = []
    for entry in db.store.count_entries.values():
        if day_id is not None and entry["meal_service_day_id"] != day_id:
            continue
        if reversal_of is not None and entry["reversal_of_entry_id"] != reversal_of:
            continue
        if meal_type is not None and entry["meal_type"] != meal_type:
            continue
        if entry_kind is not None and entry["entry_kind"] != entry_kind:
            continue
        rows.append(entry)
    return response.paginate(rows, limit, offset, ser.count_entry)


# --------------------------------------------------------------------------
# Holding-log entries
# --------------------------------------------------------------------------
@bp.post("/sfsp/meal-service-days/<day_id>/holding-logs")
@mw.endpoint([SUPERVISOR])
def post_holding_log(day_id):
    body = mw.json_body()
    meal_type = mw.field_enum(body, "meal_type", calc.MEAL_TYPES)
    temperature_class = mw.field_enum(
        body, "temperature_class", calc.TEMPERATURE_CLASSES
    )
    temperature_f = mw.field_decimal(
        body, "temperature_f", minimum=-20, maximum=250, places=1
    )
    measured_at = mw.field_datetime(body, "measured_at")

    day = lookup.require_day(day_id)
    require_owner(day["site_id"])
    require_state(day["status"] == "OPEN", "ERR_SERVICE_DAY_STATE_INVALID")

    food_received_at = db.parse_datetime(day["food_received_at"])
    if food_received_at is not None and measured_at < food_received_at:
        raise ApiError("ERR_MEASURED_BEFORE_FOOD_RECEIVED")

    site = _site_of(day)
    if meal_type not in site["approved_meal_types"]:
        raise ApiError("ERR_MEAL_TYPE_NOT_APPROVED")

    minutes_held = calc.holding_minutes(food_received_at, measured_at)
    breach_flag, breach_reason = calc.evaluate_breach(
        site, temperature_class, temperature_f, minutes_held
    )

    entry = db.new_row(
        {
            "meal_service_day_id": day["id"],
            "meal_type": meal_type,
            "temperature_class": temperature_class,
            "temperature_f": temperature_f,
            "measured_at": db.to_iso(measured_at),
            "holding_minutes": minutes_held,
            "breach_flag": breach_flag,
            "breach_reason": breach_reason,
            "recorded_by_user_id": mw.acting_user_id(),
        },
        versioned=False,
    )
    db.store.holding_logs[entry["id"]] = entry

    # Only the first breaching reading of a day changes the day.
    if breach_flag and day["food_safety_status"] == "OK":
        result = calc.classify_day(day, site)
        day["food_safety_status"] = "BREACH"
        day["breach_at"] = entry["measured_at"]
        day["discarded_meals"] = calc.unserved_production(day, result)
        day["leftover_meals"] = 0
        db.touch(day)

    return response.created_response(ser.holding_log(entry))


@bp.get("/sfsp/holding-log-entries/<entry_id>")
@mw.endpoint(ALL)
def get_holding_log(entry_id):
    entry = lookup.require_holding_log(entry_id)
    return response.object_response(ser.holding_log(entry))


@bp.get("/sfsp/holding-log-entries")
@mw.endpoint(ALL)
def list_holding_logs():
    limit, offset = mw.pagination()
    day_id = mw.query_value("meal_service_day_id")
    meal_type = mw.query_enum("meal_type", calc.MEAL_TYPES)
    breach_flag = mw.query_bool("breach_flag")

    rows = []
    for entry in db.store.holding_logs.values():
        if day_id is not None and entry["meal_service_day_id"] != day_id:
            continue
        if meal_type is not None and entry["meal_type"] != meal_type:
            continue
        if breach_flag is not None and entry["breach_flag"] != breach_flag:
            continue
        rows.append(entry)
    return response.paginate(rows, limit, offset, ser.holding_log)
