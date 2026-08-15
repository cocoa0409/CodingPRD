"""AssetTestReport and IncomeTestReport endpoints, including the lock transition
with the compliance kill-switch cascade (PRD §2.11, §3.3)."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import calc_asset_test, calc_income_test
from services.common import get_json_body, make_entity, now_iso, touch

bp = Blueprint("test_reports", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")


def _resolve_reit_quarter(body):
    reit_id = body.get("reit_id")
    quarter_id = body.get("quarter_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    if not isinstance(quarter_id, str) or not quarter_id:
        raise errors.validation("Field 'quarter_id' is required")
    reit = db.reits.get(reit_id)
    if reit is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")
    quarter = db.quarters.get(quarter_id)
    if quarter is None:
        raise errors.not_found("quarter_id does not resolve to an existing Quarter")
    return reit, quarter


def _kill_switch(reit):
    """Compliance kill-switch: suspend the REIT and auto-void every
    PENDING_APPROVAL / APPROVED DividendDeclaration. Each touched entity gets
    its own version bump and timestamp update."""
    if reit["status"] != "SUSPENDED":
        reit["status"] = "SUSPENDED"
    for d in db.dividend_declarations.values():
        if d["reit_id"] == reit["id"] and d["status"] in ("PENDING_APPROVAL", "APPROVED"):
            d["status"] = "VOID"
            touch(d)
    touch(reit)


# ----------------------------- AssetTestReport -----------------------------

@bp.route("/reit-compliance/asset-test-reports", methods=["POST"])
def create_asset_test_report():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit, quarter = _resolve_reit_quarter(body)

    # One asset test report per quarter (uniqueness)
    for r in db.asset_test_reports.values():
        if r["quarter_id"] == quarter["id"]:
            raise errors.duplicate("One asset test report per quarter")

    report = make_entity({
        "reit_id": reit["id"],
        "quarter_id": quarter["id"],
        "status": "DRAFT",
        "qualifying_75_pct": None,
        "trs_concentration_pct": None,
        "test_75_passed": None,
        "trs_test_passed": None,
    })
    db.asset_test_reports[report["id"]] = report
    return success_object(dict(report), status=201)


@bp.route("/reit-compliance/asset-test-reports/<rid>", methods=["GET"])
def get_asset_test_report(rid):
    require_roles(*ALL)
    report = db.asset_test_reports.get(rid)
    if report is None:
        raise errors.not_found("Asset test report not found")
    return success_object(dict(report))


@bp.route("/reit-compliance/asset-test-reports", methods=["GET"])
def list_asset_test_reports():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.asset_test_reports.values())
    reit_id = request.args.get("reit_id")
    quarter_id = request.args.get("quarter_id")
    if reit_id is not None:
        rows = [r for r in rows if r["reit_id"] == reit_id]
    if quarter_id is not None:
        rows = [r for r in rows if r["quarter_id"] == quarter_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(r) for r in page], limit, offset, total)


@bp.route("/reit-compliance/asset-test-reports/<rid>/lock", methods=["POST"])
def lock_asset_test_report(rid):
    require_roles("ComplianceOfficer")
    report = db.asset_test_reports.get(rid)
    if report is None:
        raise errors.not_found("Asset test report not found")
    # State check (priority 7) precedes quarter-open check (priority 8)
    if report["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT asset test reports can be locked")
    quarter = db.quarters.get(report["quarter_id"])
    if quarter is None:
        raise errors.not_found("Quarter not found")
    if quarter["status"] != "OPEN":
        raise errors.quarter_locked("Quarter is already LOCKED")

    reit = db.reits.get(report["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")

    result = calc_asset_test(reit["id"])
    report["qualifying_75_pct"] = result["qualifying_75_pct"]
    report["trs_concentration_pct"] = result["trs_concentration_pct"]
    report["test_75_passed"] = result["test_75_passed"]
    report["trs_test_passed"] = result["trs_test_passed"]

    # Freeze gross asset total on the quarter at lock time
    quarter["gross_asset_total_cents"] = result["gross_asset_total_cents"]
    quarter["status"] = "LOCKED"

    passed = result["test_75_passed"] and result["trs_test_passed"]
    report["status"] = "LOCKED" if passed else "BREACHED"

    touch(report)
    touch(quarter)
    if not passed:
        _kill_switch(reit)

    return success_object(dict(report))


# ----------------------------- IncomeTestReport ----------------------------

@bp.route("/reit-compliance/income-test-reports", methods=["POST"])
def create_income_test_report():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit, quarter = _resolve_reit_quarter(body)

    for r in db.income_test_reports.values():
        if r["quarter_id"] == quarter["id"]:
            raise errors.duplicate("One income test report per quarter")

    report = make_entity({
        "reit_id": reit["id"],
        "quarter_id": quarter["id"],
        "status": "DRAFT",
        "qualifying_75_pct": None,
        "qualifying_95_pct": None,
        "test_75_passed": None,
        "test_95_passed": None,
    })
    db.income_test_reports[report["id"]] = report
    return success_object(dict(report), status=201)


@bp.route("/reit-compliance/income-test-reports/<rid>", methods=["GET"])
def get_income_test_report(rid):
    require_roles(*ALL)
    report = db.income_test_reports.get(rid)
    if report is None:
        raise errors.not_found("Income test report not found")
    return success_object(dict(report))


@bp.route("/reit-compliance/income-test-reports", methods=["GET"])
def list_income_test_reports():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.income_test_reports.values())
    reit_id = request.args.get("reit_id")
    quarter_id = request.args.get("quarter_id")
    if reit_id is not None:
        rows = [r for r in rows if r["reit_id"] == reit_id]
    if quarter_id is not None:
        rows = [r for r in rows if r["quarter_id"] == quarter_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(r) for r in page], limit, offset, total)


@bp.route("/reit-compliance/income-test-reports/<rid>/lock", methods=["POST"])
def lock_income_test_report(rid):
    require_roles("ComplianceOfficer")
    report = db.income_test_reports.get(rid)
    if report is None:
        raise errors.not_found("Income test report not found")
    if report["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT income test reports can be locked")
    quarter = db.quarters.get(report["quarter_id"])
    if quarter is None:
        raise errors.not_found("Quarter not found")
    if quarter["status"] != "OPEN":
        raise errors.quarter_locked("Quarter is already LOCKED")

    reit = db.reits.get(report["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")

    result = calc_income_test(quarter["id"])
    report["qualifying_75_pct"] = result["qualifying_75_pct"]
    report["qualifying_95_pct"] = result["qualifying_95_pct"]
    report["test_75_passed"] = result["test_75_passed"]
    report["test_95_passed"] = result["test_95_passed"]

    quarter["gross_income_total_cents"] = result["gross_income_total_cents"]
    quarter["status"] = "LOCKED"

    passed = result["test_75_passed"] and result["test_95_passed"]
    report["status"] = "LOCKED" if passed else "BREACHED"

    touch(report)
    touch(quarter)
    if not passed:
        _kill_switch(reit)

    return success_object(dict(report))
