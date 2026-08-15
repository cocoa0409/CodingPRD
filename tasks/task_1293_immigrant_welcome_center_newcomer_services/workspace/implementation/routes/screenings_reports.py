"""Benefit screenings (eligibility tiering) and funder reports."""
from decimal import Decimal
from flask import Blueprint, request

import db
from auth import require, get_or_404
from calc import run_tiering, compute_report
from envelope import ok, ok_list, paginate
from errors import ApiError, bad_request, invalid_state
from util import body_json, req_int, req_present, req_datetime, req_enum

bp = Blueprint("screenings_reports", __name__)


# ---------------------------------------------------------------------------
# Benefit screenings
# ---------------------------------------------------------------------------

def _get_case_from_body(data):
    case_id = data.get("case_id")
    case = None
    if case_id is not None:
        if not isinstance(case_id, str):
            raise bad_request("case_id must be a string")
        case = get_or_404("cases", case_id, "case")
    return case_id, case


@bp.route("/benefit-screenings", methods=["POST"])
def create_screening():
    require("IntakeSpecialist", "CaseManager")
    data = body_json()

    # rung 3: body-referenced id
    case_id, case = _get_case_from_body(data)

    # rung 4: SUSPENDED/CLOSED cases reject new screenings
    if case is not None and case["service_status"] in ("SUSPENDED", "CLOSED"):
        raise invalid_state("case is not accepting new screenings")

    # rung 5: SEALED posture blocks screening creation for everyone
    if case is not None and case["privacy_posture"] == "SEALED":
        raise ApiError("ERR_PRIVACY_SEALED", 409, "case is SEALED")

    # rung 7: structural
    req_present(data, "case_id")
    stated = req_int(data, "stated_annual_income_cents", minimum=0)

    client = db.get("clients", case["client_id"])
    screening = db.new_entity("screenings", {
        "case_id": case_id,
        "household_size": client["household_size"],
        "stated_annual_income_cents": stated,
        "documented_annual_income_cents": None,
        "variant_used": None,
        "income_ratio": None,
        "tier": None,
        "eligible_programs": [],
        "status": "DRAFT",
    })
    return ok(db.pub(screening), status=201)


