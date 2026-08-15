"""Business logic: pricing engine, cold-chain math, invoicing, returns/credits,
crate ledger, merchandising, settlement, territory valuation, par generation.

All monetary math uses Decimal with ROUND_HALF_UP per PRD §2.7; per-unit
regulated prices carry 3 decimal places, intermediates are never rounded early.
"""

from datetime import timedelta
from decimal import Decimal

from clock import now, today_date, parse_iso, format_iso_ms
from db import DB
from errors import (
    ERR_PRICING_PERIOD_NOT_FOUND,
    ERR_RETURN_NOT_ELIGIBLE,
    err,
)
from util import (
    dec, round_half_up_int, round_half_up_3dp, round_half_up_2dp,
    ceil_div, base_fields, event_fields, touch, apply_changes, parse_date,
)

# --- calculation constants (SCAFFOLD §1.3) ---
CWT_LBS = 100
FUEL_TIERS = ((500, Decimal("0.045")), (400, Decimal("0.030")), (300, Decimal("0.015")))
DISCOUNT_TIER_1_MIN = 200000
DISCOUNT_TIER_1_RATE = Decimal("0.015")
DISCOUNT_TIER_2_MIN = 500000
DISCOUNT_TIER_2_RATE = Decimal("0.025")
EXCURSION_THRESHOLD_TENTHS_F = 400
CRITICAL_SPIKE_TENTHS_F = 500
BREACH_THRESHOLD_MINUTES = Decimal("45.0")
DOCK_BUFFER_MINUTES = 15
CREDIT_PCT = {"OUT_OF_CODE": Decimal("1.0"), "PULL_POLICY": Decimal("1.0"),
              "DAMAGED": Decimal("0.5"), "COLD_CHAIN": Decimal("1.0")}
DRIVER_PER_MIN_CENTS = 50
COMMISSION_TIER_1_MIN = 500000
COMMISSION_TIER_1_RATE = Decimal("0.24")
COMMISSION_TIER_2_MIN = 1200000
COMMISSION_TIER_2_RATE = Decimal("0.26")
COMMISSION_BASE_RATE = Decimal("0.22")
TERRITORY_MULTIPLIER = 10

WEEKDAY_PAR_FIELDS = ["par_mon", "par_tue", "par_wed", "par_thu",
                      "par_fri", "par_sat", "par_sun"]


# =============================================================================
# Pricing (regulated_milk_unit_price)
# =============================================================================

def period_for_month(month):
    for p in DB.pricing_periods.values():
        if p["month"] == month:
            return p
    return None


def select_announcement(period):
    """ACTIVE FINAL if one exists, else ACTIVE PROVISIONAL, else None."""
    if period is None:
        return None, None
    if period.get("current_final_id"):
        a = DB.price_announcements.get(period["current_final_id"])
        if a is not None and a["status"] == "ACTIVE":
            return a, "FINAL"
    if period.get("current_provisional_id"):
        a = DB.price_announcements.get(period["current_provisional_id"])
        if a is not None and a["status"] == "ACTIVE":
            return a, "PROVISIONAL"
    return None, None


def fuel_surcharge_rate(diesel_index_cents):
    for tier_min, rate in FUEL_TIERS:
        if diesel_index_cents >= tier_min:
            return rate
    return Decimal("0")


def regulated_unit_price(product, announcement):
    """3dp round-half-up per-unit price; milk_cost intermediate unrounded."""
    milk_cost = (
        dec(announcement["class_i_base_cents_per_cwt"]
            + announcement["processor_assessment_cents_per_cwt"]
            + announcement["hauling_cents_per_cwt"])
        * dec(product["weight_lbs_per_unit"]) / dec(CWT_LBS)
    )
    f = fuel_surcharge_rate(announcement["diesel_index_cents"])
    unit = milk_cost * (Decimal(1) + f) + dec(product["margin_cents_per_unit"])
    return round_half_up_3dp(unit)


def unit_price_for(product, month):
    """Price a product for the given YYYY-MM month.
    Returns (unit_price_decimal_3dp_or_exact, basis or None)."""
    if not product["regulated"]:
        return dec(product["list_price_cents"]), None
    period = period_for_month(month)
    ann, basis = select_announcement(period)
    if ann is None:
        return None, None
    return regulated_unit_price(product, ann), basis


