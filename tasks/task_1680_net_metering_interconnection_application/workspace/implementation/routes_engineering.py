"""Screening reports, supplemental reviews, and upgrade cost estimates
(PRD 3.4 / 3.5)."""

import datetime

import clock as clockmod
import envelope
import serializers as ser
import services
from errors import ApiError
from flask import Blueprint
from middleware import (begin, must_exist, must_ref, opt_string, paginate,
                        pagination, req_enum, req_int, req_string)
from store import db, stamp_new, sorted_rows, touch

bp = Blueprint("engineering", __name__)

REVIEW_TYPES = ("FACILITIES_STUDY", "SYSTEM_IMPACT_STUDY")
REVIEW_COMPLETION_OUTCOMES = ("CLEARED", "UPGRADES_REQUIRED", "DENIED")


def own_application(ctx, application):
    account = services.account_of(application)
    if account is None or account["customer_id"] != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")


# ---------------------------------------------------------------------------
# Screening reports (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.route("/screening-reports", methods=["POST"])
def create_screening_report():
    ctx = begin("DistributionEngineer")
    application_id = req_string(ctx.body, "application_id")
    application = must_ref(db.applications, application_id)
    if application["application_status"] != "CAPACITY_RESERVED":
        raise ApiError("ERR_INVALID_STATE")

    account = services.account_of(application)
    program = services.program_of(application)
    transformer = services.transformer_of(account)
    feeder = db.feeders.get(transformer["feeder_id"])
    size = application["system_size_watts_ac"]

    transformer_after = (
        services.screening_basis_aggregate("transformer", transformer, program, application) + size
    )
    transformer_limit = transformer["nameplate_watts"] * services.TRANSFORMER_LIMIT_PCT // 100
    transformer_passed = transformer_after <= transformer_limit

    feeder_after = (
        services.screening_basis_aggregate("feeder", feeder, program, application) + size
    )
    feeder_limit = feeder["peak_load_watts"] * services.FEEDER_LIMIT_PCT // 100
    feeder_passed = feeder_after < feeder_limit  # strict: equality fails

    size_within_fast_track = size <= services.FAST_TRACK_LIMIT_WATTS

    failing = []
    if not transformer_passed:
        failing.append("TRANSFORMER_CAPACITY")
    if not feeder_passed:
        failing.append("FEEDER_PENETRATION")
    if not size_within_fast_track:
        failing.append("FAST_TRACK_SIZE")
    outcome = "PASSED" if not failing else "FAILED"

    prior_count = 0
    for report in db.reports.values():
        if report["application_id"] == application["id"]:
            prior_count += 1
            if report["report_status"] == "CURRENT":
                report["report_status"] = "SUPERSEDED"
                touch(report)

    row = stamp_new({
        "application_id": application["id"],
        "screening_round": prior_count + 1,
        "report_status": "CURRENT",
        "aggregate_basis": program["screening_basis"],
        "transformer_aggregate_after_watts": transformer_after,
        "transformer_limit_watts": transformer_limit,
        "transformer_screen_passed": transformer_passed,
        "feeder_aggregate_after_watts": feeder_after,
        "feeder_limit_watts": feeder_limit,
        "feeder_screen_passed": feeder_passed,
        "size_within_fast_track": size_within_fast_track,
        "outcome": outcome,
        "failing_screens": failing,
    })
    db.reports[row["id"]] = row

    application["application_status"] = "SCREEN_PASSED" if outcome == "PASSED" else "SUPPLEMENTAL_REVIEW"
    touch(application)
    return envelope.created(ser.screening_report(row))


