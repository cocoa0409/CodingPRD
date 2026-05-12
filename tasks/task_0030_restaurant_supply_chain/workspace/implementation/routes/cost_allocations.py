"""Final period cost allocation."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import clock
import db
import errors
import helpers
import response
from middleware import auth_required


bp = Blueprint("cost_allocations", __name__, url_prefix="/supply-chain/cost-allocations")


TRANSFER_OVERHEAD_RATE = Decimal("0.10")
INDIRECT_OVERHEAD_PCT = Decimal("0.15")


def _round_half_up_int(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _ensure_decimal(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _pick_top(stores_with_weight):
    """Return store_id with the largest weight; tie-break: lowest store_code."""
    if not stores_with_weight:
        return None
    return sorted(
        stores_with_weight.items(),
        key=lambda kv: (-_ensure_decimal(kv[1]), db.stores[kv[0]]["store_code"]),
    )[0][0]


@bp.route("/run", methods=["POST"])
@auth_required("FinanceController")
def run_allocation():
    body = helpers.get_json_body()
    for f in ["period_start", "period_end", "indirect_basis"]:
        if f not in body:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Missing field: {f}")
    period_start = clock.parse_iso(body["period_start"])
    period_end = clock.parse_iso(body["period_end"])
    indirect_basis = body["indirect_basis"]
    if indirect_basis not in ("SALES_VALUE", "ORDER_VOLUME"):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE,
                           "indirect_basis must be SALES_VALUE or ORDER_VOLUME.")

    # Per-store accumulators per bucket.
    direct = {}
    transport = {}
    indirect = {}
    transfer = {}

    # 1. Direct production cost from completed batches in period.
    completed_batches = []
    for b in db.production_batches.values():
        if b["status"] != "COMPLETED" or b["produced_at"] is None:
            continue
        if period_start <= b["produced_at"] < period_end:
            completed_batches.append(b)
    completed_batches.sort(key=lambda b: (b["produced_at"], b["id"]))

    for b in completed_batches:
        recipe = db.recipes[b["recipe_id"]]
        # Re-compute provisional allocation (deterministic).
        ingredient_cost = Decimal("0")
        for ri in db.recipe_ingredients.values():
            if ri["recipe_id"] != recipe["id"]:
                continue
            ing = db.ingredients[ri["ingredient_id"]]
            ingredient_cost += Decimal(str(ri["quantity_per_unit"])) * Decimal(ing["unit_cost_cents"]) * Decimal(b["planned_units"])
        total_cost = ingredient_cost + Decimal("100")  # BATCH_SETUP_FEE_CENTS

        contributions = {}
        for line in db.order_lines.values():
            order = db.store_orders.get(line["store_order_id"])
            if order is None:
                continue
            if order["consolidation_batch_id"] != b["id"]:
                continue
            if line["recipe_id"] != b["recipe_id"]:
                continue
            contributions[order["store_id"]] = contributions.get(order["store_id"], 0) + line["quantity"]

        if not contributions or b["planned_units"] == 0:
            continue
        per_store = {}
        for sid, units in contributions.items():
            share = Decimal(units) / Decimal(b["planned_units"])
            per_store[sid] = total_cost * share
        # Round and distribute remainder.
        rounded = {sid: _round_half_up_int(v) for sid, v in per_store.items()}
        target = _round_half_up_int(total_cost)
        diff = target - sum(rounded.values())
        if diff != 0:
            top = _pick_top(contributions)
            rounded[top] += diff
        for sid, v in rounded.items():
            direct[sid] = direct.get(sid, 0) + v

    # 2. Transportation cost: distribute per route across stops by units loaded.
    # Use a simple flat per-route transportation cost: 100 cents per route base
    # (the PRD doesn't pin a number, so we use a deterministic computation —
    # number of stops * 100).
    completed_routes = []
    for r in db.delivery_routes.values():
        if r["status"] != "COMPLETED" or r["completed_at"] is None:
            continue
        if period_start <= r["completed_at"] < period_end:
            completed_routes.append(r)
    completed_routes.sort(key=lambda r: (r["completed_at"], r["id"]))

    for r in completed_routes:
        # Per-stop units loaded
        per_stop_units = {}
        total_units = 0
        for stop in r["planned_stops"]:
            units = 0
            for bid in stop["batch_ids"]:
                pb = db.production_batches.get(bid)
                if pb is not None:
                    units += pb["planned_units"]
            per_stop_units[stop["store_id"]] = per_stop_units.get(stop["store_id"], 0) + units
            total_units += units
        if total_units == 0:
            continue
        # Transportation cost per route: 1000 cents (deterministic).
        route_transport_cents = Decimal("1000")
        per_store_raw = {sid: route_transport_cents * Decimal(units) / Decimal(total_units)
                         for sid, units in per_stop_units.items()}
        rounded = {sid: _round_half_up_int(v) for sid, v in per_store_raw.items()}
        diff = _round_half_up_int(route_transport_cents) - sum(rounded.values())
        if diff != 0:
            top = _pick_top(per_stop_units)
            rounded[top] += diff
        for sid, v in rounded.items():
            transport[sid] = transport.get(sid, 0) + v

    # 3. Indirect overhead: 15% of direct production cost for the period, allocated
    #    by basis.
    total_direct = sum(direct.values())
    indirect_total = _round_half_up_int(Decimal(total_direct) * INDIRECT_OVERHEAD_PCT)

    # Determine basis weight per store from StoreOrders in the period.
    basis_weights = {}
    relevant_orders = []
    for o in db.store_orders.values():
        ts = o["submitted_at"] or o["created_at"]
        if ts is None:
            continue
        if period_start <= ts < period_end and o["status"] in ("SUBMITTED", "CONSOLIDATED", "DELIVERED"):
            relevant_orders.append(o)
    for o in relevant_orders:
        sid = o["store_id"]
        if indirect_basis == "SALES_VALUE":
            basis_weights[sid] = basis_weights.get(sid, 0) + o["total_value_cents"]
        else:  # ORDER_VOLUME
            basis_weights[sid] = basis_weights.get(sid, 0) + o["total_units"]
    total_weight = sum(basis_weights.values())
    if indirect_total > 0 and total_weight > 0:
        per_store_raw = {sid: Decimal(indirect_total) * Decimal(w) / Decimal(total_weight)
                         for sid, w in basis_weights.items()}
        rounded = {sid: _round_half_up_int(v) for sid, v in per_store_raw.items()}
        diff = indirect_total - sum(rounded.values())
        if diff != 0:
            top = _pick_top(basis_weights)
            rounded[top] += diff
        for sid, v in rounded.items():
            indirect[sid] = indirect.get(sid, 0) + v

    # 4. Inter-store transfer cost: charged to sending store, refunded to receiving.
    for entry in db.audit_log_entries:
        if entry["action"] != "INTER_STORE_TRANSFER":
            continue
        if not (period_start <= entry["created_at"] < period_end):
            continue
        payload = entry["payload"] or {}
        src = payload.get("source_store_id")
        dst = payload.get("destination_store_id")
        qty = payload.get("quantity_transferred", 0)
        recipe_id = payload.get("recipe_id")
        if not src or not dst or not recipe_id:
            continue
        recipe = db.recipes.get(recipe_id)
        if recipe is None:
            continue
        cost = _round_half_up_int(
            Decimal(qty) * Decimal(recipe["unit_price_cents"]) * TRANSFER_OVERHEAD_RATE
        )
        if cost == 0:
            continue
        transfer[src] = transfer.get(src, 0) + cost
        transfer[dst] = transfer.get(dst, 0) - cost

    all_stores = set(direct) | set(transport) | set(indirect) | set(transfer)
    by_volume = {}
    for sid in all_stores:
        # Top-volume: use total_units across all orders in the period.
        v = 0
        for o in relevant_orders:
            if o["store_id"] == sid:
                v += o["total_units"]
        by_volume[sid] = v

    per_store_results = []
    for sid in sorted(all_stores, key=lambda x: db.stores[x]["store_code"] if x in db.stores else x):
        d = direct.get(sid, 0)
        t = transport.get(sid, 0)
        i = indirect.get(sid, 0)
        tr = transfer.get(sid, 0)
        per_store_results.append({
            "store_id": sid,
            "direct_production_cost_cents": d,
            "transportation_cost_cents": t,
            "indirect_cost_cents": i,
            "inter_store_transfer_cost_cents": tr,
            "total_cents": d + t + i + tr,
        })

    return response.ok({
        "period_start": clock.iso_format(period_start),
        "period_end": clock.iso_format(period_end),
        "indirect_basis": indirect_basis,
        "per_store": per_store_results,
    })
