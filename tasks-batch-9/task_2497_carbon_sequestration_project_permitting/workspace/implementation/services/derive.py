"""Derived-field recomputation chains and cascade side effects.

PRD Section 3.8 pins the evaluation order and states that "every step reads the
*stored* output of the previous step rather than re-deriving it", so every
project-level figure below is a stored value refreshed only by the triggers the
PRD names.  The single exception is ``pisc_elapsed_years``, which Section 3.9
says "is recomputed on every read of the project rather than being written by any
mutation".
"""

from decimal import Decimal as D

import clock
import db
from errors import ApiError
from services import calc

PROJECT_FROZEN = "FROZEN"
INJECTION_STATUSES = ("INJECTION_AUTHORIZED", "INJECTION_ACTIVE")


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #


def governing_model(project):
    """The project's stored governing model (the one whose status is ACCEPTED)."""
    model_id = project.get("governing_geologic_model_id")
    if not model_id:
        return None
    return db.geologic_models.get(model_id)


def effective_rate(project):
    model = governing_model(project)
    if model is None:
        return D("0")
    return D(model["effective_injection_rate_tpy"])


def best_plan_coverage(project):
    approved = [
        p
        for p in db.plans_of(project["id"])
        if p["status"] in ("APPROVED", "APPROVED_WITH_CONDITIONS")
    ]
    if not approved:
        return D("0.00")
    best = approved[0]
    for plan in approved[1:]:
        if plan["coverage_score"] > best["coverage_score"]:
            best = plan
    return D(best["coverage_score"])


# --------------------------------------------------------------------------- #
# Recomputation chains
# --------------------------------------------------------------------------- #


def recompute_pore_space(project):
    """secured_acreage, outstanding_acreage, pore_space_consent_pct, bonus total."""
    holders = [
        t for t in db.tracts_of(project["id"]) if t["lease_status"] in calc.CONSENT_HOLDER_STATUSES
    ]
    secured = calc.q4(sum((t["net_acreage"] for t in holders), D("0")))
    total = D(project["total_project_acreage"])
    project["secured_acreage"] = secured
    project["outstanding_acreage"] = calc.q4(total - secured)
    project["pore_space_consent_pct"] = (
        calc.q2(D("100.0") * secured / total) if total > 0 else D("0.00")
    )
    project["pore_space_bonus_total_usd"] = calc.q2(
        sum((t["bonus_settlement_usd"] for t in holders), D("0"))
    )


def recompute_ca_completion(project):
    project["corrective_action_completion_pct"] = calc.ca_completion_pct(
        db.wellbores_of(project["id"])
    )


def recompute_required_assurance(project, posture=True):
    """Requirement, then the coverage re-comparison, then the possible posture move."""
    buckets = assurance_buckets(project)
    project["required_financial_assurance_usd"] = buckets["required"]
    recompute_coverage_status(project, posture=posture)


def assurance_buckets(project):
    return calc.assurance_buckets(
        project,
        db.wellbores_of(project["id"]),
        db.permits_of(project["id"]),
        effective_rate(project),
    )


def recompute_allocated_assurance(project, posture=True):
    project["allocated_assurance_usd"] = calc.q2(
        sum(
            (
                i["allocated_ca_usd"]
                + i["allocated_plugging_usd"]
                + i["allocated_pisc_usd"]
                + i["allocated_emergency_usd"]
                for i in db.instruments_of(project["id"])
                if i["status"] == "ALLOCATED"
            ),
            D("0"),
        )
    )
    recompute_coverage_status(project, posture=posture)


def recompute_coverage_status(project, posture=True):
    project["assurance_coverage_status"] = calc.coverage_status(
        project["allocated_assurance_usd"], project["required_financial_assurance_usd"]
    )
    if posture:
        apply_posture(project)


def apply_posture(project):
    """PRD 2.9 — UNDERFUNDED while injecting moves OPEN -> RESTRICTED."""
    if project["operational_posture"] == PROJECT_FROZEN:
        return
    if (
        project["assurance_coverage_status"] == "UNDERFUNDED"
        and project["operational_posture"] == "OPEN"
        and project["status"] in INJECTION_STATUSES
    ):
        project["operational_posture"] = "RESTRICTED"
        db.touch(project)
    elif (
        project["operational_posture"] == "RESTRICTED"
        and project["assurance_coverage_status"] == "FUNDED"
        and project["open_remediation_count"] == 0
    ):
        project["operational_posture"] = "OPEN"
        db.touch(project)


def recompute_ledger(project):
    project["cumulative_stored_tonnes"] = calc.cumulative_stored(
        db.periods_of_project(project["id"])
    )


def recompute_pending_credit(project):
    project["pending_credit_usd"] = calc.q2(
        sum(
            (
                c["credit_amount_usd"]
                for c in db.claims_of(project["id"])
                if c["status"] in ("SUBMITTED", "ALLOWED")
            ),
            D("0"),
        )
    )