@bp.route("/screening-reports", methods=["GET"])
def list_screening_reports():
    ctx = begin()
    rows = list(db.reports.values())
    application_id = ctx.query.get("application_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.screening_report(r) for r in page], limit, offset, total)


@bp.route("/screening-reports/<screening_report_id>", methods=["GET"])
def get_screening_report(screening_report_id):
    begin()
    row = must_exist(db.reports, screening_report_id)
    return envelope.ok(ser.screening_report(row))


# ---------------------------------------------------------------------------
# Supplemental reviews (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.route("/supplemental-reviews", methods=["POST"])
def create_supplemental_review():
    ctx = begin("DistributionEngineer")
    body = ctx.body
    application_id = req_string(body, "application_id")
    review_type = req_enum(body, "review_type", REVIEW_TYPES)
    findings = opt_string(body, "findings")
    application = must_ref(db.applications, application_id)
    if application["application_status"] != "SUPPLEMENTAL_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    for other in db.reviews.values():
        if other["application_id"] == application_id and other["review_status"] == "OPEN":
            raise ApiError("ERR_SUPPLEMENTAL_REVIEW_OPEN")
    row = stamp_new({
        "application_id": application_id,
        "review_type": review_type,
        "review_status": "OPEN",
        "outcome": None,
        "findings": findings,
    })
    db.reviews[row["id"]] = row
    return envelope.created(ser.supplemental_review(row))


@bp.route("/supplemental-reviews", methods=["GET"])
def list_supplemental_reviews():
    ctx = begin()
    rows = list(db.reviews.values())
    application_id = ctx.query.get("application_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.supplemental_review(r) for r in page], limit, offset, total)


@bp.route("/supplemental-reviews/<supplemental_review_id>", methods=["GET"])
def get_supplemental_review(supplemental_review_id):
    begin()
    row = must_exist(db.reviews, supplemental_review_id)
    return envelope.ok(ser.supplemental_review(row))


@bp.route("/supplemental-reviews/<supplemental_review_id>/complete", methods=["POST"])
def complete_supplemental_review(supplemental_review_id):
    ctx = begin("DistributionEngineer")
    row = must_exist(db.reviews, supplemental_review_id)
    outcome = req_enum(ctx.body, "outcome", REVIEW_COMPLETION_OUTCOMES)
    findings = opt_string(ctx.body, "findings")
    if row["review_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    row["review_status"] = "COMPLETED"
    row["outcome"] = outcome
    if findings is not None:
        row["findings"] = findings
    touch(row)

    application = db.applications.get(row["application_id"])
    if application is not None and application["application_status"] == "SUPPLEMENTAL_REVIEW":
        if outcome == "CLEARED":
            application["application_status"] = "SCREEN_PASSED"
            touch(application)
        elif outcome == "UPGRADES_REQUIRED":
            application["application_status"] = "AWAITING_COST_ESTIMATE"
            touch(application)
        else:  # DENIED
            application["application_status"] = "DENIED"
            application["denial_reason"] = "TECHNICALLY_INFEASIBLE"
            services.release_reservation(application)
            touch(application)
            program = services.program_of(application)
            services.promotion_scan(program)
            services.recompute_posture(program)
    return envelope.ok(ser.supplemental_review(row))


# ---------------------------------------------------------------------------
# Upgrade cost estimates (PRD 3.5)
# ---------------------------------------------------------------------------

def _validate_items(body):
    items = body.get("items")
    if not isinstance(items, list):
        raise ApiError("ERR_INVALID_REQUEST", "items must be an array.")
    for item in items:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each item must be an object.")
        if not isinstance(item.get("description"), str):
            raise ApiError("ERR_INVALID_REQUEST", "each item requires a description string.")
        amount = item.get("amount_cents")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ApiError("ERR_INVALID_REQUEST", "each item requires a non-negative integer amount_cents.")
    return items


@bp.route("/cost-estimates", methods=["POST"])
def create_cost_estimate():
    ctx = begin("DistributionEngineer")
    body = ctx.body
    application_id = req_string(body, "application_id")
    supplemental_review_id = req_string(body, "supplemental_review_id")
    items = _validate_items(body)
    contingency_pct = req_int(body, "contingency_pct", minimum=0, maximum=100)
    expected_version = body.get("expected_application_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_application_version must be an integer.")

    application = must_ref(db.applications, application_id)
    must_ref(db.reviews, supplemental_review_id)

    if application["version"] != expected_version:
        raise ApiError("ERR_STALE_APPLICATION_VERSION")
    if application["application_status"] not in ("AWAITING_COST_ESTIMATE", "CUSTOMER_DECISION_PENDING"):
        raise ApiError("ERR_INVALID_STATE")

    subtotal_cents = sum(item["amount_cents"] for item in items)
    total_cents = (subtotal_cents * (100 + contingency_pct) + 50) // 100

    for other in db.estimates.values():
        if other["application_id"] == application_id and other["estimate_status"] == "ISSUED":
            other["estimate_status"] = "SUPERSEDED"
            touch(other)

    row = stamp_new({
        "application_id": application_id,
        "supplemental_review_id": supplemental_review_id,
        "items": items,
        "contingency_pct": contingency_pct,
        "total_cents": total_cents,
        "estimate_status": "ISSUED",
        "valid_until": clockmod.now() + datetime.timedelta(days=services.ESTIMATE_VALIDITY_DAYS),
        "decided_at": None,
    })
    db.estimates[row["id"]] = row

    application["application_status"] = "CUSTOMER_DECISION_PENDING"
    touch(application)
    return envelope.created(ser.cost_estimate(row))


@bp.route("/cost-estimates", methods=["GET"])
def list_cost_estimates():
    ctx = begin()
    rows = list(db.estimates.values())
    application_id = ctx.query.get("application_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    supplemental_review_id = ctx.query.get("supplemental_review_id")
    if supplemental_review_id is not None:
        rows = [r for r in rows if r["supplemental_review_id"] == supplemental_review_id]
    estimate_status = ctx.query.get("estimate_status")
    if estimate_status is not None:
        rows = [r for r in rows if r["estimate_status"] == estimate_status]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.cost_estimate(r) for r in page], limit, offset, total)


@bp.route("/cost-estimates/<cost_estimate_id>", methods=["GET"])
def get_cost_estimate(cost_estimate_id):
    begin()
    row = must_exist(db.estimates, cost_estimate_id)
    return envelope.ok(ser.cost_estimate(row))


@bp.route("/cost-estimates/<cost_estimate_id>/accept", methods=["POST"])
def accept_cost_estimate(cost_estimate_id):
    ctx = begin("Applicant")
    row = must_exist(db.estimates, cost_estimate_id)
    application = db.applications.get(row["application_id"])
    if application is not None:
        own_application(ctx, application)
    if row["estimate_status"] != "ISSUED":
        raise ApiError("ERR_ESTIMATE_NOT_ISSUED")
    if clockmod.now() > row["valid_until"]:
        raise ApiError("ERR_ESTIMATE_EXPIRED")
    row["estimate_status"] = "ACCEPTED"
    row["decided_at"] = clockmod.now()
    touch(row)
    if application is not None:
        application["application_status"] = "UPGRADE_IN_PROGRESS"
        touch(application)
    return envelope.ok(ser.cost_estimate(row))


@bp.route("/cost-estimates/<cost_estimate_id>/decline", methods=["POST"])
def decline_cost_estimate(cost_estimate_id):
    ctx = begin("Applicant")
    row = must_exist(db.estimates, cost_estimate_id)
    application = db.applications.get(row["application_id"])
    if application is not None:
        own_application(ctx, application)
    if row["estimate_status"] != "ISSUED":
        raise ApiError("ERR_ESTIMATE_NOT_ISSUED")
    row["estimate_status"] = "DECLINED"
    row["decided_at"] = clockmod.now()
    touch(row)
    if application is not None and application["application_status"] in services.WITHDRAWABLE:
        services.withdraw_application(application, "CUSTOMER_DECLINED")
    return envelope.ok(ser.cost_estimate(row))


@bp.route("/cost-estimates/<cost_estimate_id>/mark-work-complete", methods=["POST"])
def mark_work_complete(cost_estimate_id):
    begin("DistributionEngineer")
    row = must_exist(db.estimates, cost_estimate_id)
    if row["estimate_status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE")
    row["estimate_status"] = "WORK_COMPLETE"
    touch(row)
    application = db.applications.get(row["application_id"])
    if application is not None and application["application_status"] == "UPGRADE_IN_PROGRESS":
        application["application_status"] = "SCREEN_PASSED"
        touch(application)
    return envelope.ok(ser.cost_estimate(row))
