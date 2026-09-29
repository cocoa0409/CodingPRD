"""Calculation engine (SCAFFOLD §calculations, PRD §3.4 / §3.5 / §3.6 / §3.9)."""
from decimal import Decimal

import store
from errors import fail
from store import D, cents, lb, round_half_up

# ---- constants -------------------------------------------------------------
MIN_UNIT_PRICE_CENTS_PER_LB = 1

DISCOUNT_TIER_1_MIN_LB = D("2000")
DISCOUNT_TIER_1_PCT = D("0.015")
DISCOUNT_TIER_2_MIN_LB = D("10000")
DISCOUNT_TIER_2_PCT = D("0.030")

BASE_FUEL_PCT = D("0.025")
SURGE_FUEL_PCT = D("0.040")
REBATE_TIER_1_MIN_CENTS = 500000
REBATE_TIER_1_PCT = D("0.010")
REBATE_TIER_2_MIN_CENTS = 1500000
REBATE_TIER_2_PCT = D("0.025")
SURGE_WINDOWS = (("2026-03-15", "2026-04-15"), ("2026-11-15", "2026-12-31"))

ALLERGEN_WEIGHT = {
    "NONE": D("0.0"),
    "SOY": D("0.20"),
    "EGG": D("0.35"),
    "DAIRY": D("0.40"),
    "GLUTEN": D("0.55"),
    "TREE_NUT": D("0.90"),
    "PEANUT": D("1.00"),
}
GF_CONFLICT_PENALTY = D("15.00")
TIER_AMBER_MIN = D("25.00")
TIER_RED_MIN = D("60.00")

TRAILER_COMPARTMENT_LB = D("48000")
COMPARTMENT_LB = D("24000")
COMPARTMENT_COUNT = 2

BILLABLE_HOURS_THRESHOLD = D("4.0")
INCLUDED_HOURS = D("2.0")
TIER1_HOURS = D("8.0")
TIER1_RATE_CENTS = D("18500")
TIER2_RATE_CENTS = D("14500")
RED_TIER_MULTIPLIER = D("1.250")

SPLIT_ACROSS_LOTS_ALLOWED = False


# ---- helpers ---------------------------------------------------------------
def order_lines_of(order_id):
    rows = [l for l in store.all_of("order_lines") if l["order_id"] == order_id]
    return store.sort_created(rows)


def contract_lines_of(contract_id):
    rows = [l for l in store.all_of("contract_lines") if l["contract_id"] == contract_id]
    return store.sort_created(rows)


def stops_of(route_id):
    rows = [s for s in store.all_of("stops") if s["route_id"] == route_id]
    return sorted(rows, key=lambda s: (s["window_start_at"], s["created_at"], s["_seq"]))


# ---- calculations.contract_line_settlement_price ---------------------------
def prevailing_quote(index_code, obs_date):
    best = None
    for q in store.all_of("quotes"):
        if q["index_code"] != index_code:
            continue
        if q["effective_on"] > obs_date:
            continue
        if best is None or q["effective_on"] > best["effective_on"]:
            best = q
    return best


def observation_date(order, contract, variant):
    if variant == "final_delivery_date":
        if contract is not None and contract["pricing_mode"] == "DELIVERY_DATE_INDEX":
            return order["delivered_on"]
        return order["order_placed_on"]
    return order["order_placed_on"]


def settlement_price(order, line, variant):
    """Returns (unit_price_cents, contract_line_id, quote_used)."""
    product = store.get("products", line["product_id"])
    contract = store.get("contracts", order["contract_id"]) if order["contract_id"] else None
    cl = None
    if contract is not None:
        for candidate in contract_lines_of(contract["id"]):
            if candidate["product_id"] == line["product_id"]:
                cl = candidate
                break
    if (order["contract_id"] is None or cl is None
            or contract is None or contract["status"] not in ("ACTIVE", "EXHAUSTED")):
        return product["list_price_cents_per_lb"], None, None

    obs_date = observation_date(order, contract, variant)
    if product["index_code"] == "NONE":
        raw = product["list_price_cents_per_lb"] + cl["basis_cents_per_lb"]
        return max(MIN_UNIT_PRICE_CENTS_PER_LB, raw), cl["id"], None

    if obs_date is None:
        fail("ERR_INDEX_QUOTE_MISSING", "No observation date available for index pricing")
    q = prevailing_quote(product["index_code"], obs_date)
    if q is None:
        fail("ERR_INDEX_QUOTE_MISSING",
             "No published quote for %s effective on or before the observation date"
             % product["index_code"])
    raw = q["price_cents_per_lb"] + cl["basis_cents_per_lb"]
    capped = raw if cl["cap_cents_per_lb"] is None else min(raw, cl["cap_cents_per_lb"])
    return max(MIN_UNIT_PRICE_CENTS_PER_LB, capped), cl["id"], q


