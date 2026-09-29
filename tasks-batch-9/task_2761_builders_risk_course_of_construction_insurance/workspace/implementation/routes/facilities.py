"""Storage facility endpoints (PRD 3.5)."""
from flask import Blueprint

import lookup
from db import by_facility, new_row, ordered, store, touch
from enums import ASSIGNMENT_STATUSES, FACILITY_STATUSES, PROTECTION_CLASSES
from errors import ApiError
from middleware import authenticate, body, filter_enum, get_enum, get_int, get_number, \
    get_str, pagination, paginate
from response import created, ok, ok_list

bp = Blueprint("facilities", __name__)


@bp.post("/facilities")
def register_facility():
    authenticate("RiskEngineer")
    payload = body()
    name = get_str(payload, "name")
    site_code = get_str(payload, "site_code")
    distance = get_number(payload, "distance_from_site_miles", minimum_exclusive=0)
    capacity = get_int(payload, "aggregate_capacity_cents", minimum=1)
    protection_class = get_enum(payload, "protection_class", PROTECTION_CLASSES)
    for row in store.facilities.values():
        if row["site_code"] == site_code:
            raise ApiError(
                "ERR_DUPLICATE_SITE_CODE", "Another facility already uses this site_code."
            )
    row = new_row()
    row.update({
        "name": name,
        "site_code": site_code,
        "distance_from_site_miles": distance,
        "aggregate_capacity_cents": capacity,
        "protection_class": protection_class,
        "committed_value_cents": 0,
        "status": "ACTIVE",
    })
    store.facilities[row["id"]] = row
    return created(row)


@bp.patch("/facilities/<facility_id>")
def patch_facility(facility_id):
    authenticate("RiskEngineer")
    facility = lookup.facility(facility_id)
    payload = body()
    status = get_enum(payload, "status", FACILITY_STATUSES)
    if status == facility["status"]:
        raise ApiError("ERR_INVALID_REQUEST", "The facility already carries that status.")
    facility["status"] = status
    touch(facility)
    return ok(facility)


@bp.get("/facilities/<facility_id>")
def read_facility(facility_id):
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer")
    return ok(lookup.facility(facility_id))


@bp.get("/facilities")
def list_facilities():
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer")
    limit, offset = pagination()
    status = filter_enum("status", FACILITY_STATUSES)
    protection_class = filter_enum("protection_class", PROTECTION_CLASSES)
    rows = ordered(list(store.facilities.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if protection_class is not None:
        rows = [r for r in rows if r["protection_class"] == protection_class]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/facilities/<facility_id>/storage-assignments")
def list_facility_assignments(facility_id):
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer")
    facility = lookup.facility(facility_id)
    limit, offset = pagination()
    status = filter_enum("status", ASSIGNMENT_STATUSES)
    rows = ordered(by_facility(store.assignments, facility["id"]))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)