def recompute_open_remediation_count(project):
    project["open_remediation_count"] = len(
        [o for o in db.orders_of(project["id"]) if o["status"] == "OPEN"]
    )


def refresh_pisc_elapsed(project):
    project["pisc_elapsed_years"] = calc.pisc_elapsed_years(
        project.get("pisc_start_dt"), clock.now()
    )


def recompute_pisc_duration(project):
    model = governing_model(project)
    project["pisc_duration_years"] = calc.pisc_duration(
        project.get("alternative_timeframe_years"),
        model["seal_classification"] if model else None,
        best_plan_coverage(project),
    )


def refresh_tract(tract):
    tract["net_acreage"] = calc.tract_net_acreage(tract)
    tract["bonus_settlement_usd"] = calc.tract_bonus_settlement(tract)


def refresh_plan(plan):
    sub, surf, atm, coverage = calc.plan_scores(db.methods_of(plan["id"]))
    plan["subsurface_subscore"] = sub
    plan["surface_subscore"] = surf
    plan["atmospheric_subscore"] = atm
    plan["coverage_score"] = coverage


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


def require_not_frozen(project):
    """PRD 2.9 rank 8 — the posture gate outranks every per-entity state check."""
    if project is not None and project["operational_posture"] == PROJECT_FROZEN:
        raise ApiError("ERR_PROJECT_POSTURE_FROZEN", "project operational posture is FROZEN")


# --------------------------------------------------------------------------- #
# Cascades
# --------------------------------------------------------------------------- #


def suspension_cascade(project):
    """PRD 3.6 — suspend ACTIVE permits, then revert SUBMITTED claims to DRAFT."""
    for permit in db.permits_of(project["id"]):
        if permit["permit_status"] == "ACTIVE":
            permit["permit_status"] = "SUSPENDED"
            permit["authorized_injection_rate_tpy"] = D("0")
            db.touch(permit)
    reverted = False
    for claim in db.claims_of(project["id"]):
        if claim["status"] == "SUBMITTED":
            claim["status"] = "DRAFT"
            db.touch(claim)
            reverted = True
    if reverted:
        recompute_pending_credit(project)


def restore_cascade(project):
    """PRD 3.6 — restore SUSPENDED permits once the last open order clears."""
    if project["status"] != "INJECTION_ACTIVE":
        return
    rate = effective_rate(project)
    for permit in db.permits_of(project["id"]):
        if permit["permit_status"] == "SUSPENDED":
            permit["permit_status"] = "ACTIVE"
            permit["authorized_injection_rate_tpy"] = rate
            db.touch(permit)


def screen_wellbore_for_ca(wellbore):
    """PRD 3.3 — a newly IDENTIFIED wellbore auto-escalates to CA_REQUIRED."""
    if wellbore["penetrates_seal"] or wellbore["risk_score"] >= calc.CA_REQUIRED_RISK_THRESHOLD:
        wellbore["corrective_action_status"] = "CA_REQUIRED"


def rescore_wellbore(wellbore, project):
    risk, cost = calc.wellbore_risk(wellbore, project["aor_radius_km"])
    changed = wellbore["risk_score"] != risk or wellbore["ca_cost_estimate_usd"] != cost
    wellbore["risk_score"] = risk
    wellbore["ca_cost_estimate_usd"] = cost
    return changed


# --------------------------------------------------------------------------- #
# Tax-credit helpers
# --------------------------------------------------------------------------- #


def tax_year_window(tax_year):
    start = clock.parse_iso("%04d-01-01T00:00:00Z" % int(tax_year))
    end = clock.parse_iso("%04d-01-01T00:00:00Z" % (int(tax_year) + 1))
    return start, end


def records_in_tax_year(project, tax_year):
    start, end = tax_year_window(tax_year)
    return [
        r
        for r in db.periods_of_project(project["id"])
        if r["status"] == "ACCEPTED"
        and r["period_start_dt"] >= start
        and r["period_end_dt"] <= end
    ]


def record_in_tax_year(record, tax_year):
    start, end = tax_year_window(tax_year)
    return record["period_start_dt"] >= start and record["period_end_dt"] <= end


def recompute_claim(claim, project):
    """PRD 3.9 tax_credit_amount — all four derived claim figures."""
    records = records_in_tax_year(project, claim["tax_year"])
    reported, verified, rate, amount = calc.claim_figures(
        records,
        claim["lca_upstream_emissions_factor"],
        project["cumulative_stored_tonnes"],
        claim["claim_variant"],
    )
    changed = (
        claim.get("reported_tonnes") != reported
        or claim.get("verified_tonnes") != verified
        or claim.get("credit_rate_usd_per_tonne") != rate
        or claim.get("credit_amount_usd") != amount
    )
    claim["reported_tonnes"] = reported
    claim["verified_tonnes"] = verified
    claim["credit_rate_usd_per_tonne"] = rate
    claim["credit_amount_usd"] = amount
    return changed
