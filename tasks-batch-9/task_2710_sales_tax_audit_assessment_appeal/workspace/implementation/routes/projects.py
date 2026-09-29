"""IndustryProject, selection runs and AuditLead endpoints (PRD 3.1)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import body, filter_arg, guard, opt_enum, opt_int, req_enum, req_int, req_str
from routes.common import (
    AUDIT_TYPES,
    LEAD_STATUSES,
    SELECTION_MODES,
    apply_filter,
    by_created,
    listing,
    naics,
    one,
    path_get,
)
from services import calc, derive

bp = Blueprint("projects", __name__)


@bp.post("/industry-projects")
@guard("SelectionAnalyst", "AuditSupervisor")
def create_project():
    data = body()
    project_name = req_str(data, "project_name", 1, 120)
    industry_naics_code = naics(data, "industry_naics_code")
    error_rate = req_int(data, "industry_error_rate_bp", 0, 10000)
    mode = req_enum(data, "selection_mode", SELECTION_MODES)
    threshold = opt_int(data, "selection_threshold_score", 0, 1000, 0)
    quota = opt_int(data, "selection_quota", 1, None, 1)

    rec = db.new_record(
        {
            "project_name": project_name,
            "industry_naics_code": industry_naics_code,
            "industry_error_rate_bp": error_rate,
            "selection_mode": mode,
            "selection_threshold_score": threshold,
            "selection_quota": quota,
            "selections_used": 0,
            "selections_remaining": quota,
            "last_run_at": None,
            "last_cutoff_score": None,
            "scored_lead_count": 0,
        }
    )
    db.insert("industry_projects", rec)
    return one("industry_projects", rec, 201)


@bp.get("/industry-projects")
@guard("SelectionAnalyst", "AuditSupervisor")
def list_projects():
    rows = by_created(db.all_of("industry_projects"))
    rows = apply_filter(rows, "selection_mode", SELECTION_MODES)
    value = filter_arg("industry_naics_code")
    if value is not None:
        rows = [r for r in rows if r["industry_naics_code"] == value]
    return listing("industry_projects", rows)


@bp.get("/industry-projects/<pid>")
@guard("SelectionAnalyst", "AuditSupervisor")
def read_project(pid):
    return one("industry_projects", path_get("industry_projects", pid))


@bp.post("/industry-projects/<pid>/selection-runs")
@guard("SelectionAnalyst")
def selection_run(pid):
    project = path_get("industry_projects", pid)
    threshold = int(project["selection_threshold_score"])
    quota = int(project["selection_quota"])

    candidates = []
    for tp in db.all_of("taxpayers"):
        if tp["industry_naics_code"] != project["industry_naics_code"]:
            continue
        if tp["compliance_status"] == "REVOKED":
            continue
        derive.refresh_taxpayer(tp)
        if tp["open_audit_count"] != 0:
            continue
        candidates.append(tp)

    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_CANDIDATES")

    industry_bp = min(10000, int(project["industry_error_rate_bp"]))
    scored = []
    for tp in candidates:
        v = tp["info_variance_bp"]
        d = tp["delinquency_bp"]
        m = tp["magnitude_bp"]
        p = tp["prior_audit_bp"]
        weighted_sum = 35 * v + 20 * d + 20 * industry_bp + 15 * m + 10 * p
        score = calc.full_score(v, d, industry_bp, m, p)
        scored.append(
            {
                "taxpayer": tp,
                "risk_score": score,
                "score_breakdown": {
                    "info_variance_bp": v,
                    "delinquency_bp": d,
                    "industry_error_rate_bp": industry_bp,
                    "magnitude_bp": m,
                    "prior_audit_bp": p,
                    "weighted_sum": weighted_sum,
                },
            }
        )

    scored.sort(key=lambda e: (-e["risk_score"], e["taxpayer"]["created_at"], e["taxpayer"]["_seq"]))

    selected_count = 0
    for index, entry in enumerate(scored):
        meets_threshold = entry["risk_score"] >= threshold
        within_quota = selected_count < quota
        if project["selection_mode"] == "THRESHOLD":
            select = meets_threshold
        elif project["selection_mode"] == "QUOTA":
            select = within_quota
        else:
            select = meets_threshold and within_quota
        if select:
            entry["status"] = "SELECTED"
            selected_count += 1
        else:
            entry["status"] = "SCORED" if meets_threshold else "NOT_SELECTED"
        entry["rank_position"] = index + 1

    if selected_count == 0 and project["selection_mode"] in ("THRESHOLD", "HYBRID"):
        # all-or-nothing: no lead is left behind
        raise ApiError("ERR_NO_ELIGIBLE_CANDIDATES")

    scored_at = db.clock_instant_str()
    cutoff = threshold
    for entry in scored:
        lead = db.new_record(
            {
                "industry_project_id": project["id"],
                "taxpayer_id": entry["taxpayer"]["id"],
                "status": entry["status"],
                "risk_score": entry["risk_score"],
                "score_variant": "FULL",
                "score_breakdown": entry["score_breakdown"],
                "rank_position": entry["rank_position"],
                "scored_at": scored_at,
                "promoted_from_scored": False,
                "decline_reason": None,
            }
        )
        db.insert("audit_leads", lead)
        if entry["status"] == "SELECTED":
            cutoff = entry["risk_score"]

    project["scored_lead_count"] = len(scored)
    project["last_run_at"] = scored_at
    project["last_cutoff_score"] = cutoff
    derive.refresh_project(project)
    db.touch(project)
    return one("industry_projects", project)


@bp.get("/audit-leads")
@guard("SelectionAnalyst", "AuditSupervisor")
def list_leads():
    rows = by_created(db.all_of("audit_leads"))
    for field in ("industry_project_id", "taxpayer_id"):
        value = filter_arg(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = apply_filter(rows, "status", LEAD_STATUSES)
    return listing("audit_leads", rows)


@bp.get("/audit-leads/<lid>")
@guard("SelectionAnalyst", "AuditSupervisor")
def read_lead(lid):
    return one("audit_leads", path_get("audit_leads", lid))


@bp.post("/audit-leads/<lid>/decline")
@guard("SelectionAnalyst", "AuditSupervisor")
def decline_lead(lid):
    lead = path_get("audit_leads", lid)
    data = body()
    reason = req_str(data, "decline_reason", 1, None)
    if lead["status"] not in ("SELECTED", "SCORED"):
        raise ApiError("ERR_INVALID_STATE")

    was_selected = lead["status"] == "SELECTED"
    lead["status"] = "DECLINED"
    lead["decline_reason"] = reason
    db.touch(lead)

    project = db.get("industry_projects", lead["industry_project_id"])
    if was_selected and project is not None:
        threshold = int(project["selection_threshold_score"])
        waitlist = [
            row
            for row in db.where("audit_leads", industry_project_id=project["id"], status="SCORED")
        ]
        ranked = []
        for row in waitlist:
            tp = db.get("taxpayers", row["taxpayer_id"])
            ranked.append((-int(row["risk_score"]), tp["created_at"] if tp else "", tp["_seq"] if tp else 0, row))
        ranked.sort(key=lambda e: (e[0], e[1], e[2]))
        for _, _, _, candidate in ranked:
            if int(candidate["risk_score"]) >= threshold:
                candidate["status"] = "SELECTED"
                candidate["promoted_from_scored"] = True
                db.touch(candidate)
                break
        derive.refresh_project(project)
        db.touch(project)
    return one("audit_leads", lead)


@bp.post("/audit-leads/<lid>/convert")
@guard("AuditSupervisor")
def convert_lead(lid):
    lead = path_get("audit_leads", lid)
    data = body()
    auditor = req_str(data, "lead_auditor_user_id", 1, 64)
    audit_type = opt_enum(data, "audit_type", AUDIT_TYPES, None)

    # tier 10 — the lead itself must be SELECTED
    if lead["status"] != "SELECTED":
        raise ApiError("ERR_LEAD_NOT_SELECTED")

    holder = db.get("taxpayers", lead["taxpayer_id"])
    if holder is None:
        raise ApiError("ERR_TAXPAYER_NOT_FOUND")
    # tier 11 — no other live audit of the same taxpayer
    if derive.open_audit_count(holder["id"]) != 0:
        raise ApiError("ERR_TAXPAYER_AUDIT_IN_PROGRESS")

    audit = db.new_record(
        {
            "taxpayer_id": holder["id"],
            "audit_lead_id": lead["id"],
            "agreed_agreement_id": None,
            "lead_auditor_user_id": auditor,
            "status": "PLANNED",
            "audit_type": audit_type,
            "scope_period_start": None,
            "scope_period_end": None,
            "base_statute_expiry_date": None,
            "statute_expiry_date": None,
            "waiver_days_added": 0,
            "tolled_days": 0,
            "statute_status": "UNSET",
            "projection_method": "NONE",
            "projection_status": "NOT_RUN",
            "sample_error_rate_bp": None,
            "projected_deficiency_cents": 0,
            "certificate_deficiency_cents": 0,
            "use_tax_deficiency_cents": 0,
            "examined_unit_count": 0,
            "fraud_indicator": False,
            "reopen_count": 0,
        }
    )
    db.insert("audits", audit)

    lead["status"] = "CONVERTED"
    db.touch(lead)
    derive.refresh_taxpayer(holder)
    db.touch(holder)
    project = db.get("industry_projects", lead["industry_project_id"])
    if project is not None:
        derive.refresh_project(project)
    return one("audits", audit, 201)
