"""Freight allocation, the pallet plan and the reefer surcharge allocation."""

from core.constants import (PALLET_MAX_CUBE_CM3, PALLET_MAX_WEIGHT_GRAMS,
                            REEFER_REQUIRED_TEMP_CLASSES,
                            REEFER_SURCHARGE_CENTS_PER_SLOT)
from core.errors import ApiError
from core.money import largest_remainder
from core.store import DB, ordered, touch
from services import recompute

PALLET_CLASS_ORDER = ("FROZEN", "CHILLED", "DRY")
ALLOCATED_STATES = ("FILLED", "SHORT_FILLED", "SUBSTITUTED")
FREIGHT_ORDER_STATES = ("FILLED", "SHORT_FILLED")


# ------------------------------------------------------------- freight ------

def allocate_freight(route_run):
    """LEVEL 1 across RECEIVED drop runs, LEVEL 2 across FILLED / SHORT_FILLED
    member orders.  The rounding happens once per level."""
    level1 = [d for d in recompute.drop_runs_of_route_run(route_run)
              if d["status"] == "RECEIVED"]
    shares, _ = largest_remainder(route_run["freight_cents"],
                                  [d["subtotal_cents"] for d in level1])
    for drop_run, share in zip(level1, shares):
        before = {"freight_alloc_cents": drop_run["freight_alloc_cents"]}
        drop_run["freight_alloc_cents"] = share
        if drop_run["freight_alloc_cents"] != before["freight_alloc_cents"]:
            touch(drop_run)
        _allocate_freight_level2(drop_run)


def _allocate_freight_level2(drop_run):
    orders = [o for o in recompute.orders_of_drop_run(drop_run)
              if o["status"] in FREIGHT_ORDER_STATES]
    shares, _ = largest_remainder(drop_run["freight_alloc_cents"],
                                  [o["gross_cents"] for o in orders])
    for order, share in zip(orders, shares):
        if order["freight_alloc_cents"] != share:
            order["freight_alloc_cents"] = share
            touch(order)
        recompute.recompute_order_money(order)


# -------------------------------------------------------------- pallets -----

def _unit_rows(route_run, temp_class):
    """Every allocated unit of the class, one row per unit, ordered by Item.sku
    ASC then OrderLine.created_at ASC."""
    entries = []
    for line in recompute.lines_of_route_run(route_run):
        if line["status"] not in ALLOCATED_STATES or line["allocated_units"] <= 0:
            continue
        item = DB.get("Item", line["item_id"])
        if item is None or item["temp_class"] != temp_class:
            continue
        entries.append((item, line))
    entries.sort(key=lambda e: (e[0]["sku"], e[1]["created_at"], e[1]["_seq"]))
    rows = []
    for item, line in entries:
        rows.extend([item] * line["allocated_units"])
    return rows


def build_pallets(route_run):
    route = DB.get("Route", route_run["route_id"])
    planned = []
    for temp_class in PALLET_CLASS_ORDER:
        units = _unit_rows(route_run, temp_class)
        if not units:
            continue
        current = {"temp_class": temp_class, "sequence_index": 1,
                   "weight_grams": 0, "cube_cm3": 0, "unit_count": 0}
        planned.append(current)
        for item in units:
            if (current["weight_grams"] + item["unit_weight_grams"] <= PALLET_MAX_WEIGHT_GRAMS
                    and current["cube_cm3"] + item["unit_cube_cm3"] <= PALLET_MAX_CUBE_CM3):
                current["weight_grams"] += item["unit_weight_grams"]
                current["cube_cm3"] += item["unit_cube_cm3"]
                current["unit_count"] += 1
            else:
                current = {"temp_class": temp_class,
                           "sequence_index": current["sequence_index"] + 1,
                           "weight_grams": item["unit_weight_grams"],
                           "cube_cm3": item["unit_cube_cm3"], "unit_count": 1}
                planned.append(current)

    cold = [p for p in planned if p["temp_class"] in REEFER_REQUIRED_TEMP_CLASSES]
    if len(cold) > route["reefer_slots"]:                     # rung 29
        raise ApiError("ERR_REEFER_CAPACITY_EXCEEDED")
    if len(planned) > route["max_pallets"]:                   # rung 30
        raise ApiError("ERR_PALLET_CAPACITY_EXCEEDED")

    for plan in planned:
        DB.insert("Pallet", {
            "route_run_id": route_run["id"],
            "temp_class": plan["temp_class"],
            "sequence_index": plan["sequence_index"],
            "weight_grams": plan["weight_grams"],
            "cube_cm3": plan["cube_cm3"],
            "unit_count": plan["unit_count"],
            "requires_reefer": plan["temp_class"] in REEFER_REQUIRED_TEMP_CLASSES,
            "status": "BUILDING",
        })

    route_run["cold_pallet_count"] = len(cold)
    route_run["dry_pallet_count"] = len(planned) - len(cold)
    route_run["reefer_slots_used"] = len(cold)
    route_run["reefer_surcharge_cents"] = len(cold) * REEFER_SURCHARGE_CENTS_PER_SLOT
    allocate_reefer_surcharge(route_run)
    return route_run


# ------------------------------------------------------- reefer surcharge ---

def _cold_value(order):
    total = 0
    for line in recompute.lines_of_order(order):
        if line["status"] not in ALLOCATED_STATES:
            continue
        item = DB.get("Item", line["item_id"])
        if item is None or item["temp_class"] not in REEFER_REQUIRED_TEMP_CLASSES:
            continue
        total += line["allocated_units"] * line["unit_price_cents"]
    return total


def allocate_reefer_surcharge(route_run):
    orders = [o for o in recompute.orders_of_route_run(route_run)
              if o["status"] in FREIGHT_ORDER_STATES]
    shares, _ = largest_remainder(route_run["reefer_surcharge_cents"],
                                  [_cold_value(o) for o in orders])
    for order, share in zip(orders, shares):
        if order["reefer_alloc_cents"] != share:
            order["reefer_alloc_cents"] = share
            touch(order)
        recompute.recompute_order_money(order)
    for drop_run in recompute.drop_runs_of_route_run(route_run):
        recompute.recompute_drop_reefer_alloc(drop_run)


def pallets_of_route_run(route_run):
    return ordered([p for p in DB.pallets.values()
                    if p["route_run_id"] == route_run["id"]])
