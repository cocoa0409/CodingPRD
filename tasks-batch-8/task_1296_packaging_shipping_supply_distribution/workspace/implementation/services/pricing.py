"""calc_order_pricing + calc_freight_and_oversize (SCAFFOLD §1.3, PRD §3.4/§3.7)."""
from fractions import Fraction

import db
from errors import err_invalid_request
from util import (ceil_fraction, class_numeric, freight_class_for_density,
                  to_decimal, to_fraction, RATE_CENTS_PER_LB)

CUSTOM_PRINT_SURCHARGE_NUM = 115   # 1.15 multiplicative uplift, ceil per unit
CUSTOM_PRINT_SURCHARGE_DEN = 100
PALLET_REBATE_NUM = 3              # 3% per-pallet rebate, floor per pallet
PALLET_REBATE_DEN = 100

OVERSIZE_BASE_CENTS = 8900
OVERSIZE_ZONE_STEP_CENTS = 2500
OVERSIZE_ZONE_STEP_DISTANCE = 4
HEAVY_LINE_THRESHOLD_LBS = 150
HEAVY_LINE_CENTS = 5000


def order_lines_of(order_id, include_cancelled=False):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    if not include_cancelled:
        lines = [l for l in lines if l["status"] != "CANCELLED"]
    lines.sort(key=lambda l: (l["_seq"],))
    return lines


def select_quantity_break(product_id, qty):
    """Candidate breaks: min_qty <= qty, window contains logical clock.
    Winner: largest min_qty, tie -> smallest sort_seq, then earliest created."""
    now = db.now()
    candidates = []
    for b in db.quantity_breaks.values():
        if b["product_id"] != product_id:
            continue
        if b["min_qty"] > qty:
            continue
        if b["effective_from"] > now:
            continue
        if b["effective_to"] is not None and now >= b["effective_to"]:
            continue
        candidates.append(b)
    if not candidates:
        return None
    candidates.sort(key=lambda b: (-b["min_qty"], b["sort_seq"], b["_seq"]))
    return candidates[0]


def resolve_unit_price_cents(product, qty):
    """Pinned order: quantity break first, custom-print surcharge second."""
    brk = select_quantity_break(product["id"], qty)
    unit = brk["unit_price_cents"] if brk is not None else product["base_price_cents"]
    if product["is_custom_print"]:
        unit = (unit * CUSTOM_PRINT_SURCHARGE_NUM + CUSTOM_PRINT_SURCHARGE_DEN - 1) // CUSTOM_PRINT_SURCHARGE_DEN
    return unit


def line_freight_class(product):
    cls = freight_class_for_density(product["density_pcf"])
    if cls is None:
        raise err_invalid_request(
            "Product density_pcf below 1 lb/ft3 cannot be freight-rated.")
    return cls


def recompute_line_price(line):
    product = db.products[line["product_id"]]
    line["unit_price_cents"] = resolve_unit_price_cents(product, line["qty"])
    line["freight_class"] = line_freight_class(product)


