"""Derived fields, capacity reconciliation and the transitive cascades."""
from datetime import timedelta
from decimal import Decimal

import calc
from db import bump, db, order_key, sorted_records
from util import add_days, dec, rhu3

CONTRIBUTING_EXECUTION_STATUSES = ("EXECUTED", "TERMINATION_NOTICED")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def tower_ground_leases(tower_id):
    return sorted_records([g for g in db.ground_leases.values() if g["tower_id"] == tower_id])


def active_ground_lease(tower_id):
    for lease in tower_ground_leases(tower_id):
        if lease["status"] == "ACTIVE":
            return lease
    return None


def tower_projects(tower_id):
    return sorted_records([p for p in db.projects.values() if p["tower_id"] == tower_id])


def tower_applications(tower_id):
    return sorted_records([a for a in db.applications.values() if a["tower_id"] == tower_id])


def tower_amendments(tower_id):
    return sorted_records([a for a in db.amendments.values() if a["tower_id"] == tower_id])


def contributing_amendments(tower_id):
    return [a for a in tower_amendments(tower_id)
            if a["execution_status"] in CONTRIBUTING_EXECUTION_STATUSES]


def application_lines(application_id):
    return sorted_records([l for l in db.equipment_lines.values()
                           if l["colocation_application_id"] == application_id])


def application_analyses(application_id):
    return sorted_records([a for a in db.analyses.values()
                           if a["colocation_application_id"] == application_id])


def mla_applications(mla_id):
    return sorted_records([a for a in db.applications.values()
                           if a["master_lease_agreement_id"] == mla_id])


def tenant_mlas(tenant_id):
    return sorted_records([m for m in db.mlas.values() if m["tenant_id"] == tenant_id])


def project_shares(project_id):
    return sorted_records([s for s in db.cost_shares.values()
                           if s["modification_project_id"] == project_id])


def audit_findings(audit_id):
    return sorted_records([f for f in db.findings.values()
                           if f["equipment_audit_id"] == audit_id])


def amendment_for_application(application_id):
    matches = [a for a in db.amendments.values()
               if a["colocation_application_id"] == application_id]
    return sorted_records(matches)[0] if matches else None


def application_tenant(application):
    mla = db.mlas.get(application["master_lease_agreement_id"])
    return db.tenants.get(mla["tenant_id"]) if mla else None


def amendment_tenant(amendment):
    mla = db.mlas.get(amendment["master_lease_agreement_id"])
    return db.tenants.get(mla["tenant_id"]) if mla else None


# ---------------------------------------------------------------------------
# Tower reconciliation (PRD 2.7)
# ---------------------------------------------------------------------------

def tower_reserved_load_units(tower):
    total = dec(tower["baseline_reserved_load_units"])
    for amendment in contributing_amendments(tower["id"]):
        total += dec(amendment["reserved_load_units"])
    return rhu3(total)


def tower_reserved_ground_space(tower):
    total = dec(tower["baseline_reserved_ground_sqft"])
    for amendment in contributing_amendments(tower["id"]):
        total += dec(amendment["ground_space_sqft"])
    return total


def tower_available_ground_space(tower):
    return dec(tower["ground_space_total_sqft"]) - tower_reserved_ground_space(tower)


def tower_reserved_load_pct(tower):
    return calc.loading_pct(tower_reserved_load_units(tower), tower["rated_capacity_load_units"])


def tower_open_review_count(tower):
    return len([a for a in tower_applications(tower["id"])
                if a["status"] == "UNDER_STRUCTURAL_REVIEW"])


def tower_capacity_hold_count(tower):
    return len([a for a in tower_applications(tower["id"]) if a["status"] == "CAPACITY_HOLD"])


def tower_occupied_bands(tower):
    entries = []
    for amendment in contributing_amendments(tower["id"]):
        mla = db.mlas.get(amendment["master_lease_agreement_id"])
        entries.append((
            dec(amendment["elevation_bottom_ft"]),
            order_key(amendment),
            {
                "amendment_id": amendment["id"],
                "bottom_ft": amendment["elevation_bottom_ft"],
                "top_ft": amendment["elevation_top_ft"],
                "tenant_id": mla["tenant_id"] if mla else None,
            },
        ))
    entries.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in entries]


def tower_capacity_posture(tower):
    tower_id = tower["id"]
    for lease in tower_ground_leases(tower_id):
        if lease["status"] == "EXPIRED":
            return "FROZEN"
    for project in tower_projects(tower_id):
        if project["status"] in ("FUNDED", "IN_CONSTRUCTION"):
            return "FROZEN"
    if (tower_reserved_load_pct(tower) > calc.RESTRICTED_LOAD_PCT
            or tower_available_ground_space(tower) <= 0):
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# Posture-driven application cascades (PRD 3.5)
# ---------------------------------------------------------------------------

def supersede_live_analyses(application):
    for analysis in application_analyses(application["id"]):
        if analysis["status"] in ("ISSUED", "QUOTED"):
            analysis["status"] = "SUPERSEDED"
            bump(analysis)


def stamp_review_window(application):
    application["submitted_at"] = db.clock
    application["review_deadline_at"] = review_deadline_for(application)
    application["_analysis_since_entry"] = False


