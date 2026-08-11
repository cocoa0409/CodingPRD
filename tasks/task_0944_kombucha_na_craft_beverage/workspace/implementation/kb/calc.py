"""The seventeen named calculations."""

from datetime import timedelta
from decimal import Decimal

from . import constants as C
from .store import db
from .util import (
    add_days,
    ceil_int,
    dec,
    floor_div_units,
    normalise_date,
    round2,
    whole_days_between,
    yyyymmdd,
)

ZERO = Decimal("0.00")


# ------------------------------------------------------------ scoby vitality


def scoby_vitality_score(pitch_count, generation_number, reverification_count):
    raw = (
        100
        - C.SCOBY_VITALITY_DECAY_PER_PITCH * int(pitch_count)
        - C.SCOBY_VITALITY_DECAY_PER_GENERATION * (int(generation_number) - 1)
        + C.SCOBY_REVERIFICATION_BONUS * int(reverification_count)
    )
    return max(0, min(100, int(raw)))


def recompute_vitality(culture):
    culture["vitality_score"] = scoby_vitality_score(
        culture["pitch_count"],
        culture["generation_number"],
        culture["reverification_count"],
    )
    return culture["vitality_score"]


# ------------------------------------------------------------ ABV


def abv_class_for(abv_pct):
    """Half-percent line, applied to an already-rounded figure."""
    return "ALCOHOLIC" if dec(abv_pct) >= C.NA_ABV_THRESHOLD_PCT else "NON_ALCOHOLIC"


def batch_projected_abv(f1_measured_abv_pct, planned_f2_days, f2_added_sugar_g_per_l):
    total = (
        dec(f1_measured_abv_pct)
        + C.F2_ABV_GAIN_PCT_PER_DAY * dec(planned_f2_days)
        + C.F2_SUGAR_ABV_PCT_PER_GRAM_PER_LITER * dec(f2_added_sugar_g_per_l)
    )
    return round2(total)


# ------------------------------------------------------------ label elements


def label_required_elements(abv_class, pasteurized):
    required = list(C.LABEL_BASE_ELEMENTS)
    if abv_class == "NON_ALCOHOLIC":
        required.extend(C.LABEL_NON_ALCOHOLIC_ELEMENTS)
    else:
        required.extend(C.LABEL_ALCOHOLIC_ELEMENTS)
    if pasteurized:
        required.extend(C.LABEL_PASTEURIZED_ELEMENTS)
    else:
        required.extend(C.LABEL_RAW_ELEMENTS)
    return required


# ------------------------------------------------------------ packaging yield


def packaging_gross_liters(source_draws):
    total = Decimal("0")
    for draw in source_draws:
        total += dec(draw["liters_drawn"])
    return round2(total)


def packaging_yield(gross_liters, fmt, max_units_requested):
    net = round2(
        dec(gross_liters) * (Decimal("100") - C.PACKAGING_LOSS_ALLOWANCE_PCT) / Decimal("100")
    )
    container = C.CONTAINER_LITERS_BY_FORMAT[fmt]
    capacity_units = floor_div_units(net, container)
    units = min(capacity_units, int(max_units_requested))
    return net, units


# ------------------------------------------------------------ lot inheritance


def lot_code(style, packaged_at, run_code):
    return "%s-%s-%s" % (str(style)[:3].upper(), yyyymmdd(packaged_at), run_code)


def lot_best_by_date(pasteurized, source_batch_count, packaged_at, source_batches):
    shelf_days = (
        C.SHELF_LIFE_PASTEURIZED_DAYS if pasteurized else C.SHELF_LIFE_RAW_DAYS
    )
    if int(source_batch_count) == 1:
        base_date = normalise_date(packaged_at)
    else:
        candidates = [
            normalise_date(b["f2_completed_at"])
            for b in source_batches
            if b.get("f2_completed_at") is not None
        ]
        base_date = min(candidates) if candidates else normalise_date(packaged_at)
    return normalise_date(add_days(base_date, shelf_days))


# ------------------------------------------------------------ keg / taproom


