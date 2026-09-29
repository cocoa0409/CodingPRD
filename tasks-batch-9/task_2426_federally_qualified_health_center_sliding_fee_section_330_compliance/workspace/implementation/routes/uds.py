"""Uniform data system annual reports and their clinical quality measures."""

from flask import Blueprint

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, owner_ref, require, state
from services import uds as uds_svc
from validation import Field, pagination, parse_body

bp = Blueprint("uds", __name__)

MAX_UDS_RETURN_ROUNDS = 3

MEASURE_FIELDS = [
    Field("uds_report_id", "string"),
    Field("measure_code", "string", required=True),
    Field("numerator", "integer", required=True, minimum=0),
    Field("denominator", "integer", required=True, minimum=0),
    Field("benchmark_pct", "number", required=True, minimum=0, maximum=100),
]


def _reports_of(hc_id):
    return db.in_creation_order(
        [r for r in db.db.uds_reports.values() if r["health_center_id"] == hc_id]
    )


@bp.post("/health-centers/<hc_id>/uds-reports")
def create_report(hc_id):
    authorize("ComplianceOfficer")
    body = parse_body(
        [
            Field("health_center_id", "string"),
            Field("reporting_year", "integer", required=True, minimum=2000, maximum=2100),
        ]
    )
    require("health_centers", hc_id)
    owner_ref(body, "health_center_id", "health_centers", hc_id)

    # Rung 29 — one report per grantee per reporting year.
    for existing in _reports_of(hc_id):
        if existing["reporting_year"] == body["reporting_year"]:
            raise ApiError("ERR_DUPLICATE_CHILD_KEY")

    row = db.base_row()
    row.update(
        {
            "health_center_id": hc_id,
            "reporting_year": body["reporting_year"],
            "status": "DRAFT",
            "total_patient_count": 0,
            "patients_at_or_below_100_count": 0,
            "patients_101_to_150_count": 0,
            "patients_151_to_200_count": 0,
            "patients_over_200_count": 0,
            "unverified_patient_count": 0,
            "composite_quality_rate_pct": None,
            "included_measure_count": 0,
            "computed_at": None,
            "submitted_by_user_id": None,
            "adjudicated_by_user_id": None,
            "return_reason": None,
            "return_round": 0,
        }
    )
    db.db.uds_reports[row["id"]] = row
    return object_response(serializers.uds_report(row), 201)


@bp.get("/uds-reports/<report_id>")
def read_report(report_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.uds_report(require("uds_reports", report_id)))


@bp.get("/health-centers/<hc_id>/uds-reports")
def list_reports(hc_id):
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    require("health_centers", hc_id)
    return listing(
        _reports_of(hc_id),
        serializers.uds_report,
        limit,
        offset,
        specs=[
            ("status", "status", "string"),
            ("reporting_year", "reporting_year", "integer"),
        ],
    )


@bp.post("/uds-reports/<report_id>/compute")
def compute_report(report_id):
    authorize("ComplianceOfficer")
    parse_body([])
    report = require("uds_reports", report_id)

    state(report, "status", ("DRAFT", "RETURNED"))
    looping = report["status"] == "RETURNED"
    if looping and report["return_round"] >= MAX_UDS_RETURN_ROUNDS:
        raise ApiError("ERR_LOOP_LIMIT_EXCEEDED")

    if looping:
        report["return_round"] += 1
        report["status"] = "DRAFT"

    report.update(uds_svc.income_distribution(report))
    report.update(uds_svc.composite_quality_rate(report))
    report["computed_at"] = db.now()
    db.touch(report)
    return object_response(serializers.uds_report(report))


@bp.post("/uds-reports/<report_id>/submit")
def submit_report(report_id):
    user_id = authorize("ComplianceOfficer")
    parse_body([])
    report = require("uds_reports", report_id)

    state(report, "status", ("DRAFT",))

    # Rung 40 — the report must have been computed and carry a measure.
    if report["computed_at"] is None or report["included_measure_count"] < 1:
        raise ApiError("ERR_UDS_REPORT_NOT_COMPUTED")

    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = user_id
    db.touch(report)
    return object_response(serializers.uds_report(report))


@bp.post("/uds-reports/<report_id>/adjudicate")
def adjudicate_report(report_id):
    user_id = authorize("ProjectOfficer")
    body = parse_body(
        [
            Field("decision", "enum", required=True, enum=("ACCEPT", "RETURN")),
            Field("return_reason", "string", nullable=True),
        ]
    )
    report = require("uds_reports", report_id)

    state(report, "status", ("SUBMITTED",))

    if body["decision"] == "ACCEPT":
        report["status"] = "ACCEPTED"
        report["adjudicated_by_user_id"] = user_id
    else:
        report["status"] = "RETURNED"
        report["adjudicated_by_user_id"] = user_id
        report["return_reason"] = body.get("return_reason")
    db.touch(report)
    return object_response(serializers.uds_report(report))


# --------------------------------------------------------------------------- #
# quality measure results
# --------------------------------------------------------------------------- #


@bp.post("/uds-reports/<report_id>/quality-measure-results")
def create_measure(report_id):
    authorize("ComplianceOfficer")
    body = parse_body(MEASURE_FIELDS)
    require("uds_reports", report_id)
    owner_ref(body, "uds_report_id", "uds_reports", report_id)

    # Rung 29 — one row per measure_code per report.
    for existing in uds_svc.measures_of(report_id):
        if existing["measure_code"] == body["measure_code"]:
            raise ApiError("ERR_DUPLICATE_CHILD_KEY")

    row = db.base_row()
    row.update(
        {
            "uds_report_id": report_id,
            "measure_code": body["measure_code"],
            "numerator": body["numerator"],
            "denominator": body["denominator"],
            "benchmark_pct": body["benchmark_pct"],
            "rate_pct": None,
            "inclusion_status": "INCLUDED",
            "meets_benchmark": None,
        }
    )
    db.db.quality_measure_results[row["id"]] = row
    return object_response(serializers.quality_measure_result(row), 201)


@bp.get("/quality-measure-results/<measure_id>")
def read_measure(measure_id):
    authorize(*ALL_ROLES)
    return object_response(
        serializers.quality_measure_result(require("quality_measure_results", measure_id))
    )


@bp.get("/uds-reports/<report_id>/quality-measure-results")
def list_measures(report_id):
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    require("uds_reports", report_id)
    return listing(
        uds_svc.measures_of(report_id),
        serializers.quality_measure_result,
        limit,
        offset,
        specs=[("inclusion_status", "inclusion_status", "string")],
    )
