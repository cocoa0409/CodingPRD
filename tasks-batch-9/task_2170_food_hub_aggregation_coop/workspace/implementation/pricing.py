"""Allocation waterfall and the two-variant pricing rollup (PRD 3.5 / 3.8)."""

import domain
from constants import (MARGIN_BP_CEILING, MIN_ORDER_MARGIN_CENTS,
                       TIER_1_UPPER_EXCLUSIVE_CENTS, TIER_2_UPPER_EXCLUSIVE_CENTS,
                       TIER_3_UPPER_EXCLUSIVE_CENTS)
from store import apply_bp, base_record, ceil_div, db, sorted_records, touch

PROVISIONAL_STATUSES = ("RESERVED", "STAGED")
FINAL_STATUSES = ("DELIVERED",)


# ---------------------------------------------------------------------------
# calculations.hub_margin_tier_selection
# ---------------------------------------------------------------------------

def select_margin_tier(producer_subtotal_cents):
    """Selected once from the PRE-margin subtotal; never re-selected from the
    order total after the margin has been added."""
    if producer_subtotal_cents < TIER_1_UPPER_EXCLUSIVE_CENTS:
        return 1800
    if producer_subtotal_cents < TIER_2_UPPER_EXCLUSIVE_CENTS:
        return 1500
    if producer_subtotal_cents < TIER_3_UPPER_EXCLUSIVE_CENTS:
        return 1250
    return 1000


def compute_money(entries):
    """entries: ordered list of (valuation_quantity, producer_unit_price_cents).

    Rounding order is pinned: round per allocation, THEN sum.
    """
    amounts = [q * price for (q, price) in entries]
    subtotal = sum(amounts)
    if not entries:
        return {
            "amounts": [], "margins": [], "buyer_amounts": [],
            "subtotal": 0, "tier_bp": 0, "raw_margin": 0,
            "hub_margin": 0, "order_total": 0,
        }
    tier_bp = select_margin_tier(subtotal)
    margins = [apply_bp(a, tier_bp) for a in amounts]
    raw_margin = sum(margins)
    hub_margin = raw_margin
    if raw_margin < MIN_ORDER_MARGIN_CENTS:
        hub_margin = MIN_ORDER_MARGIN_CENTS
        top_up = hub_margin - raw_margin
        target = 0
        for i in range(1, len(amounts)):
            if amounts[i] > amounts[target]:
                target = i
        margins[target] += top_up
    buyer_amounts = [amounts[i] + margins[i] for i in range(len(amounts))]
    return {
        "amounts": amounts,
        "margins": margins,
        "buyer_amounts": buyer_amounts,
        "subtotal": subtotal,
        "tier_bp": tier_bp,
        "raw_margin": raw_margin,
        "hub_margin": hub_margin,
        "order_total": subtotal + hub_margin,
    }


# ---------------------------------------------------------------------------
# calculations.order_pricing_rollup
# ---------------------------------------------------------------------------

def _valuation_set(order, variant):
    allocs = domain.order_allocations(order["id"])
    if variant == "final":
        return [a for a in allocs if a["status"] in FINAL_STATUSES]
    return [a for a in allocs if a["status"] in PROVISIONAL_STATUSES]


def _valuation_quantity(alloc, variant):
    if variant == "final":
        return alloc["delivered_quantity"]
    return alloc["quantity"]


def run_rollup(order, variant, fresh_allocation_ids=None):
    """Recompute every money and pallet rollup on the order, its lines and its
    allocations from the surviving rows."""
    fresh = fresh_allocation_ids or set()
    allocs = _valuation_set(order, variant)
    entries = [(_valuation_quantity(a, variant), a["producer_unit_price_cents"]) for a in allocs]
    money = compute_money(entries)

    for idx, alloc in enumerate(allocs):
        before = (alloc["margin_bp"], alloc["producer_amount_cents"],
                  alloc["hub_margin_cents"], alloc["buyer_amount_cents"])
        alloc["margin_bp"] = money["tier_bp"]
        alloc["producer_amount_cents"] = money["amounts"][idx]
        alloc["hub_margin_cents"] = money["margins"][idx]
        alloc["buyer_amount_cents"] = money["buyer_amounts"][idx]
        after = (alloc["margin_bp"], alloc["producer_amount_cents"],
                 alloc["hub_margin_cents"], alloc["buyer_amount_cents"])
        if after != before and alloc["id"] not in fresh:
            touch(alloc)

    # allocations that contribute nothing carry no money
    for alloc in domain.order_allocations(order["id"]):
        if alloc["status"] in ("REVERSED", "SHORT_CLOSED"):
            before = (alloc["producer_amount_cents"], alloc["hub_margin_cents"],
                      alloc["buyer_amount_cents"])
            alloc["producer_amount_cents"] = 0
            alloc["hub_margin_cents"] = 0
            alloc["buyer_amount_cents"] = 0
            if before != (0, 0, 0) and alloc["id"] not in fresh:
                touch(alloc)

    order["producer_subtotal_cents"] = money["subtotal"]
    order["margin_tier_bp"] = money["tier_bp"]
    order["hub_margin_cents"] = money["hub_margin"]
    order["order_total_cents"] = money["order_total"]

    pallets = 0
    for alloc in allocs:
        product = db.products.get(alloc["product_id"])
        if product is not None:
            pallets += ceil_div(alloc["quantity"], product["units_per_pallet"])
    order["order_pallets"] = pallets

    by_line = {}
    for idx, alloc in enumerate(allocs):
        bucket = by_line.setdefault(alloc["order_line_id"], [0, 0])
        bucket[0] += money["amounts"][idx]
        bucket[1] += money["margins"][idx]

    for line in domain.order_lines(order["id"]):
        producer_cents, margin_cents = by_line.get(line["id"], (0, 0))
        before = (line["line_producer_cents"], line["line_margin_cents"], line["line_total_cents"])
        line["line_producer_cents"] = producer_cents
        line["line_margin_cents"] = margin_cents
        line["line_total_cents"] = producer_cents + margin_cents
        after = (line["line_producer_cents"], line["line_margin_cents"], line["line_total_cents"])
        if after != before:
            touch(line)

    return money


