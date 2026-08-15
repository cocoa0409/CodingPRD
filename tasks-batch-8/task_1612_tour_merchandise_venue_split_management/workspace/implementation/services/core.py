"""Shared business logic: size curves, stock derivation, commission, royalty,
licensing, session cash math, and serializers (PRD §3, SCAFFOLD Table 3).
"""

from datetime import timedelta
from decimal import Decimal

from clock import parse_iso
from db import DB
from errors import (
    ERR_INVALID_SIZE_CURVE,
    ERR_INVALID_COMMISSION_CONFIG,
    ERR_BUNDLE_COMPONENT_INVALID,
    ERR_VALIDATION,
    err,
)
from middleware import SIZES_SIZED, SIZE_ORDER, round_half_up_cents


# ---------------------------------------------------------------- size curves

def validate_size_curve(curve, error_id=ERR_INVALID_SIZE_CURVE, http=400):
    """Keys must be a subset of {S,M,L,XL}; weights non-negative integers;
    at least one weight positive (PRD §3.1)."""
    if not isinstance(curve, dict) or len(curve) == 0:
        raise err(error_id, http, "Size curve must be a non-empty object")
    total_positive = 0
    for k, v in curve.items():
        if k not in SIZES_SIZED:
            raise err(error_id, http, f"Size curve key {k} outside S/M/L/XL")
        if not isinstance(v, int) or isinstance(v, bool):
            raise err(error_id, http, "Size curve weights must be integers")
        if v < 0:
            raise err(error_id, http, "Size curve weights must be >= 0")
        if v > 0:
            total_positive += 1
    if total_positive == 0:
        raise err(error_id, http, "Size curve needs at least one positive weight")
    return {k: int(v) for k, v in curve.items()}


# ---------------------------------------------------------------- stock ledger

def compute_warehouse_stock(product_id):
    """warehouse_stock_by_size per PRD §3.3 / SCAFFOLD warehouse_stock_reconciliation.

    initial - dispatched/received WAREHOUSE-origin shipment lines
            - FULFILLED online order units (bundle: component OS units)
            + RETURN units credited at close-out (stored on allocations).
    """
    product = DB.products[product_id]
    stock = {k: int(v) for k, v in (product.get("initial_stock_by_size") or {}).items()}

    # WAREHOUSE-origin shipments in DISPATCHED or RECEIVED state.
    for sh in DB.shipments.values():
        if sh["origin_type"] != "WAREHOUSE":
            continue
        if sh["status"] not in ("DISPATCHED", "RECEIVED"):
            continue
        for line in sh["lines"]:
            if line["product_id"] == product_id:
                stock[line["size"]] = stock.get(line["size"], 0) - line["quantity"]

    # FULFILLED online orders.
    for order in DB.online_orders.values():
        if order["status"] != "FULFILLED":
            continue
        if order["product_id"] == product_id:
            p = DB.products[order["product_id"]]
            if p["product_type"] == "BUNDLE":
                for comp in p["bundle_components"]:
                    cid = comp["component_product_id"]
                    if cid == product_id:
                        stock["OS"] = stock.get("OS", 0) - comp["qty_per_bundle"] * order["quantity"]
            else:
                size_key = order["size"] if p["sized"] else "OS"
                stock[size_key] = stock.get(size_key, 0) - order["quantity"]
        else:
            # product may be a component of a fulfilled bundle order
            op = DB.products.get(order["product_id"])
            if op and op["product_type"] == "BUNDLE":
                for comp in op["bundle_components"]:
                    if comp["component_product_id"] == product_id:
                        stock["OS"] = stock.get("OS", 0) - comp["qty_per_bundle"] * order["quantity"]

    # RETURN units credited at close-out (persisted on the allocations).
    for alloc in DB.allocations.values():
        if alloc["product_id"] == product_id and alloc.get("quantity_returned"):
            stock[alloc["size"]] = stock.get(alloc["size"], 0) + alloc["quantity_returned"]

    return stock


def warehouse_available(product_id, size):
    return compute_warehouse_stock(product_id).get(size, 0)


# ---------------------------------------------------------------- allocations

def allocation_quantity_sold(allocation_id):
    return sum(
        r["quantity"]
        for r in DB.sale_records.values()
        if r["allocation_id"] == allocation_id and r["status"] == "ACTIVE"
    )


def allocation_on_hand(alloc):
    return (
        alloc["quantity_allocated"]
        - allocation_quantity_sold(alloc["id"])
        - alloc["quantity_returned"]
        - alloc["quantity_liquidated"]
        - alloc["quantity_shrunk"]
    )


