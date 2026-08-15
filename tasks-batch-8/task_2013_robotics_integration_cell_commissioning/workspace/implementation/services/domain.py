"""Shared domain mechanics: entity lifecycle, retention ledger, cascades (PRD §2.4,
§2.8, §2.12, §3.6, §3.9)."""
import uuid
from datetime import timedelta

from db import children, store
from services import calculations as calc
from timeutil import fmt_dt, now_iso


# ---------------------------------------------------------------- basics
def new_id():
    return str(uuid.uuid4())


def common_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(ent):
    """Every mutation refreshes updated_at and increments version (PRD §2.4)."""
    ent["updated_at"] = now_iso()
    ent["version"] += 1


def pub(ent):
    """Public serialization: strip internal underscore-prefixed keys."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def pubs(ents):
    return [pub(e) for e in ents]


# ---------------------------------------------------------------- hierarchy helpers
def org_of_project(project):
    site = store.sites.get(project["customer_site_id"])
    if site is None:
        return None
    return store.orgs.get(site["integrator_org_id"])


def site_of_project(project):
    return store.sites.get(project["customer_site_id"])


def project_of(child):
    return store.projects.get(child["cell_project_id"])


# ---------------------------------------------------------------- retention ledger
def post_ledger_entry(project, entry_type, amount_cents, milestone_ref):
    ts = now_iso()
    entry = {
        "id": new_id(),
        "created_at": ts,
        "cell_project_id": project["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "milestone_ref": milestone_ref,
        "recorded_at_utc": ts,
        "_seq": store.next_seq(),
    }
    store.ledger[entry["id"]] = entry
    recompute_balance(project)
    return entry


def recompute_balance(project):
    """retention_balance_cents is derived from the project's postings (PRD §2.8)."""
    project["retention_balance_cents"] = sum(
        e["amount_cents"]
        for e in store.ledger.values()
        if e["cell_project_id"] == project["id"]
    )


def milestone_amount_for_phase(project, phase):
    """FAT/SAT milestone amount per the pinned retention_release_schedule."""
    site = store.sites[project["customer_site_id"]]
    org = store.orgs[site["integrator_org_id"]]
    total = calc.retention_total_cents(project["contract_value_cents"], org["retention_rate_bps"])
    fat, sat, _guarantee = calc.milestone_amounts(total)
    return fat if phase == "FAT" else sat


def maybe_close_project(project):
    """GUARANTEE -> CLOSED once the guarantee stands settled and the balance is zero."""
    if project["status"] != "GUARANTEE":
        return
    if project["retention_balance_cents"] != 0:
        return
    guarantee = guarantee_of_project(project["id"])
    if guarantee is not None and guarantee["guarantee_status"] in ("MET", "MISSED", "WAIVED"):
        project["status"] = "CLOSED"


# ---------------------------------------------------------------- guarantees
def guarantee_of_project(project_id):
    gs = children("guarantees", "cell_project_id", project_id)
    return gs[-1] if gs else None


def init_guarantee(project):
    """Born at SAT -> TRAINING: created directly in MEASURING (PRD §3.9)."""
    start = store.logical_clock
    end = start + timedelta(days=project["guarantee_window_days"])
    g = {
        **common_fields(),
        "cell_project_id": project["id"],
        "guarantee_window_days": project["guarantee_window_days"],
        "window_start_utc": fmt_dt(start),
        "window_end_utc": fmt_dt(end),
        "guarantee_status": "MEASURING",
        "observed_uptime_pct": None,
        "observed_cycle_time_s": None,
        "shortfall_pct": None,
    }
    store.guarantees[g["id"]] = g
    return g


# ---------------------------------------------------------------- cascades
def rework_cascade(project, phase):
    """FAT/SAT -> DESIGN cascade (PRD §3.6). Caller bumps the project version once."""
    project["rework_count"] += 1
    for prog in children("programs", "cell_project_id", project["id"]):
        if prog["dev_status"] == "RELEASED":
            prog["dev_status"] = "REWORK"  # sim_status deliberately unchanged
            touch(prog)
    for sel in children("selections", "cell_project_id", project["id"]):
        if sel["selection_status"] == "LOCKED":
            sel["selection_status"] = "VALIDATED"
            touch(sel)
    if phase == "SAT":
        for a in children("assessments", "cell_project_id", project["id"]):
            if a["status"] == "APPROVED":
                a["status"] = "SUPERSEDED"
                touch(a)
                shell = {
                    **common_fields(),
                    "cell_project_id": project["id"],
                    "assessment_revision": a["assessment_revision"] + 1,
                    "risk_score_pre_mitigation": a["risk_score_pre_mitigation"],
                    "pl_target": a["pl_target"],
                    "pl_achieved": a.get("pl_achieved"),
                    "fencing_length_m": a["fencing_length_m"],
                    "light_curtain_zones": a["light_curtain_zones"],
                    "muting_required": a["muting_required"],
                    "safety_function_budget_pct": None,
                    "status": "DRAFT",
                    "approved_by_safety_lead_id": None,
                    "_created_by": a.get("_created_by"),
                }
                store.assessments[shell["id"]] = shell
    project["status"] = "DESIGN"


def terminate_cascade(project):
    """Termination cascade (PRD §3.9). Caller bumps the project version once."""
    for s in children("studies", "cell_project_id", project["id"]):
        if s["status"] in ("DRAFT", "SUBMITTED"):
            s["status"] = "REJECTED"
            touch(s)
    for p in children("programs", "cell_project_id", project["id"]):
        if p["sim_status"] == "SIM_RUNNING":
            p["sim_status"] = "SIM_FAILED"
            touch(p)
    for t in children("sessions", "cell_project_id", project["id"]):
        if t["session_status"] in ("SCHEDULED", "IN_PROGRESS"):
            t["session_status"] = "CANCELLED"
            touch(t)
    for pkg in children("packages", "cell_project_id", project["id"]):
        if pkg["package_status"] in ("QUOTED", "ORDERED"):
            pkg["package_status"] = "SUPERSEDED"
            touch(pkg)
    for m in children("plans", "cell_project_id", project["id"]):
        if m["plan_status"] == "ACTIVE":
            m["plan_status"] = "CLOSED"
            touch(m)


# ---------------------------------------------------------------- computed fields
def compute_forecast(pkg, site):
    pkg["forecast_consumption_months"] = calc.spare_forecast(
        pkg["recommended_coverage_months"], site["shift_windows_per_day"]
    )


def compute_hours_until_due(plan):
    plan["hours_until_due"] = calc.hours_until_due(
        plan["first_due_at_hours"], plan["interval_operating_hours"],
        plan["current_operating_hours"],
    )
