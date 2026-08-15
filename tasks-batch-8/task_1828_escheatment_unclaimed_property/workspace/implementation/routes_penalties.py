"""Penalty assessment endpoints (PRD 3.8)."""

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, get_report_or_404, get_assessment_or_404,
    find_applicable_rule, round_half_up_cents, floor_pct, BP_DENOMINATOR,
)

bp = Blueprint("penalties", __name__)


def assessment_view(a):
    return {
        "id": a["id"],
        "report_id": a["report_id"],
        "assessed_date": a["assessed_date"].isoformat(),
        "days_late": a["days_late"],
        "penalty_cents": a["penalty_cents"],
        "interest_cents": a["interest_cents"],
        "total_cents": a["total_cents"],
        "status": a["status"],
        "waiver_reason": a["waiver_reason"],
        "dispute_reason": a["dispute_reason"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/escheatment/holder-reports/<reportId>/penalty-assessments")
def create_assessment(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    mw.body_json(required=False)
    report = get_report_or_404(reportId)
    if report["status"] not in ("SUBMITTED", "ACCEPTED"):
        raise_error(
            errors.ERR_REPORT_NOT_SUBMITTED,
            "Penalty assessment requires a SUBMITTED or ACCEPTED report",
        )
    for existing in db.penalty_assessments.values():
        if existing["report_id"] == report["id"] and existing["status"] in ("ASSESSED", "DISPUTED"):
            raise_error(
                errors.ERR_PENALTY_ALREADY_ASSESSED,
                "An ASSESSED or DISPUTED penalty already exists for this report",
            )
    assessed_date = clock.today()
    days_late = max(0, (report["submitted_date"] - report["due_date"]).days)

    # Rate schedule comes from the rule of the first INCLUDED line's property
    # type (a report's lines all share one state).
    rule = None
    first_line = next(
        (l for l in sorted(db.line_items.values(), key=lambda x: (x["created_at"], x["id"]))
         if l["report_id"] == report["id"] and l["status"] == "INCLUDED"),
        None,
    )
    if first_line is not None:
        prop = db.properties.get(first_line["property_id"])
        if prop is not None:
            rule = find_applicable_rule(
                prop["state_code"], prop["property_type"], prop["last_contact_date"]
            )
    if rule is None:
        # Fallback: any rule for the report's state supplies the schedule.
        rule = next(
            (r for r in db.dormancy_rules.values() if r["state_code"] == report["state_code"]),
            None,
        )

    if days_late == 0 or rule is None:
        penalty_cents = 0
    else:
        if days_late <= rule["gross_negligence_day_threshold"]:
            rate = rule["daily_penalty_cents"]
        else:
            # Gross rate applies to ALL days, not marginally.
            rate = rule["gross_daily_penalty_cents"]
        raw = rate * days_late
        cap = floor_pct(rule["penalty_cap_pct"], report["total_provisional_cents"])
        penalty_cents = min(raw, cap)

    if days_late == 0 or rule is None:
        interest_cents = 0
    else:
        days_interest = (assessed_date - report["due_date"]).days
        interest_cents = 0
        for line in db.line_items.values():
            if line["report_id"] != report["id"] or line["status"] not in ("INCLUDED", "FINAL"):
                continue
            base = line["final_value_cents"] if line["status"] == "FINAL" else line["provisional_value_cents"]
            # Pinned rounding order: round each line half-up first, then sum.
            interest_cents += round_half_up_cents(
                base * rule["annual_interest_rate_bp"] * days_interest, BP_DENOMINATOR
            )

    assessment = new_entity({
        "report_id": report["id"],
        "assessed_date": assessed_date,
        "days_late": days_late,
        "penalty_cents": penalty_cents,
        "interest_cents": interest_cents,
        "total_cents": penalty_cents + interest_cents,
        "status": "ASSESSED",
        "waiver_reason": None,
        "dispute_reason": None,
    })
    db.penalty_assessments[assessment["id"]] = assessment
    return resp.success(assessment_view(assessment), "object", 201)


@bp.get("/escheatment/holder-reports/<reportId>/penalty-assessments")
def list_assessments(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    report = get_report_or_404(reportId)
    limit, offset = mw.pagination_params()
    items = [a for a in db.penalty_assessments.values() if a["report_id"] == report["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([assessment_view(a) for a in page], "array", 200, pagination=meta)


@bp.get("/escheatment/penalty-assessments/<assessmentId>")
def get_assessment(assessmentId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    assessment = get_assessment_or_404(assessmentId)
    return resp.success(assessment_view(assessment), "object", 200)


@bp.post("/escheatment/penalty-assessments/<assessmentId>/pay")
def pay_assessment(assessmentId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("TreasuryOps",))
    mw.body_json(required=False)
    assessment = get_assessment_or_404(assessmentId)
    if assessment["status"] != "ASSESSED":
        raise_error(errors.ERR_PENALTY_NOT_ASSESSED, "Pay requires an ASSESSED assessment")
    assessment["status"] = "PAID"
    touch(assessment)
    return resp.success(assessment_view(assessment), "object", 200)


@bp.post("/escheatment/penalty-assessments/<assessmentId>/waive")
def waive_assessment(assessmentId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    data = mw.body_json()
    reason = mw.req_string(data, "waiver_reason")
    assessment = get_assessment_or_404(assessmentId)
    if assessment["status"] not in ("ASSESSED", "DISPUTED"):
        raise_error(
            errors.ERR_PENALTY_NOT_ASSESSED,
            "Waive requires an ASSESSED or DISPUTED assessment",
        )
    assessment["status"] = "WAIVED"
    assessment["waiver_reason"] = reason
    touch(assessment)
    return resp.success(assessment_view(assessment), "object", 200)


@bp.post("/escheatment/penalty-assessments/<assessmentId>/dispute")
def dispute_assessment(assessmentId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    reason = mw.req_string(data, "dispute_reason")
    assessment = get_assessment_or_404(assessmentId)
    if assessment["status"] != "ASSESSED":
        raise_error(errors.ERR_PENALTY_NOT_ASSESSED, "Dispute requires an ASSESSED assessment")
    assessment["status"] = "DISPUTED"
    assessment["dispute_reason"] = reason
    touch(assessment)
    return resp.success(assessment_view(assessment), "object", 200)


@bp.post("/escheatment/penalty-assessments/<assessmentId>/uphold")
def uphold_assessment(assessmentId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    mw.body_json(required=False)
    assessment = get_assessment_or_404(assessmentId)
    if assessment["status"] != "DISPUTED":
        raise_error(errors.ERR_PENALTY_NOT_DISPUTED, "Uphold requires a DISPUTED assessment")
    assessment["status"] = "ASSESSED"
    touch(assessment)
    return resp.success(assessment_view(assessment), "object", 200)
