"""Product qualifications, lab validation runs and decisions (PRD 3.2)."""
from flask import Blueprint

import calc
import clock
import errors
import response
import serializers
import services
import validation
from db import db, insert, insert_event, ordered, touch
from middleware import (ROLE_ADMIN, ROLE_CUSTOMER, ROLE_QUALITY, ROLE_SCHEDULER,
                        acting_user, endpoint, is_customer, require_owner)

bp = Blueprint("qualifications", __name__)

QUALIFICATION_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_VALIDATION", "CHANGES_REQUESTED",
                          "QUALIFIED", "EXPIRED", "SUPERSEDED")
INTEGRITY_RESULTS = ("PASS", "MARGINAL", "FAIL")
DECISION_OUTCOMES = ("QUALIFY", "REQUEST_CHANGES")


def _recipe(data):
    return {
        "sku_code": validation.get_str(data, "sku_code"),
        "version_label": validation.get_str(data, "version_label"),
        "pressure_mpa": validation.get_num(data, "pressure_mpa",
                                           exclusive_minimum=0, maximum=600),
        "hold_time_seconds": validation.get_int(data, "hold_time_seconds",
                                                exclusive_minimum=0),
        "max_water_temp_c": validation.get_num(data, "max_water_temp_c"),
        "package_format": validation.get_enum(data, "package_format",
                                              calc.PACKAGE_FORMATS),
        "package_burst_pressure_mpa": validation.get_num(data,
                                                         "package_burst_pressure_mpa"),
        "film_thickness_micron": validation.get_int(data, "film_thickness_micron",
                                                    exclusive_minimum=0),
        "target_log_reduction": validation.get_num(data, "target_log_reduction"),
    }


def _reject_duplicate_version(customer_id, sku_code, version_label):
    for row in db.qualifications.values():
        if (row["customer_id"] == customer_id and row["sku_code"] == sku_code
                and row["version_label"] == version_label):
            raise errors.conflict(
                "ERR_DUPLICATE_QUALIFICATION_VERSION",
                "This customer already has that SKU at that version label.")


def _create_qualification(customer_id, product_family_id, supersedes_id, recipe):
    fields = dict(recipe)
    fields.update({
        "customer_id": customer_id,
        "product_family_id": product_family_id,
        "supersedes_qualification_id": supersedes_id,
        "package_suitability_score": calc.package_suitability_score(
            recipe["pressure_mpa"], recipe["package_burst_pressure_mpa"],
            recipe["film_thickness_micron"], recipe["package_format"]),
        "validation_run_acceptable_count": 0,
        "revision_round": 0,
        "status": "DRAFT",
        "qualified_at": None,
        "expires_at": None,
    })
    return insert(db.qualifications, fields)