def keg_deposit_settlement(condition, days_out):
    if condition == "DAMAGED":
        forfeit = round2(C.KEG_DEPOSIT_AMOUNT * C.KEG_DAMAGE_FORFEIT_PCT / Decimal("100"))
    elif int(days_out) <= C.KEG_RETURN_WINDOW_DAYS:
        forfeit = ZERO
    else:
        forfeit = round2(C.KEG_DEPOSIT_AMOUNT * C.KEG_LATE_FORFEIT_PCT / Decimal("100"))
    refund = round2(C.KEG_DEPOSIT_AMOUNT - forfeit)
    return refund, forfeit


def taproom_fill_charge(requested_liters, container_type):
    liters = dec(requested_liters)
    gross = round2(liters * C.TAPROOM_RATE_PER_LITER)
    discount_pct = (
        C.TAPROOM_BULK_DISCOUNT_PCT
        if liters >= C.GROWLER_BULK_TIER_LITERS
        else Decimal("0")
    )
    discount = round2(gross * discount_pct / Decimal("100"))
    container_fee = C.HOUSE_GROWLER_FEE if container_type == "HOUSE_GROWLER" else ZERO
    sanitation_fee = (
        C.CUSTOMER_GROWLER_SANITATION_FEE
        if container_type == "CUSTOMER_GROWLER"
        else ZERO
    )
    return round2(gross - discount + container_fee + sanitation_fee)


# ------------------------------------------------------------ shipment totals