def review_deadline_for(application):
    mla = db.mlas.get(application["master_lease_agreement_id"])
    days = calc.STANDARD_REVIEW_DAYS
    if application.get("expedited_requested") and mla and mla.get("expedited_review_days") is not None:
        days = mla["expedited_review_days"]
    submitted_at = application.get("submitted_at")
    if submitted_at is None:
        return None
    return submitted_at + timedelta(days=int(days))


def freeze_pushback(tower):
    """A posture recomputed to FROZEN pushes every reviewing application back."""
    if tower_capacity_posture(tower) != "FROZEN":
        return
    for application in tower_applications(tower["id"]):
        if application["status"] == "UNDER_STRUCTURAL_REVIEW":
            application["status"] = "CAPACITY_HOLD"
            bump(application)


def promote_if_open(tower):
    """A posture-clearing event promotes exactly one held application."""
    if tower_capacity_posture(tower) != "OPEN":
        return None
    held = [a for a in tower_applications(tower["id"]) if a["status"] == "CAPACITY_HOLD"]
    if not held:
        return None
    winner = sorted(held, key=lambda a: (
        a["created_at"],
        dec(a["requested_ground_space_sqft"]),
        dec(a["requested_elevation_bottom_ft"]),
        a["_seq"],
    ))[0]
    winner["status"] = "UNDER_STRUCTURAL_REVIEW"
    stamp_review_window(winner)
    supersede_live_analyses(winner)
    bump(winner)
    return winner


# ---------------------------------------------------------------------------
# Tenant receivables and the arrears interlock (PRD 2.12)
# ---------------------------------------------------------------------------

def credit_status_for(tenant):
    return ("DELINQUENT" if tenant["outstanding_balance_cents"] >= calc.DELINQUENCY_THRESHOLD_CENTS
            else "CURRENT")


def application_privilege_for(mla):
    tenant = db.tenants.get(mla["tenant_id"])
    if mla["status"] == "EXPIRED":
        return "SUSPENDED"
    if tenant is not None and credit_status_for(tenant) == "DELINQUENT":
        return "SUSPENDED"
    return "ENABLED"


def executed_amendment_count(mla):
    return len([a for a in db.amendments.values()
                if a["master_lease_agreement_id"] == mla["id"]
                and a["execution_status"] == "EXECUTED"])


def suspend_tenant_privileges(tenant):
    for mla in tenant_mlas(tenant["id"]):
        if mla["status"] != "ACTIVE":
            continue
        bump(mla)
        for application in mla_applications(mla["id"]):
            if application["status"] in ("SUBMITTED", "UNDER_STRUCTURAL_REVIEW"):
                application["status"] = "ON_HOLD"
                bump(application)


def enable_tenant_privileges(tenant):
    for mla in tenant_mlas(tenant["id"]):
        if mla["status"] != "ACTIVE":
            continue
        bump(mla)
        unhold_applications(mla)


def unhold_applications(mla):
    for application in mla_applications(mla["id"]):
        if application["status"] == "ON_HOLD":
            application["status"] = "SUBMITTED"
            stamp_review_window(application)
            bump(application)


def adjust_tenant_balance(tenant, delta_cents):
    """Move a tenant balance and run the credit / privilege / hold cascade."""
    if delta_cents == 0:
        return
    before = credit_status_for(tenant)
    tenant["outstanding_balance_cents"] += int(delta_cents)
    bump(tenant)
    after = credit_status_for(tenant)
    if before == after:
        return
    if after == "DELINQUENT":
        suspend_tenant_privileges(tenant)
    else:
        enable_tenant_privileges(tenant)


# ---------------------------------------------------------------------------
# Derived money reads
# ---------------------------------------------------------------------------

def ground_lease_current_rent(lease, as_of=None):
    return calc.ground_lease_rent_at(
        lease["base_monthly_rent_cents"],
        lease["escalator_pct"],
        lease["commencement_date"],
        as_of if as_of is not None else db.clock,
    )


def amendment_current_rent(amendment, as_of=None):
    return calc.amendment_rent_at(
        amendment["base_monthly_rent_cents"],
        amendment["escalator_pct"],
        amendment["effective_date"],
        as_of if as_of is not None else db.clock,
    )


def application_total_load_units(application):
    total = Decimal(0)
    for line in application_lines(application["id"]):
        total += dec(line["load_units"])
    return rhu3(total)


def newest_live_analysis(application_id):
    live = [a for a in application_analyses(application_id) if a["status"] != "SUPERSEDED"]
    if not live:
        return None
    return sorted(live, key=order_key)[-1]


def has_structural_clearance(application):
    for analysis in application_analyses(application["id"]):
        if analysis["status"] != "SUPERSEDED" and analysis["result"] == "PASS":
            return True
    newest = newest_live_analysis(application["id"])
    if newest is not None:
        for project in db.projects.values():
            if project["status"] == "CERTIFIED" and project["originating_analysis_id"] == newest["id"]:
                return True
    return False


def project_allocated_cents(project):
    total = 0
    for share in project_shares(project["id"]):
        if share["status"] in ("PENDING", "ACCEPTED", "BILLED"):
            total += share["share_cents"]
    return total


def audit_retro_total(audit):
    return sum(f["retroactive_billing_cents"] for f in audit_findings(audit["id"]))


def renewal_window_open(lease, as_of=None):
    as_of = as_of if as_of is not None else db.clock
    return as_of.date() >= add_days(lease["term_end_date"], -calc.RENEWAL_WINDOW_DAYS).date()
