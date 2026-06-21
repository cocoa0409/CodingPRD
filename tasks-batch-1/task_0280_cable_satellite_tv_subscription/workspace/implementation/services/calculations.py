"""Calculation rules (PRD §3.7, §3.8, §3.10 / SCAFFOLD §1.3).

All money is integer cents. Where a fraction is applied (percent-off discount,
proration factor), the result is rounded HALF UP to whole cents (PRD §2.10).
Per-line rounding for prorated statements is applied independently before
summing (PRD §3.10).
"""

from decimal import Decimal, ROUND_HALF_UP

import db

# Calculation constants (SCAFFOLD §1.3).
PREMIER_RANK = 3
SERVICE_TRUCK_ROLL_CENTS = 9900
ETF_MAX_CENTS = 24000
ETF_MID_CENTS = 15000
ETF_MIN_CENTS = 2000
ETF_PER_MONTH_CENTS = 1500


def round_half_up(value):
    """Round a numeric value to a whole integer using round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_round_half_up(cents, fraction):
    """Multiply integer cents by a fraction and round half up to whole cents."""
    return int((Decimal(cents) * Decimal(str(fraction))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Line-item helpers
# ---------------------------------------------------------------------------
def current_subscription(account_id):
    """The single ACTIVE-or-DOWNGRADED subscription on the account, if any."""
    for sub in db.subscriptions.values():
        if sub["account_id"] == account_id and sub["status"] in ("ACTIVE", "DOWNGRADED"):
            return sub
    return None


def active_addon_sum(account_id):
    return sum(
        a["fee_cents"]
        for a in db.add_on_subscriptions.values()
        if a["account_id"] == account_id and a["status"] == "ACTIVE"
    )


def assigned_equipment_sum(account_id):
    return sum(
        lease["monthly_lease_cents"]
        for lease in db.equipment_leases.values()
        if lease["account_id"] == account_id and lease["status"] == "ASSIGNED"
    )


def active_promotion_application(account_id):
    for pa in db.promotion_applications.values():
        if pa["account_id"] == account_id and pa["status"] == "ACTIVE":
            return pa
    return None


def package_rank(package_id):
    if package_id is None:
        return None
    pkg = db.channel_packages.get(package_id)
    return pkg["rank"] if pkg else None


# ---------------------------------------------------------------------------
# regional_sports_fee (PRD §3.8)
# ---------------------------------------------------------------------------
def regional_sports_fee(account):
    """Regional sports fee for the account's state at the current package rank."""
    state = account["service_state_code"]
    rule = None
    for r in db.regional_sports_fee_rules.values():
        if r["state_code"] == state and r["active"]:
            rule = r
            break
    if rule is None:
        return 0
    rank = package_rank(account["active_package_id"])
    base = rule["base_fee_cents"]
    surcharge = rule["premier_surcharge_cents"] if (rank is not None and rank >= PREMIER_RANK) else 0
    return base + surcharge


# ---------------------------------------------------------------------------
# promo_discount (PRD §3.7)
# ---------------------------------------------------------------------------
def promo_discount(account_id, gross, package_base):
    """Discount contributed by the single ACTIVE PromotionApplication, else 0.

    gross/package_base are the bases this discount is applied over. equipment
    sum (for EQUIPMENT_WAIVER) is read from current ASSIGNED leases.
    """
    pa = active_promotion_application(account_id)
    if pa is None:
        return 0
    offer = db.promotion_offers.get(pa["promotion_offer_id"])
    if offer is None:
        return 0
    kind = offer["discount_kind"]
    if kind == "PERCENT_OFF_PACKAGE":
        return mul_round_half_up(package_base, offer["percent_off"])
    if kind == "FLAT_OFF_TOTAL":
        return min(offer["flat_off_cents"], gross)
    if kind == "EQUIPMENT_WAIVER":
        return assigned_equipment_sum(account_id)
    return 0


# ---------------------------------------------------------------------------
# monthly_recurring_charge (PRD §3.7)
# ---------------------------------------------------------------------------
def monthly_recurring_charge(account):
    """Recompute the account's monthly_recurring_cents from live line items.

    Evaluation order is pinned (PRD §3.7):
      1 package_base, 2 addon_sum, 3 equip_sum, 4 rsf, 5 gross,
      6 discount(gross, package_base), 7 max(0, gross - discount).
    SUSPENDED / CANCELLED short-circuit to 0.
    """
    if account["lifecycle_status"] in ("SUSPENDED", "CANCELLED"):
        return 0
    sub = current_subscription(account["id"])
    package_base = sub["base_fee_cents"] if sub else 0
    addon_sum = active_addon_sum(account["id"])
    equip_sum = assigned_equipment_sum(account["id"])
    rsf = account["regional_sports_fee_cents"]
    gross = package_base + addon_sum + equip_sum + rsf
    discount = promo_discount(account["id"], gross, package_base)
    return max(0, gross - discount)


# ---------------------------------------------------------------------------
# visit_fee (PRD §3.8)
# ---------------------------------------------------------------------------
def visit_fee_on_complete(visit_type):
    """Truck-roll fee on COMPLETED: INSTALL waived (0), SERVICE charged."""
    if visit_type == "INSTALL":
        return 0
    return SERVICE_TRUCK_ROLL_CENTS


