"""Coverage-year ledger (scaffold §1.3 policy_year_ledger / PRD §3.7).

On every APPROVE we re-attribute the WHOLE covering PolicyYear from scratch in
incident_date order; WELLNESS claims draw the separate wellness allowance bucket
and never enter the deductible/cap ledger.
"""
from __future__ import annotations

from decimal import Decimal

import db
from services.calculations import WELLNESS_ALLOWANCE_CENTS
from services.common import round_half_up


def find_covering_policy_year(policy_id: str, incident_iso: str):
    """Return the PolicyYear whose [period_start, period_end) contains incident_date,
    or None. Half-open: period_start inclusive, period_end exclusive.
    """
    incident = db.parse_iso_dt(incident_iso)
    for py in db.policy_years.values():
        if py.get("policy_id") != policy_id:
            continue
        start = db.parse_iso_dt(py["period_start"])
        end = db.parse_iso_dt(py["period_end"])
        if start <= incident < end:
            return py
    return None


def _ledger_set(policy: dict, policy_year: dict, this_claim: dict):
    """Non-wellness APPROVED/PAID claims of the covering year, plus this claim if
    non-wellness. Sorted by (incident_date ASC, created_at ASC) — never id.
    """
    members = []
    for c in db.claims.values():
        if c["id"] == this_claim["id"]:
            continue
        if c.get("policy_id") != policy["id"]:
            continue
        if c.get("claim_type") == "WELLNESS":
            continue
        if c.get("status") not in ("APPROVED", "PAID"):
            continue
        # must belong to the same covering policy-year
        cpy = find_covering_policy_year(policy["id"], c["incident_date"])
        if cpy is None or cpy["id"] != policy_year["id"]:
            continue
        members.append(c)
    if this_claim.get("claim_type") != "WELLNESS":
        members.append(this_claim)
    members.sort(
        key=lambda c: (
            db.parse_iso_dt(c["incident_date"]),
            c.get("created_at", ""),
            c.get("_seq", 0),
        )
    )
    return members


def reattribute(policy: dict, policy_year: dict, this_claim: dict) -> None:
    """Re-attribute the covering PolicyYear from scratch, writing each member
    claim's deductible_applied_cents and reimbursed_cents, then reconcile the
    PolicyYear accumulators. Mutates `this_claim` payable fields too.
    """
    rate = Decimal(policy["reimbursement_rate_bps"]) / Decimal(10000)
    members = _ledger_set(policy, policy_year, this_claim)

    ded_used = 0
    reimb_used = 0
    for c in members:
        eligible = c.get("eligible_amount_cents") or 0
        remaining_ded = max(0, policy["annual_deductible_cents"] - ded_used)
        c["deductible_applied_cents"] = min(remaining_ded, eligible)
        post_ded = eligible - c["deductible_applied_cents"]
        raw_reimb = round_half_up(Decimal(post_ded) * rate)
        remaining_cap = max(0, policy["annual_cap_cents"] - reimb_used)
        c["reimbursed_cents"] = min(raw_reimb, remaining_cap)
        c["wellness_paid_cents"] = 0
        ded_used += c["deductible_applied_cents"]
        reimb_used += c["reimbursed_cents"]

    # WELLNESS claims: separate bucket, never in the deductible/cap ledger.
    if this_claim.get("claim_type") == "WELLNESS":
        this_claim["deductible_applied_cents"] = 0
        this_claim["reimbursed_cents"] = 0
        remaining_wellness = max(
            0, WELLNESS_ALLOWANCE_CENTS - (policy_year.get("wellness_used_cents") or 0)
        )
        this_claim["wellness_paid_cents"] = min(
            this_claim.get("eligible_amount_cents") or 0, remaining_wellness
        )

    reconcile_policy_year(policy, policy_year)


def reconcile_policy_year(policy: dict, policy_year: dict) -> None:
    """Recompute PY accumulators from its APPROVED/PAID claims.

    deductible_met_cents / reimbursed_cents from non-wellness ledger claims;
    wellness_used_cents from wellness claims. reimbursed_cents capped at the
    policy's annual_cap_cents.
    """
    ded = 0
    reimb = 0
    wellness = 0
    for c in db.claims.values():
        if c.get("policy_id") != policy["id"]:
            continue
        if c.get("status") not in ("APPROVED", "PAID"):
            continue
        cpy = find_covering_policy_year(policy["id"], c["incident_date"])
        if cpy is None or cpy["id"] != policy_year["id"]:
            continue
        if c.get("claim_type") == "WELLNESS":
            wellness += c.get("wellness_paid_cents") or 0
        else:
            ded += c.get("deductible_applied_cents") or 0
            reimb += c.get("reimbursed_cents") or 0

    policy_year["deductible_met_cents"] = ded
    policy_year["reimbursed_cents"] = min(reimb, policy["annual_cap_cents"])
    policy_year["wellness_used_cents"] = wellness
