"""Facilities, providers and the logical clock."""
from flask import Blueprint, request

import calc
import db
import resolve
import response
import serialize
import validate
from db import store
from errors import ApiError
from middleware import (ALL_ROLES, AUDIOLOGIST, EI_COORDINATOR, FACILITY_ADMIN,
                        FACILITY_SCREENER, NAVIGATOR, PROGRAM_ADMIN,
                        PROGRAM_AUDITOR, endpoint, identity, user_id)

bp = Blueprint("facilities", __name__)

RATE_FIELDS = ("cohort_screened_rate", "encounter_screened_rate",
               "followup_resolution_rate", "report_timeliness_rate")


@bp.post("/facilities")
@endpoint([PROGRAM_ADMIN])
def create_facility():
    body = validate.body()
    name = validate.string_field(body, "name", min_len=1, max_len=120)
    facility_type = validate.enum_field(body, "facility_type",
                                        validate.FACILITY_TYPES)
    region_code = validate.enum_field(body, "region_code", validate.REGION_CODES)
    budget = validate.int_field(body, "navigation_budget_units_total",
                                required=False, minimum=0, maximum=999, default=40)
    row = db.base_row()
    row.update({
        "name": name,
        "facility_type": facility_type,
        "region_code": region_code,
        "navigation_budget_units_total": budget,
        "manual_adjustment_points_total": 0,
        "performance_score": None,
        "encounter_basis_performance_score": None,
        "last_closed_period_label": None,
    })
    for field in RATE_FIELDS:
        row[field] = None
    store.facilities[row["id"]] = row
    return response.single(row, serialize.facility, 201)


@bp.post("/facilities/<facility_id>/penalty-adjustments")
@endpoint([PROGRAM_ADMIN])
def penalty_adjustment(facility_id):
    body = validate.body()
    delta = validate.int_field(body, "points_delta")
    if delta == 0:
        validate.bad("Field 'points_delta' must be non-zero.")
    reason = validate.string_field(body, "reason", min_len=1)
    facility = resolve.one("facility", facility_id)
    if calc.penalty_balance(facility) + delta < 0:
        raise ApiError("ERR_NEGATIVE_PENALTY_BALANCE")
    facility["manual_adjustment_points_total"] += delta
    db.touch(facility)
    return response.single(facility, serialize.facility)


@bp.get("/facilities/<facility_id>")
@endpoint(ALL_ROLES)
def get_facility(facility_id):
    facility = resolve.one("facility", facility_id)
    identity()
    return response.single(facility, serialize.facility)


@bp.get("/facilities/<facility_id>/providers")
@endpoint(ALL_ROLES)
def list_facility_providers(facility_id):
    limit, offset = response.pagination()
    facility = resolve.one("facility", facility_id)
    identity()
    rows = [p for p in store.providers.values()
            if p["facility_id"] == facility["id"]]
    provider_type = request.args.get("provider_type")
    if provider_type:
        rows = [p for p in rows if p["provider_type"] == provider_type]
    credential_status = request.args.get("credential_status")
    if credential_status:
        rows = [p for p in rows if p["credential_status"] == credential_status]
    return response.listing(db.sort_rows(rows), serialize.provider, limit, offset)


@bp.get("/facilities/<facility_id>/performance")
@endpoint([PROGRAM_ADMIN, PROGRAM_AUDITOR, FACILITY_ADMIN])
def facility_performance(facility_id):
    facility = resolve.one("facility", facility_id)
    identity()
    balance = calc.penalty_balance(facility)

    def as_number(value):
        return None if value is None else float(value)

    data = {
        "facility_id": facility["id"],
        "performance_score": as_number(facility["performance_score"]),
        "encounter_basis_performance_score":
            as_number(facility["encounter_basis_performance_score"]),
        "cohort_screened_rate": as_number(facility["cohort_screened_rate"]),
        "encounter_screened_rate": as_number(facility["encounter_screened_rate"]),
        "followup_resolution_rate": as_number(facility["followup_resolution_rate"]),
        "report_timeliness_rate": as_number(facility["report_timeliness_rate"]),
        "penalty_points_balance": balance,
        "reporting_compliance_status": calc.compliance_posture(balance),
        "last_closed_period_label": facility["last_closed_period_label"],
    }
    return response.payload(data)


@bp.post("/providers")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN])
def create_provider():
    body = validate.body()
    facility_id = validate.id_field(body, "facility_id")
    provider_type = validate.enum_field(body, "provider_type",
                                        validate.PROVIDER_TYPES)
    full_name = validate.string_field(body, "full_name", min_len=1, max_len=120)
    region_code = validate.enum_field(body, "region_code", validate.REGION_CODES)
    languages = validate.language_list(body, "languages", default=["EN"])
    credential_status = validate.enum_field(body, "credential_status",
                                            validate.CREDENTIAL_STATUSES,
                                            required=False, default="ACTIVE")
    max_open_tasks = validate.int_field(body, "max_open_tasks", required=False,
                                        minimum=1, maximum=50, default=5)
    linked = resolve.fks({"facility_id": facility_id})
    identity(facility_id=linked["facility_id"]["id"])
    row = db.base_row()
    row.update({
        "facility_id": linked["facility_id"]["id"],
        "provider_type": provider_type,
        "full_name": full_name,
        "region_code": region_code,
        "languages": languages,
        "credential_status": credential_status,
        "max_open_tasks": max_open_tasks,
    })
    store.providers[row["id"]] = row
    return response.single(row, serialize.provider, 201)


@bp.get("/providers/<provider_id>")
@endpoint(ALL_ROLES)
def get_provider(provider_id):
    provider = resolve.one("provider", provider_id)
    identity()
    return response.single(provider, serialize.provider)


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_clock():
    body = validate.body()
    instant = validate.datetime_field(body, "to_iso8601")
    db.set_clock(instant)
    return response.payload({"current_utc": db.fmt_dt(db.now())})