# =============================================================================
# Invoice math (invoice_line_rounding + invoice_volume_discount)
# =============================================================================

def volume_discount(subtotal_cents):
    if subtotal_cents >= DISCOUNT_TIER_2_MIN:
        rate = DISCOUNT_TIER_2_RATE
    elif subtotal_cents >= DISCOUNT_TIER_1_MIN:
        rate = DISCOUNT_TIER_1_RATE
    else:
        rate = Decimal("0")
    discount = round_half_up_int(dec(subtotal_cents) * rate)
    return discount, rate


def invoice_amounts(subtotal_cents):
    discount, _rate = volume_discount(subtotal_cents)
    return subtotal_cents, discount, subtotal_cents - discount


def recompute_invoice_status_and_order(inv):
    """amount_due -> status; re-derive the order's payment_status; open AR."""
    inv["amount_due_cents"] = (
        inv["total_cents"] - inv["credits_applied_cents"] - inv["payments_applied_cents"]
    )
    if inv["status"] == "OPEN" and inv["amount_due_cents"] == 0:
        inv["status"] = "SETTLED"
    touch(inv)
    order = DB.orders.get(inv["order_id"])
    if order is not None:
        if inv["status"] == "VOID":
            new_ps = "UNINVOICED"
        elif inv["status"] == "SETTLED":
            new_ps = "PAID"
        elif inv["credits_applied_cents"] + inv["payments_applied_cents"] > 0:
            new_ps = "PARTIALLY_PAID"
        else:
            new_ps = "INVOICED"
        apply_changes(order, {"payment_status": new_ps})
    refresh_store_open_ar(inv["store_id"])


def refresh_store_open_ar(store_id):
    """open_ar_cents = SUM(amount_due_cents) over the store's OPEN invoices."""
    store = DB.stores.get(store_id)
    if store is None:
        return
    total = sum(
        i["amount_due_cents"]
        for i in DB.invoices.values()
        if i["store_id"] == store_id and i["status"] == "OPEN"
    )
    apply_changes(store, {"open_ar_cents": total})


def refresh_store_crates(store):
    store["crate_balance"] = crate_balance_of(store["id"])
    store["deposit_liability_cents"] = store["crate_balance"] * store["crate_deposit_cents"]


def crate_balance_of(store_id):
    drops = pickups = adjustments = 0
    for c in DB.crate_transactions.values():
        if c["store_id"] != store_id:
            continue
        if c["kind"] == "DROP":
            drops += c["crate_count"]
        elif c["kind"] == "PICKUP":
            pickups += c["crate_count"]
        else:  # ADJUSTMENT (signed)
            adjustments += c["crate_count"]
    return drops - pickups + adjustments


# =============================================================================
# True-up repricing (invoice_true_up)
# =============================================================================

def run_true_up(period, final_announcement):
    """Reprice OPEN PROVISIONAL-basis invoices of the period's month,
    in invoice created_at ASC order (insertion sequence breaks clock ties)."""
    targets = [
        inv for inv in DB.invoices.values()
        if inv["invoice_month"] == period["month"]
        and inv["pricing_basis"] == "PROVISIONAL"
        and inv["status"] == "OPEN"
    ]
    targets.sort(key=lambda i: i["_seq"])
    touched_stores = set()
    for inv in targets:
        order = DB.orders.get(inv["order_id"])
        old_total = inv["total_cents"]
        subtotal = 0
        for line in order["lines"]:
            product = DB.products.get(line["product_id"])
            if product["regulated"]:
                price = regulated_unit_price(product, final_announcement)
            else:
                price = dec(product["list_price_cents"])
            line["unit_price_cents"] = float(price)
            line["line_amount_cents"] = round_half_up_int(
                dec(line["delivered_units"]) * price
            )
            subtotal += line["line_amount_cents"]
        subtotal, discount, total = invoice_amounts(subtotal)
        apply_changes(order, {"subtotal_cents": subtotal})
        inv["subtotal_cents"] = subtotal
        inv["discount_cents"] = discount
        inv["total_cents"] = total
        inv["true_up_delta_cents"] = total - old_total
        inv["pricing_basis"] = "FINAL"
        recompute_invoice_status_and_order(inv)
        touched_stores.add(inv["store_id"])


