"""The 15 pinned calculations of SCAFFOLD.yaml 1.3 / PRD 3.

Every rounding placement here is load-bearing: FLOOR where the spec says FLOOR,
ROUND_HALF_UP where it says ROUND_HALF_UP, and never a float for money.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import store as db
import derive as dv

# --- constants ---------------------------------------------------------------
DEFAULT_LIFT_BP = 10000
COVER_WEEKS = 4
PUSH_FILL_RATE_BP = 8000
FREIGHT_MIN_USD = Decimal("45.00")
PER_UNIT_HANDLING_USD = Decimal("0.85")
NET_MARGIN_BP = 5500
TRANSFER_TTL_DAYS = 7
MODEL_BY_TYPE = {"BASIC": "MIN_MAX", "SEASONAL": "DEMAND_DRIVEN", "FASHION": "PUSH"}
METHOD_FOR_MODEL = {
    "MIN_MAX": "MIN_MAX_TOPUP",
    "DEMAND_DRIVEN": "DEMAND_DRIVEN",
    "PUSH": "PUSH_SIZE_PROFILE",
}


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    """FLOOR of an exact rational, integer inputs."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )


# --- 1. replenishment_model_resolution ---------------------------------------
def replenishment_model(item):
    if item["replenishment_model_override"] is not None:
        return item["replenishment_model_override"]
    return MODEL_BY_TYPE[item["item_type"]]


# --- 2. promo_lift_factor_bp -------------------------------------------------
def promo_lift_factor_bp(program_id, store, item):
    clock = db.now()
    candidates = []
    for event in db.promo_events.values():
        if event["program_id"] != program_id or event["status"] != "ACTIVE":
            continue
        if not (event["start_date"] <= clock <= event["end_date"]):
            continue
        if event["item_class"] is not None and event["item_class"] != item["item_class"]:
            continue
        scope = event["scope"]
        if scope == "PROGRAM":
            pass
        elif scope == "CLUSTER":
            if event["cluster_code"] != store["cluster_code"]:
                continue
        elif scope == "STORE":
            if event["store_id"] != store["id"]:
                continue
        candidates.append(event)
    if not candidates:
        return DEFAULT_LIFT_BP
    candidates.sort(
        key=lambda e: (
            -dv.SPECIFICITY_RANK[e["scope"]],
            -e["lift_factor_bp"],
            e["created_at"],
            e["_seq"],
        )
    )
    return candidates[0]["lift_factor_bp"]


# --- 3. store_need_units -----------------------------------------------------
def store_need_units(run, store, item, position, plan):
    method = run["method"]
    basis = run["need_basis"]
    available = dv.available_units(position)
    in_transit = dv.in_transit_units(position)
    if basis == "FORWARD_LOOKING":
        pipeline = available + in_transit + position["on_order_units"]
    else:
        pipeline = available + in_transit

    if method == "MIN_MAX_TOPUP":
        target = position["max_units"]
    elif method == "PUSH_SIZE_PROFILE":
        capacity = plan["capacity_units"] if plan else 0
        target = floor_div(capacity * PUSH_FILL_RATE_BP, 10000)
    else:  # DEMAND_DRIVEN
        if basis == "FORWARD_LOOKING":
            lift_bp = promo_lift_factor_bp(item["program_id"], store, item)
            weekly = half_up_int(
                Decimal(position["weekly_forecast_units"]) * Decimal(lift_bp) / 10000
            )
            target = weekly * COVER_WEEKS
        else:
            weekly = (
                Decimal(position["trailing_4wk_sales_units"])
                * Decimal(store["grade_index_bp"])
                / 10000
                / 4
            )
            target = half_up_int(weekly * COVER_WEEKS)
    return max(0, target - pipeline)


