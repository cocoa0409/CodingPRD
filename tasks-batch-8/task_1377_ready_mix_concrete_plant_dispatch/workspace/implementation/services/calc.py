"""Calculation rules (scaffold 1.3): batch weights, w/c ratio, charges,
strength acceptance, credit exposure, order fulfillment, truck selector."""

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import stores

WATER_LB_PER_GAL = Decimal("8.34")


def d(v):
    return Decimal(str(v))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return d(value).quantize(q, rounding=ROUND_HALF_UP)


def round_int(value):
    return int(round_half_up(value, 0))


# ------------------------------------------------------------ batch ticket

def compute_batch_ticket(mix, qty_yd3, extra_batch_water_gal):
    """batch_weights_and_dosing: pinned order, round-per-line then sum."""
    qty = d(qty_yd3)
    cement_lb = round_half_up(d(mix["cement_content_lb_per_yd3"]) * qty, 0)
    base_water_lb = round_half_up(d(mix["design_wc_ratio"]) * cement_lb, 0)
    extra_water_lb = round_half_up(WATER_LB_PER_GAL * d(extra_batch_water_gal or 0), 1)
    batch_water_lb = base_water_lb + extra_water_lb
    admixture_doses = []
    total = Decimal("0")
    for adm in mix.get("admixtures") or []:
        dose = round_half_up(d(adm["dose_oz_per_cwt"]) * cement_lb / Decimal(100), 1)
        admixture_doses.append({
            "admixture_code": adm["admixture_code"],
            "dose_oz": float(dose),
        })
        total += dose
    return {
        "cement_lb": int(cement_lb),
        "batch_water_lb": float(batch_water_lb),
        "extra_batch_water_gal": extra_batch_water_gal or 0,
        "admixture_doses": admixture_doses,
        "total_admixture_oz": float(total),
        "base_water_lb": base_water_lb,
        "extra_water_lb": extra_water_lb,
    }


# -------------------------------------------------------------- w/c ratio

def compute_actual_wc(ticket, load_id):
    """actual_wc_ratio: batch water + 8.34 * sum(site gallons); 3 decimals."""
    additions = [w for w in stores["water_additions"].values() if w["load_id"] == load_id]
    site_gal = sum((d(w["gallons"]) for w in additions), Decimal("0"))
    total_water_lb = d(ticket["batch_water_lb"]) + WATER_LB_PER_GAL * site_gal
    ratio = round_half_up(total_water_lb / d(ticket["cement_lb"]), 3)
    return float(ratio)


# ------------------------------------------------------------------ money

def select_index(plant_id, month):
    """Greatest effective_month <= given month; None when none published."""
    best = None
    for idx in stores["cement_price_indices"].values():
        if idx["plant_id"] != plant_id:
            continue
        if idx["effective_month"] <= month and (best is None or idx["effective_month"] > best["effective_month"]):
            best = idx
    return best


def is_saturday(pour_date):
    return datetime.strptime(pour_date, "%Y-%m-%d").date().weekday() == 5


def escalated_base(price_list, plant_id, month):
    idx = select_index(plant_id, month)
    if idx is None:
        ratio = Decimal("1.0")
    else:
        ratio = d(idx["index_points"]) / d(price_list["escalation_base_index_points"])
    return round_int(d(price_list["base_price_per_yd3_cents"]) * ratio)


def compute_provisional_quote(order, price_list):
    """PROVISIONAL variant: ordered qty, confirm-month index, wait=0,
    short-load=0, Saturday surcharge on the concrete line alone."""
    confirm_month = clock.now().strftime("%Y-%m")
    base = escalated_base(price_list, order["plant_id"], confirm_month)
    concrete = round_int(d(order["qty_yd3"]) * base)
    saturday = 0
    if is_saturday(order["pour_date"]):
        saturday = round_int(d(concrete) * d(price_list["saturday_surcharge_pct"]))
    return base, concrete + saturday