# =============================================================================
# Returns (return_credit_amount)
# =============================================================================

def returned_units_so_far(order_id, product_id, exclude_return_id=None):
    """Cumulative returned units for (order, product) over non-REJECTED returns."""
    total = 0
    for r in DB.returns.values():
        if r["order_id"] != order_id or r["product_id"] != product_id:
            continue
        if exclude_return_id is not None and r["id"] == exclude_return_id:
            continue
        if r["status"] == "REJECTED":
            continue
        total += r["quantity_units"]
    return total


def current_basis_unit_credit(product, route):
    """CURRENT basis: price of the product as of the scan date (clock date)."""
    if not product["regulated"]:
        return dec(product["list_price_cents"])
    month = today_date().strftime("%Y-%m")
    period = period_for_month(month)
    ann, _basis = select_announcement(period)
    if ann is None:
        raise err(
            ERR_PRICING_PERIOD_NOT_FOUND,
            "No announcement exists for the scan month",
        )
    return regulated_unit_price(product, ann)


def create_return_record(order, pickup_trip_id, product_id, quantity_units,
                         reason_code, scanned_code_date, initial_status,
                         system_created=False):
    """Shared return-construction path for manual scans and the QA cascade."""
    store = DB.stores[order["store_id"]]
    route = DB.routes[store["route_id"]]
    product = DB.products[product_id]
    scan_date = parse_date(scanned_code_date)
    days_to_expiry = (scan_date - today_date()).days

    # Eligibility per reason_code (return_credit_amount step 2). COLD_CHAIN is
    # system-created only; DAMAGED accepts any day count.
    if not system_created:
        if reason_code == "COLD_CHAIN":
            raise err(ERR_RETURN_NOT_ELIGIBLE, "COLD_CHAIN returns are system-created only")
        if reason_code == "OUT_OF_CODE" and not (days_to_expiry < 0):
            raise err(ERR_RETURN_NOT_ELIGIBLE, "OUT_OF_CODE requires days_to_expiry_at_scan < 0")
        if reason_code == "PULL_POLICY" and not (0 <= days_to_expiry <= store["pull_window_days"]):
            raise err(ERR_RETURN_NOT_ELIGIBLE, "PULL_POLICY requires 0 <= days <= pull_window_days")

    credit_pct = CREDIT_PCT[reason_code]
    line = next(
        (l for l in order["lines"] if l["product_id"] == product_id),
        None,
    )
    if route["credit_price_basis"] == "ORIGINAL":
        unit_credit = dec(line["unit_price_cents"])
    else:  # CURRENT
        unit_credit = current_basis_unit_credit(product, route)
    credit_amount = round_half_up_int(dec(quantity_units) * unit_credit * credit_pct)

    r = base_fields()
    r.update({
        "order_id": order["id"],
        "store_id": order["store_id"],
        "pickup_trip_id": pickup_trip_id,
        "product_id": product_id,
        "quantity_units": quantity_units,
        "reason_code": reason_code,
        "scanned_code_date": scanned_code_date,
        "days_to_expiry_at_scan": days_to_expiry,
        "credit_pct": float(credit_pct),
        "unit_credit_cents": float(unit_credit),
        "credit_amount_cents": credit_amount,
        "status": initial_status,
    })
    DB.returns[r["id"]] = r
    return r


# =============================================================================
# Credit memos
# =============================================================================

def create_credit_memo(ret):
    m = base_fields()
    m.update({
        "return_id": ret["id"],
        "store_id": ret["store_id"],
        "invoice_id": None,
        "amount_cents": ret["credit_amount_cents"],
        "applied_cents": 0,
        "remaining_cents": ret["credit_amount_cents"],
        "status": "ISSUED",
        "_applications": [],  # [(invoice_id, amount)] for void compensation
    })
    DB.credit_memos[m["id"]] = m
    return m