@bp.post("/product-qualifications")
@endpoint([ROLE_CUSTOMER])
def create_qualification():
    data = validation.body()
    customer_id = validation.get_id(data, "customer_id")
    product_family_id = validation.get_id(data, "product_family_id")
    recipe = _recipe(data)
    supersedes_id = validation.get_id(data, "supersedes_qualification_id",
                                      required=False, default=None)

    services.find(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    services.find(db.product_families, product_family_id,
                  "ERR_PRODUCT_FAMILY_NOT_FOUND")
    if supersedes_id is not None:
        services.find(db.qualifications, supersedes_id, "ERR_QUALIFICATION_NOT_FOUND")

    require_owner(customer_id)
    _reject_duplicate_version(customer_id, recipe["sku_code"], recipe["version_label"])

    row = _create_qualification(customer_id, product_family_id, supersedes_id, recipe)
    return response.created(serializers.plain(row))


@bp.post("/product-qualifications/<row_id>/supersede")
@endpoint([ROLE_CUSTOMER])
def supersede_qualification(row_id):
    data = validation.body()
    expected_version = validation.get_int(data, "expected_qualification_version")
    recipe = _recipe(data)

    source = services.find(db.qualifications, row_id, "ERR_QUALIFICATION_NOT_FOUND")
    require_owner(source["customer_id"])
    if expected_version != source["version"]:
        raise errors.precondition("ERR_STALE_QUALIFICATION_VERSION",
                                  "The qualification has changed since it was read.")
    if source["status"] != "QUALIFIED":
        raise errors.conflict("ERR_INVALID_QUALIFICATION_STATE",
                              "Only a QUALIFIED qualification may be superseded.")
    _reject_duplicate_version(source["customer_id"], recipe["sku_code"],
                              recipe["version_label"])

    revision = _create_qualification(source["customer_id"], source["product_family_id"],
                                     source["id"], recipe)
    source["status"] = "SUPERSEDED"
    touch(source)
    return response.created(serializers.plain(revision))


@bp.post("/product-qualifications/<row_id>/submit")
@endpoint([ROLE_CUSTOMER])
def submit_qualification(row_id):
    row = services.find(db.qualifications, row_id, "ERR_QUALIFICATION_NOT_FOUND")
    require_owner(row["customer_id"])
    if row["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise errors.conflict("ERR_INVALID_QUALIFICATION_STATE",
                              "Only a DRAFT or CHANGES_REQUESTED qualification may be "
                              "submitted.")
    if (row["status"] == "CHANGES_REQUESTED"
            and row["revision_round"] > calc.MAX_REVISION_ROUNDS):
        raise errors.unprocessable("ERR_REVISION_LIMIT_REACHED",
                                   "The revision round limit has been reached.")
    row["status"] = "SUBMITTED"
    touch(row)
    return response.object_response(serializers.plain(row))


@bp.post("/product-qualifications/<row_id>/validation-runs")
@endpoint([ROLE_QUALITY])
def create_validation_run(row_id):
    data = validation.body()
    measured_pressure = validation.get_num(data, "measured_pressure_mpa")
    measured_hold = validation.get_int(data, "measured_hold_time_seconds")
    achieved_log_reduction = validation.get_num(data, "achieved_log_reduction")
    integrity = validation.get_enum(data, "package_integrity_result", INTEGRITY_RESULTS)
    units_tested = validation.get_int(data, "units_tested", exclusive_minimum=0)
    leaker_count = validation.get_int(data, "leaker_count", minimum=0)
    if leaker_count > units_tested:
        raise errors.invalid_request("Field 'leaker_count' may not exceed 'units_tested'.")

    qualification = services.find(db.qualifications, row_id,
                                  "ERR_QUALIFICATION_NOT_FOUND")
    if qualification["status"] not in ("SUBMITTED", "UNDER_VALIDATION"):
        raise errors.conflict("ERR_INVALID_QUALIFICATION_STATE",
                              "Validation runs may only be appended to a SUBMITTED or "
                              "UNDER_VALIDATION qualification.")

    acceptable = (integrity == "PASS"
                  and calc.D(measured_pressure) >= calc.D(qualification["pressure_mpa"])
                  and int(measured_hold) >= int(qualification["hold_time_seconds"])
                  and calc.D(achieved_log_reduction)
                  >= calc.D(qualification["target_log_reduction"]))

    run = insert_event(db.validation_runs, {
        "qualification_id": qualification["id"],
        "measured_pressure_mpa": measured_pressure,
        "measured_hold_time_seconds": measured_hold,
        "achieved_log_reduction": achieved_log_reduction,
        "package_integrity_result": integrity,
        "units_tested": units_tested,
        "leaker_count": leaker_count,
        "run_verdict": "ACCEPTABLE" if acceptable else "UNACCEPTABLE",
        "recorded_by_user_id": acting_user(),
    })

    qualification["validation_run_acceptable_count"] = sum(
        1 for r in services.runs_of_qualification(qualification["id"])
        if r["run_verdict"] == "ACCEPTABLE")
    if qualification["status"] == "SUBMITTED":
        qualification["status"] = "UNDER_VALIDATION"
    touch(qualification)

    return response.created(serializers.plain(run))


@bp.get("/product-qualifications/<row_id>/validation-runs")
@endpoint([ROLE_QUALITY, ROLE_CUSTOMER])
def list_validation_runs(row_id):
    limit, offset = validation.pagination()
    qualification = services.find(db.qualifications, row_id,
                                  "ERR_QUALIFICATION_NOT_FOUND")
    require_owner(qualification["customer_id"])
    rows = services.runs_of_qualification(qualification["id"])
    return response.page(rows, serializers.plain, limit, offset)


@bp.post("/product-qualifications/<row_id>/decision")
@endpoint([ROLE_QUALITY])
def decide_qualification(row_id):
    data = validation.body()
    outcome = validation.get_enum(data, "outcome", DECISION_OUTCOMES)
    validation.get_str(data, "decision_note", required=False, default=None)

    row = services.find(db.qualifications, row_id, "ERR_QUALIFICATION_NOT_FOUND")
    if row["status"] != "UNDER_VALIDATION":
        raise errors.conflict("ERR_INVALID_QUALIFICATION_STATE",
                              "Only an UNDER_VALIDATION qualification may be decided.")

    if outcome == "QUALIFY":
        if row["validation_run_acceptable_count"] < calc.MIN_ACCEPTABLE_VALIDATION_RUNS:
            raise errors.unprocessable("ERR_INSUFFICIENT_VALIDATION_RUNS",
                                       "At least two acceptable validation runs are "
                                       "required.")
        if row["package_format"] == "GLASS":
            raise errors.unprocessable("ERR_PACKAGE_FORMAT_NOT_PERMITTED",
                                       "Glass is never HPP-suitable.")
        if not (calc.D(row["package_burst_pressure_mpa"])
                > calc.D(row["pressure_mpa"])):
            raise errors.unprocessable("ERR_BURST_PRESSURE_INSUFFICIENT",
                                       "Burst pressure must exceed the process "
                                       "pressure.")
        if calc.D(row["package_suitability_score"]) < calc.MIN_PACKAGE_SUITABILITY_SCORE:
            raise errors.unprocessable("ERR_PACKAGE_NOT_SUITABLE",
                                       "The package suitability score is below 70.00.")
        now = clock.now()
        row["status"] = "QUALIFIED"
        row["qualified_at"] = now
        row["expires_at"] = clock.plus_days(now, calc.QUALIFICATION_VALID_DAYS)
    else:
        row["status"] = "CHANGES_REQUESTED"
        row["revision_round"] += 1
    touch(row)
    return response.object_response(serializers.plain(row))


@bp.get("/product-qualifications/<row_id>")
@endpoint([ROLE_CUSTOMER, ROLE_QUALITY, ROLE_SCHEDULER])
def get_qualification(row_id):
    row = services.find(db.qualifications, row_id, "ERR_QUALIFICATION_NOT_FOUND")
    require_owner(row["customer_id"])
    return response.object_response(serializers.plain(row))


@bp.get("/product-qualifications")
@endpoint([ROLE_CUSTOMER, ROLE_QUALITY, ROLE_SCHEDULER, ROLE_ADMIN])
def list_qualifications():
    limit, offset = validation.pagination()
    customer_id = validation.qs_str("customer_id")
    product_family_id = validation.qs_str("product_family_id")
    supersedes_id = validation.qs_str("supersedes_qualification_id")
    status = validation.qs_enum("status", QUALIFICATION_STATUSES)

    rows = []
    for row in db.qualifications.values():
        if customer_id is not None and row["customer_id"] != customer_id:
            continue
        if product_family_id is not None and row["product_family_id"] != product_family_id:
            continue
        if (supersedes_id is not None
                and row["supersedes_qualification_id"] != supersedes_id):
            continue
        if status is not None and row["status"] != status:
            continue
        if is_customer() and row["customer_id"] != acting_user():
            continue
        rows.append(row)
    return response.page(ordered(rows), serializers.plain, limit, offset)