def calc_order_pricing(order):
    """Recompute unit prices, subtotal, pallet discount, grand total.
    Uses currently stored oversize_surcharge_cents / freight_estimate_cents."""
    subtotal = 0
    pallet_discount = 0
    for line in order_lines_of(order["id"]):
        product = db.products[line["product_id"]]
        unit = resolve_unit_price_cents(product, line["qty"])
        line["unit_price_cents"] = unit
        line["freight_class"] = line_freight_class(product)
        subtotal += unit * line["qty"]
        pallets = line["qty"] // product["pallet_qty"]
        pallet_discount += pallets * (unit * PALLET_REBATE_NUM // PALLET_REBATE_DEN)
    order["subtotal_cents"] = subtotal
    order["pallet_discount_cents"] = pallet_discount
    order["grand_total_cents"] = (subtotal - pallet_discount
                                  + order["oversize_surcharge_cents"]
                                  + order["freight_estimate_cents"])


def _majority_warehouse_zone_distance(order, line_infos):
    """Zone distance = max(1, abs(ship_zone - zone of majority ship-from)).
    Majority = greatest total quantity among the line set; tie -> code ASC."""
    per_wh = {}
    for info in line_infos:
        wid = info["warehouse_id"]
        if wid is None:
            continue
        per_wh[wid] = per_wh.get(wid, 0) + info["qty"]
    if not per_wh:
        return 1
    best = max(per_wh.items(), key=lambda kv: (kv[1], _neg_code_rank(kv[0])))
    wh = db.warehouses[best[0]]
    return max(1, abs(order["ship_zone"] - wh["zone"]))


def _neg_code_rank(warehouse_id):
    # ascending code as tie-break inside max(): invert by using negative ord sum
    code = db.warehouses[warehouse_id]["code"]
    return tuple(-ord(c) for c in code)


def calc_freight_and_oversize(order, variant, decisions=None):
    """variant: 'provisional' (all non-CANCELLED lines, 11/10 uplift) or
    'final' (shipped lines with shipped quantities, no uplift).
    `decisions` (from the sourcing simulation) supplies the selected ship-from
    warehouse for each line before allocation is applied.
    Sets order oversize_surcharge_cents, freight_estimate_cents, grand_total."""
    selected_wh = {}
    if decisions:
        for d in decisions:
            if d["warehouse"] is not None:
                selected_wh[d["line"]["id"]] = d["warehouse"]["id"]

    def wh_of(line):
        return selected_wh.get(line["id"], line["allocated_warehouse_id"])

    if variant == "final":
        lines = [l for l in order_lines_of(order["id"]) if l["status"] == "SHIPPED"]
        line_infos = [{
            "qty": l["shipped_qty"],
            "weight": to_decimal(db.products[l["product_id"]]["weight_lbs_per_unit"]),
            "freight_class": l["freight_class"],
            "oversize": db.products[l["product_id"]]["oversize"],
            "warehouse_id": wh_of(l),
        } for l in lines]
    else:
        lines = order_lines_of(order["id"])
        line_infos = [{
            "qty": l["qty"],
            "weight": to_decimal(db.products[l["product_id"]]["weight_lbs_per_unit"]),
            "freight_class": l["freight_class"],
            "oversize": db.products[l["product_id"]]["oversize"],
            "warehouse_id": wh_of(l),
        } for l in lines]

    zone_distance = _majority_warehouse_zone_distance(order, line_infos)

    # --- oversize surcharge (mode a: tiered threshold on distance) ---
    surcharge = 0
    if any(i["oversize"] for i in line_infos):
        surcharge = OVERSIZE_BASE_CENTS
        if zone_distance >= OVERSIZE_ZONE_STEP_DISTANCE:
            surcharge += OVERSIZE_ZONE_STEP_CENTS
        if any(i["qty"] * i["weight"] > HEAVY_LINE_THRESHOLD_LBS for i in line_infos):
            surcharge += HEAVY_LINE_CENTS
    order["oversize_surcharge_cents"] = surcharge

    # --- freight estimate ---
    if not line_infos:
        freight = 0
    else:
        class_max = max((class_numeric(i["freight_class"]) for i in line_infos))
        class_max_str = None
        for i in line_infos:
            if class_numeric(i["freight_class"]) == class_max:
                class_max_str = i["freight_class"]
                break
        rate_cents = RATE_CENTS_PER_LB[class_max_str]
        weight = Fraction(0)
        for i in line_infos:
            weight += to_fraction(i["weight"]) * i["qty"]
        zone_factor = Fraction(100 + 12 * (zone_distance - 1), 100)
        amount = weight * rate_cents * zone_factor
        if variant == "provisional":
            amount *= Fraction(11, 10)
        freight = ceil_fraction(amount)
    order["freight_estimate_cents"] = freight

    order["grand_total_cents"] = (order["subtotal_cents"]
                                  - order["pallet_discount_cents"]
                                  + order["oversize_surcharge_cents"]
                                  + order["freight_estimate_cents"])