def apply_memo_to_invoice(memo, invoice):
    """applied = min(remaining, amount_due); updates memo, invoice, order, store."""
    applied = min(memo["remaining_cents"], invoice["amount_due_cents"])
    if applied > 0:
        memo["applied_cents"] += applied
        memo["remaining_cents"] -= applied
        memo["invoice_id"] = invoice["id"]
        memo["_applications"].append((invoice["id"], applied))
        invoice["credits_applied_cents"] += applied
    memo["status"] = "APPLIED" if memo["remaining_cents"] == 0 else (
        "PARTIALLY_APPLIED" if memo["applied_cents"] > 0 else "ISSUED"
    )
    touch(memo)
    recompute_invoice_status_and_order(invoice)
    return applied


def auto_apply_memo(memo, own_order_id):
    """Target = own order's invoice if still OPEN, else the store's oldest OPEN
    invoice (created_at ASC, insertion order breaks ties)."""
    target = None
    for inv in DB.invoices.values():
        if inv["order_id"] == own_order_id and inv["status"] == "OPEN":
            target = inv
            break
    if target is None:
        candidates = [
            i for i in DB.invoices.values()
            if i["store_id"] == memo["store_id"] and i["status"] == "OPEN"
        ]
        candidates.sort(key=lambda i: i["_seq"])
        target = candidates[0] if candidates else None
    if target is not None:
        apply_memo_to_invoice(memo, target)
    else:
        touch(memo)


def approve_return_side_effects(ret):
    """APPROVED -> CREDITED: create the memo and auto-apply it."""
    memo = create_credit_memo(ret)
    auto_apply_memo(memo, ret["order_id"])
    ret["status"] = "CREDITED"
    touch(ret)
    return memo


# =============================================================================
# Cold chain (temperature_excursion)
# =============================================================================

def box_readings(trip_id):
    rs = [r for r in DB.temperature_readings.values()
          if r["trip_id"] == trip_id and r["zone"] == "BOX"]
    rs.sort(key=lambda r: (r["recorded_at"], r["_seq"]))
    return rs


def recompute_cold_chain(trip, closing_dt=None):
    """Step-function accrual over BOX readings (left-closed intervals); the
    trailing above-threshold reading accrues until closing_dt when given
    (trip completion clock). Breach = cumulative >= 45.0 OR any BOX > 500."""
    readings = box_readings(trip["id"])
    total_seconds = Decimal(0)
    spike = False
    for i, r in enumerate(readings):
        if r["temp_tenths_f"] > CRITICAL_SPIKE_TENTHS_F:
            spike = True
        if r["temp_tenths_f"] > EXCURSION_THRESHOLD_TENTHS_F:
            if i + 1 < len(readings):
                delta = parse_iso(readings[i + 1]["recorded_at"]) - parse_iso(r["recorded_at"])
                total_seconds += dec(delta.total_seconds())
            elif closing_dt is not None:
                delta = closing_dt - parse_iso(r["recorded_at"])
                if delta.total_seconds() > 0:
                    total_seconds += dec(delta.total_seconds())
    minutes = round_half_up_2dp(total_seconds / dec(60))
    breach = bool(spike or minutes >= BREACH_THRESHOLD_MINUTES)
    apply_changes(trip, {
        "excursion_minutes": float(minutes),
        "cold_chain_breach": breach,
    })


# =============================================================================
# Trip load helpers
# =============================================================================

def line_case_count(line):
    """Case count per line: present as `cases` once gained (manual orders at
    creation; generated orders at confirm), otherwise derived on the fly."""
    if "cases" in line:
        return line["cases"]
    product = DB.products.get(line["product_id"])
    return ceil_div(line["quantity_units"], product["units_per_case"])


def order_case_count(order):
    return sum(line_case_count(l) for l in order["lines"])


def order_delivered_case_count(order):
    total = 0
    for l in order["lines"]:
        if "delivered_units" in l:
            product = DB.products.get(l["product_id"])
            total += ceil_div(l["delivered_units"], product["units_per_case"])
    return total


def refresh_trip_loaded_cases(trip):
    """Reserved load = SUM of cases over PLANNED and CONFIRMED orders."""
    total = sum(
        order_case_count(o)
        for o in DB.orders.values()
        if o["trip_id"] == trip["id"]
        and o["fulfillment_status"] in ("PLANNED", "CONFIRMED")
    )
    apply_changes(trip, {"loaded_cases": total})


