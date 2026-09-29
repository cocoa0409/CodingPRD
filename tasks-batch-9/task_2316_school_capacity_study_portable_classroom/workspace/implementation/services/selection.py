"""Calculation eligible_unit_selection (PRD 3.5)."""

import constants as C
from db import db
from services.feasibility import pad_admits


def eligible_units(site):
    candidates = []
    for unit in db.units.values():
        if unit["allocation_status"] != "IN_STORAGE":
            continue
        if unit["condition_status"] != "SERVICEABLE":
            continue
        if unit["condition_grade"] not in ("A", "B", "C"):
            continue
        if unit["lifetime_relocation_count"] >= C.MAX_LIFETIME_RELOCATIONS:
            continue
        if unit["rated_seats"] < C.MIN_SEATS_PER_UNIT:
            continue
        if not pad_admits(site, unit["size_class"]):
            continue
        candidates.append(unit)
    return candidates


def select_unit(site):
    candidates = eligible_units(site)
    if not candidates:
        return None
    candidates.sort(
        key=lambda u: (
            u["accumulated_relocation_cost_cents"],
            C.CONDITION_GRADE_RANK[u["condition_grade"]],
            -u["rated_seats"],
            u["created_at"],
            u["_seq"],
        )
    )
    return candidates[0]
