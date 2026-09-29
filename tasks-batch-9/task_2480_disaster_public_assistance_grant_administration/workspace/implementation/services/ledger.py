"""Lookups, cascades and the conserved ledger quantities (PRD 2.9, 3.7, 3.8)."""
from datetime import timedelta

from db import db, new_row, now, now_iso, order_key, setf, touch
from services.calc import (
    dec,
    federal_share_obligation,
    floor_int,
    risk_score_monitoring,
    risk_tier,
)
from services.constants import (
    LEDGER_PROJECT_STATUSES,
    PER_CAPITA_INDICATOR_CENTS,
    REPORT_GRACE_DAYS,
    SINGLE_AUDIT_THRESHOLD_CENTS,
    WATERFALL_PROJECT_STATUSES,
)
from db import format_instant, parse_instant


# ---------------------------------------------------------------------------
# navigation
# ---------------------------------------------------------------------------

def applicant_of_facility(facility):
    return db.applicants.get(facility["applicant_id"]) if facility else None


def disaster_of_applicant(applicant):
    return db.disasters.get(applicant["disaster_id"]) if applicant else None


def disaster_of_facility(facility):
    return disaster_of_applicant(applicant_of_facility(facility))


def applicant_of_project(project):
    return db.applicants.get(project["applicant_id"]) if project else None


def disaster_of_project(project):
    return disaster_of_applicant(applicant_of_project(project))


def facility_of_project(project):
    return db.facilities.get(project["facility_id"]) if project else None


def applicant_of_deobligation(deob):
    project = db.projects.get(deob["project_id"]) if deob else None
    return applicant_of_project(project)


def projects_of_applicant(applicant_id):
    return [p for p in db.projects.values() if p["applicant_id"] == applicant_id]


def facilities_of_applicant(applicant_id):
    return [f for f in db.facilities.values() if f["applicant_id"] == applicant_id]


def policies_of_facility(facility_id):
    return [p for p in db.insurance_policies.values() if p["facility_id"] == facility_id]


def lines_of_project(project_id):
    return [c for c in db.cost_line_items.values() if c["project_id"] == project_id]


def reviewed_lines_of_project(project_id):
    return [c for c in lines_of_project(project_id)
            if c["review_status"] in ("ALLOWED", "PARTIALLY_ALLOWED")]


def deobligations_of_project(project_id):
    return [d for d in db.deobligations.values() if d["project_id"] == project_id]


def reports_of_applicant(applicant_id):
    return [r for r in db.progress_reports.values() if r["applicant_id"] == applicant_id]


def covering_policies(facility_id, incident_start_at):
    """Policies whose closed effective interval contains the incident start."""
    start = parse_instant(incident_start_at)
    result = []
    if start is None:
        return result
    for policy in policies_of_facility(facility_id):
        low = parse_instant(policy["effective_start_at"])
        high = parse_instant(policy["effective_end_at"])
        if low is not None and high is not None and low <= start <= high:
            result.append(policy)
    return result


# ---------------------------------------------------------------------------
# recomputation
# ---------------------------------------------------------------------------

def recompute_project_deobligations(project):
    deobs = deobligations_of_project(project["id"])
    final_net = sum(d["amount_cents"] - d["reversed_cents"]
                    for d in deobs if d["status"] == "FINAL")
    proposed = sum(d["amount_cents"] for d in deobs if d["status"] == "PROPOSED")
    setf(project, "deobligated_cents", final_net)
    setf(project, "pending_deobligation_cents", proposed)