@bp.route("/benefit-screenings/<screening_id>", methods=["GET"])
def get_screening(screening_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    s = get_or_404("screenings", screening_id, "benefit screening")
    return ok(db.pub(s))


@bp.route("/benefit-screenings", methods=["GET"])
def list_screenings():
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    items = db.all_of("screenings")
    for param in ("case_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if str(s.get(param)) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(s) for s in page], meta)


def _recompute(screening, variant):
    income = (screening["stated_annual_income_cents"]
              if variant == "SELF_REPORTED"
              else screening["documented_annual_income_cents"])
    ratio, tier, programs = run_tiering(income, screening["household_size"],
                                        variant)
    screening["variant_used"] = variant
    screening["income_ratio"] = ratio
    screening["tier"] = tier
    screening["eligible_programs"] = programs


@bp.route("/benefit-screenings/<screening_id>/run", methods=["POST"])
def run_screening(screening_id):
    require("IntakeSpecialist", "CaseManager")
    s = get_or_404("screenings", screening_id, "benefit screening")
    if s["status"] != "DRAFT":
        raise invalid_state("screening is not DRAFT")
    _recompute(s, "SELF_REPORTED")
    s["status"] = "SCREENED"
    db.touch(s)
    return ok(db.pub(s))


@bp.route("/benefit-screenings/<screening_id>/verify", methods=["POST"])
def verify_screening(screening_id):
    require("CaseManager")
    s = get_or_404("screenings", screening_id, "benefit screening")
    if s["status"] != "SCREENED":
        raise invalid_state("screening is not SCREENED")
    data = body_json()
    documented = req_int(data, "documented_annual_income_cents", minimum=0)
    s["documented_annual_income_cents"] = documented
    _recompute(s, "VERIFIED")
    db.touch(s)
    return ok(db.pub(s))


@bp.route("/benefit-screenings/<screening_id>/explain", methods=["POST"])
def explain_screening(screening_id):
    require("CaseManager")
    s = get_or_404("screenings", screening_id, "benefit screening")
    if s["status"] != "SCREENED":
        raise invalid_state("screening is not SCREENED")
    s["status"] = "EXPLAINED"
    db.touch(s)
    return ok(db.pub(s))


@bp.route("/benefit-screenings/<screening_id>/reopen", methods=["POST"])
def reopen_screening(screening_id):
    require("CaseManager")
    s = get_or_404("screenings", screening_id, "benefit screening")
    if s["status"] != "SCREENED":
        raise invalid_state("screening is not SCREENED")
    s["status"] = "DRAFT"
    s["income_ratio"] = None
    s["tier"] = None
    s["eligible_programs"] = []
    db.touch(s)
    return ok(db.pub(s))


# ---------------------------------------------------------------------------
# Funder reports
# ---------------------------------------------------------------------------

def _validate_streams(streams):
    if not isinstance(streams, list) or not streams:
        raise bad_request("funding_streams must be a non-empty array")
    total = Decimal(0)
    for i, s in enumerate(streams):
        if not isinstance(s, dict):
            raise bad_request("each funding stream must be an object")
        name = s.get("stream_name")
        if not isinstance(name, str):
            raise bad_request("each funding stream needs a stream_name")
        share = s.get("share_pct")
        if not isinstance(share, (int, float)) or isinstance(share, bool):
            raise bad_request("each funding stream needs a numeric share_pct")
        total += Decimal(str(share))
    if total != Decimal(100):
        raise bad_request("funding stream share_pct values must sum to 100")


def _periods_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _fill_report(report):
    result = compute_report(report["period_start"], report["period_end"],
                            report["funding_streams"])
    report["lines"] = result["lines"]
    report["stream_totals"] = result["stream_totals"]
    report["total_cost_cents"] = result["total_cost_cents"]
    report["reportable_client_count"] = result["reportable_client_count"]
    report["aggregate_client_count"] = result["aggregate_client_count"]


@bp.route("/funder-reports", methods=["POST"])
def create_report():
    require("CenterAdmin")
    data = body_json()
    period_start = req_datetime(data, "period_start")
    period_end = req_datetime(data, "period_end")
    streams = data.get("funding_streams")
    if period_end <= period_start:
        raise bad_request("period_end must be after period_start")
    _validate_streams(streams)

    for other in db.all_of("reports"):
        if other["status"] == "RETURNED":
            continue
        if _periods_overlap(period_start, period_end,
                            other["period_start"], other["period_end"]):
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP", 409,
                           "period overlaps an existing report")

    report = db.new_entity("reports", {
        "period_start": period_start,
        "period_end": period_end,
        "funding_streams": [
            {"stream_name": s["stream_name"], "share_pct": s["share_pct"]}
            for s in streams],
        "status": "DRAFT",
        "lines": [],
        "stream_totals": [],
        "total_cost_cents": 0,
        "reportable_client_count": 0,
        "aggregate_client_count": 0,
        "submitted_by_id": None,
        "reviewed_by_id": None,
    })
    _fill_report(report)
    return ok(db.pub(report), status=201)


@bp.route("/funder-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    require("CenterAdmin", "FunderAuditor")
    report = get_or_404("reports", report_id, "funder report")
    return ok(db.pub(report))


@bp.route("/funder-reports", methods=["GET"])
def list_reports():
    require("CenterAdmin", "FunderAuditor")
    items = db.all_of("reports")
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return ok_list([db.pub(r) for r in page], meta)


@bp.route("/funder-reports/<report_id>/regenerate", methods=["POST"])
def regenerate_report(report_id):
    require("CenterAdmin")
    report = get_or_404("reports", report_id, "funder report")
    if report["status"] not in ("DRAFT", "RETURNED"):
        raise invalid_state("only DRAFT or RETURNED reports regenerate")
    _fill_report(report)
    db.touch(report)
    return ok(db.pub(report))


@bp.route("/funder-reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    user_id, _ = require("CenterAdmin")
    report = get_or_404("reports", report_id, "funder report")
    if report["status"] not in ("DRAFT", "RETURNED"):
        raise invalid_state("only DRAFT or RETURNED reports may be submitted")
    # freshness checkpoint: recomputed lines must equal the stored lines
    fresh = compute_report(report["period_start"], report["period_end"],
                           report["funding_streams"])
    if fresh["lines"] != report["lines"]:
        raise ApiError("ERR_REPORT_STALE", 409,
                       "stored lines are stale; regenerate first")
    was_returned = report["status"] == "RETURNED"
    report["status"] = "SUBMITTED"
    report["submitted_by_id"] = user_id
    if was_returned:
        report["reviewed_by_id"] = None
    db.touch(report)
    return ok(db.pub(report))


@bp.route("/funder-reports/<report_id>/review", methods=["POST"])
def review_report(report_id):
    user_id, _ = require("FunderAuditor")
    report = get_or_404("reports", report_id, "funder report")
    if report["status"] != "SUBMITTED":
        raise invalid_state("report is not SUBMITTED")
    data = body_json()
    decision = req_enum(data, "decision", {"ACCEPTED", "RETURNED"})
    report["status"] = decision
    report["reviewed_by_id"] = user_id
    db.touch(report)
    return ok(db.pub(report))
