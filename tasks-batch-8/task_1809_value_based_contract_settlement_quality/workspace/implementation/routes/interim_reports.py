"""InterimReport endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_YEAR_NOT_MEASURING,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import calculations as calc
from services import engine
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("interim_reports", __name__)


def _get_report_or_404(report_id: str) -> dict:
    report = db.interim_reports.get(report_id)
    if report is None:
        raise_err(ERR_NOT_FOUND, "InterimReport id does not exist")
    return report


@bp.route("/vbc/interim-reports", methods=["POST"])
@require_roles("ActuaryAnalyst")
def create_interim_report(_user_id: str, _role: str):
    body = get_json_body()
    # Priority 3: body FK existence.
    raw_year = body.get("performance_year_id")
    if isinstance(raw_year, str) and raw_year != "" and raw_year not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")
    # Priority 5: shape (months_elapsed scalar range 1..11).
    reject_unknown_fields(body, {"performance_year_id", "months_elapsed", "expected_performance_year_version"})
    performance_year_id = require_string(body, "performance_year_id")
    months_elapsed = require_int(body, "months_elapsed", minimum=1, maximum=11)
    expected_version = require_int(body, "expected_performance_year_version")
    if performance_year_id not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")

    year = db.performance_years[performance_year_id]
    # Priority 14: OCC against the year.
    if expected_version != year["version"]:
        raise_err(ERR_STALE_VERSION, "expected_performance_year_version does not match the year's current version")

    # Supersede any prior DRAFT report of the year.
    for report in db.interim_reports.values():
        if report["performance_year_id"] == performance_year_id and report["report_status"] == "DRAFT":
            db.apply_updates(report, {"report_status": "SUPERSEDED"})

    contract = engine.contract_of_year(year)
    estimates = calc.compute_interim_estimates(contract, year, months_elapsed, db.clock_date())

    seq = max(
        (r["report_seq"] for r in db.interim_reports.values() if r["performance_year_id"] == performance_year_id),
        default=0,
    ) + 1
    report = {
        "performance_year_id": performance_year_id,
        "months_elapsed": months_elapsed,
        "report_seq": seq,
        "est_actual_annualization_cents": estimates["est_actual_annualization_cents"],
        "est_actual_completion_cents": estimates["est_actual_completion_cents"],
        "est_net_payable_cents": estimates["est_net_payable_cents"],
        "reserve_accrual_cents": estimates["reserve_accrual_cents"],
        "report_status": "DRAFT",
        "published_on": None,
    }
    db.stamp_new(report)
    db.interim_reports[report["id"]] = report
    # Creating the report mutates the parent year's version (§1.2.1).
    db.touch(year)
    return success_object(report, 201)


@bp.route("/vbc/interim-reports", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_interim_reports(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.interim_reports.values()))
    items = apply_filters(items, ["performance_year_id", "report_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/interim-reports/<report_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_interim_report(report_id: str, _user_id: str, _role: str):
    return success_object(_get_report_or_404(report_id))


@bp.route("/vbc/interim-reports/<report_id>/publish", methods=["POST"])
@require_roles("ActuaryAnalyst")
def publish_interim_report(report_id: str, _user_id: str, _role: str):
    report = _get_report_or_404(report_id)
    if report["report_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT report can be published")
    year = db.performance_years[report["performance_year_id"]]
    if year["year_status"] not in ("MEASURING", "RECONCILING"):
        raise_err(ERR_YEAR_NOT_MEASURING, "Publish requires the year to be MEASURING or RECONCILING")

    # Supersede any other PUBLISHED report of the year.
    for other in db.interim_reports.values():
        if (
            other["id"] != report_id
            and other["performance_year_id"] == report["performance_year_id"]
            and other["report_status"] == "PUBLISHED"
        ):
            db.apply_updates(other, {"report_status": "SUPERSEDED"})

    report["report_status"] = "PUBLISHED"
    report["published_on"] = db.clock_date_iso()
    db.touch(report)
    # Post the reserve accrual onto the year (a year mutation).
    db.apply_updates(year, {"accrued_reserve_cents": report["reserve_accrual_cents"]})
    return success_object(report)
