"""Calculation primitives. SCAFFOLD §1.3."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import db


# ---------------------------------------------------------------------------
# gross_estate_value
# ---------------------------------------------------------------------------

def compute_gross_estate(estate_id: str) -> int:
    """Sum appraised_value_cents over Assets in INCLUDED status, iterated by created_at ASC."""
    assets = [a for a in db.assets.values() if a["estate_id"] == estate_id and a["status"] == "INCLUDED"]
    assets.sort(key=lambda a: a["created_at"])
    return sum(a["appraised_value_cents"] for a in assets)


def recompute_and_store_gross(estate: dict) -> None:
    estate["gross_estate_value_cents"] = compute_gross_estate(estate["id"])


# ---------------------------------------------------------------------------
# net_taxable_estate
# ---------------------------------------------------------------------------

def select_net_variant(estate: dict) -> str:
    if estate["status"] in ("ADMINISTRATION", "CLOSED") and estate.get("inventory_snapshot_gross_cents") is not None:
        return "final"
    return "provisional"


def compute_net_taxable(estate: dict) -> dict:
    """Returns the full breakdown so endpoints can return the same structure."""
    variant = select_net_variant(estate)
    if variant == "provisional":
        gross_used = estate["gross_estate_value_cents"]
    else:
        gross_used = estate["inventory_snapshot_gross_cents"]
        if gross_used is None:
            gross_used = estate["gross_estate_value_cents"]

    exempt_cents = sum(
        a["appraised_value_cents"]
        for a in db.assets.values()
        if a["estate_id"] == estate["id"]
        and a["status"] == "INCLUDED"
        and a["category"] == "RETIREMENT_IRA"
    )

    allowed_claims_total = sum(
        c["amount_cents"]
        for c in db.creditor_claims.values()
        if c["estate_id"] == estate["id"] and c["status"] in ("ALLOWED", "PAID")
    )

    net = max(0, gross_used - exempt_cents - allowed_claims_total)
    return {
        "gross_estate_value_cents": gross_used,
        "exempt_cents": exempt_cents,
        "allowed_claims_total_cents": allowed_claims_total,
        "net_taxable_estate_cents": net,
        "variant": variant,
    }


def recompute_and_store_net(estate: dict) -> None:
    estate["net_taxable_estate_cents"] = compute_net_taxable(estate)["net_taxable_estate_cents"]
    estate["_net_taxable_has_run"] = True


# ---------------------------------------------------------------------------
# creditor_payment_waterfall
# ---------------------------------------------------------------------------

CLASS_PRIORITY = {"SECURED": 1, "ADMIN": 2, "FUNERAL": 3, "TAX": 4, "UNSECURED": 5}


def _close_estate_draft_exists(estate_id: str) -> bool:
    return any(
        o["estate_id"] == estate_id and o["order_type"] == "CLOSE_ESTATE" and o["status"] == "DRAFT"
        for o in db.probate_orders.values()
    )


def _claims_for_estate_allowed(estate_id: str) -> list:
    return [c for c in db.creditor_claims.values() if c["estate_id"] == estate_id and c["status"] == "ALLOWED"]


def waterfall_pay(estate: dict, target_claim: dict) -> Optional[int]:
    """Determine how many cents the target claim is entitled to under current state.

    Returns the integer cents payable to the target, or None if there are
    insufficient funds (caller should raise ERR_INSUFFICIENT_ESTATE_FUNDS).
    """
    estate_id = estate["id"]
    already_paid_total = sum(
        c["paid_amount_cents"]
        for c in db.creditor_claims.values()
        if c["estate_id"] == estate_id and c["status"] == "PAID"
    )

    if _close_estate_draft_exists(estate_id):
        return _waterfall_pro_rata(estate, target_claim, already_paid_total)
    return _waterfall_priority_full(estate, target_claim, already_paid_total)


def _waterfall_priority_full(estate: dict, target_claim: dict, already_paid_total: int) -> Optional[int]:
    estate_id = estate["id"]
    remaining = estate["gross_estate_value_cents"] - already_paid_total

    for cls in ("SECURED", "ADMIN", "FUNERAL", "TAX", "UNSECURED"):
        claims_in_class = [c for c in _claims_for_estate_allowed(estate_id) if c["claim_class"] == cls]
        claims_in_class.sort(key=lambda c: (c["created_at"], c["amount_cents"]))
        for c in claims_in_class:
            if c["id"] != target_claim["id"]:
                consumption = min(remaining, c["amount_cents"])
                remaining -= consumption
                continue
            # Target claim reached
            if remaining <= 0:
                return None
            return min(c["amount_cents"], remaining)
    # Target not found among ALLOWED -> state error caller should've prevented
    return None


def _waterfall_pro_rata(estate: dict, target_claim: dict, already_paid_total: int) -> Optional[int]:
    """When a CLOSE_ESTATE draft exists, under-funded classes split pro-rata."""
    estate_id = estate["id"]
    remaining = estate["gross_estate_value_cents"] - already_paid_total

    target_class = target_claim["claim_class"]

    for cls in ("SECURED", "ADMIN", "FUNERAL", "TAX", "UNSECURED"):
        claims_in_class = [c for c in _claims_for_estate_allowed(estate_id) if c["claim_class"] == cls]
        claims_in_class.sort(key=lambda c: (c["created_at"], c["amount_cents"]))
        class_total = sum(c["amount_cents"] for c in claims_in_class)

        if cls != target_class:
            # Consume notionally; if the whole class fits, subtract class_total,
            # else subtract whatever remains (class is short-funded).
            consumed = min(remaining, class_total)
            remaining -= consumed
            continue

        # This is the target's class. Decide between full-pay (sufficient) and pro-rata (under-funded).
        if remaining <= 0:
            return None
        if remaining >= class_total:
            # Fully funded; pay target in full.
            return target_claim["amount_cents"]
        # Pro-rata distribution.
        shares = {}
        residual_pool = remaining
        floor_sum = 0
        for c in claims_in_class:
            share = (c["amount_cents"] * remaining) // class_total
            shares[c["id"]] = share
            floor_sum += share
        residual = residual_pool - floor_sum
        # Allocate residual cents one at a time in created_at ASC order
        for c in claims_in_class:
            if residual <= 0:
                break
            shares[c["id"]] += 1
            residual -= 1
        payable = shares.get(target_claim["id"], 0)
        if payable <= 0:
            return None
        return payable
    return None


# ---------------------------------------------------------------------------
# intestacy_share_allocation
# ---------------------------------------------------------------------------

STATE_SHARES = {
    "CA": {"spouse_first_bp": 5000, "child_pool_bp": 5000},
    "NY": {"spouse_first_bp": 5000, "child_pool_bp": 5000},
    "TX": {"spouse_first_bp": 3333, "child_pool_bp": 6667},
    "FL": {"spouse_first_bp": 5000, "child_pool_bp": 5000},
    "IL": {"spouse_first_bp": 5000, "child_pool_bp": 5000},
}

RELATIONSHIP_ORDER = ("SPOUSE", "CHILD", "PARENT", "SIBLING", "CHARITY")


def intestacy_shares(estate: dict, decedent: dict) -> dict:
    state_code = decedent["domicile_state_code"]
    table = STATE_SHARES.get(state_code, {"spouse_first_bp": 5000, "child_pool_bp": 5000})

    designations = [
        b for b in db.beneficiary_designations.values()
        if b["estate_id"] == estate["id"] and b["status"] in ("DRAFT", "ACTIVE")
    ]
    by_rel: dict[str, list] = {}
    for b in designations:
        by_rel.setdefault(b["relationship"], []).append(b)
    for lst in by_rel.values():
        lst.sort(key=lambda b: b["created_at"])

    assigned: dict[str, int] = {}
    total_remaining = 10000

    for rel in RELATIONSHIP_ORDER:
        peers = by_rel.get(rel) or []
        if not peers:
            continue
        if rel == "SPOUSE":
            pool = table["spouse_first_bp"]
        elif rel == "CHILD":
            pool = table["child_pool_bp"]
        else:
            pool = total_remaining
        if pool <= 0:
            continue
        pool = min(pool, total_remaining)
        base = pool // len(peers)
        rem = pool - base * len(peers)
        for i, b in enumerate(peers):
            assigned[b["id"]] = base + (1 if i < rem else 0)
        total_remaining -= pool

    total_assigned = sum(assigned.values())
    return {"shares": assigned, "total_bp_assigned": total_assigned}


# ---------------------------------------------------------------------------
# guardian_age_eligibility
# ---------------------------------------------------------------------------

def _add_years(dt: datetime, years: int) -> datetime:
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 fallback on non-leap years
        return dt.replace(year=dt.year + years, day=28)


def guardian_eligible(ward_date_of_birth: datetime, date_of_death: datetime) -> bool:
    """Ward is eligible iff (ward_dob + 18y) > date_of_death (strict)."""
    ward_18 = _add_years(ward_date_of_birth, 18)
    # Compare on date semantics (UTC).
    return ward_18.date() > date_of_death.date()