# ---- calculations.order_line_extended_price -------------------------------
def discount_rate(quantity_lb):
    q = D(quantity_lb)
    if q < DISCOUNT_TIER_1_MIN_LB:
        return D("0.000")
    if q < DISCOUNT_TIER_2_MIN_LB:
        return DISCOUNT_TIER_1_PCT
    return DISCOUNT_TIER_2_PCT


def extended_cents(quantity_lb, unit_price_cents):
    gross = D(quantity_lb) * D(unit_price_cents)
    net = gross * (D(1) - discount_rate(quantity_lb))
    return cents(net)


# ---- calculations.order_total_settlement -----------------------------------
def _surge_bounds():
    from validate import parse_instant
    out = []
    for start, end in SURGE_WINDOWS:
        out.append((store.day_of(parse_instant(start, "surge")),
                    store.day_of(parse_instant(end, "surge"))))
    return out


def in_surge_window(requested_delivery_on):
    if requested_delivery_on is None:
        return False
    day = store.day_of(requested_delivery_on)
    for start, end in _surge_bounds():
        if start <= day <= end:
            return True
    return False


def order_totals(subtotal, requested_delivery_on, tech_attach_fee_cents):
    surge = in_surge_window(requested_delivery_on)
    fuel_pct = SURGE_FUEL_PCT if surge else BASE_FUEL_PCT
    fuel = cents(D(subtotal) * fuel_pct)
    rebate_base = subtotal + fuel
    if surge:
        rebate_pct = D("0.000")
    elif rebate_base < REBATE_TIER_1_MIN_CENTS:
        rebate_pct = D("0.000")
    elif rebate_base < REBATE_TIER_2_MIN_CENTS:
        rebate_pct = REBATE_TIER_1_PCT
    else:
        rebate_pct = REBATE_TIER_2_PCT
    rebate = cents(D(subtotal) * rebate_pct)
    total = subtotal + fuel + tech_attach_fee_cents - rebate
    return {
        "surge_window": surge,
        "fuel_surcharge_cents": fuel,
        "volume_rebate_cents": rebate,
        "total_cents": total,
    }


def price_order(order, variant):
    """Pure pricing pass: returns the per-line and order-level figures."""
    lines = order_lines_of(order["id"])
    per_line = []
    subtotal = 0
    for ln in lines:
        unit, cl_id, quote = settlement_price(order, ln, variant)
        ext = extended_cents(ln["quantity_lb"], unit)
        subtotal += ext
        per_line.append({
            "line": ln,
            "unit_price_cents": unit,
            "contract_line_id": cl_id,
            "extended_cents": ext,
            "quote": quote,
        })
    totals = order_totals(subtotal, order["requested_delivery_on"],
                          order["tech_attach_fee_cents"])
    totals["subtotal_cents"] = subtotal
    return per_line, totals


def apply_pricing(order, per_line, totals):
    for item in per_line:
        ln = item["line"]
        changed = (ln["unit_price_cents"] != item["unit_price_cents"]
                   or ln["extended_cents"] != item["extended_cents"]
                   or ln["contract_line_id"] != item["contract_line_id"])
        ln["unit_price_cents"] = item["unit_price_cents"]
        ln["extended_cents"] = item["extended_cents"]
        ln["contract_line_id"] = item["contract_line_id"]
        if changed:
            store.bump(ln)
    order["subtotal_cents"] = totals["subtotal_cents"]
    order["surge_window"] = totals["surge_window"]
    order["fuel_surcharge_cents"] = totals["fuel_surcharge_cents"]
    order["volume_rebate_cents"] = totals["volume_rebate_cents"]
    order["total_cents"] = totals["total_cents"]