def trip_orders(trip_id):
    return [o for o in DB.orders.values() if o["trip_id"] == trip_id]


# =============================================================================
# QA breach cascade (TruckTrip adjudicate CONFIRM_BREACH, 5 hops)
# =============================================================================

def run_breach_cascade(trip):
    delivered = [
        o for o in trip_orders(trip["id"])
        if o["fulfillment_status"] == "DELIVERED"
    ]
    delivered.sort(key=lambda o: o["_seq"])
    for order in delivered:
        for line in order["lines"]:
            line["cold_chain_flag"] = True
        touch(order)
    for order in delivered:
        invoice = next(
            (i for i in DB.invoices.values() if i["order_id"] == order["id"]),
            None,
        )
        for line in order["lines"]:
            # Hop 2: system return, immediately APPROVED; the standard system
            # transition then moves it APPROVED -> CREDITED.
            ret = create_return_record(
                order=order,
                pickup_trip_id=trip["id"],
                product_id=line["product_id"],
                quantity_units=line["delivered_units"],
                reason_code="COLD_CHAIN",
                scanned_code_date=line["scanned_code_date"],
                initial_status="APPROVED",
                system_created=True,
            )
            # Hop 3: credit memo in ISSUED.
            memo = create_credit_memo(ret)
            # Hop 4: auto-apply to the order's own invoice (still OPEN by
            # construction; otherwise the store's oldest OPEN invoice).
            if invoice is not None and invoice["status"] == "OPEN":
                apply_memo_to_invoice(memo, invoice)
            else:
                auto_apply_memo(memo, order["id"])
            ret["status"] = "CREDITED"
            touch(ret)
        # Hop 5: payment_status re-derived inside apply path; ensure even when
        # no invoice application occurred.
        if invoice is not None:
            inv = invoice
            if inv["status"] == "VOID":
                new_ps = "UNINVOICED"
            elif inv["status"] == "SETTLED":
                new_ps = "PAID"
            elif inv["credits_applied_cents"] + inv["payments_applied_cents"] > 0:
                new_ps = "PARTIALLY_PAID"
            else:
                new_ps = "INVOICED"
            apply_changes(order, {"payment_status": new_ps})


# =============================================================================
# Weekly settlement (driver_weekly_settlement)
# =============================================================================

def weekly_settlement(driver_id, week_start_date):
    week_end = week_start_date + timedelta(days=7)

    def in_window(d):
        return week_start_date <= d < week_end

    gross = 0
    for o in DB.orders.values():
        if o["fulfillment_status"] != "DELIVERED":
            continue
        trip = DB.trips.get(o["trip_id"])
        if trip is None or trip["driver_id"] != driver_id:
            continue
        if not in_window(parse_date(o["service_date"])):
            continue
        gross += sum(l.get("line_amount_cents", 0) for l in o["lines"])

    credits = 0
    for r in DB.returns.values():
        if r["status"] not in ("APPROVED", "CREDITED"):
            continue
        order = DB.orders.get(r["order_id"])
        if order is None:
            continue
        trip = DB.trips.get(order["trip_id"])
        if trip is None or trip["driver_id"] != driver_id:
            continue
        if not in_window(parse_date(order["service_date"])):
            continue
        credits += r["credit_amount_cents"]

    net = gross - credits
    if net >= COMMISSION_TIER_1_MIN and net <= COMMISSION_TIER_2_MIN:
        rate = COMMISSION_TIER_1_RATE
    elif net > COMMISSION_TIER_2_MIN:
        rate = COMMISSION_TIER_2_RATE
    else:
        rate = COMMISSION_BASE_RATE
    commission = round_half_up_int(dec(net) * rate)

    labor_minutes = 0
    for s in DB.merchandising_sessions.values():
        if s["driver_id"] != driver_id or s["status"] != "CLOSED":
            continue
        check_in_date = parse_iso(s["check_in_at"]).date()
        if in_window(check_in_date):
            labor_minutes += s["minutes"]
    driver_labor = labor_minutes * DRIVER_PER_MIN_CENTS

    return {
        "gross_sales_cents": gross,
        "credits_cents": credits,
        "net_sales_cents": net,
        "commission_rate": float(rate),
        "commission_cents": commission,
        "labor_minutes": labor_minutes,
        "driver_labor_cents": driver_labor,
        "settlement_cents": commission + driver_labor,
    }