def find_allocation(show_id, product_id, size):
    for a in DB.allocations.values():
        if a["show_id"] == show_id and a["product_id"] == product_id and a["size"] == size:
            return a
    return None


def size_curve_split(show, product, total_units):
    """Largest-remainder split per SCAFFOLD size_curve_split. Returns
    [(size, qty)] rows to create (only positive-weight sizes for sized products)."""
    if not product["sized"]:
        return [("OS", total_units)]
    curve = show["size_curve"] if show.get("size_curve") else DB.tours[show["tour_id"]]["default_size_curve"]
    W = sum(curve.values())
    rows = []
    floors = {}
    fracs = {}
    for size, w in curve.items():
        if w <= 0:
            continue
        raw = Decimal(total_units) * Decimal(w) / Decimal(W)
        fl = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
        floors[size] = fl
        fracs[size] = raw - Decimal(fl)
    remainder = total_units - sum(floors.values())
    # largest fractional part first; ties by ascending size order S<M<L<XL<OS
    order = sorted(floors.keys(), key=lambda s: (-fracs[s], SIZE_ORDER[s]))
    awarded = set(order[:remainder])
    for size in sorted(floors.keys(), key=lambda s: SIZE_ORDER[s]):
        qty = floors[size] + (1 if size in awarded else 0)
        rows.append((size, qty))
    return rows


# ---------------------------------------------------------------- commission

def commission_for(show, base_cents):
    """venue_commission rate_fn per SCAFFOLD: FLAT single rate, or marginal
    tiers with per-tier round-half-up then sum."""
    if base_cents <= 0:
        base_cents = max(0, base_cents)
    if show["commission_mode"] == "FLAT":
        return round_half_up_cents(base_cents * show["flat_commission_bps"])
    commission = 0
    prev_cap = 0
    for tier in show["commission_tiers"]:
        up_to = tier["up_to_cents"]
        if up_to is None:
            portion = max(0, base_cents - prev_cap)
        else:
            portion = max(0, min(base_cents, up_to) - prev_cap)
            prev_cap = up_to
        commission += round_half_up_cents(portion * tier["rate_bps"])
    return commission


# ---------------------------------------------------------------- royalty

def compute_royalty_arms(net_to_tour, std_bps, threshold, bonus_bps):
    """Tiered marginal artist royalty with per-segment round-half-up."""
    if net_to_tour <= threshold:
        return round_half_up_cents(net_to_tour * std_bps)
    return (
        round_half_up_cents(threshold * std_bps)
        + round_half_up_cents((net_to_tour - threshold) * (std_bps + bonus_bps))
    )


def compute_licensing_split(show_id, flat_per_unit, licensed_bps):
    """Per-LICENSED-product max(flat*qty, round_half_up(bps*gross/10000)); sum."""
    per_product = {}
    for r in DB.sale_records.values():
        if r["show_id"] != show_id or r["status"] != "ACTIVE":
            continue
        prod = DB.products[r["product_id"]]
        if prod["royalty_treatment"] != "LICENSED":
            continue
        agg = per_product.setdefault(r["product_id"], {"qty": 0, "gross": 0})
        agg["qty"] += r["quantity"]
        agg["gross"] += r["gross_cents"]
    total = 0
    for agg in per_product.values():
        flat_arm = flat_per_unit * agg["qty"]
        pct_arm = round_half_up_cents(licensed_bps * agg["gross"])
        total += max(flat_arm, pct_arm)
    return total


def online_royalty_figures(order, tour):
    """(artist_royalty, licensing) for the online_royalty calculation using the
    tour's CURRENT config (caller decides whether that is creation- or
    fulfillment-time)."""
    gross = order["gross_cents"]
    artist = round_half_up_cents(gross * tour["standard_rate_bps"])
    prod = DB.products[order["product_id"]]
    if prod["royalty_treatment"] == "LICENSED":
        licensing = max(
            tour["licensed_flat_per_unit_cents"] * order["quantity"],
            round_half_up_cents(tour["licensed_rate_bps"] * gross),
        )
    else:
        licensing = 0
    return artist, licensing


def royalty_snapshot_from_tour(tour):
    return {
        "pinned_standard_rate_bps": tour["standard_rate_bps"],
        "pinned_tier_threshold_cents": tour["tier_threshold_cents"],
        "pinned_tier_bonus_bps": tour["tier_bonus_bps"],
        "pinned_licensed_flat_per_unit_cents": tour["licensed_flat_per_unit_cents"],
        "pinned_licensed_rate_bps": tour["licensed_rate_bps"],
    }