def recompute_applicant_ledger(applicant):
    applicant_id = applicant["id"]
    projects = projects_of_applicant(applicant_id)
    total_obligated = sum(
        p["federal_share_obligated_cents"] - p["deobligated_cents"]
        for p in projects if p["status"] in LEDGER_PROJECT_STATUSES
    )
    drawdowns = [d for d in db.drawdowns.values() if d["applicant_id"] == applicant_id]
    total_drawn = sum(d["approved_cents"] for d in drawdowns
                      if d["status"] in ("PAID", "REFUNDED"))
    total_refunded = sum(d["refunded_cents"] for d in drawdowns
                         if d["status"] == "REFUNDED")
    cash = total_drawn - total_refunded
    available = total_obligated - cash
    project_ids = set(p["id"] for p in projects)
    pending = sum(d["amount_cents"] for d in db.deobligations.values()
                  if d["project_id"] in project_ids and d["status"] == "PROPOSED")
    delinquent = len([r for r in reports_of_applicant(applicant_id)
                      if r["status"] == "DELINQUENT"])

    setf(applicant, "total_obligated_cents", total_obligated)
    setf(applicant, "total_drawn_cents", total_drawn)
    setf(applicant, "total_refunded_cents", total_refunded)
    setf(applicant, "cash_on_hand_cents", cash)
    setf(applicant, "available_drawdown_cents", available)
    setf(applicant, "pending_deobligation_cents", pending)
    setf(applicant, "delinquent_report_count", delinquent)
    setf(applicant, "drawdown_status",
         "SUSPENDED" if (delinquent > 0 or pending > 0) else "ACTIVE")
    if applicant["audit_requirement"] == "SINGLE_AUDIT" \
            or total_obligated >= SINGLE_AUDIT_THRESHOLD_CENTS:
        setf(applicant, "audit_requirement", "SINGLE_AUDIT")


def recompute_disaster_rollups(disaster):
    applicants = [a for a in db.applicants.values()
                  if a["disaster_id"] == disaster["id"]]
    setf(disaster, "total_obligated_cents",
         sum(a["total_obligated_cents"] for a in applicants))
    setf(disaster, "total_drawn_cents",
         sum(a["cash_on_hand_cents"] for a in applicants))
    setf(disaster, "enhanced_monitoring_applicant_count",
         len([a for a in applicants if a["monitoring_status"] == "ENHANCED"]))
    setf(disaster, "suspended_applicant_count",
         len([a for a in applicants if a["drawdown_status"] == "SUSPENDED"]))


def recompute_disaster_indicator(disaster):
    applicant_ids = set(a["id"] for a in db.applicants.values()
                        if a["disaster_id"] == disaster["id"])
    facility_ids = set(f["id"] for f in db.facilities.values()
                       if f["applicant_id"] in applicant_ids)
    total = sum(s["validated_loss_cents"] for s in db.damage_sites.values()
                if s["facility_id"] in facility_ids
                and s["validation_status"] == "VALIDATED")
    population = disaster["population"]
    per_capita = floor_int(dec(total) / dec(population)) if population else 0
    setf(disaster, "total_validated_loss_cents", total)
    setf(disaster, "per_capita_impact_cents", per_capita)
    setf(disaster, "indicator_met", per_capita >= PER_CAPITA_INDICATOR_CENTS)


def cascade_applicant(applicant):
    """Recompute the applicant ledger and roll the change up to the declaration."""
    if applicant is None:
        return None
    recompute_applicant_ledger(applicant)
    disaster = disaster_of_applicant(applicant)
    if disaster is not None:
        recompute_disaster_rollups(disaster)
    return disaster


def rescore_monitoring(applicant):
    score = risk_score_monitoring(applicant)
    setf(applicant, "risk_score_monitoring", float(score))
    setf(applicant, "monitoring_scored_at", now_iso())
    setf(applicant, "risk_tier", risk_tier(score))


def refresh_risk_tier(applicant):
    if applicant["monitoring_scored_at"] is not None:
        setf(applicant, "risk_tier", risk_tier(applicant["risk_score_monitoring"]))
    else:
        setf(applicant, "risk_tier", risk_tier(applicant["risk_score_screening"]))


# ---------------------------------------------------------------------------
# quarter derivation
# ---------------------------------------------------------------------------