# --- 4. receipt_proration ----------------------------------------------------
def receipt_proration(pool, candidates):
    """candidates: list of dicts {store, position, need, headroom}.

    Returns (allocations, remaining) where allocations parallels candidates.
    """
    total_need = sum(c["need"] for c in candidates)
    base = []
    alloc = []
    capped_by_capacity = []
    for c in candidates:
        base_i = floor_div(pool * c["need"], total_need) if total_need else 0
        capped_i = min(base_i, c["need"])
        alloc_i = min(capped_i, c["headroom"])
        base.append(base_i)
        alloc.append(alloc_i)
        capped_by_capacity.append(capped_i - alloc_i)
    remaining = pool - sum(alloc)
    while remaining > 0:
        room = [
            idx
            for idx, c in enumerate(candidates)
            if alloc[idx] < min(c["need"], c["headroom"])
        ]
        if not room:
            break
        room.sort(
            key=lambda idx: (
                -(candidates[idx]["need"] - alloc[idx]),
                dv.GRADE_RANK[candidates[idx]["store"]["grade"]],
                candidates[idx]["store"]["store_code"],
            )
        )
        alloc[room[0]] += 1
        remaining -= 1
    return alloc, capped_by_capacity, remaining


# --- 5. size_breakdown_split -------------------------------------------------
def size_breakdown_split(curve, units):
    counts = {}
    for entry in curve:
        counts[entry["size_code"]] = floor_div(units * entry["share_bp"], 10000)
    remainder = units - sum(counts.values())
    order = sorted(curve, key=lambda e: (-e["share_bp"], e["size_code"]))
    while remainder > 0:
        for entry in order:
            if remainder == 0:
                break
            counts[entry["size_code"]] += 1
            remainder -= 1
    return [
        {"size_code": e["size_code"], "units": counts[e["size_code"]]}
        for e in curve
    ]


# --- 6. transfer_size_split --------------------------------------------------
def transfer_size_split(item, donor, receiver, units, source_reason):
    """Returns the size_split array, or None when no candidate size exists."""
    profile = dv.profile_of_item(item)
    curve = profile["size_curve"] if profile else []
    donor_units = {
        e["size_code"]: e["units"] for e in donor["size_on_hand"] if e["units"] > 0
    }
    if source_reason == "REBALANCE":
        receiver_units = {e["size_code"]: e["units"] for e in receiver["size_on_hand"]}
        candidates = [
            (e["size_code"], e["share_bp"])
            for e in dv.core_sizes(item)
            if receiver_units.get(e["size_code"], 0) == 0
            and donor_units.get(e["size_code"], 0) > 0
        ]
    else:
        candidates = [
            (e["size_code"], donor_units[e["size_code"]])
            for e in curve
            if donor_units.get(e["size_code"], 0) > 0
        ]
    if not candidates:
        return None
    denom = sum(weight for _, weight in candidates)
    counts = {}
    for code, weight in candidates:
        counts[code] = floor_div(units * weight, denom) if denom else 0
    remainder = units - sum(counts.values())
    order = sorted(candidates, key=lambda c: (-c[1], c[0]))
    while remainder > 0:
        placed = False
        for code, _ in order:
            if counts[code] < donor_units.get(code, 0):
                counts[code] += 1
                remainder -= 1
                placed = True
                break
        if not placed:
            break
    codes = [code for code, _ in candidates]
    return [
        {"size_code": e["size_code"], "units": counts[e["size_code"]]}
        for e in curve
        if e["size_code"] in codes and counts[e["size_code"]] > 0
    ]


# --- 7. transfer_landed_cost_usd --------------------------------------------
def transfer_landed_cost(from_store, units):
    freight = money(
        Decimal(from_store["freight_flat_usd"]) + Decimal(units) * PER_UNIT_HANDLING_USD
    )
    if freight < FREIGHT_MIN_USD:
        freight = FREIGHT_MIN_USD
    if freight < Decimal("50.00"):
        rate_bp = 1200
    elif freight < Decimal("150.00"):
        rate_bp = 900
    else:
        rate_bp = 600
    handling = money(freight * Decimal(rate_bp) / 10000)
    return freight, handling, freight + handling


# --- 8. transfer_benefit_usd -------------------------------------------------
def transfer_benefit(item, to_store, size_split):
    unit_margin = Decimal(item["retail_price_usd"]) * Decimal(NET_MARGIN_BP) / 10000
    realised = unit_margin * Decimal(to_store["historical_sell_through_bp"]) / 10000
    total = Decimal("0.00")
    for line in size_split:
        total += money(Decimal(line["units"]) * realised)
    return total.quantize(Decimal("0.01"))