def visit_fee_on_no_show():
    """No-show always charges the full service truck-roll fee regardless of type."""
    return SERVICE_TRUCK_ROLL_CENTS


# ---------------------------------------------------------------------------
# early_termination_fee (PRD §3.8)
# ---------------------------------------------------------------------------
def early_termination_fee(contract_term_months, tenure_months):
    """ETF tiered by months remaining on contract (inclusive lower edges)."""
    if contract_term_months == 0:
        return 0
    if tenure_months >= contract_term_months:
        return 0
    remaining = contract_term_months - tenure_months
    if remaining >= 12:
        return ETF_MAX_CENTS
    if remaining >= 6:  # 6 <= remaining < 12
        return ETF_MID_CENTS
    # 1 <= remaining < 6
    return ETF_MIN_CENTS + remaining * ETF_PER_MONTH_CENTS


# ---------------------------------------------------------------------------
# statement_total (PRD §3.10) — dual variant FULL_CYCLE vs PRORATED
# ---------------------------------------------------------------------------
def _cycle_visit_charges(account_id, cycle_index):
    """Sum of truck_roll_fee_cents for visits whose terminal outcome fell in this cycle."""
    total = 0
    for v in db.service_visits.values():
        if v["account_id"] != account_id:
            continue
        if v["status"] in ("COMPLETED", "NO_SHOW") and v.get("billed_cycle_index") == cycle_index:
            total += v["truck_roll_fee_cents"]
    return total


def compute_statement(account, cycle_index, proration_mode, days_in_cycle, active_days):
    """Compute all statement line items per PRD §3.10. Returns a dict of charge fields."""
    account_id = account["id"]
    sub = current_subscription(account_id)
    package = sub["base_fee_cents"] if sub else 0
    addon = active_addon_sum(account_id)
    equipment_recurring = assigned_equipment_sum(account_id)
    unreturned_one_time = sum(
        lease["unreturned_charge_cents"]
        for lease in db.equipment_leases.values()
        if lease["account_id"] == account_id and lease["status"] == "UNRETURNED"
    )
    rsf = account["regional_sports_fee_cents"]
    visits = _cycle_visit_charges(account_id, cycle_index)

    # ETF owed only if account cancelled in this cycle.
    etf = 0
    if (account["lifecycle_status"] == "CANCELLED"
            and account.get("cancellation_effective_cycle") == cycle_index):
        etf = early_termination_fee(account["contract_term_months"],
                                    account.get("etf_tenure_at_cancel",
                                                account["tenure_months"]))

    if proration_mode == "FULL_CYCLE":
        package_charge = package
        addon_charge = addon
        equipment_charge = equipment_recurring + unreturned_one_time
        rsf_charge = rsf
        gross_recurring = package + addon + equipment_recurring + rsf
        promo = promo_discount(account_id, gross_recurring, package)
    else:  # PRORATED
        f = Decimal(active_days) / Decimal(days_in_cycle) if days_in_cycle else Decimal(0)
        package_charge = mul_round_half_up(package, f)
        addon_charge = mul_round_half_up(addon, f)
        equipment_recurring_charge = mul_round_half_up(equipment_recurring, f)
        rsf_charge = mul_round_half_up(rsf, f)
        equipment_charge = equipment_recurring_charge + unreturned_one_time
        # promo computed on the PRORATED recurring base, rounded half up.
        prorated_package = package_charge
        prorated_gross = package_charge + addon_charge + equipment_recurring_charge + rsf_charge
        promo = _promo_discount_prorated(account_id, prorated_gross, prorated_package,
                                         equipment_recurring_charge, f)

    total = (package_charge + addon_charge + equipment_charge + rsf_charge
             + visits + etf - promo)
    total = max(0, total)

    return {
        "package_charge_cents": package_charge,
        "addon_charge_cents": addon_charge,
        "equipment_charge_cents": equipment_charge,
        "regional_sports_fee_cents": rsf_charge,
        "visit_charge_cents": visits,
        "promo_discount_cents": promo,
        "etf_charge_cents": etf,
        "total_cents": total,
    }


def _promo_discount_prorated(account_id, prorated_gross, prorated_package,
                             prorated_equipment, factor):
    """Promo discount computed over the prorated recurring base (PRD §3.10).

    PERCENT_OFF_PACKAGE -> percent of the prorated package charge (already a
    whole-cent prorated value), rounded half up.
    FLAT_OFF_TOTAL      -> min(flat, prorated_gross).
    EQUIPMENT_WAIVER    -> the prorated recurring equipment portion.
    """
    pa = active_promotion_application(account_id)
    if pa is None:
        return 0
    offer = db.promotion_offers.get(pa["promotion_offer_id"])
    if offer is None:
        return 0
    kind = offer["discount_kind"]
    if kind == "PERCENT_OFF_PACKAGE":
        return mul_round_half_up(prorated_package, offer["percent_off"])
    if kind == "FLAT_OFF_TOTAL":
        return min(offer["flat_off_cents"], prorated_gross)
    if kind == "EQUIPMENT_WAIVER":
        return prorated_equipment
    return 0
