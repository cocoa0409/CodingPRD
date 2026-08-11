"""Domain services: calculations, ledgers, cascades, serializers."""
from datetime import datetime, timezone
from decimal import Decimal

from store import DB
from util import D, money, parse_dt, r2, touch

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIER_PCT = {
    "LARGE_HUB": Decimal("0.75"),
    "MEDIUM_HUB": Decimal("0.80"),
    "SMALL_HUB": Decimal("0.90"),
    "NONHUB": Decimal("0.95"),
}
STATE_PCT_OF_NONFEDERAL = Decimal("0.5")
CONTINGENCY_PCT = Decimal("0.10")
ASSURANCE_CODES = ["TITLE_VI", "BUY_AMERICAN", "DBE_PROGRAM",
                   "ENVIRONMENTAL_REVIEW", "PREVAILING_WAGE", "AIRPORT_FEES"]

AIRPORT_TIERS = {"LARGE_HUB", "MEDIUM_HUB", "SMALL_HUB", "NONHUB"}
FACILITY_TYPES = {"RUNWAY", "TAXIWAY", "APRON"}
PROJECT_TYPES = {"RUNWAY_SAFETY", "CAPACITY", "PRESERVATION",
                 "SECURITY", "ENVIRONMENTAL", "NOISE"}
CLOSURE_TYPES = {"FULL_CLOSURE", "NIGHT_ONLY"}
FINDING_CODES = {"INELIGIBLE_COST", "MISSING_DOCUMENTATION",
                 "DBE_SHORTFALL", "PROCUREMENT", "OTHER"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
ASSET_KINDS = {"EQUIPMENT", "LAND"}

# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_priority_scores(p):
    """cip_priority_score: both variants, 2dp round-half-up, cap/floor."""
    s_eff = p["safety_score"] * (2 if p["runway_safety_noncompliant"] else 1)
    base = (Decimal("0.30") * s_eff
            + Decimal("0.20") * p["preservation_score"]
            + Decimal("0.20") * p["capacity_score"]
            + Decimal("0.15") * p["security_score"]
            + Decimal("0.15") * p["environmental_score"])
    bonus = Decimal(5) if p["multi_airport_system"] else Decimal(0)
    sponsor = min(Decimal(100), r2(base + bonus))
    base_f = (Decimal("0.40") * p["safety_score"]
              + Decimal("0.25") * p["capacity_score"]
              + Decimal("0.15") * p["preservation_score"]
              + Decimal("0.10") * p["security_score"]
              + Decimal("0.10") * p["environmental_score"])
    penalty = Decimal(10) if p["runway_safety_noncompliant"] else Decimal(0)
    federal = max(Decimal(0), r2(base_f - penalty))
    return sponsor, federal


def funding_split(total_budget, fed_pct):
    """Waterfall: federal -> state (50% of non-federal) -> local remainder."""
    federal = r2(fed_pct * total_budget)
    state = r2(STATE_PCT_OF_NONFEDERAL * (total_budget - federal))
    local = total_budget - federal - state
    return federal, state, local


def retainage_split(gross, pct):
    withheld = r2(gross * pct)
    return withheld, gross - withheld


def amendment_calc(grant, added_scope_cost):
    base = grant["total_budget"] + added_scope_cost
    new_total = r2(base / (Decimal(1) - CONTINGENCY_PCT))
    contingency = new_total - base
    federal_delta = r2(grant["federal_share_pct_dec"]
                       * (new_total - grant["total_budget"]))
    return new_total, contingency, federal_delta


def asset_elapsed_years(asset):
    in_service = parse_dt(asset["in_service_date"], "in_service_date")
    days = (DB.clock - in_service).days  # whole days (floor for positive)
    elapsed = days // 365
    return max(0, min(asset["useful_life_years"], elapsed))


def asset_credit_recompute(asset):
    elapsed = asset_elapsed_years(asset)
    if asset["useful_life_years"] > 0:
        credit = r2(asset["acquisition_federal_share"] * Decimal(elapsed)
                    / Decimal(asset["useful_life_years"]))
    else:
        credit = Decimal("0")
    asset["service_credit_value"] = credit
    asset["remaining_restricted_value"] = (
        asset["acquisition_federal_share"] - credit)
    return elapsed


def disposal_payback(asset, grant, fair_market_value=None):
    elapsed = asset_elapsed_years(asset)
    remaining_years = asset["useful_life_years"] - elapsed
    if remaining_years <= 0:
        return Decimal("0.00")
    life = Decimal(asset["useful_life_years"])
    rem = Decimal(remaining_years)
    if asset["asset_kind"] == "EQUIPMENT":
        return r2(asset["acquisition_federal_share"] * rem / life)
    # LAND: fair-market variant uses the grant's CURRENT federal_share_pct.
    return r2(D(fair_market_value) * grant["federal_share_pct_dec"] * rem / life)


def drawdown_amounts(invoices, fed_pct):
    """total_net: plain sum; federal_amount: per-line round-half-up then sum."""
    total_net = sum((inv["net_payable"] for inv in invoices), Decimal("0"))
    federal = sum((r2(inv["net_payable"] * fed_pct) for inv in invoices),
                  Decimal("0"))
    return total_net, federal


# ---------------------------------------------------------------------------
# Cross-entity helpers
# ---------------------------------------------------------------------------

def program_deadline_dt(fiscal_year):
    return datetime(fiscal_year - 1, 12, 31, 23, 59, 59,
                    tzinfo=timezone.utc)


def application_deadline_dt(fiscal_year):
    return datetime(fiscal_year - 1, 5, 15, 23, 59, 59,
                    tzinfo=timezone.utc)


def application_deadline_str(fiscal_year):
    return f"{fiscal_year - 1}-05-15T23:59:59Z"


def program_projects(program_id):
    return [p for p in DB.projects.values() if p["program_id"] == program_id]


def recompute_selected_total(program):
    program["selected_total_cost"] = sum(
        (p["estimated_cost"] for p in program_projects(program["id"])
         if p["status"] == "SELECTED"), Decimal("0"))


def app_assurances(application_id):
    return [a for a in DB.assurances.values()
            if a["application_id"] == application_id]


def assurances_cleared(application_id):
    return sum(1 for a in app_assurances(application_id)
               if a["status"] in ("CERTIFIED", "WAIVED"))


def contract_invoices(contract_id):
    return [i for i in DB.invoices.values() if i["contract_id"] == contract_id]


def ledger_recompute(contract):
    """invoiced_total/retainage_held over confirmed invoices; remaining value.

    Confirmed = VERIFIED | INCLUDED | PAID (SUBMITTED/REJECTED/WITHHELD are
    excluded so the verify cap, reject flow, and withhold cascade reconcile).
    A CLOSED contract has its retainage released to 0.
    """
    invs = contract_invoices(contract["id"])
    confirmed = [i for i in invs if i["status"] in ("VERIFIED", "INCLUDED", "PAID")]
    contract["invoiced_total"] = sum(
        (i["gross_amount"] for i in confirmed), Decimal("0"))
    contract["remaining_value"] = (
        contract["awarded_value"] - contract["invoiced_total"])
    if contract["status"] == "CLOSED":
        contract["retainage_held"] = Decimal("0")
    else:
        contract["retainage_held"] = sum(
            (i["retainage_withheld"] for i in confirmed), Decimal("0"))


def scrub_project_from_applications(project, statuses):
    """Remove a fallen/dropped project from applications in the given statuses."""
    for app in DB.applications.values():
        if app["status"] in statuses and project["id"] in app["project_ids"]:
            app["project_ids"] = [pid for pid in app["project_ids"]
                                  if pid != project["id"]]
            app["total_eligible_cost"] = sum(
                (DB.projects[pid]["estimated_cost"]
                 for pid in app["project_ids"] if pid in DB.projects),
                Decimal("0"))
            touch(app)


def apply_selection(program, budget):
    """Recompute scores/rank for all non-DROPPED projects; prefix sweep."""
    projs = [p for p in program_projects(program["id"])
             if p["status"] != "DROPPED"]
    for p in projs:
        s, f = compute_priority_scores(p)
        p["priority_score_sponsor"] = s
        p["priority_score_federal"] = f
    ranked = sorted(projs, key=lambda p: (-p["priority_score_sponsor"],
                                          p["created_at"], p["_seq"]))
    cumulative = Decimal("0")
    breached = False
    for idx, p in enumerate(ranked, start=1):
        p["selection_rank"] = idx
        if not breached and cumulative + p["estimated_cost"] <= budget:
            new_status = "SELECTED"
            cumulative += p["estimated_cost"]
        else:
            new_status = "DEFERRED"
            breached = True
        if p["status"] == "SELECTED" and new_status == "DEFERRED":
            scrub_project_from_applications(p, ("DRAFT",))
        p["status"] = new_status
        touch(p)
    program["selection_budget"] = budget
    recompute_selected_total(program)
    touch(program)


def closeout_settle_and_cascade(grant):
    """Final settlement + depth-3 cascade; grant ends CLOSED (caller touches)."""
    sponsor = DB.sponsors[grant["sponsor_id"]]
    released = grant["federal_obligated"] - grant["federal_drawn"]
    entitlement_released = min(released, grant["entitlement_portion"])
    grant["federal_obligated"] = grant["federal_drawn"]
    sponsor["npe_entitlement_available"] += entitlement_released
    touch(sponsor)
    for contract in [c for c in DB.contracts.values()
                     if c["grant_id"] == grant["id"]]:
        if contract["status"] == "AWARDED":
            contract["status"] = "CLOSED"
            for inv in contract_invoices(contract["id"]):
                if inv["status"] in ("VERIFIED", "WITHHELD"):
                    inv["status"] = "PAID"
                    touch(inv)
            ledger_recompute(contract)
            touch(contract)
    for asset in [a for a in DB.assets.values()
                  if a["grant_id"] == grant["id"]]:
        if asset["status"] == "IN_SERVICE":
            asset_credit_recompute(asset)
            touch(asset)
    grant["status"] = "CLOSED"


def run_checkpoint():
    applications_expired = 0
    for app in list(DB.applications.values()):
        if app["status"] in ("DRAFT", "UNDER_REVIEW", "RETURNED"):
            program = DB.programs.get(app["program_id"])
            if program and DB.clock > application_deadline_dt(
                    program["fiscal_year"]):
                app["status"] = "EXPIRED"
                touch(app)
                applications_expired += 1
    programs_expired = 0
    for program in list(DB.programs.values()):
        if program["status"] in ("DRAFT", "SUBMITTED", "AMENDMENT_DRAFT") and \
                DB.clock > program_deadline_dt(program["fiscal_year"]):
            program["status"] = "EXPIRED"
            for p in program_projects(program["id"]):
                if p["status"] in ("PROPOSED", "SELECTED", "DEFERRED"):
                    p["status"] = "DROPPED"
                    touch(p)
            recompute_selected_total(program)
            touch(program)
            programs_expired += 1
    assets_recomputed = 0
    for asset in list(DB.assets.values()):
        if asset["status"] == "IN_SERVICE":
            asset_credit_recompute(asset)
            touch(asset)
            assets_recomputed += 1
    return {"applications_expired": applications_expired,
            "programs_expired": programs_expired,
            "assets_recomputed": assets_recomputed}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_sponsor(s):
    return {"id": s["id"], "sponsor_name": s["sponsor_name"],
            "loc_id": s["loc_id"], "airport_size_tier": s["airport_size_tier"],
            "npe_entitlement_total": money(s["npe_entitlement_total"]),
            "npe_entitlement_available": money(s["npe_entitlement_available"]),
            "status": s["status"], "created_at": s["created_at"],
            "updated_at": s["updated_at"], "version": s["version"]}


def ser_facility(f):
    return {"id": f["id"], "sponsor_id": f["sponsor_id"],
            "facility_name": f["facility_name"],
            "facility_type": f["facility_type"],
            "created_at": f["created_at"], "updated_at": f["updated_at"],
            "version": f["version"]}


def ser_program(p):
    return {"id": p["id"], "sponsor_id": p["sponsor_id"],
            "fiscal_year": p["fiscal_year"],
            "selection_budget": money(p["selection_budget"]),
            "selected_total_cost": money(p["selected_total_cost"]),
            "status": p["status"], "created_at": p["created_at"],
            "updated_at": p["updated_at"], "version": p["version"]}


def _score(v):
    return None if v is None else float(v)


def ser_project(p):
    return {"id": p["id"], "program_id": p["program_id"], "title": p["title"],
            "project_type": p["project_type"],
            "estimated_cost": money(p["estimated_cost"]),
            "safety_score": p["safety_score"],
            "capacity_score": p["capacity_score"],
            "preservation_score": p["preservation_score"],
            "security_score": p["security_score"],
            "environmental_score": p["environmental_score"],
            "runway_safety_noncompliant": p["runway_safety_noncompliant"],
            "multi_airport_system": p["multi_airport_system"],
            "priority_score_sponsor": _score(p["priority_score_sponsor"]),
            "priority_score_federal": _score(p["priority_score_federal"]),
            "selection_rank": p["selection_rank"],
            "status": p["status"], "created_at": p["created_at"],
            "updated_at": p["updated_at"], "version": p["version"]}


def ser_application(a):
    return {"id": a["id"], "sponsor_id": a["sponsor_id"],
            "program_id": a["program_id"], "project_ids": a["project_ids"],
            "total_eligible_cost": money(a["total_eligible_cost"]),
            "created_by_user_id": a["created_by_user_id"],
            "assurances_total": a["assurances_total"],
            "assurances_cleared": assurances_cleared(a["id"]),
            "submission_deadline": a["submission_deadline"],
            "offered_federal_obligated":
                None if a["offered_federal_obligated"] is None
                else money(a["offered_federal_obligated"]),
            "offered_entitlement_portion":
                None if a["offered_entitlement_portion"] is None
                else money(a["offered_entitlement_portion"]),
            "created_grant_id": a["created_grant_id"],
            "status": a["status"], "created_at": a["created_at"],
            "updated_at": a["updated_at"], "version": a["version"]}


def ser_assurance(a):
    return {"id": a["id"], "created_at": a["created_at"],
            "application_id": a["application_id"],
            "assurance_code": a["assurance_code"],
            "certified_by_user_id": a["certified_by_user_id"],
            "status": a["status"]}


def ser_grant(gr):
    return {"id": gr["id"], "sponsor_id": gr["sponsor_id"],
            "application_id": gr["application_id"],
            "grant_number": gr["grant_number"],
            "federal_share_pct": float(gr["federal_share_pct_dec"]),
            "total_budget": money(gr["total_budget"]),
            "federal_obligated": money(gr["federal_obligated"]),
            "federal_drawn": money(gr["federal_drawn"]),
            "federal_available":
                money(gr["federal_obligated"] - gr["federal_drawn"]),
            "state_share_estimated": money(gr["state_share_estimated"]),
            "local_share_estimated": money(gr["local_share_estimated"]),
            "entitlement_portion": money(gr["entitlement_portion"]),
            "status": gr["status"], "created_at": gr["created_at"],
            "updated_at": gr["updated_at"], "version": gr["version"]}


def ser_amendment(a):
    return {"id": a["id"], "grant_id": a["grant_id"],
            "added_scope_cost": money(a["added_scope_cost"]),
            "reason": a["reason"],
            "contingency_amount": money(a["contingency_amount"]),
            "new_total_budget": money(a["new_total_budget"]),
            "federal_delta": money(a["federal_delta"]),
            "status": a["status"], "created_at": a["created_at"],
            "updated_at": a["updated_at"], "version": a["version"]}


def ser_contractor(c):
    return {"id": c["id"], "sponsor_id": c["sponsor_id"],
            "contractor_name": c["contractor_name"],
            "dbe_certified": c["dbe_certified"], "status": c["status"],
            "created_at": c["created_at"], "updated_at": c["updated_at"],
            "version": c["version"]}


def ser_contract(c):
    return {"id": c["id"], "grant_id": c["grant_id"],
            "cip_project_id": c["cip_project_id"],
            "contractor_id": c["contractor_id"],
            "awarded_value": money(c["awarded_value"]),
            "dbe_goal_pct": money(c["dbe_goal_pct"]),
            "retainage_pct": float(c["retainage_pct"]),
            "invoiced_total": money(c["invoiced_total"]),
            "remaining_value": money(c["remaining_value"]),
            "retainage_held": money(c["retainage_held"]),
            "dbe_posture": c["dbe_posture"], "status": c["status"],
            "created_at": c["created_at"], "updated_at": c["updated_at"],
            "version": c["version"]}


def ser_dbe_report(r):
    return {"id": r["id"], "created_at": r["created_at"],
            "contract_id": r["contract_id"],
            "reporting_period": r["reporting_period"],
            "dbe_paid_amount": money(r["dbe_paid_amount"]),
            "total_paid_amount": money(r["total_paid_amount"]),
            "achieved_dbe_pct": money(r["achieved_dbe_pct"]),
            "status": r["status"]}


def ser_invoice(i):
    return {"id": i["id"], "contract_id": i["contract_id"],
            "invoice_number": i["invoice_number"], "period": i["period"],
            "gross_amount": money(i["gross_amount"]),
            "retainage_withheld": money(i["retainage_withheld"]),
            "net_payable": money(i["net_payable"]),
            "drawdown_id": i["drawdown_id"], "status": i["status"],
            "created_at": i["created_at"], "updated_at": i["updated_at"],
            "version": i["version"]}


def ser_reimbursement(r):
    return {"id": r["id"], "grant_id": r["grant_id"],
            "invoice_ids": r["invoice_ids"],
            "total_net": money(r["total_net"]),
            "federal_amount": money(r["federal_amount"]),
            "prepared_by_user_id": r["prepared_by_user_id"],
            "certified_by_user_id": r["certified_by_user_id"],
            "status": r["status"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "version": r["version"]}


def ser_finding(f):
    return {"id": f["id"], "created_at": f["created_at"],
            "grant_id": f["grant_id"], "finding_code": f["finding_code"],
            "severity": f["severity"], "description": f["description"],
            "status": f["status"]}


def ser_asset(a):
    return {"id": a["id"], "grant_id": a["grant_id"],
            "asset_kind": a["asset_kind"], "description": a["description"],
            "acquisition_federal_share": money(a["acquisition_federal_share"]),
            "useful_life_years": a["useful_life_years"],
            "in_service_date": a["in_service_date"],
            "service_credit_value": money(a["service_credit_value"]),
            "remaining_restricted_value": money(a["remaining_restricted_value"]),
            "payback_due": money(a["payback_due"]),
            "status": a["status"], "created_at": a["created_at"],
            "updated_at": a["updated_at"], "version": a["version"]}


def ser_phase(p):
    return {"id": p["id"], "grant_id": p["grant_id"],
            "cip_project_id": p["cip_project_id"],
            "facility_id": p["facility_id"],
            "contractor_id": p["contractor_id"],
            "closure_type": p["closure_type"],
            "start_utc": p["start_utc"], "end_utc": p["end_utc"],
            "status": p["status"], "created_at": p["created_at"],
            "updated_at": p["updated_at"], "version": p["version"]}