def snapshot_matches_tour(settlement, tour):
    return (
        settlement["pinned_standard_rate_bps"] == tour["standard_rate_bps"]
        and settlement["pinned_tier_threshold_cents"] == tour["tier_threshold_cents"]
        and settlement["pinned_tier_bonus_bps"] == tour["tier_bonus_bps"]
        and settlement["pinned_licensed_flat_per_unit_cents"] == tour["licensed_flat_per_unit_cents"]
        and settlement["pinned_licensed_rate_bps"] == tour["licensed_rate_bps"]
    )


# ---------------------------------------------------------------- settlement math

def sessions_of_show(show_id):
    return [s for s in DB.sessions.values() if s["show_id"] == show_id]


def active_sales_of_show(show_id):
    return [r for r in DB.sale_records.values() if r["show_id"] == show_id and r["status"] == "ACTIVE"]


def compute_provisional_figures(show):
    """provisional gross = sum over sessions of (counted - float) + CARD gross."""
    cash_part = 0
    for s in sessions_of_show(show["id"]):
        counted = s.get("counted_cash_cents")
        if counted is not None:
            cash_part += counted - s["cash_float_cents"]
    card_part = sum(r["gross_cents"] for r in active_sales_of_show(show["id"]) if r["tender"] == "CARD")
    gross = cash_part + card_part
    return gross, commission_for(show, gross)


def compute_final_figures(settlement):
    """Recompute final register figures using the pinned royalty snapshot."""
    show = DB.shows[settlement["show_id"]]
    final_gross = sum(r["gross_cents"] for r in active_sales_of_show(show["id"]))
    commission_final = commission_for(show, final_gross)
    net = final_gross - commission_final
    royalty = compute_royalty_arms(
        net,
        settlement["pinned_standard_rate_bps"],
        settlement["pinned_tier_threshold_cents"],
        settlement["pinned_tier_bonus_bps"],
    )
    licensing = compute_licensing_split(
        show["id"],
        settlement["pinned_licensed_flat_per_unit_cents"],
        settlement["pinned_licensed_rate_bps"],
    )
    company = net - royalty - licensing
    settlement["final_gross_cents"] = final_gross
    settlement["venue_commission_final_cents"] = commission_final
    settlement["net_to_tour_cents"] = net
    settlement["artist_royalty_cents"] = royalty
    settlement["licensing_cents"] = licensing
    settlement["company_share_cents"] = company


def recompute_royalty_from_final(settlement):
    """Used by rebase-royalty when RECONCILED: keep final_gross/commission,
    recompute royalty/licensing/company with the new snapshot."""
    net = settlement["net_to_tour_cents"]
    royalty = compute_royalty_arms(
        net,
        settlement["pinned_standard_rate_bps"],
        settlement["pinned_tier_threshold_cents"],
        settlement["pinned_tier_bonus_bps"],
    )
    licensing = compute_licensing_split(
        settlement["show_id"],
        settlement["pinned_licensed_flat_per_unit_cents"],
        settlement["pinned_licensed_rate_bps"],
    )
    settlement["artist_royalty_cents"] = royalty
    settlement["licensing_cents"] = licensing
    settlement["company_share_cents"] = net - royalty - licensing


# ---------------------------------------------------------------- session cash

def session_expected_cash(session):
    return session["cash_float_cents"] + sum(
        r["gross_cents"]
        for r in DB.sale_records.values()
        if r["session_id"] == session["id"] and r["status"] == "ACTIVE" and r["tender"] == "CASH"
    )


def session_variance(session):
    counted = session.get("counted_cash_cents")
    if counted is None:
        return None
    return counted - session_expected_cash(session)


# ---------------------------------------------------------------- misc

def tour_royalty_payable(tour_id):
    total = 0
    for st in DB.settlements.values():
        show = DB.shows[st["show_id"]]
        if show["tour_id"] == tour_id and st["status"] == "FINALIZED":
            total += (st["artist_royalty_cents"] or 0) + (st["licensing_cents"] or 0)
    for o in DB.online_orders.values():
        if o["tour_id"] == tour_id and o["status"] == "FULFILLED":
            total += (o["artist_royalty_final_cents"] or 0) + (o["licensing_final_cents"] or 0)
    return total


def settlement_of_show(show_id):
    for st in DB.settlements.values():
        if st["show_id"] == show_id:
            return st
    return None


