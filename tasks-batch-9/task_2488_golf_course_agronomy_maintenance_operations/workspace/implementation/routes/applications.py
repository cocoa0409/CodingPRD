"""Applicators, pesticide product labels and the application record."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import services
from envelope import created, ok
from errors import ApiError
from serializers import applicator_out, application_out, product_out
from store import clock, store
from util import dec, dmin, rhu
from validators import (bad, body, endpoint, field_bool, field_date, field_dt,
                        field_enum, field_int, field_num, field_str, field_uuid,
                        pagination, path_uuid, query_bool, query_enum, query_uuid)

from routes.common import list_response

bp = Blueprint("applications", __name__)

LICENSE_CATEGORIES = ("CAT_3_TURF", "CAT_7_AQUATIC", "CAT_3_AND_7")
LICENSE_STATUSES = ("ACTIVE", "EXPIRED", "SUSPENDED")
PRODUCT_CATEGORIES = ("CAT_3_TURF", "CAT_7_AQUATIC")
RECORD_STATUSES = ("RECORDED", "VERIFIED", "VOIDED")
POSTING_STATUSES = ("NOT_REQUIRED", "POSTED", "RELEASED")
VOID_REASONS = ("DATA_ENTRY_ERROR", "SAFETY_VIOLATION")


# --------------------------------------------------------------------------
# applicators
# --------------------------------------------------------------------------
@bp.post("/applicators")
@endpoint(("Superintendent",))
def create_applicator():
    payload = body()
    full_name = field_str(payload, "full_name", max_len=120)
    license_number = field_str(payload, "license_number", max_len=120)
    license_category = field_enum(payload, "license_category", LICENSE_CATEGORIES)
    license_expires_on = field_date(payload, "license_expires_on")

    for existing in store.applicators.values():
        if existing["license_number"] == license_number:
            raise ApiError("ERR_DUPLICATE_LICENSE_NUMBER")

    record = services.base_record()
    record.update({
        "full_name": full_name,
        "license_number": license_number,
        "license_category": license_category,
        "license_expires_on": license_expires_on,
        "suspended_at": None,
    })
    store.applicators[record["id"]] = record
    return created(applicator_out(record))


@bp.get("/applicators")
@endpoint(("Superintendent", "Agronomist", "Applicator"))
def list_applicators():
    page = pagination()
    license_category = query_enum("license_category", LICENSE_CATEGORIES)
    license_status = query_enum("license_status", LICENSE_STATUSES)
    records = [
        record for record in store.applicators.values()
        if (license_category is None or record["license_category"] == license_category)
        and (license_status is None or calc.license_status(record) == license_status)
    ]
    return list_response(records, applicator_out, page=page)


@bp.get("/applicators/<applicator_id>")
@endpoint(("Superintendent", "Agronomist", "Applicator"))
def get_applicator(applicator_id):
    path_uuid(applicator_id, "ERR_APPLICATOR_NOT_FOUND")
    record = services.require(store.applicators, applicator_id,
                              "ERR_APPLICATOR_NOT_FOUND")
    return ok(applicator_out(record))


# --------------------------------------------------------------------------
# pesticide products
# --------------------------------------------------------------------------
@bp.post("/pesticide-products")
@endpoint(("Superintendent",))
def create_product():
    payload = body()
    record = services.base_record(versioned=False)
    record.update({
        "trade_name": field_str(payload, "trade_name", max_len=120),
        "epa_reg_no": field_str(payload, "epa_reg_no", max_len=120),
        "requires_license_category": field_enum(payload, "requires_license_category",
                                                PRODUCT_CATEGORIES),
        "rei_hours": field_int(payload, "rei_hours", minimum=0, maximum=336),
        "min_buffer_ft": field_num(payload, "min_buffer_ft", minimum=0),
        "max_wind_speed_mph": field_num(payload, "max_wind_speed_mph", exclusive_min=0),
        "posting_required": field_bool(payload, "posting_required"),
        "nitrogen_pct": field_num(payload, "nitrogen_pct", required=False,
                                  default=Decimal("0"), minimum=0, maximum=100),
    })
    store.products[record["id"]] = record
    return created(product_out(record))


@bp.get("/pesticide-products")
@endpoint(("Superintendent", "Agronomist", "Applicator"))
def list_products():
    page = pagination()
    category = query_enum("requires_license_category", PRODUCT_CATEGORIES)
    posting_required = query_bool("posting_required")
    records = [
        record for record in store.products.values()
        if (category is None or record["requires_license_category"] == category)
        and (posting_required is None
             or record["posting_required"] == posting_required)
    ]
    return list_response(records, product_out, page=page)


@bp.get("/pesticide-products/<product_id>")
@endpoint(("Superintendent", "Agronomist", "Applicator"))
def get_product(product_id):
    path_uuid(product_id, "ERR_PRODUCT_NOT_FOUND")
    record = services.require(store.products, product_id, "ERR_PRODUCT_NOT_FOUND")
    return ok(product_out(record))


# --------------------------------------------------------------------------
# applications
# --------------------------------------------------------------------------
@bp.post("/applications")
@endpoint(("Applicator",))
def create_application():
    payload = body()
    area_id = field_uuid(payload, "turf_area_id")
    product_id = field_uuid(payload, "product_id")
    applicator_id = field_uuid(payload, "applicator_id")
    task_id = field_uuid(payload, "plan_task_id", required=False)
    applied_at = field_dt(payload, "applied_at")
    if applied_at > clock():
        bad("'applied_at' may not be after the current clock reading.")
    rate = field_num(payload, "rate_lb_per_acre", exclusive_min=0)
    wind_speed = field_num(payload, "wind_speed_mph", minimum=0)
    distance = field_num(payload, "distance_to_water_ft", minimum=0)

    area = services.require(store.turf_areas, area_id, "ERR_TURF_AREA_NOT_FOUND")
    task = None
    if task_id is not None:
        task = services.require(store.plan_tasks, task_id, "ERR_PLAN_TASK_NOT_FOUND")
    applicator = services.require(store.applicators, applicator_id,
                                  "ERR_APPLICATOR_NOT_FOUND")
    product = services.require(store.products, product_id, "ERR_PRODUCT_NOT_FOUND")

    if task is not None and task["status"] != "SCHEDULED":
        raise ApiError("ERR_TASK_STATE_INVALID")

    if applicator["suspended_at"] is not None or \
            applied_at.date() > applicator["license_expires_on"]:
        raise ApiError("ERR_LICENSE_EXPIRED")

    if wind_speed > dec(product["max_wind_speed_mph"]):
        raise ApiError("ERR_WIND_LIMIT_EXCEEDED")

    effective_distance = dmin(dec(distance), dec(area["distance_to_water_ft"]))
    if effective_distance < dec(product["min_buffer_ft"]):
        raise ApiError("ERR_BUFFER_ZONE_VIOLATION")

    total_lb, nitrogen_lb, rei_expires_at = calc.application_mass_and_nitrogen(
        rate, area["area_sq_ft"], product["nitrogen_pct"], applied_at,
        product["rei_hours"])

    thousands = dec(area["area_sq_ft"]) / Decimal(1000)
    applied_after = rhu(
        calc.turf_nitrogen_applied(area) + rhu(nitrogen_lb / thousands, 3), 3)
    projected_after = rhu(applied_after + calc.turf_nitrogen_planned(area), 3)
    if projected_after > calc.turf_nitrogen_ceiling(area):
        raise ApiError("ERR_NITROGEN_LOAD_LIMIT")

    course = store.courses.get(area["course_id"])
    if course is not None and course["play_posture"] == "CLOSED":
        raise ApiError("ERR_COURSE_CLOSED")
    if area["agronomic_status"] == "OUT_OF_PLAY":
        raise ApiError("ERR_TURF_AREA_OUT_OF_PLAY")

    if not services.category_authorises(applicator["license_category"],
                                        product["requires_license_category"]):
        raise ApiError("ERR_LICENSE_CATEGORY_MISMATCH")

    if task is not None and task["turf_area_id"] != area_id:
        raise ApiError("ERR_TASK_TURF_AREA_MISMATCH")

    if task is not None:
        plan = store.plans.get(task["plan_id"])
        outside = (applied_at < task["planned_window_start"]
                   or applied_at >= task["planned_window_end"])
        if plan is not None and applied_at.year != int(plan["plan_year"]):
            outside = True
        if outside:
            raise ApiError("ERR_APPLICATION_OUTSIDE_PLAN_WINDOW")

    record = services.base_record()
    record.update({
        "turf_area_id": area_id,
        "product_id": product_id,
        "applicator_id": applicator_id,
        "plan_task_id": task_id,
        "applied_at": applied_at,
        "rate_lb_per_acre": rate,
        "wind_speed_mph": wind_speed,
        "distance_to_water_ft": distance,
        "total_lb": total_lb,
        "nitrogen_lb": nitrogen_lb,
        "rei_expires_at": rei_expires_at,
        "record_status": "RECORDED",
        "posting_status": "POSTED" if product["posting_required"] else "NOT_REQUIRED",
        "verified_by_applicator_id": None,
        "void_reason": None,
    })
    store.applications[record["id"]] = record

    services.recompute_turf_nitrogen(area)
    if record["posting_status"] == "POSTED":
        services.recompute_turf_rei(area)
    services.touch(area)
    return created(application_out(record))


@bp.get("/applications")
@endpoint(("Superintendent", "Agronomist", "Applicator"))
def list_applications():
    page = pagination()
    area_id = query_uuid("turf_area_id")
    product_id = query_uuid("product_id")
    applicator_id = query_uuid("applicator_id")
    task_id = query_uuid("plan_task_id")
    verified_by = query_uuid("verified_by_applicator_id")
    record_status = query_enum("record_status", RECORD_STATUSES)
    posting_status = query_enum("posting_status", POSTING_STATUSES)
    records = [
        record for record in store.applications.values()
        if (area_id is None or record["turf_area_id"] == area_id)
        and (product_id is None or record["product_id"] == product_id)
        and (applicator_id is None or record["applicator_id"] == applicator_id)
        and (task_id is None or record["plan_task_id"] == task_id)
        and (verified_by is None or record["verified_by_applicator_id"] == verified_by)
        and (record_status is None or record["record_status"] == record_status)
        and (posting_status is None or record["posting_status"] == posting_status)
    ]
    return list_response(records, application_out, page=page)


@bp.get("/applications/<application_id>")
@endpoint(("Superintendent", "Agronomist", "Applicator"))
def get_application(application_id):
    path_uuid(application_id, "ERR_APPLICATION_NOT_FOUND")
    record = services.require(store.applications, application_id,
                              "ERR_APPLICATION_NOT_FOUND")
    return ok(application_out(record))


@bp.post("/applications/<application_id>/verify")
@endpoint(("Applicator",), need_user_id=True)
def verify_application(application_id):
    path_uuid(application_id, "ERR_APPLICATION_NOT_FOUND")
    body()
    verifier = store.applicators.get(g.user_id)
    if verifier is None:
        raise ApiError("ERR_APPLICATOR_NOT_FOUND")
    record = services.require(store.applications, application_id,
                              "ERR_APPLICATION_NOT_FOUND")
    if record["record_status"] != "RECORDED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    if calc.license_status(verifier) != "ACTIVE":
        raise ApiError("ERR_LICENSE_EXPIRED")
    product = store.products.get(record["product_id"])
    if product is not None and not services.category_authorises(
            verifier["license_category"], product["requires_license_category"]):
        raise ApiError("ERR_LICENSE_CATEGORY_MISMATCH")
    if record["applicator_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    record["record_status"] = "VERIFIED"
    record["verified_by_applicator_id"] = g.user_id
    services.touch(record)

    area = store.turf_areas.get(record["turf_area_id"])
    if area is not None:
        services.sync_turf_ledgers(area)
    return ok(application_out(record))


@bp.post("/applications/<application_id>/void")
@endpoint(("Superintendent",))
def void_application(application_id):
    path_uuid(application_id, "ERR_APPLICATION_NOT_FOUND")
    payload = body()
    reason = field_enum(payload, "void_reason", VOID_REASONS)
    record = services.require(store.applications, application_id,
                              "ERR_APPLICATION_NOT_FOUND")
    if record["record_status"] == "VOIDED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    record["record_status"] = "VOIDED"
    record["void_reason"] = reason
    if record["posting_status"] == "POSTED":
        record["posting_status"] = "RELEASED"
    services.touch(record)
    services.void_application_cascade(record, reason)
    return ok(application_out(record))


@bp.post("/applications/<application_id>/release-posting")
@endpoint(("Applicator",))
def release_posting(application_id):
    path_uuid(application_id, "ERR_APPLICATION_NOT_FOUND")
    body()
    record = services.require(store.applications, application_id,
                              "ERR_APPLICATION_NOT_FOUND")
    if record["posting_status"] != "POSTED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    expiry = record["rei_expires_at"]
    if expiry is not None and clock() < expiry:
        raise ApiError("ERR_REI_ACTIVE")

    record["posting_status"] = "RELEASED"
    services.touch(record)
    area = store.turf_areas.get(record["turf_area_id"])
    if area is not None:
        services.recompute_turf_rei(area)
        services.touch(area)
    return ok(application_out(record))
