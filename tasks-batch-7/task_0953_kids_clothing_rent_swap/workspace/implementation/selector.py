"""The box-fill and replacement selectors (PRD 3.3 / 3.4).

`id` is never a decision input; every ranking is fully deterministic.

Empty-pool diagnosis follows the rung numbers: 53 (size) then 54 (no stock at
all) then 55 (retire-graded) then 56 (capsule allocation missing).
"""

import calc
import store
from errors import ApiError

ALLOCATABLE_GRADES = ("A", "B", "C", "D")


def _in_stock_of_style(style_id):
    return [u for u in store.all_rows("units")
            if u["style_id"] == style_id and u["state"] == "IN_STOCK"]


def member_active_capsule_ids(member_id):
    out = set()
    for allocation in store.all_rows("capsule_allocations"):
        if allocation["member_id"] == member_id and allocation["status"] == "ACTIVE":
            out.add(allocation["capsule_id"])
    return out


def capsule_open(capsule_id):
    capsule = store.get("capsules", capsule_id)
    return capsule is not None and capsule["status"] in ("OPEN", "EMBARGO_LIFTED")


def _stage_pools(style, member, capsule_predicate):
    pool = _in_stock_of_style(style["id"])
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_STOCK")
    sized = [u for u in pool if calc.size_compatible(style["size_code"], member["child_size_code"])]
    if not sized:
        raise ApiError("ERR_SIZE_INCOMPATIBLE")
    graded = [u for u in sized
              if u["current_grade"] in ALLOCATABLE_GRADES and not u["retirement_eligible"]]
    if not graded:
        raise ApiError("ERR_UNIT_RETIRE_GRADED")
    final = [u for u in graded if capsule_predicate(u)]
    if not final:
        raise ApiError("ERR_CAPSULE_ALLOCATION_MISSING")
    return final


def _rank_least_worn(units):
    return sorted(units, key=lambda u: (u["cycles_completed"],
                                        u["cumulative_cleaning_cost_cents"],
                                        store.order_key(u)))


def _rank_oldest_acquired(units):
    return sorted(units, key=lambda u: (store.order_key(u), u["cycles_completed"]))


def box_fill(style, member, exclude_ids=()):
    """STANDARD_FILL unless the style's stock is capsule stock the member holds."""
    held = member_active_capsule_ids(member["id"])
    pool = _in_stock_of_style(style["id"])
    capsule_variant = any(
        u["capsule_id"] is not None and u["capsule_id"] in held and capsule_open(u["capsule_id"])
        for u in pool
    )
    if capsule_variant:
        def predicate(u):
            return (u["capsule_id"] is not None
                    and u["capsule_id"] in held
                    and capsule_open(u["capsule_id"]))
        ranked = _rank_oldest_acquired(_stage_pools(style, member, predicate))
    else:
        ranked = _rank_least_worn(_stage_pools(style, member, lambda u: u["capsule_id"] is None))
    for unit in ranked:
        if unit["id"] not in exclude_ids:
            return unit
    raise ApiError("ERR_NO_ELIGIBLE_STOCK")


def swap_replacement(style, member, exclude_ids=()):
    held = member_active_capsule_ids(member["id"])

    def predicate(u):
        if u["capsule_id"] is None:
            return True
        return capsule_open(u["capsule_id"]) and u["capsule_id"] in held

    ranked = _rank_least_worn(_stage_pools(style, member, predicate))
    for unit in ranked:
        if unit["id"] not in exclude_ids:
            return unit
    raise ApiError("ERR_NO_ELIGIBLE_STOCK")