def shipment_lines_of(shipment_id):
    rows = [
        line
        for line in db.shipment_lines.values()
        if line["shipment_id"] == shipment_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def recompute_shipment_totals(shipment):
    active = [
        line
        for line in shipment_lines_of(shipment["id"])
        if line["line_status"] == "ACTIVE"
    ]
    shipment["total_units"] = sum(int(line["units"]) for line in active)
    total_liters = Decimal("0")
    subtotal = Decimal("0")
    for line in active:
        total_liters += dec(line["line_liters"])
        subtotal += dec(line["extended_price"])
    shipment["total_liters"] = round2(total_liters)
    shipment["subtotal"] = round2(subtotal)
    return shipment


# ------------------------------------------------------------ invoice ageing


def aging_bucket_for(days_past_due):
    days = int(days_past_due)
    if days == 0:
        return "CURRENT"
    if days <= C.AGING_BUCKET_1_MAX_DAYS:
        return "B1_1_30"
    if days <= C.AGING_BUCKET_2_MAX_DAYS:
        return "B2_31_60"
    return "B3_61_PLUS"


def late_fee_for(shipment, months_late):
    """Round per line, then sum -- the ordering is pinned."""
    if int(months_late) == 0:
        return ZERO
    total = Decimal("0")
    for line in shipment_lines_of(shipment["id"]):
        if line["line_status"] != "ACTIVE":
            continue
        total += round2(
            dec(line["extended_price"])
            * C.LATE_FEE_MONTHLY_RATE_PCT
            / Decimal("100")
            * dec(months_late)
        )
    return round2(total)


def recompute_shipment_aging(shipment):
    """PAID shipments are frozen; CANCELLED / RECALL_HOLD read 0.00 / CURRENT."""
    status = shipment["status"]
    if status == "PAID":
        return shipment
    if status in ("CANCELLED", "RECALL_HOLD"):
        shipment["days_past_due"] = 0
        shipment["late_fee"] = ZERO
        shipment["aging_bucket"] = "CURRENT"
        return shipment
    if status != "DELIVERED" or shipment.get("due_date") is None:
        shipment["days_past_due"] = 0
        shipment["late_fee"] = ZERO
        shipment["aging_bucket"] = "CURRENT"
        return shipment
    days = max(0, whole_days_between(shipment["due_date"], db.clock))
    months_late = 0 if days == 0 else ceil_int(Decimal(days) / Decimal(30))
    shipment["days_past_due"] = days
    shipment["late_fee"] = late_fee_for(shipment, months_late)
    shipment["aging_bucket"] = aging_bucket_for(days)
    return shipment


def account_shipments(account_id):
    rows = [s for s in db.shipments.values() if s["account_id"] == account_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def recompute_outstanding_balance(account):
    """Steps 1-3 of the credit-exposure calculation."""
    total = Decimal("0")
    for shipment in account_shipments(account["id"]):
        if shipment["status"] != "DELIVERED":
            continue
        recompute_shipment_aging(shipment)
        total += dec(shipment["subtotal"]) + dec(shipment["late_fee"])
    account["outstanding_balance"] = round2(total)
    return account["outstanding_balance"]


def credit_exposure(account, shipment):
    """Steps 1-4; step 5 lives in the confirm gate."""
    outstanding = recompute_outstanding_balance(account)
    return round2(dec(outstanding) + dec(shipment["subtotal"]))


# ------------------------------------------------------- self-distribution


def recompute_self_dist_ledger(account):
    if account["channel"] != "SELF_DISTRIBUTION":
        account["ytd_self_dist_liters"] = round2(account.get("ytd_self_dist_liters") or ZERO)
        return account["ytd_self_dist_liters"]
    year = db.clock.year
    total = Decimal("0")
    for shipment in account_shipments(account["id"]):
        if shipment["status"] not in ("DELIVERED", "PAID"):
            continue
        delivered = shipment.get("delivered_on_date")
        if delivered is None or delivered.year != year:
            continue
        total += dec(shipment["total_liters"])
    account["ytd_self_dist_liters"] = round2(total)
    return account["ytd_self_dist_liters"]


# ------------------------------------------------------------ subscription


def _cycle_paused_days(subscription):
    start = subscription.get("current_pause_start_date")
    end = subscription.get("current_pause_end_date")
    if start is None or end is None:
        return 0
    cycle_first = subscription["cycle_start_date"].date()
    cycle_last = (subscription["cycle_start_date"] + timedelta(days=C.SUBSCRIPTION_CYCLE_DAYS - 1)).date()
    pause_first = start.date()
    pause_last = end.date()
    lower = max(cycle_first, pause_first)
    upper = min(cycle_last, pause_last)
    if upper < lower:
        return 0
    return (upper - lower).days + 1


def loyalty_discount_pct(completed_cycles):
    return (
        C.LOYALTY_TIER2_DISCOUNT_PCT
        if int(completed_cycles) >= C.LOYALTY_MIN_CYCLES
        else Decimal("0")
    )


def subscription_cycle_charge(subscription):
    """Proration first; the loyalty discount is taken on the prorated base."""
    paused_days = _cycle_paused_days(subscription)
    active_days = C.SUBSCRIPTION_CYCLE_DAYS - paused_days
    if active_days < 0:
        active_days = 0
    prorated_base = round2(
        C.SUBSCRIPTION_CYCLE_PRICE * Decimal(active_days) / Decimal(C.SUBSCRIPTION_CYCLE_DAYS)
    )
    pct = loyalty_discount_pct(subscription["completed_cycles"])
    discount = round2(prorated_base * pct / Decimal("100"))
    return round2(prorated_base - discount)


def subscription_skip_credit(subscription):
    """No proration: the full list price less the loyalty discount on it."""
    pct = loyalty_discount_pct(subscription["completed_cycles"])
    discount = round2(C.SUBSCRIPTION_CYCLE_PRICE * pct / Decimal("100"))
    return round2(C.SUBSCRIPTION_CYCLE_PRICE - discount)


def recompute_completed_cycles(subscription):
    subscription["completed_cycles"] = sum(
        1
        for a in db.subscription_allocations.values()
        if a["subscription_id"] == subscription["id"] and a["status"] == "SHIPPED"
    )
    return subscription["completed_cycles"]


# --------------------------------------------------- FEFO release order


def fefo_candidates(preferred_recipe_id):
    """RELEASED lots of the recipe, ranked best_by_date ASC, created_at ASC."""
    released = [
        lot
        for lot in db.finished_lots.values()
        if lot["status"] == "RELEASED" and lot["recipe_id"] == preferred_recipe_id
    ]
    released.sort(key=lambda r: (r["best_by_date"], r["created_at"], r["_seq"]))
    return released


def lot_units_available(lot):
    return int(lot["on_hand_units"]) - int(lot["reserved_units"])


def lot_shelf_ok(lot):
    threshold = add_days(db.clock, C.MIN_REMAINING_SHELF_DAYS)
    return lot["best_by_date"] > threshold