def quarter_bounds(quarter_label):
    year = int(quarter_label[:4])
    quarter = int(quarter_label[6])
    start_month = 1 + 3 * (quarter - 1)
    period_start = _utc(year, start_month)
    if quarter == 4:
        period_end = _utc(year + 1, 1)
    else:
        period_end = _utc(year, start_month + 3)
    due = period_end + timedelta(days=REPORT_GRACE_DAYS)
    return format_instant(period_start), format_instant(period_end), format_instant(due)


def _utc(year, month):
    from datetime import datetime, timezone
    return datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)


def current_quarter_label():
    clock = now()
    return "%04d-Q%d" % (clock.year, (clock.month - 1) // 3 + 1)


def create_progress_report(applicant, quarter_label, status,
                           expenditures=0, pct_complete=0, submitted_at=None):
    period_start, period_end, due = quarter_bounds(quarter_label)
    return new_row("progress_reports", {
        "applicant_id": applicant["id"],
        "quarter_label": quarter_label,
        "period_start_at": period_start,
        "period_end_at": period_end,
        "due_at": due,
        "expenditures_to_date_cents": expenditures,
        "pct_complete": pct_complete,
        "submitted_at": submitted_at,
        "status": status,
    })


# ---------------------------------------------------------------------------
# deobligation creation (system cascades)
# ---------------------------------------------------------------------------

def create_deobligation(project, reason, amount_cents, user_id):
    return new_row("deobligations", {
        "project_id": project["id"],
        "reason": reason,
        "amount_cents": amount_cents,
        "status": "PROPOSED",
        "determined_by_user_id": user_id,
        "finalized_at": None,
        "appeal_deadline_at": None,
        "reversed_cents": 0,
    })


# ---------------------------------------------------------------------------
# insurance duplication-of-benefits waterfall
# ---------------------------------------------------------------------------

def insurance_dob_waterfall(policy, settlement_amount_cents, user_id):
    facility = db.facilities.get(policy["facility_id"])
    candidates = [p for p in db.projects.values()
                  if p["facility_id"] == policy["facility_id"]
                  and p["status"] in WATERFALL_PROJECT_STATUSES]
    candidates.sort(key=lambda p: (p["category"],) + order_key(p))

    available = settlement_amount_cents
    touched_applicants = {}
    for project in candidates:
        room = project["repair_eligible_cents"] - project["settlement_allocated_cents"]
        if room < 0:
            room = 0
        take = available if available < room else room
        if take:
            setf(project, "settlement_allocated_cents",
                 project["settlement_allocated_cents"] + take)
        setf(project, "insurance_reduction_cents",
             max(project["anticipated_insurance_cents"],
                 project["settlement_allocated_cents"]))
        available -= take
        if project["status"] in ("OBLIGATED", "CLOSEOUT_REQUESTED") and take > 0:
            disaster = disaster_of_project(project)
            pct = disaster["federal_cost_share_pct"] if disaster else 0
            recomputed = federal_share_obligation(
                project["repair_eligible_cents"],
                project["insurance_reduction_cents"],
                project["mitigation_approved_cents"],
                pct,
            )
            shortfall = (project["federal_share_obligated_cents"]
                         - project["deobligated_cents"] - recomputed)
            if shortfall > 0:
                create_deobligation(project, "INSURANCE_DOB", shortfall, user_id)
                recompute_project_deobligations(project)
                applicant = applicant_of_project(project)
                if applicant is not None:
                    touched_applicants[applicant["id"]] = applicant

    setf(policy, "allocated_cents", settlement_amount_cents - available)
    setf(policy, "unallocated_cents", available)

    for applicant in touched_applicants.values():
        cascade_applicant(applicant)
    if not touched_applicants and facility is not None:
        # keep declaration rollups coherent even when nothing was deobligated
        applicant = applicant_of_facility(facility)
        if applicant is not None:
            cascade_applicant(applicant)
