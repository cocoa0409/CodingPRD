from flask import Blueprint

from constants import ALL_ROLES, QUARTERS_PER_FISCAL_YEAR, REPORT_TYPES
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services.domain import get_or_404, list_response
from util import new_id, parse_body, req_str, req_int, req_enum, opt_str_nullable

bp = Blueprint("reports", __name__)

AUTHOR_ROLES = ["DevelopmentOfficer", "InvestmentOfficer"]
TERMINAL_DISTRIBUTION_STATES = ("DISTRIBUTED", "CANCELLED")


def _terminated_gate(pool):
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )


def _fiscal_year_complete(pool, fiscal_year):
    return QUARTERS_PER_FISCAL_YEAR * (
        fiscal_year - pool["inception_fiscal_year"] + 1
    ) <= pool["current_quarter_index"]


@bp.route("/endowment/reports", methods=["POST"])
def create_report():
    user_id, _ = authenticate(AUTHOR_ROLES)
    body = parse_body(required=True)
    pool_id = req_str(body, "pool_id")
    report_type = req_enum(body, "report_type", REPORT_TYPES)
    fiscal_year = req_int(body, "fiscal_year")
    fund_id = opt_str_nullable(body, "fund_id")
    if report_type == "DONOR_FUND":
        if fund_id is None:
            raise_err(
                "ERR_INVALID_REQUEST",
                "fund_id is required for DONOR_FUND reports",
            )
    elif fund_id is not None:
        raise_err(
            "ERR_INVALID_REQUEST",
            "fund_id must be null for non-DONOR_FUND reports",
        )

    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    if fund_id is not None:
        fund = get_or_404(store.funds, fund_id, "Fund")
        if fund["pool_id"] != pool_id:
            raise_err(
                "ERR_INVALID_REQUEST",
                "fund_id must reference a fund of the report's pool",
            )
    _terminated_gate(pool)

    duplicate = any(
        r["pool_id"] == pool_id
        and r["fund_id"] == fund_id
        and r["fiscal_year"] == fiscal_year
        and r["report_type"] == report_type
        for r in store.reports.values()
    )
    if duplicate:
        raise_err(
            "ERR_DUPLICATE_RECORD",
            "A report already exists for this pool/fund/fiscal_year/report_type",
        )

    if not _fiscal_year_complete(pool, fiscal_year):
        raise_err(
            "ERR_INCOMPLETE_FISCAL_YEAR",
            f"Fiscal year {fiscal_year} is not complete for this pool",
        )

    rec = {
        "id": new_id(),
        "pool_id": pool_id,
        "fund_id": fund_id,
        "report_type": report_type,
        "fiscal_year": fiscal_year,
        "report_status": "DRAFT",
        "created_by_user_id": user_id,
        "published_by_user_id": None,
        "version": 1,
    }
    stamp_new(rec)
    store.reports[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/reports", methods=["GET"])
def list_reports():
    authenticate(ALL_ROLES)
    return list_response(
        store.reports,
        [
            ("pool_id", "pool_id", "str"),
            ("fund_id", "fund_id", "str"),
            ("report_type", "report_type", "str"),
            ("fiscal_year", "fiscal_year", "int"),
            ("report_status", "report_status", "str"),
        ],
    )


@bp.route("/endowment/reports/<report_id>", methods=["GET"])
def get_report(report_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.reports, report_id, "AnnualReport")))


@bp.route("/endowment/reports/<report_id>/submit_review", methods=["POST"])
def submit_review(report_id):
    authenticate(AUTHOR_ROLES)
    report = get_or_404(store.reports, report_id, "AnnualReport")
    if report["report_status"] != "DRAFT":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot submit for review a report in state "
            f"{report['report_status']}",
        )
    _terminated_gate(store.pools.get(report["pool_id"]))
    report["report_status"] = "UNDER_REVIEW"
    bump(report)
    return success(pub(report))


@bp.route("/endowment/reports/<report_id>/return_for_revision", methods=["POST"])
def return_for_revision(report_id):
    authenticate(["BoardMember"])
    report = get_or_404(store.reports, report_id, "AnnualReport")
    if report["report_status"] != "UNDER_REVIEW":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot return for revision a report in state "
            f"{report['report_status']}",
        )
    _terminated_gate(store.pools.get(report["pool_id"]))
    report["report_status"] = "DRAFT"
    bump(report)
    return success(pub(report))


@bp.route("/endowment/reports/<report_id>/publish", methods=["POST"])
def publish(report_id):
    user_id, _ = authenticate(["BoardMember"])
    report = store.reports.get(report_id)
    # Priority 3 (segregation of duties) before existence (5) where evaluable.
    if report is not None and user_id == report["created_by_user_id"]:
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "The publisher must differ from the report's author",
        )
    if report is None:
        raise_err("ERR_NOT_FOUND", f"AnnualReport not found: {report_id}")
    if report["report_status"] != "UNDER_REVIEW":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot publish a report in state {report['report_status']}",
        )
    pool = store.pools.get(report["pool_id"])
    _terminated_gate(pool)

    if not _fiscal_year_complete(pool, report["fiscal_year"]):
        raise_err(
            "ERR_INCOMPLETE_FISCAL_YEAR",
            f"Fiscal year {report['fiscal_year']} is not complete for this pool",
        )
    # Every distribution in scope for the fiscal year must be terminal.
    if report["report_type"] == "DONOR_FUND":
        scoped = [
            d
            for d in store.distributions.values()
            if d["fund_id"] == report["fund_id"]
            and d["fiscal_year"] == report["fiscal_year"]
        ]
    else:
        pool_fund_ids = {
            f["id"] for f in store.funds.values() if f["pool_id"] == pool["id"]
        }
        scoped = [
            d
            for d in store.distributions.values()
            if d["fund_id"] in pool_fund_ids
            and d["fiscal_year"] == report["fiscal_year"]
        ]
    if any(
        d["distribution_status"] not in TERMINAL_DISTRIBUTION_STATES for d in scoped
    ):
        raise_err(
            "ERR_INCOMPLETE_FISCAL_YEAR",
            "Every distribution in the report's scope for the fiscal year "
            "must be DISTRIBUTED or CANCELLED",
        )

    if report["report_type"] == "BOARD_INVESTMENT":
        unacked = any(
            a["pool_id"] == pool["id"]
            and a["drift_status"] == "BREACHED"
            and not a["drift_acknowledged"]
            for a in store.allocations.values()
        )
        if unacked:
            raise_err(
                "ERR_DRIFT_NOT_ACKNOWLEDGED",
                "Every BREACHED allocation must be acknowledged before a "
                "BOARD_INVESTMENT report is published",
            )

    report["report_status"] = "PUBLISHED"
    report["published_by_user_id"] = user_id
    bump(report)
    return success(pub(report))
