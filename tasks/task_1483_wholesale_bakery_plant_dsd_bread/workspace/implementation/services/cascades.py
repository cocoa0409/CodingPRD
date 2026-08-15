"""Cross-entity cascade side effects."""

from db import DB
from helpers import touch
from services.calculations import compute_stale_ratio, SUSPENSION_STALE_RATIO
from decimal import Decimal


def cascade_batch_rejected(batch):
    """Hop 1: plan shortfall; Hop 2: flag stops; Hop 3: orders LOCKED -> SHORTED."""
    plan = DB.production_plans.get(batch.get("production_plan_id"))
    if plan is not None:
        plan["shortfall_units"] = int(plan.get("shortfall_units") or 0) + int(batch["qty_units"])
        touch(plan)

    for stop in DB.route_stops.values():
        if stop.get("status") != "PENDING":
            continue
        if batch["id"] not in (stop.get("batch_ids") or []):
            continue
        stop["shortfall_flag"] = True
        touch(stop)
        order = DB.store_orders.get(stop.get("store_order_id"))
        if order is not None and order.get("status") == "LOCKED":
            order["status"] = "SHORTED"
            touch(order)


def cascade_stop_reconciled(stop):
    """DELIVERED -> RECONCILED cascade to the underlying order."""
    order = DB.store_orders.get(stop.get("store_order_id"))
    if order is None:
        return
    delivered = int(stop.get("delivered_units") or 0)
    total = int(order.get("total_units") or 0)
    if delivered == total:
        if order.get("status") == "LOCKED":
            order["status"] = "FULFILLED"
            touch(order)
    else:
        if order.get("status") in ("LOCKED", "SHORTED"):
            order["status"] = "PARTIALLY_FULFILLED"
            touch(order)


def cascade_index_published(index):
    """Finalize matching PROVISIONAL schedules; update product surcharges."""
    from services.calculations import compute_surcharge_cents

    plant = DB.plants.get(index["plant_id"])
    if plant is None:
        return

    def find_index(ingredient):
        for ix in DB.ingredient_indices.values():
            if (
                ix.get("plant_id") == index["plant_id"]
                and ix.get("ingredient") == ingredient
                and ix.get("period") == index["period"]
            ):
                return ix
        return None

    flour_ix = find_index("FLOUR")
    butter_ix = find_index("BUTTER")
    if flour_ix is None or butter_ix is None:
        return
    if flour_ix.get("status") != "PUBLISHED" or butter_ix.get("status") != "PUBLISHED":
        return

    # All products for this plant (schedules key on product+period)
    for sched in DB.surcharge_schedules.values():
        if sched.get("period") != index["period"]:
            continue
        if sched.get("status") != "PROVISIONAL":
            continue
        product = DB.products.get(sched.get("product_id"))
        if product is None or product.get("plant_id") != index["plant_id"]:
            continue
        final_cents = compute_surcharge_cents(
            product, plant, flour_ix["published_value"], butter_ix["published_value"]
        )
        sched["final_surcharge_cents"] = final_cents
        sched["status"] = "FINALIZED"
        touch(sched)
        product["current_surcharge_cents"] = final_cents
        touch(product)


def cascade_plan_created(plant, bake_date, new_plan_id):
    """Supersede any existing DRAFT plan for same plant+bake_date."""
    for plan in DB.production_plans.values():
        if plan["id"] == new_plan_id:
            continue
        if (
            plan.get("plant_id") == plant["id"]
            and plan.get("bake_date") == bake_date
            and plan.get("status") == "DRAFT"
        ):
            plan["status"] = "SUPERSEDED"
            touch(plan)


def close_day_sweeps(plant):
    """Ops-run checkpoint sweeps for a plant.

    1. Batches in PROOFING whose proof has run > 120 minutes -> OVERPROOFED.
    2. ACTIVE stores with stale_ratio > 0.15 -> SUSPENDED.
    3. CONFIRMED orders whose cutoff has passed -> LOCKED.
    """
    from services.calculations import cutoff_instant
    from services.calculations import parse_iso_z

    plant_id = plant["id"]

    # Sweep 1: overproof batches (only batches belonging to this plant's plans)
    plan_ids = {p["id"] for p in DB.production_plans.values() if p.get("plant_id") == plant_id}
    for batch in DB.batches.values():
        if batch.get("production_plan_id") not in plan_ids:
            continue
        if batch.get("status") != "PROOFING":
            continue
        proof_started = batch.get("proof_started_at")
        if not proof_started:
            continue
        proof_dt = parse_iso_z(proof_started)
        elapsed_min = (DB.clock - proof_dt).total_seconds() / 60.0
        if elapsed_min > 120:
            batch["status"] = "OVERPROOFED"
            touch(batch)

    # Sweep 2: suspend high-stale stores
    for store in DB.stores.values():
        if store.get("plant_id") != plant_id:
            continue
        if store.get("status") != "ACTIVE":
            continue
        ratio = compute_stale_ratio(store)
        if Decimal(str(ratio)) > SUSPENSION_STALE_RATIO:
            store["status"] = "SUSPENDED"
            store["stale_ratio"] = ratio
            touch(store)

    # Sweep 3: lock CONFIRMED orders past cutoff
    for order in DB.store_orders.values():
        if order.get("plant_id") != plant_id:
            continue
        if order.get("status") != "CONFIRMED":
            continue
        store = DB.stores.get(order.get("store_id"))
        if store is None:
            continue
        cutoff = cutoff_instant(store, order["delivery_date"])
        if DB.clock > cutoff:
            order["status"] = "LOCKED"
            touch(order)
