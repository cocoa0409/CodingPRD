"""Pricing, promo resolution, margin, capacity, suggestion, cull, credit calculations (scaffold §1.3)."""
from decimal import Decimal, ROUND_HALF_UP
import db
import clock
from util import touch

CASHLESS_FEE_BPS = 275
CULL_MIN_UNITS_4WK = 2
CULL_WINDOW_DAYS = 28
CLAIM_WINDOW_DAYS = 30
SHORT_DATE_DAYS = 14
DEEP_SHORT_DATE_DAYS = 7

WEEKDAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def round_half_up_decimal(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_div(numer, denom):
    """round_half_up(numer / denom) for non-negative/negative ints via Decimal."""
    return round_half_up_decimal(Decimal(numer) / Decimal(denom))


# ---------------- Promotions ----------------

def promo_effective_cents(promo, base_price_cents):
    if promo["discount_type"] == "PERCENT_OFF":
        return round_half_up_decimal(Decimal(base_price_cents) * Decimal(promo["discount_value"]) / Decimal(100))
    return promo["discount_value"]  # CENTS_OFF


def resolve_discount_per_case(product, operator_id, now_dt):
    """promo_price_resolution: EXCLUSIVE winner or sum of STACKABLE."""
    eligible = []
    for p in db.promotions.values():
        if p["status"] != "ACTIVE":
            continue
        if p["product_id"] != product["id"]:
            continue
        if p.get("operator_id") is not None and p["operator_id"] != operator_id:
            continue
        if not (p["starts_at_dt"] <= now_dt < p["ends_at_dt"]):
            continue
        eligible.append(p)
    if not eligible:
        return 0
    exclusives = [p for p in eligible if p["stacking_class"] == "EXCLUSIVE"]
    if exclusives:
        # winner: max effective_cents; tie-break earliest created_at ASC (never id)
        best = None
        best_val = None
        for p in exclusives:
            eff = promo_effective_cents(p, product["base_price_cents"])
            if best is None or eff > best_val or (eff == best_val and p["created_at"] < best["created_at"]):
                best = p
                best_val = eff
        return best_val
    return sum(promo_effective_cents(p, product["base_price_cents"]) for p in eligible)


def price_order_lines(order):
    """order_pricing (pinned rounding: round per line per case, then sum).
    Mutates order lines with unit_price_cents/line_total_cents; sets order totals."""
    now_dt = clock.now()
    order_total = 0
    promo_discount = 0
    for line in order["lines"]:
        product = db.products[line["product_id"]]
        discount = resolve_discount_per_case(product, order["operator_id"], now_dt)
        unit_price = max(0, product["base_price_cents"] - discount)
        line_total = unit_price * line["quantity_cases"]
        line["unit_price_cents"] = unit_price
        line["line_total_cents"] = line_total
        order_total += line_total
        promo_discount += product["base_price_cents"] * line["quantity_cases"] - line_total
    order["order_total_cents"] = order_total
    order["promo_discount_cents"] = promo_discount


def active_planogram_for_location(location_id):
    for pg in db.planograms.values():
        if pg["location_id"] == location_id and pg["status"] == "ACTIVE":
            return pg
    return None


def compute_provisional_margin(order):
    """margin_per_vend provisional variant (at submit)."""
    planogram = active_planogram_for_location(order["location_id"])
    slot_by_product = {s["product_id"]: s for s in planogram["slots"]} if planogram else {}
    total_units = 0
    retail_value = 0
    for line in order["lines"]:
        product = db.products[line["product_id"]]
        units = product["case_pack_qty"] * line["quantity_cases"]
        total_units += units
        slot = slot_by_product.get(line["product_id"])
        retail_value += slot["vend_price_cents"] * product["case_pack_qty"] * line["quantity_cases"]
    if total_units == 0:
        order["provisional_margin_per_vend_cents"] = 0
        return
    order["provisional_margin_per_vend_cents"] = round_half_up_div(
        retail_value - order["order_total_cents"], total_units
    )


# ---------------- Capacity ----------------

def capacity_consumption(route_id, date_str):
    firm = 0
    optimistic = 0
    for o in db.orders.values():
        if o["route_id"] != route_id or o["requested_delivery_date"] != date_str:
            continue
        if o["fulfillment_status"] == "CONFIRMED":
            firm += o["total_cases"]
            optimistic += o["total_cases"]
        elif o["fulfillment_status"] == "SUBMITTED":
            optimistic += o["total_cases"]
    return firm, optimistic


# ---------------- Telemetry / suggestion ----------------

def latest_event_item_map(location_id):
    """Per product_id: (recorded_at, created_at, event, item) for the latest event
    containing an item for that product. Tie-break: later created_at."""
    best = {}
    for ev in db.telemetry_events.values():
        if ev["location_id"] != location_id:
            continue
        for item in ev["items"]:
            pid = item["product_id"]
            key = (ev["recorded_at_dt"], ev["created_at"])
            if pid not in best or key > best[pid][0]:
                best[pid] = (key, ev, item)
    return best


def rebuild_projection(location):
    """CASCADE B link 1: rebuild on_hand_projection from the event being ingested."""
    latest = latest_event_item_map(location["id"])
    projection = []
    for pid, (_, ev, item) in latest.items():
        projection.append({
            "product_id": pid,
            "on_hand_units": item["on_hand_units"],
            "as_of_event_id": ev["id"],
        })
    location["on_hand_projection"] = projection
    touch(location)


def suggested_lines(location):
    """suggested_replenishment_qty: slots of ACTIVE planogram with cull_flag false."""
    planogram = active_planogram_for_location(location["id"])
    if planogram is None:
        return None, []  # caller gates ERR_NO_ACTIVE_PLANOGRAM
    latest = latest_event_item_map(location["id"])
    lines = []
    for slot in planogram["slots"]:
        if slot.get("cull_flag"):
            continue
        pid = slot["product_id"]
        if pid not in latest:
            continue
        _, _, item = latest[pid]
        raw = slot["par_level_units"] - item["on_hand_units"]
        if raw <= 0:
            continue
        product = db.products.get(pid)
        if product is None:
            continue
        cases = -(-raw // product["case_pack_qty"])  # ceil division
        lines.append({"product_id": pid, "quantity_cases": cases})
    return planogram, lines


def refresh_suggested_draft(location):
    """CASCADE B link 2: recompute lines of the location's latest DRAFT TELEMETRY_SUGGESTED order."""
    candidates = [
        o for o in db.orders.values()
        if o["location_id"] == location["id"]
        and o["fulfillment_status"] == "DRAFT"
        and o["source"] == "TELEMETRY_SUGGESTED"
    ]
    if not candidates:
        return
    order = max(candidates, key=lambda o: o["created_at"])
    _, lines = suggested_lines(location)
    total_cases = sum(l["quantity_cases"] for l in lines)
    # Preserve pinned pricing fields only if lines present (draft is unpinned anyway)
    order["lines"] = lines
    order["total_cases"] = total_cases
    touch(order)


# ---------------- Cull ----------------

def cull_evaluate(planogram):
    """weekly_velocity_cull over the planogram's location telemetry."""
    now_dt = clock.now()
    from datetime import timedelta
    window_start = now_dt - timedelta(days=CULL_WINDOW_DAYS)
    velocity = {}
    products_seen = set()
    for ev in db.telemetry_events.values():
        if ev["location_id"] != planogram["location_id"]:
            continue
        if not (window_start <= ev["recorded_at_dt"] <= now_dt):
            continue
        for item in ev["items"]:
            pid = item["product_id"]
            products_seen.add(pid)
            velocity[pid] = velocity.get(pid, 0) + item["units_vended"]
    for slot in planogram["slots"]:
        pid = slot["product_id"]
        if pid not in products_seen:
            slot["cull_flag"] = False  # insufficient data -> not culled
        else:
            slot["cull_flag"] = velocity.get(pid, 0) < CULL_MIN_UNITS_4WK
    touch(planogram)


# ---------------- Credit claims ----------------

def line_credit(order_line, quantity_units, pct, case_pack_qty):
    """round_half_up(unit_price_cents * quantity_units * pct / case_pack_qty) per line."""
    numer = order_line["unit_price_cents"] * quantity_units * pct
    return round_half_up_decimal(Decimal(numer) / Decimal(case_pack_qty * 100))


def auto_apply_credit(operator, claim=None):
    """CASCADE link 2 (claim approve): apply operator balance to oldest OPEN order.
    Returns nothing; mutates operator/claim/order per cascade rules."""
    open_orders = [
        o for o in db.orders.values()
        if o["operator_id"] == operator["id"] and o["settlement_status"] == "OPEN"
    ]
    if not open_orders:
        return
    open_orders.sort(key=lambda o: o["created_at"])
    order = open_orders[0]
    x = min(operator["credit_balance_cents"], order["amount_due_cents"])
    if x <= 0:
        return
    operator["credit_balance_cents"] -= x
    touch(operator)
    if claim is not None:
        claim["applied_cents"] += x
    order["credit_applied_cents"] += x
    order["amount_due_cents"] -= x
    if order["amount_due_cents"] == 0:
        order["settlement_status"] = "SETTLED"  # auto-settle; settled_tender stays null
    touch(order)
