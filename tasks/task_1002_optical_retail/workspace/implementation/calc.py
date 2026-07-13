"""Calculation rules (SCAFFOLD 1.3 / PRD 3.4-3.9). All money is integer cents;
every fractional step names its rounding mode explicitly (PRD 2.6)."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import store

# --- lens_upcharge -------------------------------------------------------
COATING_BUNDLE_PCT = Decimal("0.15")
PRISM_SURCHARGE_CENTS = 4500
HIGH_POWER_RATE_CENTS_PER_DIOPTER = Decimal("1000")
HIGH_POWER_CAP_CENTS = 6000

# --- order_price_quote ---------------------------------------------------
DISCOUNT_TIER_1_CENTS = 25000
DISCOUNT_TIER_2_CENTS = 50000

# --- customer_return_risk_score -----------------------------------------
ROLLING_WINDOW_DAYS = 180
STRICT_HISTORY_THRESHOLD = 3
W_ZERO_KEPT = Decimal("0.6")
W_OVERDUE = Decimal("0.4")
BLOCK_THRESHOLD = 70

# --- remake_liability ----------------------------------------------------
WARRANTY_WINDOW_DAYS = 365
RX_CHANGE_GRACE_DAYS = 30
REMAKE_SHARE_PCT = Decimal("0.50")
REMAKE_SHIPPING_CENTS = 1500

# --- kit_late_fee --------------------------------------------------------
LATE_FEE_PER_DAY_CENTS = 500
LATE_FEE_CAP_CENTS = 5000

# --- prescription ranges -------------------------------------------------
PD_MIN_MM = Decimal("45.0")
PD_MAX_MM = Decimal("80.0")


def dec(value):
    return Decimal(str(value))


def floor_cents(value):
    """Floor of a non-negative money product."""
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def round_half_up(value):
    """Exactly one half rounds away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =========================================================================
# lens_upcharge
# =========================================================================
def rx_power(rx):
    """The stronger sphere plus one half of the stronger cylinder (PRD 3.5)."""
    max_sphere = max(abs(dec(rx["od_sphere"])), abs(dec(rx["os_sphere"])))
    max_cyl = max(abs(dec(rx["od_cylinder"])), abs(dec(rx["os_cylinder"])))
    return max_sphere + Decimal("0.5") * max_cyl


def required_index_tier(power):
    if power < Decimal("4.00"):
        return Decimal("1.50")
    if power < Decimal("6.00"):
        return Decimal("1.60")
    if power < Decimal("8.00"):
        return Decimal("1.67")
    return Decimal("1.74")


def lens_upcharge(rx, material, coatings):
    power = rx_power(rx)

    material_price = material["base_price_cents"]
    coating_total = sum(c["base_price_cents"] for c in coatings)
    coating_discount = (
        floor_cents(dec(coating_total) * COATING_BUNDLE_PCT) if len(coatings) >= 2 else 0
    )
    prism_surcharge = (
        PRISM_SURCHARGE_CENTS if dec(rx["prism_diopters"]) >= Decimal("0.50") else 0
    )
    raw_high_power = round_half_up(
        (power - Decimal("6.00")) * HIGH_POWER_RATE_CENTS_PER_DIOPTER
    )
    high_power_surcharge = min(HIGH_POWER_CAP_CENTS, max(0, raw_high_power))

    return (
        material_price
        + coating_total
        - coating_discount
        + prism_surcharge
        + high_power_surcharge
    )


# =========================================================================
# order_price_quote
# =========================================================================
def _discount_pct(subtotal_cents):
    if subtotal_cents < DISCOUNT_TIER_1_CENTS:
        return Decimal("0.00")
    if subtotal_cents < DISCOUNT_TIER_2_CENTS:
        return Decimal("0.10")
    return Decimal("0.15")