# ---------------------------------------------------------------------------
# calculations.line_allocation_waterfall
# ---------------------------------------------------------------------------

def _price_ceiling_ok(product, line):
    price = product["producer_unit_price_cents"]
    worst_margin = apply_bp(price, MARGIN_BP_CEILING)
    return price + worst_margin <= line["max_unit_price_cents"]


def _candidates(line, order, tentative):
    out = []
    for product in db.products.values():
        if product["status"] != "LISTED":
            continue
        if product["commodity_code"] != line["commodity_code"]:
            continue
        if product["storage_class"] != line["storage_class"]:
            continue
        if product["unit_of_measure"] != line["unit_of_measure"]:
            continue
        available = max(0, product["quantity_offered"]
                        - product["quantity_committed"]
                        - tentative.get(product["id"], 0))
        if available <= 0:
            continue
        start = product["offer_window_start"]
        end = product["offer_window_end"]
        if start is None or end is None:
            continue
        requested = order["requested_delivery_date"]
        if not (start <= requested < end):
            continue
        producer = db.producers.get(product["producer_id"])
        if producer is None:
            continue
        if producer["onboarding_status"] != "ACTIVE":
            continue
        if not domain.compliance_ok(producer):
            continue
        if not _price_ceiling_ok(product, line):
            continue
        out.append((product, available))
    return out


def _rank_key(pair):
    product, _available = pair
    producer = db.producers.get(product["producer_id"])
    patronage = producer["patronage_volume_cents"] if producer else 0
    return (product["producer_unit_price_cents"], patronage,
            product["created_at"], product["_seq"])


def plan_allocations(order):
    """Physical pass.  Returns (plan, per_line_allocated) without persisting."""
    lines = domain.order_lines(order["id"])
    tentative = {}
    plan = []
    per_line = {}
    for line in lines:
        remaining = line["quantity_requested"]
        candidates = sorted(_candidates(line, order, tentative), key=_rank_key)
        for product, available in candidates:
            if remaining <= 0:
                break
            take = min(remaining, available)
            if take <= 0:
                continue
            plan.append({
                "line": line,
                "product": product,
                "quantity": take,
                "producer_unit_price_cents": product["producer_unit_price_cents"],
            })
            tentative[product["id"]] = tentative.get(product["id"], 0) + take
            remaining -= take
        per_line[line["id"]] = line["quantity_requested"] - remaining
    return plan, per_line


def commit_allocations(order, plan, per_line):
    """Persist the planned split, then run the provisional money pass."""
    fresh = set()
    touched_products = {}
    for item in plan:
        alloc = base_record({
            "order_line_id": item["line"]["id"],
            "product_id": item["product"]["id"],
            "quantity": item["quantity"],
            "producer_unit_price_cents": item["producer_unit_price_cents"],
            "margin_bp": 0,
            "producer_amount_cents": 0,
            "hub_margin_cents": 0,
            "buyer_amount_cents": 0,
            "delivered_quantity": 0,
            "rejected_quantity": 0,
            "producer_charge_cents": 0,
            "hub_absorbed_cents": 0,
            "staged_temp_c": None,
            "temp_excursion": False,
            "status": "RESERVED",
        })
        db.allocations[alloc["id"]] = alloc
        fresh.add(alloc["id"])
        product = item["product"]
        product["quantity_committed"] += item["quantity"]
        domain.recompute_product_available(product)
        touched_products[product["id"]] = product

    for product in touched_products.values():
        touch(product)

    for line in domain.order_lines(order["id"]):
        allocated = per_line.get(line["id"], 0)
        line["quantity_allocated"] = allocated
        if allocated == 0:
            line["status"] = "PENDING"
        elif allocated < line["quantity_requested"]:
            line["status"] = "SHORT"
        else:
            line["status"] = "ALLOCATED"
        touch(line)

    run_rollup(order, "provisional", fresh_allocation_ids=fresh)
    return fresh
