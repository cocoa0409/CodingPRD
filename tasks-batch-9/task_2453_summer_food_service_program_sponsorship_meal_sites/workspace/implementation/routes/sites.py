"""Meal sites, their two status axes and the attendance forecast.

PRD sec 3.4 (registration and eligibility), sec 3.5 (status axes), sec 3.9 (forecast).
"""

from flask import Blueprint, request

import db
import middleware as mw
import response
from errors import ApiError
from routes.common import require_owner, require_state
from services import cascades
from services import calculations as calc
from services import lookup
from services import serializers as ser

bp = Blueprint("sites", __name__)

REVIEWER = mw.ROLE_STATE_AGENCY_REVIEWER
SPONSOR_ADMIN = mw.ROLE_SPONSOR_ADMIN
MONITOR = mw.ROLE_FIELD_MONITOR
ALL = mw.ALL_ROLES

APPROVAL_STATUSES = ("PENDING_REVIEW", "APPROVED", "DENIED", "SUSPENDED")
OPERATING_STATUSES = ("NOT_STARTED", "OPERATING", "CLOSED_FOR_SEASON")
AREA_BASED_TYPES = ("OPEN", "RESTRICTED_OPEN", "MIGRANT")


@bp.post("/sfsp/sites")
@mw.endpoint([SPONSOR_ADMIN])
def create_site():
    body = mw.json_body()
    sponsor_id = mw.field_str(body, "sponsor_id")
    name = mw.field_str(body, "name")
    site_type = mw.field_enum(body, "site_type", calc.SITE_TYPES)
    production_mode = mw.field_enum(body, "production_mode", calc.PRODUCTION_MODES)
    meal_types = mw.field_list(body, "approved_meal_types")
    max_attendance = mw.field_int(body, "approved_max_attendance", minimum=1)
    start_date = mw.field_date(body, "operating_start_date")
    end_date = mw.field_date(body, "operating_end_date")
    area_record_id = mw.field_str(body, "area_eligibility_record_id", required=False)
    enrolled_pct = mw.field_decimal(
        body, "enrolled_free_reduced_pct", required=False, minimum=0, maximum=100, places=2
    )
    is_open_air = mw.field_bool(body, "is_open_air", required=False, default=False)
    is_rural = mw.field_bool(body, "is_rural", required=False, default=False)

    if len(meal_types) == 0:
        mw.bad_request("Field 'approved_meal_types' must not be empty.")
    seen = set()
    for meal_type in meal_types:
        if not isinstance(meal_type, str) or meal_type not in calc.MEAL_TYPES:
            mw.bad_request("Field 'approved_meal_types' contains an unknown meal type.")
        if meal_type in seen:
            mw.bad_request("Field 'approved_meal_types' must not contain duplicates.")
        seen.add(meal_type)
    if end_date < start_date:
        mw.bad_request("Field 'operating_end_date' must not precede 'operating_start_date'.")

    sponsor = lookup.require_sponsor(sponsor_id)
    area_record = None
    if area_record_id is not None:
        area_record = lookup.require_area_record(area_record_id)
    require_owner(sponsor["id"])
    require_state(
        sponsor["application_status"] == "APPROVED", "ERR_SPONSOR_NOT_APPROVED"
    )

    if site_type in AREA_BASED_TYPES and area_record is None:
        raise ApiError("ERR_AREA_RECORD_REQUIRED")
    if site_type == "CLOSED_ENROLLED" and enrolled_pct is None:
        raise ApiError("ERR_ENROLLED_PCT_REQUIRED")

    if site_type in ("CAMP", "MIGRANT"):
        if len(meal_types) > 3:
            raise ApiError("ERR_MEAL_TYPE_COUNT_EXCEEDED")
        if len(meal_types) == 3 and not (
            "AM_SNACK" in seen or "PM_SNACK" in seen
        ):
            raise ApiError("ERR_MEAL_TYPE_COUNT_EXCEEDED")
    elif len(meal_types) > 2:
        raise ApiError("ERR_MEAL_TYPE_COUNT_EXCEEDED")

    site = db.new_row(
        {
            "sponsor_id": sponsor["id"],
            "area_eligibility_record_id": area_record["id"] if area_record else None,
            "name": name,
            "site_type": site_type,
            "production_mode": production_mode,
            "is_open_air": is_open_air,
            "is_rural": is_rural,
            "approved_meal_types": list(meal_types),
            "approved_max_attendance": max_attendance,
            "enrolled_free_reduced_pct": enrolled_pct,
            "operating_start_date": db.date_iso(start_date),
            "operating_end_date": db.date_iso(end_date),
            "eligibility_basis": "UNDETERMINED",
            "eligibility_pct_used": None,
            "approval_status": "PENDING_REVIEW",
            "operating_status": "NOT_STARTED",
            "first_operating_date": None,
            "claim_hold": False,
            "compliance_flag_count": 0,
            "voided_day_count": 0,
            "suspension_reason": None,
        }
    )
    db.store.sites[site["id"]] = site
    return response.created_response(ser.site(site))