def calendar_date_of(show):
    return parse_iso(show["show_date"]).date()


def validate_commission_config(body, mode):
    """Returns (flat_bps, tiers) validated per PRD §3.2."""
    flat_bps = body.get("flat_commission_bps")
    tiers = body.get("commission_tiers")
    if mode == "FLAT":
        if flat_bps is None or not isinstance(flat_bps, int) or isinstance(flat_bps, bool) \
                or flat_bps < 0 or flat_bps > 10000:
            raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                      "FLAT show requires flat_commission_bps in 0..10000")
        if tiers is not None:
            raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                      "FLAT show must leave commission_tiers null")
        return flat_bps, None
    # TIERED
    if flat_bps is not None:
        raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                  "TIERED show must leave flat_commission_bps null")
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                  "TIERED show requires a non-empty commission_tiers list")
    null_caps = 0
    prev_cap = None
    for t in tiers:
        if not isinstance(t, dict):
            raise err(ERR_INVALID_COMMISSION_CONFIG, 400, "Tier must be an object")
        up_to = t.get("up_to_cents")
        rate = t.get("rate_bps")
        if up_to is None:
            null_caps += 1
            if t is not tiers[-1]:
                raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                          "Only the trailing tier may have null up_to_cents")
        else:
            if not isinstance(up_to, int) or isinstance(up_to, bool) or up_to < 0:
                raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                          "up_to_cents must be a non-negative integer or null")
            if null_caps > 0:
                raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                          "A numbered tier cannot follow the null tier")
            if prev_cap is not None and up_to <= prev_cap:
                raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                          "Tiers must be strictly ascending by up_to_cents")
            prev_cap = up_to
        if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0 or rate > 10000:
            raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                      "rate_bps must be in 0..10000")
    if null_caps != 1:
        raise err(ERR_INVALID_COMMISSION_CONFIG, 400,
                  "Exactly one trailing null up_to_cents tier is required")
    return None, [{"up_to_cents": t["up_to_cents"], "rate_bps": t["rate_bps"]} for t in tiers]


def validate_bundle_components(tour_id, components, self_id=None):
    """Components: list of {component_product_id, qty_per_bundle}; each REGULAR,
    non-sized, same tour, not the bundle itself, not another bundle."""
    if not isinstance(components, list) or len(components) == 0:
        raise err(ERR_BUNDLE_COMPONENT_INVALID, 400,
                  "BUNDLE product requires a non-empty bundle_components list")
    out = []
    for c in components:
        if not isinstance(c, dict):
            raise err(ERR_BUNDLE_COMPONENT_INVALID, 400, "Bundle component must be an object")
        cid = c.get("component_product_id")
        qty = c.get("qty_per_bundle")
        if cid is None or cid not in DB.products:
            raise err(ERR_BUNDLE_COMPONENT_INVALID, 400, "Bundle component product missing")
        if self_id is not None and cid == self_id:
            raise err(ERR_BUNDLE_COMPONENT_INVALID, 400, "Bundle may not reference itself")
        comp = DB.products[cid]
        if comp["product_type"] != "REGULAR":
            raise err(ERR_BUNDLE_COMPONENT_INVALID, 400, "Bundle components must be REGULAR")
        if comp["sized"]:
            raise err(ERR_BUNDLE_COMPONENT_INVALID, 400, "Bundle components must be non-sized")
        if comp["tour_id"] != tour_id:
            raise err(ERR_BUNDLE_COMPONENT_INVALID, 400,
                      "Bundle components must belong to the bundle's tour")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise err(ERR_BUNDLE_COMPONENT_INVALID, 400,
                      "qty_per_bundle must be a positive integer")
        out.append({"component_product_id": cid, "qty_per_bundle": qty})
    return out


def validate_stock_map(stock_map, sized):
    """initial_stock_by_size: sized -> keys subset of {S,M,L,XL}; non-sized -> OS only;
    values >= 0 integers."""
    if stock_map is None:
        return {}
    if not isinstance(stock_map, dict):
        raise err(ERR_VALIDATION, 400, "initial_stock_by_size must be an object")
    allowed = set(SIZES_SIZED) if sized else {"OS"}
    for k, v in stock_map.items():
        if k not in allowed:
            raise err(ERR_VALIDATION, 400, f"initial_stock_by_size key {k} not allowed")
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise err(ERR_VALIDATION, 400,
                      "initial_stock_by_size values must be non-negative integers")
    return {k: int(v) for k, v in stock_map.items()}


LEAD_TIME = timedelta(hours=48)
