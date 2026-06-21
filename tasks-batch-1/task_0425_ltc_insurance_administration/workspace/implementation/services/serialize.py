"""Entity -> response-body serialization. Computes derived fields on read."""
from db import STORE
from services import calc


# --- Derived / computed helpers ---------------------------------------------

def policy_benefits_triggered(policy_id):
    """True iff the latest BenefitTriggerCertification for the policy is CERTIFIED."""
    certs = [c for c in STORE.trigger_certifications.values() if c["policy_id"] == policy_id]
    if not certs:
        return False
    certs.sort(key=lambda c: c["_seq"])
    return certs[-1]["decision"] == "CERTIFIED"


def policy_elimination_days_satisfied(policy):
    """Distinct qualifying service dates across APPROVED claims, capped at
    elimination_period_days (PRD §3.9)."""
    policy_id = policy["id"]
    approved_claim_ids = {
        c["id"] for c in STORE.claims.values()
        if c["policy_id"] == policy_id and c["status"] == "APPROVED"
    }
    days = set()
    for line in STORE.claim_lines.values():
        if line["claim_id"] in approved_claim_ids and line["is_qualifying_day"] is True:
            days.add(line["service_date"])
    return min(len(days), int(policy["elimination_period_days"]))


def policy_inflated_daily(policy):
    return calc.grow(policy["daily_benefit_max_cents"], policy["inflation_rider"],
                     policy["inflation_years_elapsed"])


def policy_inflated_monthly(policy):
    return calc.grow(policy["monthly_benefit_max_cents"], policy["inflation_rider"],
                     policy["inflation_years_elapsed"])


def pool_inflated_pool_cents(policy, pool):
    """Grown lifetime pool less any nonforfeiture reduction (PRD §3.12)."""
    grown = calc.grow(policy["initial_pool_cents"], policy["inflation_rider"],
                      policy["inflation_years_elapsed"])
    return grown - pool["nonforfeiture_reduction_cents"]


def pool_lifetime_paid_cents(policy_id):
    total = 0
    for e in STORE.ledger_entries.values():
        if e["policy_id"] == policy_id and e["source_kind"] == "CLAIM_PAYMENT":
            total += abs(e["amount_cents"])
    return total


# --- Serializers -------------------------------------------------------------

def policyholder(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "state_code": p["state_code"],
        "date_of_birth": p["date_of_birth"],
        "medicaid_state_eligible": p["medicaid_state_eligible"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def policy(p):
    return {
        "id": p["id"],
        "policyholder_id": p["policyholder_id"],
        "product_mode": p["product_mode"],
        "daily_benefit_max_cents": p["daily_benefit_max_cents"],
        "monthly_benefit_max_cents": p["monthly_benefit_max_cents"],
        "initial_pool_cents": p["initial_pool_cents"],
        "inflation_rider": p["inflation_rider"],
        "elimination_period_days": p["elimination_period_days"],
        "is_partnership_policy": p["is_partnership_policy"],
        "inflation_years_elapsed": p["inflation_years_elapsed"],
        "inflated_daily_max_cents": policy_inflated_daily(p),
        "inflated_monthly_max_cents": policy_inflated_monthly(p),
        "coverage_status": p["coverage_status"],
        "premium_status": p["premium_status"],
        "benefits_triggered": policy_benefits_triggered(p["id"]),
        "elimination_days_satisfied": policy_elimination_days_satisfied(p),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def benefit_pool(pool):
    pol = STORE.policies[pool["policy_id"]]
    inflated = pool_inflated_pool_cents(pol, pool)
    lifetime = pool_lifetime_paid_cents(pool["policy_id"])
    remaining = inflated - lifetime
    if remaining < 0:
        remaining = 0
    return {
        "id": pool["id"],
        "policy_id": pool["policy_id"],
        "inflated_pool_cents": inflated,
        "lifetime_paid_cents": lifetime,
        "nonforfeiture_reduction_cents": pool["nonforfeiture_reduction_cents"],
        "remaining_pool_cents": remaining,
        "created_at": pool["created_at"],
        "updated_at": pool["updated_at"],
        "version": pool["version"],
    }


def premium_invoice(inv):
    return {
        "id": inv["id"],
        "policy_id": inv["policy_id"],
        "period_index": inv["period_index"],
        "amount_cents": inv["amount_cents"],
        "due_date": inv["due_date"],
        "grace_deadline": inv["grace_deadline"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def rate_filing(f):
    return {
        "id": f["id"],
        "policy_id": f["policy_id"],
        "requested_increase_pct": f["requested_increase_pct"],
        "approved_increase_pct": f["approved_increase_pct"],
        "effective_period_index": f["effective_period_index"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def trigger_certification(c):
    # Append-only event: id + created_at only (PRD §2.4)
    return {
        "id": c["id"],
        "policy_id": c["policy_id"],
        "adl_deficiencies": c["adl_deficiencies"],
        "cognitive_impairment": c["cognitive_impairment"],
        "decision": c["decision"],
        "assessed_by_id": c["assessed_by_id"],
        "supersedes_id": c["supersedes_id"],
        "created_at": c["created_at"],
    }


def provider(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "provider_type": p["provider_type"],
        "state_code": p["state_code"],
        "license_active": p["license_active"],
        "eligibility_status": p["eligibility_status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def care_plan(cp):
    return {
        "id": cp["id"],
        "policy_id": cp["policy_id"],
        "provider_id": cp["provider_id"],
        "care_setting": cp["care_setting"],
        "authored_by_id": cp["authored_by_id"],
        "status": cp["status"],
        "created_at": cp["created_at"],
        "updated_at": cp["updated_at"],
        "version": cp["version"],
    }


def claim(c):
    return {
        "id": c["id"],
        "policy_id": c["policy_id"],
        "care_plan_id": c["care_plan_id"],
        "service_month": c["service_month"],
        "month_paid_cents": c["month_paid_cents"],
        "requires_reassessment": c["requires_reassessment"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def claim_line(l):
    return {
        "id": l["id"],
        "claim_id": l["claim_id"],
        "service_date": l["service_date"],
        "billed_charge_cents": l["billed_charge_cents"],
        "is_qualifying_day": l["is_qualifying_day"],
        "elimination_applied": l["elimination_applied"],
        "benefit_paid_cents": l["benefit_paid_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ledger_entry(e):
    # Append-only event: id + created_at only (PRD §2.4)
    return {
        "id": e["id"],
        "policy_id": e["policy_id"],
        "claim_id": e["claim_id"],
        "source_kind": e["source_kind"],
        "amount_cents": e["amount_cents"],
        "created_at": e["created_at"],
    }


def partnership_disregard(pd):
    return {
        "id": pd["id"],
        "policy_id": pd["policy_id"],
        "protected_asset_cents": pd["protected_asset_cents"],
        "disregard_status": pd["disregard_status"],
        "created_at": pd["created_at"],
        "updated_at": pd["updated_at"],
        "version": pd["version"],
    }