def compute_final_charge(load, order, price_list):
    """FINAL variant: discharged qty, pour-month index, actual wait,
    short-load, Saturday surcharge (excludes wait). Per-line round then sum."""
    pour_month = order["pour_date"][:7]
    base = escalated_base(price_list, order["plant_id"], pour_month)
    concrete = round_int(d(load["discharged_qty_yd3"]) * base)
    short_load = 0
    if d(load["discharged_qty_yd3"]) < d(price_list["min_load_yd3"]):
        short_load = int(price_list["short_load_fee_cents"])
    billable_wait = max(0, int(load["on_site_minutes"]) - int(price_list["wait_free_minutes"]))
    wait_fee = min(billable_wait * int(price_list["wait_rate_per_minute_cents"]),
                   int(price_list["wait_fee_cap_cents"]))
    saturday = 0
    if is_saturday(order["pour_date"]):
        saturday = round_int(d(concrete + short_load) * d(price_list["saturday_surcharge_pct"]))
    final = concrete + short_load + wait_fee + saturday
    return {
        "escalated_base_cents": base,
        "concrete_cents": concrete,
        "short_load_fee_cents": short_load,
        "wait_fee_cents": wait_fee,
        "saturday_fee_cents": saturday,
        "final_charge_cents": final,
    }


# ------------------------------------------------------------- fulfillment

def recompute_delivered_qty(order):
    """order_fulfillment: sum discharged over COMPLETED loads (1 decimal)."""
    total = sum(
        (d(l["discharged_qty_yd3"]) for l in stores["loads"].values()
         if l["order_id"] == order["id"] and l["status"] == "COMPLETED"),
        Decimal("0"),
    )
    order["delivered_qty_yd3"] = float(round_half_up(total, 1))
    return order["delivered_qty_yd3"]


# --------------------------------------------------------------- exposure

def recompute_credit_exposure(customer):
    """credit_exposure: forward-looking; HOLD iff exposure >= credit_limit."""
    order_sum = sum(
        (int(o["provisional_total_cents"] or 0) for o in stores["orders"].values()
         if o["customer_id"] == customer["id"]
         and o["delivery_status"] in ("CONFIRMED", "SCHEDULED", "IN_PROGRESS")),
        0,
    )
    invoice_sum = sum(
        (int(inv["total_cents"] or 0) for inv in stores["invoices"].values()
         if inv["customer_id"] == customer["id"]
         and inv["status"] in ("DRAFT", "ISSUED", "DISPUTED")),
        0,
    )
    exposure = order_sum + invoice_sum
    changed = (
        customer["credit_exposure_cents"] != exposure
        or customer["credit_status"] != ("HOLD" if exposure >= customer["credit_limit_cents"] else "GOOD")
    )
    customer["credit_exposure_cents"] = exposure
    customer["credit_status"] = "HOLD" if exposure >= customer["credit_limit_cents"] else "GOOD"
    return changed


# ------------------------------------------------------------ water cascade

def apply_water_liability(load):
    """strength_acceptance helper: set liability when over_watered; flip
    non-terminal cylinder sets DESIGN_BASIS -> AS_PLACED."""
    additions = [w for w in stores["water_additions"].values() if w["load_id"] == load["id"]]
    any_auth = any(w["customer_authorized"] for w in additions)
    load["strength_liability"] = "CUSTOMER" if any_auth else "PLANT"
    for cs in stores["cylinder_sets"].values():
        if cs["load_id"] == load["id"] and cs["status"] not in ("CERTIFIED", "FLAGGED"):
            cs["acceptance_basis"] = "AS_PLACED"


# -------------------------------------------------------------- acceptance

def acceptance_passed(cylinder_set):
    return int(cylinder_set["final_strength_psi"]) >= int(cylinder_set["required_strength_psi"])


def break_age_ok(cylinder_set, days):
    cast_at = clock.parse_iso(cylinder_set["cast_at"])
    return clock.now() >= cast_at + timedelta(days=days)
