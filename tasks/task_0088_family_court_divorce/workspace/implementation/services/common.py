"""Shared lookup / serialization / ledger helpers used by all route modules."""
from __future__ import annotations

from typing import Dict, Any, List, Optional

import db
from errors import APIError, ERR_NOT_FOUND, ERR_CASE_TERMINAL

CASE_TERMINAL_STATES = {"JUDGMENT_ENTERED", "DISMISSED"}

# Fields that are internal bookkeeping and must NOT appear in serialized output.
_INTERNAL_FIELDS = {"_seq"}


def serialize(obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if k not in _INTERNAL_FIELDS}


def serialize_list(objs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [serialize(o) for o in objs]


def sorted_by_creation(objs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """List default sort: ascending by creation order (PRD §2.3)."""
    return sorted(objs, key=lambda o: o.get("_seq", 0))


# ---- existence resolution (ERR_NOT_FOUND, PRD §2.4 left-to-right) -----------
def require(store: Dict[str, Dict[str, Any]], rid: Any, label: str = "resource") -> Dict[str, Any]:
    if not isinstance(rid, str) or rid not in store:
        raise APIError(ERR_NOT_FOUND, 404, f"{label} not found")
    return store[rid]


def get_case(case_id: Any) -> Dict[str, Any]:
    return require(db.cases, case_id, "Case")


def get_party(party_id: Any) -> Dict[str, Any]:
    return require(db.parties, party_id, "Party")


# ---- terminal-case guard (ERR_CASE_TERMINAL, PRD §3.1) ----------------------
def assert_case_not_terminal(case: Dict[str, Any]) -> None:
    if case["status"] in CASE_TERMINAL_STATES:
        raise APIError(ERR_CASE_TERMINAL, 409, "Case is in a terminal status")


# ---- party helpers ----------------------------------------------------------
def parties_for_case(case_id: str) -> List[Dict[str, Any]]:
    return [p for p in db.parties.values() if p["case_id"] == case_id]


def party_with_role(case_id: str, role: str) -> Optional[Dict[str, Any]]:
    for p in db.parties.values():
        if p["case_id"] == case_id and p["role"] == role:
            return p
    return None


def petitioner_of(case_id: str) -> Optional[Dict[str, Any]]:
    return party_with_role(case_id, "PETITIONER")


def respondent_of(case_id: str) -> Optional[Dict[str, Any]]:
    return party_with_role(case_id, "RESPONDENT")


# ---- disclosure helpers -----------------------------------------------------
def verified_disclosure_for_party(party_id: str) -> Optional[Dict[str, Any]]:
    for d in db.financial_disclosures.values():
        if d["party_id"] == party_id and d["status"] == "VERIFIED":
            return d
    return None


def recompute_disclosure_flags(case: Dict[str, Any]) -> None:
    """Recompute petitioner/respondent disclosure-verified flags (PRD §2.8)."""
    pet = petitioner_of(case["id"])
    resp = respondent_of(case["id"])
    pet_ok = bool(pet and verified_disclosure_for_party(pet["id"]))
    resp_ok = bool(resp and verified_disclosure_for_party(resp["id"]))
    case["petitioner_disclosure_verified"] = pet_ok
    case["respondent_disclosure_verified"] = resp_ok


# ---- ledger -----------------------------------------------------------------
def recompute_active_support_total(case: Dict[str, Any]) -> None:
    """active_support_total_cents = SUM(ACTIVE SupportOrder.monthly_amount_cents)
    for this case (PRD §2.8). Caller is responsible for bumping the case if a
    mutation occurred.
    """
    total = 0
    for so in db.support_orders.values():
        if so["case_id"] == case["id"] and so["status"] == "ACTIVE":
            total += int(so["monthly_amount_cents"])
    case["active_support_total_cents"] = total
