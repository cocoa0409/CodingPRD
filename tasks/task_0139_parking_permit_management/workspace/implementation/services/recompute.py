"""Synchronous recomputation of derived counters/balances (PRD §2.7).

Each recompute mutates the affected entity: it refreshes updated_at and
increments version (PRD §2.4 — "Recomputation of a derived field ... is itself
a mutation"). These helpers are called from the side-effect blocks of the
state machines and creates.
"""
from __future__ import annotations

from typing import Dict, Any

import db


def garage_for_zone(zone: Dict[str, Any]) -> Dict[str, Any]:
    return db.garages.get(zone["garage_id"])


def zone_for_space(space: Dict[str, Any]) -> Dict[str, Any]:
    return db.zones.get(space["zone_id"])


def garage_for_space(space: Dict[str, Any]):
    zone = zone_for_space(space)
    if zone is None:
        return None
    return db.garages.get(zone["garage_id"])


def spaces_of_garage(garage_id: str) -> list:
    out = []
    for sp in db.spaces.values():
        zone = db.zones.get(sp["zone_id"])
        if zone is not None and zone["garage_id"] == garage_id:
            out.append(sp)
    return out


def recompute_garage_counts(garage: Dict[str, Any], bump: bool = True) -> None:
    """total_space_count = all spaces resolving into this garage (any status);
    occupied_count = those with is_occupied true."""
    sps = spaces_of_garage(garage["id"])
    garage["total_space_count"] = len(sps)
    garage["occupied_count"] = sum(1 for s in sps if s.get("is_occupied"))
    if bump:
        db.bump(garage)


def recompute_zone_active_permits(zone: Dict[str, Any], bump: bool = True) -> None:
    """permits_active_count = ACTIVE permits in this zone."""
    cnt = sum(
        1
        for p in db.permits.values()
        if p["zone_id"] == zone["id"] and p["status"] == "ACTIVE"
    )
    zone["permits_active_count"] = cnt
    if bump:
        db.bump(zone)


def recompute_motorist_balance(motorist: Dict[str, Any], bump: bool = True) -> None:
    """outstanding_balance_cents = sum of amount_due_cents across this
    motorist's citations whose status IN {ISSUED, UPHELD}."""
    total = 0
    for c in db.citations.values():
        if c.get("motorist_id") == motorist["id"] and c["status"] in ("ISSUED", "UPHELD"):
            total += c.get("amount_due_cents", 0)
    motorist["outstanding_balance_cents"] = total
    if bump:
        db.bump(motorist)


def set_space_occupied(space: Dict[str, Any], occupied: bool, bump: bool = True) -> None:
    space["is_occupied"] = occupied
    if bump:
        db.bump(space)