# --- 9. transfer_benefit_ratio_bp -------------------------------------------
def benefit_ratio_bp(benefit_usd, landed_cost_usd):
    if Decimal(landed_cost_usd) == 0:
        return 0
    return half_up_int(Decimal(benefit_usd) / Decimal(landed_cost_usd) * 10000)


# --- 10/11. assortment health + remedy selection ----------------------------
def remedy_selection(position):
    """Returns the target StorePosition or None (-> MARKDOWN)."""
    if dv.available_units(position) == 0:
        return None
    item = db.items[position["item_id"]]
    needed = dv.available_units(position)
    candidates = []
    for other in dv.positions_of_item(item["id"]):
        if other["store_id"] == position["store_id"]:
            continue
        if dv.assortment_status(other) != "COMPLETE":
            continue
        store = db.stores.get(other["store_id"])
        if not store or store["status"] != "ACTIVE":
            continue
        plan = dv.in_effect_plan(store["id"], item["item_class"])
        if dv.headroom(other, plan) < needed:
            continue
        candidates.append((store, other))
    if not candidates:
        return None
    candidates.sort(
        key=lambda pair: (
            -pair[0]["historical_sell_through_bp"],
            dv.GRADE_RANK[pair[0]["grade"]],
            pair[0]["store_code"],
        )
    )
    return candidates[0][1]


# --- 12. markdown_depth_bp ---------------------------------------------------
def markdown_depth_bp(broken_count, core_size_count):
    if core_size_count == 0:
        ratio_bp = 0
    else:
        ratio_bp = floor_div(broken_count * 10000, core_size_count)
    if ratio_bp < 2500:
        return 0
    if ratio_bp < 5000:
        return 1500
    if ratio_bp < 7500:
        return 3000
    return 4500


# --- 13. cluster_scorecard ---------------------------------------------------
def allocated_units_for(position):
    total = 0
    for line in db.lines.values():
        if line["store_id"] != position["store_id"]:
            continue
        if line["fulfillment_status"] not in ("PENDING", "SHIPPED", "RECEIVED"):
            continue
        if dv.line_item_id(line) != position["item_id"]:
            continue
        total += line["units_allocated"]
    return total


def cluster_scorecard(included, basis):
    rows = []
    for position in included:
        available = dv.available_units(position)
        rows.append(
            {
                "position": position,
                "covered": min(available, position["min_units"]),
                "sold": position["trailing_4wk_sales_units"],
                "base": position["trailing_4wk_sales_units"] + available,
                "min_units": position["min_units"],
            }
        )
    if basis == "SIMPLE_AVERAGE":
        in_stock_ratios = []
        sell_ratios = []
        for row in rows:
            if row["min_units"] == 0:
                in_stock_ratios.append(10000)
            else:
                in_stock_ratios.append(floor_div(row["covered"] * 10000, row["min_units"]))
            if row["base"] == 0:
                sell_ratios.append(0)
            else:
                sell_ratios.append(floor_div(row["sold"] * 10000, row["base"]))
        in_stock_bp = half_up_int(Decimal(sum(in_stock_ratios)) / Decimal(len(rows)))
        sell_bp = half_up_int(Decimal(sum(sell_ratios)) / Decimal(len(rows)))
    else:
        min_total = sum(r["min_units"] for r in rows)
        covered_total = sum(r["covered"] for r in rows)
        base_total = sum(r["base"] for r in rows)
        sold_total = sum(r["sold"] for r in rows)
        in_stock_bp = 10000 if min_total == 0 else floor_div(covered_total * 10000, min_total)
        sell_bp = 0 if base_total == 0 else floor_div(sold_total * 10000, base_total)

    deviation = 0
    total_sold = 0
    for row in rows:
        deviation += abs(allocated_units_for(row["position"]) - row["sold"])
        total_sold += row["sold"]
    if total_sold == 0:
        accuracy_bp = 0
    else:
        accuracy_bp = max(0, 10000 - floor_div(deviation * 10000, total_sold))
    return in_stock_bp, sell_bp, accuracy_bp
