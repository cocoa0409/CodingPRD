"""Accreditation reporting and Cascade C (PRD 3.9).

The two variants aggregate the same pool differently on purpose, and the
dispatcher-equal-weight variant keeps its per-dispatcher rates unrounded so
that only the programme mean is ever rounded.
"""
from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
import helpers
import validate
from auth import require
from cascades import set_fields
from envelope import ok, public
from errors import fail
from store import base_row, clock, db

bp = Blueprint("reports", __name__)

VARIANTS = ("CASE_WEIGHTED", "DISPATCHER_EQUAL_WEIGHT")
RECIPIENTS = ("MEDICAL_DIRECTOR", "OVERSIGHT_COMMITTEE")


def _pool(program_id, window_start, window_end):
    """FINALIZED reviews of the programme's dispatchers inside [start, end)."""
    rows = []
    for review in db.reviews.values():
        if review["status"] != "FINALIZED":
            continue
        dispatcher = db.dispatchers.get(review["dispatcher_id"])
        if dispatcher is None or dispatcher["program_id"] != program_id:
            continue
        finalized_at = review["finalized_at"]
        if finalized_at is None:
            continue
        if not (window_start <= finalized_at < window_end):
            continue
        rows.append(review)
    return rows


def _case_weighted_pct(compliant_count, review_count):
    return calc.q1(calc.HUNDRED * Decimal(compliant_count) / Decimal(review_count))


def _dispatcher_equal_weight_pct(pool):
    totals = {}
    for review in pool:
        entry = totals.setdefault(review["dispatcher_id"], [0, 0])
        entry[0] += 1
        if review["compliant"]:
            entry[1] += 1
    # Each per-dispatcher rate stays unrounded; only the mean is rounded.
    summed = Decimal("0")
    for count, compliant in totals.values():
        summed += Decimal(compliant) / Decimal(count)
    return calc.q1(calc.HUNDRED * (summed / Decimal(len(totals))))


def _high_risk_figures(pool):
    high_risk = [r for r in pool if r["high_risk"]]
    passes = 0
    for review in high_risk:
        record = cascades.hrcr_of_review(review["id"])
        if record is not None and record["dacpr_pass"] is True:
            passes += 1
    if not high_risk:
        pct = None
    else:
        pct = calc.q1(
            calc.HUNDRED * Decimal(passes) / Decimal(len(high_risk))
        )
    return len(high_risk), passes, pct


@bp.post("/audit-programs/<program_id>/accreditation-reports")
@require("AccreditationOfficer")
def build_report(program_id):
    payload = validate.body()
    variant = validate.get_enum(payload, "variant", VARIANTS)
    window_start = validate.get_instant(payload, "window_start")
    window_end = validate.get_instant(payload, "window_end")

    program = helpers.program(program_id)

    if window_end <= window_start:
        fail(
            "ERR_REPORT_WINDOW_INVALID",
            "window_end must be strictly after window_start.",
        )

    pool = _pool(program["id"], window_start, window_end)
    if not pool:
        fail(
            "ERR_NO_FINALIZED_REVIEWS_IN_WINDOW",
            "No finalized reviews fall inside the window.",
        )

    review_count = len(pool)
    compliant_count = len([r for r in pool if r["compliant"]])
    dispatcher_count = len(set(r["dispatcher_id"] for r in pool))
    if variant == "CASE_WEIGHTED":
        compliance_pct = _case_weighted_pct(compliant_count, review_count)
    else:
        compliance_pct = _dispatcher_equal_weight_pct(pool)

    hr_count, hr_passes, hr_pct = _high_risk_figures(pool)
    threshold_met = compliance_pct >= program["target_compliance_pct"] and (
        hr_pct is None or hr_pct >= program["high_risk_target_pct"]
    )

    report = base_row()
    report.update(
        {
            "program_id": program["id"],
            "variant": variant,
            "window_start": window_start,
            "window_end": window_end,
            "review_count": review_count,
            "compliant_review_count": compliant_count,
            "dispatcher_count": dispatcher_count,
            "compliance_pct": compliance_pct,
            "high_risk_review_count": hr_count,
            "high_risk_pass_count": hr_passes,
            "high_risk_compliance_pct": hr_pct,
            "threshold_met": bool(threshold_met),
            "status": "DRAFT",
            "submitted_to": None,
            "submitted_at": None,
        }
    )
    db.reports[report["id"]] = report
    return ok(public(report), 201)


@bp.get("/audit-programs/<program_id>/accreditation-reports")
@require("ProgramAdmin", "QaSupervisor", "MedicalDirector", "AccreditationOfficer")
def list_reports(program_id):
    limit, offset = validate.pagination()
    program = helpers.program(program_id)
    filters = {
        "status": request.args.get("status"),
        "variant": request.args.get("variant"),
    }
    rows = [
        r
        for r in db.reports.values()
        if r["program_id"] == program["id"] and helpers.matches(r, filters)
    ]
    return helpers.respond_list(rows, limit, offset)


@bp.post("/accreditation-reports/<report_id>/submit")
@require("AccreditationOfficer")
def submit_report(report_id):
    payload = validate.body()
    recipient = validate.get_enum(payload, "submitted_to", RECIPIENTS)

    report = helpers.report(report_id)

    if report["status"] != "DRAFT":
        fail("ERR_REPORT_ALREADY_SUBMITTED", "This report has already been filed.")

    set_fields(
        report,
        {
            "status": "SUBMITTED",
            "submitted_to": recipient,
            "submitted_at": clock(),
        },
    )
    cascades.cascade_c_submit(report)
    return ok(public(report))