# =============================================================================
# Territory valuation (territory_valuation)
# =============================================================================

def territory_value(route_id, trailing_weeks):
    clock_date = today_date()
    lower = clock_date - timedelta(days=7 * trailing_weeks)  # exclusive
    upper = clock_date  # inclusive

    route_store_ids = {
        s["id"] for s in DB.stores.values() if s["route_id"] == route_id
    }
    window_orders = [
        o for o in DB.orders.values()
        if o["store_id"] in route_store_ids
        and o["fulfillment_status"] == "DELIVERED"
        and lower < parse_date(o["service_date"]) <= upper
    ]
    gross = sum(
        l.get("line_amount_cents", 0)
        for o in window_orders for l in o["lines"]
    )
    order_ids = {o["id"] for o in window_orders}
    credits = sum(
        r["credit_amount_cents"]
        for r in DB.returns.values()
        if r["order_id"] in order_ids and r["status"] in ("APPROVED", "CREDITED")
    )
    net = gross - credits
    avg_weekly = round_half_up_int(dec(net) / dec(trailing_weeks))
    return TERRITORY_MULTIPLIER * avg_weekly


# =============================================================================
# Standing par generation (standing_par_generation)
# =============================================================================

def generate_orders_for_trip(trip):
    route = DB.routes[trip["route_id"]]
    stores = [
        s for s in DB.stores.values()
        if s["route_id"] == route["id"] and s["status"] == "ACTIVE"
    ]
    stores.sort(key=lambda s: s["_seq"])
    weekday_idx = parse_date(trip["service_date"]).weekday()  # Mon=0
    par_field = WEEKDAY_PAR_FIELDS[weekday_idx]

    created_order_ids = []
    skipped_store_ids = []
    for store in stores:
        lines = []
        pars = [
            p for p in DB.standing_pars.values()
            if p["store_id"] == store["id"] and p["status"] == "ACTIVE"
        ]
        pars.sort(key=lambda p: p["_seq"])
        for p in pars:
            qty = p[par_field]
            if qty <= 0:
                continue
            product = DB.products.get(p["product_id"])
            if product is None or product["status"] != "ACTIVE":
                continue  # DISCONTINUED products silently excluded
            lines.append({"product_id": p["product_id"], "quantity_units": qty})
        if not lines:
            skipped_store_ids.append(store["id"])
            continue
        existing = [
            o for o in DB.orders.values()
            if o["trip_id"] == trip["id"] and o["store_id"] == store["id"]
            and o["fulfillment_status"] != "CANCELLED"
        ]
        if existing:
            skipped_store_ids.append(store["id"])
            continue  # idempotent re-run
        cases = 0
        for l in lines:
            product = DB.products[l["product_id"]]
            cases += ceil_div(l["quantity_units"], product["units_per_case"])
        if trip["loaded_cases"] + cases > trip["case_capacity"]:
            skipped_store_ids.append(store["id"])
            continue
        svc_date = parse_date(trip["service_date"])
        from util import date_to_iso_minute
        win_start = date_to_iso_minute(svc_date, store["dock_open_min"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        win_end = date_to_iso_minute(svc_date, store["dock_close_min"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        o = base_fields()
        o.update({
            "store_id": store["id"],
            "trip_id": trip["id"],
            "service_date": trip["service_date"],
            "source": "PAR_GENERATED",
            "lines": lines,
            "delivery_window_start": win_start,
            "delivery_window_end": win_end,
            "fulfillment_status": "PLANNED",
            "payment_status": "UNINVOICED",
            "subtotal_cents": 0,
        })
        DB.orders[o["id"]] = o
        trip["loaded_cases"] += cases
        touch(trip)
        created_order_ids.append(o["id"])
    return created_order_ids, skipped_store_ids