# ---- calculations.customer_open_exposure -----------------------------------
def recompute_open_exposure(customer, bump_on_change=True):
    total = 0
    for o in store.all_of("orders"):
        if o["customer_id"] != customer["id"]:
            continue
        if o["pricing_status"] in ("PROVISIONAL", "FINAL"):
            total += o["total_cents"]
    changed = customer["open_exposure_cents"] != total
    customer["open_exposure_cents"] = total
    status_before = customer["status"]
    if customer["status"] == "ACTIVE" and total > customer["credit_limit_cents"]:
        customer["status"] = "CREDIT_HOLD"
    if customer["status"] == "CREDIT_HOLD" and total <= customer["credit_limit_cents"]:
        customer["status"] = "ACTIVE"
    if bump_on_change and (changed or status_before != customer["status"]):
        store.bump(customer)
    return total


# ---- calculations.customer_allergen_risk_score ----------------------------
IN_FLIGHT_STATES = ("NEW", "ALLOCATED", "ROUTED", "LOADED")
AUDITED_STATES = ("DELIVERED", "SHORT_SHIPPED")


def risk_input_lines(customer_id, states):
    rows = []
    for o in store.all_of("orders"):
        if o["customer_id"] != customer_id:
            continue
        if o["fulfillment_status"] == "CANCELLED":
            continue
        if o["fulfillment_status"] not in states:
            continue
        for ln in order_lines_of(o["id"]):
            if ln["allocation_status"] == "RELEASED":
                continue
            rows.append(ln)
    return rows


def recompute_risk_score(customer, variant):
    states = IN_FLIGHT_STATES if variant == "exposure_provisional" else AUDITED_STATES
    lines = risk_input_lines(customer["id"], states)
    if not lines:
        score = D("0.00")
    else:
        weighted = D(0)
        pounds = D(0)
        has_gluten = False
        for ln in lines:
            product = store.get("products", ln["product_id"])
            klass = product["allergen_class"]
            weighted += ALLERGEN_WEIGHT[klass] * D(ln["quantity_lb"])
            pounds += D(ln["quantity_lb"])
            if klass == "GLUTEN":
                has_gluten = True
        raw = (weighted / pounds) * D(100)
        penalty = GF_CONFLICT_PENALTY if (
            customer["allergen_program"] == "GLUTEN_FREE_CERTIFIED" and has_gluten) else D(0)
        score = min(D("100.00"), round_half_up(raw + penalty, 2))
    tier = "GREEN" if score < TIER_AMBER_MIN else ("AMBER" if score < TIER_RED_MIN else "RED")
    changed = (customer["allergen_risk_score"] != score or customer["risk_tier"] != tier)
    customer["allergen_risk_score"] = score
    customer["risk_tier"] = tier
    if changed:
        store.bump(customer)
    return score


# ---- calculations.lot_rotation_selector -----------------------------------
def select_lot(line, on_hand_override=None):
    product = store.get("products", line["product_id"])
    clock = store.clock_date()
    need = D(line["quantity_lb"])
    candidates = []
    for lot in store.all_of("lots"):
        if lot["product_id"] != line["product_id"]:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        on_hand = on_hand_override.get(lot["id"]) if on_hand_override is not None else None
        if on_hand is None:
            on_hand = D(lot["quantity_on_hand_lb"])
        if lb(on_hand) < lb(need):
            continue
        if store.days_between(clock, lot["expires_on"]) < product["min_rotation_days"]:
            continue
        zone = store.get("zones", lot["zone_id"])
        if zone is None or zone["status"] != "OPEN":
            continue
        if zone["allergen_class"] != product["allergen_class"]:
            continue
        candidates.append((lot, on_hand))
    if not candidates:
        fail("ERR_NO_ELIGIBLE_LOT", "No eligible lot for order line %s" % line["id"])
    candidates.sort(key=lambda item: (item[0]["expires_on"], -item[1],
                                      item[0]["created_at"], item[0]["_seq"]))
    return candidates[0][0]


# ---- calculations.bulk_silo_fill_plan -------------------------------------
def find_silo(customer_id, product_id):
    for s in store.all_of("silos"):
        if s["customer_id"] == customer_id and s["product_id"] == product_id:
            return s
    return None


