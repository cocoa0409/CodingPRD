"""Contract-term + service-credit domain logic (PRD §3.3, §3.4, §3.7, §3.9)."""
from datetime import timedelta

from db import db, now_iso, clock_now
from common import stamp_new


def grant_term_credits(term, plan_id):
    """compute_entitlement_grant (PRD §3.4 / scaffold §1.3).

    Forward-looking valuation of the bundle at term start. Considers only ACTIVE
    PlanService rows of the term's plan, ordered by service_code ascending, and
    ignores any retired inclusion line. Creates one ServiceCredit bucket per
    line. Sets term.entitlement_granted_cents / _consumed_cents / _balance_cents.
    """
    lines = [
        ps for ps in db.plan_services.values()
        if ps["plan_id"] == plan_id and ps["status"] == "ACTIVE"
    ]
    lines.sort(key=lambda ps: ps["service_code"])

    granted_cents = 0
    for ps in lines:
        qty = ps["included_quantity"]
        bucket = {
            "contract_term_id": term["id"],
            "service_code": ps["service_code"],
            "granted_quantity": qty,
            "consumed_quantity": 0,
            "unit_value_cents": ps["unit_value_cents"],
            # OPEN if granted > 0 else EXHAUSTED (PRD §3.4).
            "status": "OPEN" if qty > 0 else "EXHAUSTED",
        }
        stamp_new(bucket)
        db.service_credits[bucket["id"]] = bucket
        granted_cents += qty * ps["unit_value_cents"]

    term["entitlement_granted_cents"] = granted_cents
    term["entitlement_consumed_cents"] = 0
    term["entitlement_balance_cents"] = granted_cents


def reconcile_term_balance(term):
    """reconcile_term_balance (PRD §3.7 / scaffold §1.3).

    entitlement_consumed_cents = sum over ALL buckets of the term (regardless of
    status — FORFEITED buckets keep their consumed_quantity) of
    consumed_quantity * unit_value_cents. balance = granted - consumed.
    """
    consumed = 0
    for c in db.service_credits.values():
        if c["contract_term_id"] == term["id"]:
            consumed += c["consumed_quantity"] * c["unit_value_cents"]
    term["entitlement_consumed_cents"] = consumed
    term["entitlement_balance_cents"] = term["entitlement_granted_cents"] - consumed


def term_credits(term_id):
    return [c for c in db.service_credits.values()
            if c["contract_term_id"] == term_id]


def active_term_for_membership(membership_id):
    """Resolve the membership's currently-ACTIVE ContractTerm, if any."""
    for t in db.contract_terms.values():
        if t["membership_id"] == membership_id and t["status"] == "ACTIVE":
            return t
    return None


def create_term(membership, plan_id, term_index, starts_at):
    """Create a ContractTerm (system fields) and grant its credit buckets."""
    ends_at = starts_at + timedelta(days=365)
    term = {
        "membership_id": membership["id"],
        "plan_id": plan_id,
        "term_index": term_index,
        "starts_at": _iso(starts_at),
        "ends_at": _iso(ends_at),
        "entitlement_granted_cents": 0,
        "entitlement_consumed_cents": 0,
        "entitlement_balance_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(term)
    db.contract_terms[term["id"]] = term
    grant_term_credits(term, plan_id)
    return term


def _iso(dt):
    from db import iso
    return iso(dt)
