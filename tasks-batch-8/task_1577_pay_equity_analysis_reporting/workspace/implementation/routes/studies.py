"""PayEquityStudy endpoints (PRD §3.1, §3.2, §3.3, §3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_STUDY_INVALID_STATE,
    ERR_NO_QUALIFYING_GROUPS,
    ERR_UNANALYZED_GROUPS,
    ERR_RATIONALE_REQUIRED,
    ERR_GAPS_NOT_RESOLVED,
    ERR_PLAN_NOT_COMMITTED,
    ERR_GAPS_NOT_CLOSED,
    ERR_STUDY_PERIOD_OVERLAP,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import (
    new_record, touch, groups_of_study, runs_of_group, runs_of_study,
    plans_of_study, cycles_of_study, plan_ready_for_monitoring,
)
from util import parse_date
from validate import (
    get_body, req_str, req_date, req_enum_list, opt_num, opt_int,
    require_path_resource,
)

bp = Blueprint("studies", __name__)

PROTECTED_CLASSES = {"GENDER", "ETHNICITY", "AGE_BAND"}


@bp.post("/pay-equity-studies")
def create_study():
    authorized(["CompAnalyst"])
    body = get_body()
    # Priority 3.7: request shape
    name = req_str(body, "name")
    start = req_date(body, "analysis_period_start")
    end = req_date(body, "analysis_period_end")
    protected = req_enum_list(body, "protected_classes", PROTECTED_CLASSES, non_empty=True)
    if parse_date(end) < parse_date(start):
        raise_error(ERR_INVALID_REQUEST,
                    "analysis_period_end must be >= analysis_period_start")
    significance_threshold = opt_num(body, "significance_threshold", 0.05)
    actionable_gap_pct = opt_num(body, "actionable_gap_pct", 2.0)
    min_group_size = opt_int(body, "min_group_size", 30)
    monitor_cadence_days = opt_int(body, "monitor_cadence_days", 180)

    # Priority 6 (temporal): CLOSED-interval period overlap — sharing even one
    # boundary date conflicts (PRD §2.9).
    new_start, new_end = parse_date(start), parse_date(end)
    for existing in db["pay_equity_studies"].values():
        ex_start = parse_date(existing["analysis_period_start"])
        ex_end = parse_date(existing["analysis_period_end"])
        if new_start <= ex_end and ex_start <= new_end:
            raise_error(ERR_STUDY_PERIOD_OVERLAP,
                        "analysis period overlaps an existing study's period")

    rec = new_record("pay_equity_studies", {
        "name": name,
        "analysis_period_start": start,
        "analysis_period_end": end,
        "protected_classes": protected,
        "significance_threshold": significance_threshold,
        "actionable_gap_pct": actionable_gap_pct,
        "min_group_size": min_group_size,
        "monitor_cadence_days": monitor_cadence_days,
        "status": "DRAFT",
        "review_rounds": 0,
        "privileged_model_run_ids": [],
        "snapshot_count": 0,
        "assigned_snapshot_count": 0,
        "unresolved_finding_count": 0,
        "actionable_finding_count": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/pay-equity-studies")
def list_studies():
    return list_response("pay_equity_studies", {
        "status": request.args.get("status"),
    })


@bp.get("/pay-equity-studies/<rid>")
def get_study(rid):
    return get_one("pay_equity_studies", rid)


@bp.post("/pay-equity-studies/<rid>/advance")
def advance_study(rid):
    authorized(["CompAnalyst"])
    study = require_path_resource("pay_equity_studies", rid)
    # State precondition first (PRD §3.1)
    if study["status"] != "DRAFT":
        raise_error(ERR_STUDY_INVALID_STATE, "advance requires study in DRAFT")
    qualifying = [g for g in groups_of_study(rid)
                  if g["member_count"] >= study["min_group_size"]]
    if not qualifying:
        raise_error(ERR_NO_QUALIFYING_GROUPS,
                    "advance requires at least one group with member_count >= min_group_size")
    study["status"] = "MODELING"
    touch(study)
    return success_object(public(study))


@bp.post("/pay-equity-studies/<rid>/submit-legal-review")
def submit_legal_review(rid):
    authorized(["CompAnalyst"])
    study = require_path_resource("pay_equity_studies", rid)
    if study["status"] != "MODELING":
        raise_error(ERR_STUDY_INVALID_STATE,
                    "submit-legal-review requires study in MODELING")
    for group in groups_of_study(rid):
        if group["status"] in ("LOCKED", "ANALYZED"):
            final_runs = [r for r in runs_of_group(group["id"]) if r["status"] == "FINAL"]
            if not final_runs:
                raise_error(ERR_UNANALYZED_GROUPS,
                            "every LOCKED/ANALYZED group must hold a FINAL model run")
    study["status"] = "UNDER_LEGAL_REVIEW"
    study["review_rounds"] = study.get("review_rounds", 0) + 1
    touch(study)
    return success_object(public(study))


@bp.post("/pay-equity-studies/<rid>/legal-decision")
def legal_decision(rid):
    authorized(["LegalCounsel"])
    study = require_path_resource("pay_equity_studies", rid)
    body = get_body()
    # Priority 3.7 (shape) before priority 4 (state) per PRD §2.8
    decision = body.get("decision")
    if decision not in ("APPROVE", "REQUEST_CHANGES"):
        raise_error(ERR_INVALID_REQUEST, "decision must be APPROVE or REQUEST_CHANGES")
    rationale = body.get("rationale")
    if decision == "REQUEST_CHANGES":
        if rationale is None or not isinstance(rationale, str) or rationale.strip() == "":
            raise_error(ERR_RATIONALE_REQUIRED,
                        "rationale is required for REQUEST_CHANGES")
    if study["status"] != "UNDER_LEGAL_REVIEW":
        raise_error(ERR_STUDY_INVALID_STATE,
                    "legal-decision requires study in UNDER_LEGAL_REVIEW")
    if decision == "APPROVE":
        study["status"] = "PRIVILEGED_FINAL"
        # Version-pin: ids of all FINAL model runs in the study
        final_runs = [r for r in runs_of_study(rid) if r["status"] == "FINAL"]
        final_runs.sort(key=lambda r: (r["created_at"], r["_seq"]))
        study["privileged_model_run_ids"] = [r["id"] for r in final_runs]
    else:
        study["status"] = "DRAFT"
        study["privileged_model_run_ids"] = []
    touch(study)
    return success_object(public(study))


@bp.post("/pay-equity-studies/<rid>/open-remediation")
def open_remediation(rid):
    authorized(["LegalCounsel"])
    study = require_path_resource("pay_equity_studies", rid)
    if study["status"] != "PRIVILEGED_FINAL":
        raise_error(ERR_STUDY_INVALID_STATE,
                    "open-remediation requires study in PRIVILEGED_FINAL")
    study["status"] = "REMEDIATION_OPEN"
    touch(study)
    return success_object(public(study))


@bp.post("/pay-equity-studies/<rid>/begin-monitoring")
def begin_monitoring(rid):
    authorized(["CompAnalyst"])
    study = require_path_resource("pay_equity_studies", rid)
    if study["status"] != "REMEDIATION_OPEN":
        raise_error(ERR_STUDY_INVALID_STATE,
                    "begin-monitoring requires study in REMEDIATION_OPEN")
    # Gates checked in this order (PRD §3.4): unresolved findings first
    if study["unresolved_finding_count"] != 0:
        raise_error(ERR_GAPS_NOT_RESOLVED,
                    "begin-monitoring requires unresolved_finding_count == 0")
    if not plan_ready_for_monitoring(rid):
        raise_error(ERR_PLAN_NOT_COMMITTED,
                    "begin-monitoring requires a plan in FULLY_COMMITTED or COMPLETED")
    study["status"] = "MONITORING"
    touch(study)
    return success_object(public(study))


@bp.post("/pay-equity-studies/<rid>/close")
def close_study(rid):
    authorized(["LegalCounsel"])
    study = require_path_resource("pay_equity_studies", rid)
    if study["status"] == "PRIVILEGED_FINAL":
        # Clean-study path (PRD §3.3)
        if study["actionable_finding_count"] != 0:
            raise_error(ERR_GAPS_NOT_CLOSED,
                        "close from PRIVILEGED_FINAL requires actionable_finding_count == 0")
    elif study["status"] == "MONITORING":
        completed = [c for c in cycles_of_study(rid) if c["status"] == "COMPLETED"]
        latest = max(completed, key=lambda c: c["cycle_index"]) if completed else None
        if latest is None or latest["retest_result"] != "GAPS_CLOSED":
            raise_error(ERR_GAPS_NOT_CLOSED,
                        "close from MONITORING requires the latest COMPLETED cycle "
                        "to have retest_result GAPS_CLOSED")
    else:
        raise_error(ERR_STUDY_INVALID_STATE,
                    "close requires study in PRIVILEGED_FINAL or MONITORING")
    study["status"] = "CLOSED"
    touch(study)
    return success_object(public(study))
