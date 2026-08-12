"""Analysis runs: create (scope overlap), lock, unlock, compute, finalize, archive."""
from flask import Blueprint, request

import db
from errors import already_terminal, err, invalid_request, invalid_state
from middleware import (
    body, check_enum, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj
from services.analysis import compute_run, dataset_stale, in_scope
from services.cap import periods_overlap

bp = Blueprint("analysis_runs", __name__)

PRODUCTS = ("CONVENTIONAL", "FHA", "VA")
BASES = ("RACE", "ETHNICITY", "SEX", "AGE")
ROLES = ("FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")
TERMINAL_FINDING_STATES = ("REFUTED", "CLOSED", "SUPERSEDED")


@bp.post("/fair-lending/analysis-runs")
@require_roles("FairLendingAnalyst")
def create_run():
    data = body()
    market_id = require_field(data, "market_id")
    product_type = check_enum(require_field(data, "product_type"), PRODUCTS, "product_type")
    basis = check_enum(
        require_field(data, "prohibited_basis"), BASES, "prohibited_basis"
    )
    period_start = require_field(data, "period_start")
    period_end = require_field(data, "period_end")
    if not (period_start < period_end):
        raise invalid_request("period_start must be before period_end")
    get_or_404("markets", market_id, "Market")
    # Scope overlap: same market+product+basis, half-open period overlap, among
    # non-ARCHIVED runs.
    for r in db.STORES["runs"].values():
        if (
            r["market_id"] == market_id
            and r["product_type"] == product_type
            and r["prohibited_basis"] == basis
            and r["status"] != "ARCHIVED"
            and periods_overlap(period_start, period_end, r["period_start"], r["period_end"])
        ):
            raise err(
                "ERR_SCOPE_OVERLAP",
                "Analysis run scope overlaps an existing non-ARCHIVED run",
            )
    rec = db.new_record(
        {
            "market_id": market_id,
            "product_type": product_type,
            "prohibited_basis": basis,
            "period_start": period_start,
            "period_end": period_end,
            "status": "DRAFT",
            "locked_at": None,
            "snapshot_application_count": None,
            "approval_rate_protected_net": None,
            "approval_rate_control_net": None,
            "impact_ratio_net": None,
            "impact_ratio_raw": None,
            "pricing_disparity_unadjusted_bps": None,
            "pricing_disparity_adjusted_bps": None,
            "adverse_classification": None,
            "screening_flag": False,
            "open_finding_count": 0,
            "finalized_at": None,
            "_snapshot_ids": [],
        }
    )
    db.STORES["runs"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/analysis-runs")
@require_roles(*ROLES)
def list_runs():
    page, total, limit, offset = list_page(
        "runs",
        {"market_id": request.args.get("market_id"), "status": request.args.get("status")},
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/analysis-runs/<runId>")
@require_roles(*ROLES)
def get_run(runId):
    rec = get_or_404("runs", runId, "AnalysisRun")
    return success_obj(db.public(rec))


@bp.post("/fair-lending/analysis-runs/<runId>/lock")
@require_roles("FairLendingAnalyst")
def lock_run(runId):
    rec = get_or_404("runs", runId, "AnalysisRun")
    if rec["status"] == "ARCHIVED":
        raise already_terminal("AnalysisRun is ARCHIVED")
    if rec["status"] != "DRAFT":
        raise invalid_state("AnalysisRun is not in DRAFT status")
    scope = [a for a in db.STORES["applications"].values() if in_scope(rec, a)]
    if not scope:
        raise err("ERR_NO_IN_SCOPE_APPLICATIONS", "Zero in-scope applications")
    if any(a["status"] != "VALIDATED" for a in scope):
        raise err(
            "ERR_APPLICATIONS_NOT_VALIDATED",
            "Every in-scope application must be VALIDATED",
        )
    rec["status"] = "DATA_LOCKED"
    rec["locked_at"] = db.now_iso()
    rec["_snapshot_ids"] = [a["id"] for a in scope]
    rec["snapshot_application_count"] = len(scope)
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/analysis-runs/<runId>/unlock")
@require_roles("FairLendingAnalyst")
def unlock_run(runId):
    rec = get_or_404("runs", runId, "AnalysisRun")
    if rec["status"] == "ARCHIVED":
        raise already_terminal("AnalysisRun is ARCHIVED")
    if rec["status"] != "DATA_LOCKED":
        raise invalid_state("AnalysisRun is not in DATA_LOCKED status")
    if any(f["analysis_run_id"] == rec["id"] for f in db.STORES["findings"].values()):
        raise err("ERR_RUN_HAS_OPEN_FINDINGS", "Findings exist on the run")
    rec["status"] = "DRAFT"
    rec["locked_at"] = None
    rec["_snapshot_ids"] = []
    rec["snapshot_application_count"] = None
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/analysis-runs/<runId>/compute")
@require_roles("FairLendingAnalyst")
def compute(runId):
    rec = get_or_404("runs", runId, "AnalysisRun")
    if rec["status"] == "ARCHIVED":
        raise already_terminal("AnalysisRun is ARCHIVED")
    if rec["status"] != "DATA_LOCKED":
        raise invalid_state("AnalysisRun is not in DATA_LOCKED status")
    if dataset_stale(rec):
        raise err(
            "ERR_STALE_DATASET",
            "An in-scope application changed after locked_at; unlock and re-lock",
        )
    compute_run(rec)
    return success_obj(db.public(rec))


def _privilege_gate(rec):
    for st in db.STORES["self_tests"].values():
        if (
            st.get("analysis_run_id") == rec["id"]
            and st["disclosure_status"] == "PRIVILEGED"
            and st["status"] == "ACTIVE"
        ):
            raise err(
                "ERR_PRIVILEGE_GATE",
                "Run is linked to a PRIVILEGED self-test still ACTIVE",
            )


@bp.post("/fair-lending/analysis-runs/<runId>/finalize")
@require_roles("FairLendingOfficer")
def finalize_run(runId):
    rec = get_or_404("runs", runId, "AnalysisRun")
    if rec["status"] == "ARCHIVED":
        raise already_terminal("AnalysisRun is ARCHIVED")
    if rec["status"] not in ("COMPUTED", "UNDER_REVIEW"):
        raise invalid_state("AnalysisRun is not finalizable in state %s" % rec["status"])
    _privilege_gate(rec)
    if rec["status"] == "UNDER_REVIEW":
        open_findings = [
            f
            for f in db.STORES["findings"].values()
            if f["analysis_run_id"] == rec["id"]
            and f["status"] not in TERMINAL_FINDING_STATES
        ]
        if open_findings:
            raise err("ERR_FINDINGS_OPEN", "Linked findings are not all terminal")
    rec["status"] = "FINALIZED"
    rec["finalized_at"] = db.now_iso()
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/analysis-runs/<runId>/archive")
@require_roles("FairLendingOfficer")
def archive_run(runId):
    rec = get_or_404("runs", runId, "AnalysisRun")
    if rec["status"] == "ARCHIVED":
        raise already_terminal("AnalysisRun is ARCHIVED")
    if rec["status"] != "FINALIZED":
        raise invalid_state("AnalysisRun is not in FINALIZED status")
    rec["status"] = "ARCHIVED"
    db.touch(rec)
    return success_obj(db.public(rec))