def bulk_fill_plan(order, line):
    silo = find_silo(order["customer_id"], line["product_id"])
    if silo is None:
        fail("ERR_NO_SILO_FOR_PRODUCT",
             "No silo registered for this customer and SKU")
    if silo["product_id"] != line["product_id"]:
        fail("ERR_ENTITY_LINK_MISMATCH", "Silo product differs from the order line product")
    headroom = D(silo["capacity_lb"]) - D(silo["residual_lb"])
    qty = D(line["quantity_lb"])
    if line["contract_line_id"] is None:
        contract_room = qty
    else:
        cl = store.get("contract_lines", line["contract_line_id"])
        contract_room = max(D(0), D(cl["volume_committed_lb"]) - D(cl["volume_drawn_lb"]) + qty)
    fillable = min(headroom, qty, TRAILER_COMPARTMENT_LB, contract_room)
    if lb(fillable) < lb(qty):
        fail("ERR_SILO_HEADROOM_INSUFFICIENT", "Silo headroom insufficient for this line")
    if lb(fillable) < lb(silo["min_fill_lb"]):
        fail("ERR_BULK_FILL_BELOW_MIN", "Computed fill is below the silo minimum")
    return silo


# ---- calculations.route_load_waterfall ------------------------------------
def stop_pounds(stop):
    order = store.get("orders", stop["order_id"])
    total = D(0)
    if order is None:
        return total
    for ln in order_lines_of(order["id"]):
        total += D(ln["quantity_lb"])
    return total


def route_waterfall(route, participating=None, enforce=True):
    if participating is None:
        participating = [s for s in stops_of(route["id"]) if s["status"] != "CANCELLED"]
    load = D(0)
    for stop in participating:
        load += stop_pounds(stop)
    if enforce:
        remaining = [COMPARTMENT_LB for _ in range(COMPARTMENT_COUNT)]
        for stop in participating:
            need = stop_pounds(stop)
            for idx in range(COMPARTMENT_COUNT):
                take = min(need, remaining[idx])
                remaining[idx] -= take
                need -= take
            if need > 0:
                fail("ERR_ROUTE_CAPACITY_EXCEEDED",
                     "The trailer compartments cannot absorb the stop pounds")
        if lb(load) > lb(route["vehicle_capacity_lb"]):
            fail("ERR_ROUTE_CAPACITY_EXCEEDED",
                 "Planned load exceeds the vehicle capacity")
    util = round_half_up(D(load) / D(route["vehicle_capacity_lb"]) * D(100), 2)
    return len(participating), lb(load), util


def apply_waterfall(route, participating=None, enforce=True):
    count, load, util = route_waterfall(route, participating, enforce)
    route["stop_count"] = count
    route["planned_load_lb"] = load
    route["utilization_pct"] = util
    return count, load, util


# ---- calculations.tech_support_attach_fee ---------------------------------
def attach_fee(hours_logged, risk_tier):
    billable = max(D(0), D(hours_logged) - INCLUDED_HOURS)
    tier1 = min(billable, TIER1_HOURS)
    tier2 = max(D(0), billable - TIER1_HOURS)
    gross = tier1 * TIER1_RATE_CENTS + tier2 * TIER2_RATE_CENTS
    multiplier = RED_TIER_MULTIPLIER if risk_tier == "RED" else D("1.000")
    return cents(gross * multiplier)


# ---- zone aggregate ------------------------------------------------------
def recompute_zone_on_hand(zone):
    if zone is None:
        return
    total = D(0)
    for lot in store.all_of("lots"):
        if lot["zone_id"] != zone["id"]:
            continue
        if lot["status"] in ("AVAILABLE", "QUARANTINED"):
            total += D(lot["quantity_on_hand_lb"])
    if lb(zone["on_hand_lb"]) != lb(total):
        zone["on_hand_lb"] = lb(total)
        store.bump(zone)
    else:
        zone["on_hand_lb"] = lb(total)


def recompute_contract_volumes(contract):
    if contract is None:
        return
    committed = D(0)
    drawn = D(0)
    for cl in contract_lines_of(contract["id"]):
        committed += D(cl["volume_committed_lb"])
        drawn += D(cl["volume_drawn_lb"])
    contract["committed_volume_lb"] = lb(committed)
    contract["drawn_volume_lb"] = lb(drawn)