@bp.get("/sfsp/sites/<site_id>")
@mw.endpoint(ALL)
def get_site(site_id):
    site = lookup.require_site(site_id)
    return response.object_response(ser.site(site))


@bp.get("/sfsp/sites")
@mw.endpoint([REVIEWER, SPONSOR_ADMIN, MONITOR])
def list_sites():
    limit, offset = mw.pagination()
    sponsor_id = mw.query_value("sponsor_id")
    area_record_id = mw.query_value("area_eligibility_record_id")
    approval_status = mw.query_enum("approval_status", APPROVAL_STATUSES)
    operating_status = mw.query_enum("operating_status", OPERATING_STATUSES)
    site_type = mw.query_enum("site_type", calc.SITE_TYPES)

    rows = []
    for site in db.store.sites.values():
        if sponsor_id is not None and site["sponsor_id"] != sponsor_id:
            continue
        if (
            area_record_id is not None
            and site["area_eligibility_record_id"] != area_record_id
        ):
            continue
        if approval_status is not None and site["approval_status"] != approval_status:
            continue
        if operating_status is not None and site["operating_status"] != operating_status:
            continue
        if site_type is not None and site["site_type"] != site_type:
            continue
        rows.append(site)
    return response.paginate(rows, limit, offset, ser.site)


@bp.post("/sfsp/sites/<site_id>/eligibility-determination")
@mw.endpoint([REVIEWER])
def determine_eligibility(site_id):
    site = lookup.require_site(site_id)
    require_state(site["approval_status"] == "PENDING_REVIEW", "ERR_SITE_STATE_INVALID")

    basis = "NOT_ELIGIBLE"
    pct_used = None
    if site["site_type"] == "CAMP":
        basis = "CAMP_INDIVIDUAL"
        pct_used = None
    elif site["site_type"] == "CLOSED_ENROLLED":
        pct_used = site["enrolled_free_reduced_pct"]
        if pct_used is not None and pct_used >= calc.AREA_ELIGIBILITY_THRESHOLD_PCT:
            basis = "ENROLLED_DOCUMENTATION"
        else:
            basis = "NOT_ELIGIBLE"
    else:
        record = db.store.area_records.get(site["area_eligibility_record_id"])
        if record is None:
            basis = "NOT_ELIGIBLE"
            pct_used = None
        else:
            pct_used = record["free_reduced_pct"]
            valid_through = db.parse_date(record["valid_through_date"])
            start_date = db.parse_date(site["operating_start_date"])
            if valid_through is not None and start_date is not None and valid_through < start_date:
                basis = "NOT_ELIGIBLE"
            elif record["data_source"] == "SCHOOL_DATA":
                basis = (
                    "AREA_ELIGIBLE"
                    if pct_used >= calc.AREA_ELIGIBILITY_THRESHOLD_PCT
                    else "NOT_ELIGIBLE"
                )
            else:
                basis = (
                    "AREA_ELIGIBLE"
                    if pct_used >= calc.CENSUS_ACS_THRESHOLD_PCT
                    else "NOT_ELIGIBLE"
                )

    site["eligibility_basis"] = basis
    site["eligibility_pct_used"] = pct_used
    db.touch(site)
    return response.object_response(ser.site(site))