def order_price_quote(frame, lens_upcharge_cents, customer, policy, fsa_amount_cents=0):
    """The ESTIMATED variant. Evaluation order is pinned (PRD 3.6)."""
    subtotal = frame["price_cents"] + lens_upcharge_cents
    pct = _discount_pct(subtotal)
    discount = floor_cents(dec(subtotal) * pct)
    net = subtotal - discount

    frame_after_discount = frame["price_cents"] - floor_cents(
        dec(frame["price_cents"]) * pct
    )
    lens_after_discount = net - frame_after_discount

    if policy is None or policy["network"] == "OUT_OF_NETWORK":
        benefit_frame = 0
        benefit_lens = 0
    else:
        benefit_frame = min(policy["frame_allowance_remaining_cents"], frame_after_discount)
        benefit_lens = max(0, lens_after_discount - policy["lens_copay_cents"])

    benefit_applied = benefit_frame + benefit_lens
    due_pre_fsa = net - benefit_applied

    fsa_applied = min(fsa_amount_cents, customer["fsa_balance_cents"], due_pre_fsa)
    customer_due = due_pre_fsa - fsa_applied

    return {
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "benefit_frame_cents": benefit_frame,
        "benefit_lens_cents": benefit_lens,
        "benefit_applied_cents": benefit_applied,
        "fsa_applied_cents": fsa_applied,
        "customer_due_cents": customer_due,
    }


def final_quote(order, allowed_amount_cents):
    """The FINAL variant: the insurer's allowed amount caps the retailer's estimate.
    Nothing else is recomputed (PRD 3.8)."""
    estimated_benefit = order["benefit_applied_cents"]
    final_benefit = min(estimated_benefit, allowed_amount_cents)
    net = order["subtotal_cents"] - order["discount_cents"]
    return final_benefit, net - final_benefit - order["fsa_applied_cents"]


# =========================================================================
# oon_reimbursement -- round EACH line, THEN sum.
# =========================================================================
def oon_reimbursement(claim, policy):
    pct = dec(policy["oon_reimburse_pct"])
    schedule = policy["oon_fee_schedule"] or {}
    total = 0
    for line in claim["service_lines"]:
        schedule_cap = schedule.get(line["code"], 0)
        eligible = min(line["billed_cents"], schedule_cap)
        total += round_half_up(dec(eligible) * pct)
    remaining_annual = policy["annual_max_cents"] - policy["annual_reimbursed_cents"]
    return min(total, remaining_annual)


# =========================================================================
# customer_return_risk_score
# =========================================================================
def recompute_return_risk(customer):
    """Recomputed on kit return and whenever the clock flips a kit to OVERDUE."""
    history = [
        k
        for k in store.ordered(store.kits)
        if k["customer_id"] == customer["id"] and k["status"] in ("RETURNED", "OVERDUE")
    ]
    lifetime = len(history)

    if lifetime >= STRICT_HISTORY_THRESHOLD:
        window = history  # STRICT
    else:  # ROLLING
        cutoff = store.minus_days(store.clock_now(), ROLLING_WINDOW_DAYS)
        window = [k for k in history if k["_due_date_dt"] >= cutoff]

    if not window:
        score = 0
    else:
        zero_kept = sum(1 for k in window if k["kept_count"] == 0)
        overdue = sum(1 for k in window if k["was_overdue"])
        score = round_half_up(
            Decimal(100)
            * (W_ZERO_KEPT * Decimal(zero_kept) + W_OVERDUE * Decimal(overdue))
            / Decimal(len(window))
        )

    changed = (
        customer["lifetime_kit_count"] != lifetime
        or customer["return_risk_score"] != score
    )
    customer["lifetime_kit_count"] = lifetime
    customer["return_risk_score"] = score
    if changed:
        store.touch(customer)


# =========================================================================
# kit_late_fee
# =========================================================================
def kit_late_fee(kit):
    now = store.clock_now()
    due = kit["_due_date_dt"]
    if now <= due:
        return 0
    days_late = store.days_between_ceil(now, due)
    return min(LATE_FEE_CAP_CENTS, days_late * LATE_FEE_PER_DAY_CENTS)


# =========================================================================
# remake_liability
# =========================================================================
def remake_liability(reason, days_since_delivery, order_lens_upcharge_cents):
    share = floor_cents(dec(order_lens_upcharge_cents) * REMAKE_SHARE_PCT)
    if reason == "MANUFACTURER_DEFECT":
        return 0
    if reason == "RX_CHANGE":
        return 0 if days_since_delivery <= RX_CHANGE_GRACE_DAYS else share
    # CUSTOMER_DAMAGE -- no grace period at all.
    return share + REMAKE_SHIPPING_CENTS
