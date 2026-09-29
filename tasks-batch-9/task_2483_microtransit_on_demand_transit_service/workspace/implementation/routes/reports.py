"""Subsidy reporting and certification (PRD Section 3.9)."""
from flask import Blueprint

import db
import listing
import middleware
import response
import serializers
import validation
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import reports as report_service

bp = Blueprint("reports", __name__)

VARIANTS = ("PROVISIONAL", "FINAL")
SUBMITTABLE = ("DRAFT", "REJECTED", "AMENDED")


def get_report(report_id):
    report = db.subsidy_reports.get(report_id)
    if report is None:
        raise ApiError("ERR_SUBSIDY_REPORT_NOT_FOUND")
    return report


@bp.post("/subsidy-reports")
@endpoint(["FinanceAnalyst"])
def create_report():
    body = validation.get_body()

    zone_raw = validation.raw_fk(body, "zone_id")
    zone = db.service_zones.get(zone_raw) if zone_raw is not None else None
    if zone_raw is not None and zone is None:
        raise ApiError("ERR_SERVICE_ZONE_NOT_FOUND")

    validation.req_str(body, "zone_id")
    period_start = validation.req_date(body, "period_start_date")
    period_end = validation.req_date(body, "period_end_date")
    variant = validation.req_enum(body, "variant", VARIANTS)

    # priority 10 -- reporting period ordering
    if period_end < period_start:
        raise ApiError("ERR_REPORT_PERIOD_INVALID")

    # priority 27 -- reporting period overlap
    if report_service.period_overlaps(zone["id"], variant, period_start, period_end):
        raise ApiError("ERR_REPORT_PERIOD_OVERLAP")

    report = db.base_record()
    report.update({
        "zone_id": zone["id"],
        "period_start_date": period_start,
        "period_end_date": period_end,
        "variant": variant,
        "state": "DRAFT",
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
        "rejection_reason": None,
        "amendment_count": 0,
        "total_trips": 0,
        "total_fare_revenue_cents": 0,
        "total_operating_cost_cents": 0,
        "subsidy_per_trip_cents": 0,
    })
    report_service.recompute_totals(report)
    db.subsidy_reports.add(report)
    return response.created(serializers.pick(report, serializers.SUBSIDY_REPORT))


@bp.post("/subsidy-reports/<report_id>/submit")
@endpoint(["FinanceAnalyst"])
def submit_report(report_id):
    report = get_report(report_id)
    if report["state"] not in SUBMITTABLE:
        raise ApiError("ERR_INVALID_REPORT_STATE")

    report["state"] = "SUBMITTED"
    report["submitted_by_user_id"] = middleware.user_id()
    report["rejection_reason"] = None
    report_service.recompute_totals(report)
    db.touch(report)
    return response.object_response(
        serializers.pick(report, serializers.SUBSIDY_REPORT))


@bp.post("/subsidy-reports/<report_id>/certify")
@endpoint(["FundingAgencyAuditor"])
def certify_report(report_id):
    report = get_report(report_id)
    body = validation.get_body()
    validation.opt_str(body, "note", min_len=0)

    if report["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_REPORT_STATE")

    # priority 16 -- segregation of duties
    if middleware.user_id() == report["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # priority 21 -- the equivalent-service verdict
    zone = db.service_zones.get(report["zone_id"])
    if zone is None or zone["equivalence_verdict"] != "COMPLIANT":
        raise ApiError("ERR_EQUIVALENCE_DEFICIENT")

    # priority 35 -- every block in the period finalised
    if report_service.blocks_not_finalized(report):
        raise ApiError("ERR_BLOCKS_NOT_FINALIZED")

    report["state"] = "CERTIFIED"
    report["certified_by_user_id"] = middleware.user_id()
    db.touch(report)
    return response.object_response(
        serializers.pick(report, serializers.SUBSIDY_REPORT))


@bp.post("/subsidy-reports/<report_id>/reject")
@endpoint(["FundingAgencyAuditor"])
def reject_report(report_id):
    report = get_report(report_id)
    body = validation.get_body()
    reason = validation.req_str(body, "rejection_reason")

    if report["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_REPORT_STATE")

    report["state"] = "REJECTED"
    report["rejection_reason"] = reason
    report["submitted_by_user_id"] = None
    db.touch(report)
    return response.object_response(
        serializers.pick(report, serializers.SUBSIDY_REPORT))


@bp.post("/subsidy-reports/<report_id>/amend")
@endpoint(["FinanceAnalyst"])
def amend_report(report_id):
    report = get_report(report_id)
    if report["state"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_REPORT_STATE")

    report["state"] = "AMENDED"
    report["amendment_count"] += 1
    report["certified_by_user_id"] = None
    report["submitted_by_user_id"] = None
    db.touch(report)
    return response.object_response(
        serializers.pick(report, serializers.SUBSIDY_REPORT))


@bp.get("/subsidy-reports/<report_id>")
@endpoint(ALL_ROLES)
def read_report(report_id):
    report = get_report(report_id)
    return response.object_response(
        serializers.pick(report, serializers.SUBSIDY_REPORT))


@bp.get("/subsidy-reports")
@endpoint(ALL_ROLES)
def list_reports():
    return listing.list_endpoint(
        db.subsidy_reports.ordered(), serializers.SUBSIDY_REPORT,
        {"zone_id": "zone_id", "state": "state", "variant": "variant"})
