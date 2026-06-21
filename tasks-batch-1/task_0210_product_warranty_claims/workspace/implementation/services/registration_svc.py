"""Registration derived-field reconciliation and serialization.

Holds the cross-cutting logic shared by many routes:
  * remaining_coverage reconciliation from the ledger stream (PRD §2.7)
  * active_tier / warranty_end_date recomputation (PRD §3.4)
  * version + updated_at bump on every mutation/cascade (PRD §2.4, §2.9)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import db
from services import calc
from services.timeutil import add_months, parse_iso


# ---- common-field minting ---------------------------------------------------

def mint_common(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Attach id/created_at/updated_at/version (full common set)."""
    ts = db.now_iso()
    entity["id"] = db.new_uuid()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def mint_lean(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Attach id/created_at only (Owner, WarrantyTransfer, LedgerEntry)."""
    entity["id"] = db.new_uuid()
    entity["created_at"] = db.now_iso()
    entity["_seq"] = db.next_seq()
    return entity


def bump(entity: Dict[str, Any]) -> None:
    """Increment version and refresh updated_at on a common-fields entity."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = db.now_iso()


# ---- ledger -----------------------------------------------------------------

def make_ledger_entry(registration_id: str, entry_type: str, reason: str,
                      amount_cents: int, claim_id: Optional[str] = None) -> Dict[str, Any]:
    entry = {
        "registration_id": registration_id,
        "claim_id": claim_id,
        "entry_type": entry_type,
        "reason": reason,
        "amount_cents": amount_cents,
    }
    mint_lean(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry


def ledger_for(registration_id: str) -> List[Dict[str, Any]]:
    rows = [e for e in db.ledger_entries.values() if e["registration_id"] == registration_id]
    rows.sort(key=lambda e: e["_seq"])
    return rows


# ---- tier resolution --------------------------------------------------------

def base_tier_for_product(product_id: str) -> Optional[Dict[str, Any]]:
    for t in db.coverage_tiers.values():
        if t["product_id"] == product_id and t["tier_name"] == "BASE":
            return t
    return None


def active_extensions(registration_id: str) -> List[Dict[str, Any]]:
    return [e for e in db.extended_warranties.values()
            if e["registration_id"] == registration_id and e["status"] == "ACTIVE"]


def in_force_tiers(reg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Tiers currently in force: BASE (always) plus the tiers of ACTIVE extensions."""
    tiers: List[Dict[str, Any]] = []
    base = base_tier_for_product(reg["product_id"])
    if base is not None:
        tiers.append(base)
    for ext in active_extensions(reg["id"]):
        tier = db.coverage_tiers.get(ext["coverage_tier_id"])
        if tier is not None:
            tiers.append(tier)
    return tiers


def highest_coverage_tier(reg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The in-force tier with the greatest coverage_cap_cents (BASE if none else)."""
    tiers = in_force_tiers(reg)
    if not tiers:
        return None
    return max(tiers, key=lambda t: (t["coverage_cap_cents"], t["_seq"]))


# ---- derived-field recomputation -------------------------------------------

def recompute_warranty_end_date(reg: Dict[str, Any]) -> None:
    """purchase_date + base_warranty_months + active extension_months (PRD §3.2/§3.4).

    The active extension months are those of all ACTIVE extensions on the reg.
    """
    product = db.products[reg["product_id"]]
    months = product["base_warranty_months"]
    for ext in active_extensions(reg["id"]):
        tier = db.coverage_tiers.get(ext["coverage_tier_id"])
        if tier is not None:
            months += tier["extension_months"]
    pdate = parse_iso(reg["purchase_date"])
    reg["warranty_end_date"] = _iso(add_months(pdate, months))


def recompute_remaining_coverage(reg: Dict[str, Any]) -> None:
    """remaining = cap - debits + credits, clamped at floor (PRD §2.7)."""
    tier = db.coverage_tiers.get(reg.get("active_tier_id"))
    cap = tier["coverage_cap_cents"] if tier is not None else 0
    debits = 0
    credits = 0
    for e in ledger_for(reg["id"]):
        if e["entry_type"] == "DEBIT":
            debits += e["amount_cents"]
        elif e["entry_type"] == "CREDIT":
            credits += e["amount_cents"]
    remaining = cap - debits + credits
    if remaining < calc.COVERAGE_FLOOR_CENTS:
        remaining = calc.COVERAGE_FLOOR_CENTS
    reg["remaining_coverage_cents"] = remaining


def recompute_active_tier(reg: Dict[str, Any]) -> None:
    """Set active_tier_id to the highest-coverage in-force tier (BASE if none)."""
    tier = highest_coverage_tier(reg)
    reg["active_tier_id"] = tier["id"] if tier is not None else None


def reconcile(reg: Dict[str, Any]) -> None:
    """Full derived-field reconciliation: active tier, end date, remaining coverage."""
    recompute_active_tier(reg)
    recompute_warranty_end_date(reg)
    recompute_remaining_coverage(reg)


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---- serialization ----------------------------------------------------------

_INTERNAL = ("_seq",)


def public(entity: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in entity.items() if k not in _INTERNAL}


def public_registration(reg: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a registration with derived fields recomputed on read (PRD §2.7)."""
    reconcile(reg)
    return public(reg)