@bp.post("/sfsp/sites/<site_id>/approval-decision")
@mw.endpoint([REVIEWER])
def decide_site_approval(site_id):
    body = mw.json_body()
    decision = mw.field_enum(
        body, "decision", ("APPROVED", "DENIED", "SUSPENDED", "REINSTATED")
    )
    reason = mw.field_str(body, "reason", required=False)
    if decision in ("DENIED", "SUSPENDED") and reason is None:
        mw.bad_request("Field 'reason' is required for a %s decision." % decision)

    site = lookup.require_site(site_id)
    current = site["approval_status"]

    if decision == "APPROVED":
        require_state(current in ("PENDING_REVIEW", "SUSPENDED"), "ERR_SITE_STATE_INVALID")
        if current == "SUSPENDED":
            require_state(
                not cascades.live_critical_actions(site["id"]), "ERR_SITE_STATE_INVALID"
            )
    elif decision == "REINSTATED":
        require_state(current == "SUSPENDED", "ERR_SITE_STATE_INVALID")
        require_state(
            not cascades.live_critical_actions(site["id"]), "ERR_SITE_STATE_INVALID"
        )
    elif decision == "SUSPENDED":
        require_state(current == "APPROVED", "ERR_SITE_STATE_INVALID")
    else:  # DENIED
        require_state(current in ("PENDING_REVIEW", "SUSPENDED"), "ERR_SITE_STATE_INVALID")

    if decision == "APPROVED" and current == "PENDING_REVIEW":
        sponsor = lookup.require_sponsor(site["sponsor_id"])
        require_state(
            sponsor["application_status"] == "APPROVED", "ERR_SPONSOR_NOT_APPROVED"
        )
        if site["eligibility_basis"] == "UNDETERMINED":
            raise ApiError("ERR_ELIGIBILITY_NOT_DETERMINED")
        if site["eligibility_basis"] == "NOT_ELIGIBLE":
            raise ApiError("ERR_SITE_NOT_ELIGIBLE")

    if decision == "APPROVED" and current == "PENDING_REVIEW":
        site["approval_status"] = "APPROVED"
        db.touch(site)
    elif decision in ("APPROVED", "REINSTATED"):
        cascades.reinstate_site(site)
    elif decision == "SUSPENDED":
        cascades.suspend_site(site, reason)
    elif current == "PENDING_REVIEW":  # DENIED from PENDING_REVIEW
        site["approval_status"] = "DENIED"
        site["suspension_reason"] = reason
        db.touch(site)
    else:  # DENIED from SUSPENDED
        cascades.deny_site_from_suspended(site, reason)

    return response.object_response(ser.site(site))


@bp.post("/sfsp/sites/<site_id>/operating-status")
@mw.endpoint([SPONSOR_ADMIN])
def move_operating_status(site_id):
    body = mw.json_body()
    to_status = mw.field_enum(body, "to_status", ("OPERATING", "CLOSED_FOR_SEASON"))

    site = lookup.require_site(site_id)
    require_owner(site["sponsor_id"])

    if to_status == "OPERATING":
        require_state(site["operating_status"] == "NOT_STARTED", "ERR_SITE_STATE_INVALID")
        require_state(
            site["approval_status"] not in ("PENDING_REVIEW", "DENIED"),
            "ERR_SITE_NOT_APPROVED",
        )
        require_state(site["approval_status"] != "SUSPENDED", "ERR_SITE_SUSPENDED")
        site["operating_status"] = "OPERATING"
        db.touch(site)
    else:
        require_state(site["operating_status"] == "OPERATING", "ERR_SITE_STATE_INVALID")
        has_open_day = any(
            day["status"] == "OPEN" for day in lookup.site_days(site["id"])
        )
        if has_open_day:
            raise ApiError("ERR_DAY_HAS_OPEN_SERVICE")
        cascades.close_season(site)

    return response.object_response(ser.site(site))


@bp.get("/sfsp/sites/<site_id>/attendance-forecast")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def attendance_forecast(site_id):
    if "service_date" not in request.args:
        mw.bad_request("Query parameter 'service_date' is required.")
    if "method" not in request.args:
        mw.bad_request("Query parameter 'method' is required.")
    service_date = mw.query_date("service_date")
    method = mw.query_enum("method", calc.FORECAST_METHODS)

    site = lookup.require_site(site_id)
    result = calc.attendance_forecast(site, service_date, method)
    if result is None:
        raise ApiError("ERR_INSUFFICIENT_FORECAST_HISTORY")
    return response.object_response(result)
