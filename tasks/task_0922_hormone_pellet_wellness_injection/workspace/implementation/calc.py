"""The nineteen named calculations of PRD section 3.

Every rounding step is pinned exactly where the PRD pins it: money is exact
rational arithmetic until the single declared round-half-up.
"""
from fractions import Fraction

import config
import store
import util


# ------------------------------------------------------------- lookups -----
def allocations_of_procedure(procedure_id):
    return store.where("PelletAllocation", procedure_id=procedure_id)


def allocations_of_lot(lot_id):
    return store.where("PelletAllocation", lot_id=lot_id)


def price_per_mg(hormone_type):
    return config.PELLET_PRICE_CENTS_PER_MG[hormone_type]


# ----------------------------------------- 1. pellet_count_from_dose --------
def pellet_count_from_dose(hormone_type, prescribed_dose_mg):
    """Greedy largest-first with a ceiling on the remainder (PRD 3.3)."""
    large_mg, small_mg = config.PELLET_LADDER[hormone_type]
    dose = util.frac(prescribed_dose_mg)
    large_count = util.floor_frac(dose / large_mg)
    remainder = dose - large_count * large_mg
    small_count = 0 if remainder == 0 else util.ceil_div_frac(remainder / small_mg)
    return {
        "planned_large_count": large_count,
        "planned_small_count": small_count,
        "planned_pellet_count": large_count + small_count,
        "planned_total_mg": large_count * large_mg + small_count * small_mg,
    }


# ------------------------------------------- 2. procedure_delivered_mg ------
def procedure_delivered_mg(procedure, variant):
    """PLANNED reads the consult plan; ACTUAL sums CONSUMED allocations only."""
    if variant == "PLANNED":
        return procedure.get("planned_total_mg", 0)
    total = Fraction(0)
    for row in allocations_of_procedure(procedure["id"]):
        if row["status"] == "CONSUMED":
            total += util.frac(row["quantity"]) * util.frac(row["strength_mg"])
    return util.numout(total)


# ---------------------------------------------- 3. rolling_mg_exposure ------
def rolling_mg_exposure(patient_id, hormone_type, variant, now):
    window_lo = util.add_days(now, -config.ROLLING_MG_WINDOW_DAYS)
    window_hi = util.add_days(now, config.ROLLING_MG_WINDOW_DAYS)
    total = Fraction(0)
    for proc in store.where("Procedure", patient_id=patient_id, hormone_type=hormone_type):
        if proc["status"] == "COMPLETED" and proc.get("performed_at") is not None:
            if window_lo <= proc["performed_at"] <= now:
                total += util.frac(proc.get("delivered_total_mg", 0))
    if variant == "INCLUDING_SCHEDULED":
        for proc in store.where("Procedure", patient_id=patient_id, hormone_type=hormone_type):
            if proc["status"] in ("SCHEDULED", "CONSENTED", "SUPPLY_OPENED"):
                start = proc.get("scheduled_start")
                if start is not None and now < start <= window_hi:
                    total += util.frac(proc.get("planned_total_mg", 0))
    return util.numout(total)


# --------------------------------------------- 4. fefo_allocation_plan ------
def fefo_allocation_plan(procedure, consult, released_extra=None):
    """Earliest-expiry-first walk over both strength legs (PRD 3.5).

    `released_extra` maps lot id -> pellets credited back by the supersession
    that precedes this plan, so the walk sees the refreshed inventory without
    anything having been written yet.  Returns None when either leg is short.
    """
    released_extra = released_extra or {}
    hormone = procedure["hormone_type"]
    large_mg, small_mg = config.PELLET_LADDER[hormone]
    legs = (
        (large_mg, consult.get("planned_large_count", 0)),
        (small_mg, consult.get("planned_small_count", 0)),
    )
    virtual = {}

    def on_hand(lot):
        if lot["id"] not in virtual:
            virtual[lot["id"]] = lot["qty_on_hand"] + released_extra.get(lot["id"], 0)
        return virtual[lot["id"]]

    draws = []
    for strength, need in legs:
        if need <= 0:
            continue
        candidates = [
            lot for lot in store.all_rows("PelletLot")
            if lot["hormone_type"] == hormone
            and util.frac(lot["strength_mg"]) == util.frac(strength)
            and lot["sterility_status"] == "RELEASED"
            and lot["expiry_date"] > procedure["scheduled_start"]
            and on_hand(lot) > 0
        ]
        candidates.sort(key=lambda lot: (lot["expiry_date"], lot["created_at"], lot["_seq"]))
        remaining = need
        for lot in candidates:
            if remaining <= 0:
                break
            take = min(remaining, on_hand(lot))
            if take <= 0:
                continue
            virtual[lot["id"]] = on_hand(lot) - take
            draws.append({"lot": lot, "strength_mg": lot["strength_mg"], "quantity": take})
            remaining -= take
        if remaining > 0:
            return None
    return draws


# -------------------------------------------- 5. lab_band_classification ---
def lab_band_classification(analyte, value):
    ref_low, ref_high, opt_low, opt_high, critical_high, unit = config.ANALYTE_BANDS[analyte]
    if value < ref_low:
        reference = "BELOW_REF"
    elif value > ref_high:
        reference = "ABOVE_REF"
    else:
        reference = "IN_REF"
    if value < opt_low:
        optimal = "BELOW_OPTIMAL"
    elif value > opt_high:
        optimal = "ABOVE_OPTIMAL"
    else:
        optimal = "IN_OPTIMAL"
    return {
        "unit": unit,
        "lab_reference_band": reference,
        "clinic_optimal_band": optimal,
        "critical_flag": value > critical_high,
    }


# ------------------------------------------------- 6. redose_eligibility ----
def redose_anchor(patient_id, hormone_type):
    """performed_at of the most recent COMPLETED procedure of that hormone."""
    best = None
    for proc in store.where("Procedure", patient_id=patient_id, hormone_type=hormone_type):
        if proc["status"] != "COMPLETED" or proc.get("performed_at") is None:
            continue
        if best is None or proc["performed_at"] > best:
            best = proc["performed_at"]
    return best


def redose_factors(hormone_type, anchor, panel, consult, scheduled_start, now):
    f1 = (
        anchor is not None
        and scheduled_start is not None
        and util.days_between(anchor, scheduled_start)
        >= config.MIN_REDOSE_INTERVAL_DAYS[hormone_type]
    )
    f2 = False
    if anchor is not None and panel is not None and panel.get("is_trough_draw"):
        gap = util.days_between(anchor, panel["drawn_at"])
        f2 = (
            config.TROUGH_WINDOW_OPEN_DAYS[hormone_type]
            <= gap
            <= config.TROUGH_WINDOW_CLOSE_DAYS[hormone_type]
        )
    f3 = panel is not None and util.days_between(panel["drawn_at"], now) <= config.LAB_MAX_AGE_DAYS
    f4 = consult is not None and consult.get("symptom_score", -1) >= config.REDOSE_MIN_SYMPTOM_SCORE
    f5 = (
        panel is not None
        and panel.get("analyte") == config.PRIMARY_ANALYTE.get(hormone_type)
        and panel.get("clinic_optimal_band") == "BELOW_OPTIMAL"
    )
    return {
        "f1_interval_ok": bool(f1),
        "f2_trough_ok": bool(f2),
        "f3_freshness_ok": bool(f3),
        "f4_symptom_ok": bool(f4),
        "f5_band_ok": bool(f5),
    }


# --------------------------------- 7. procedure_pellet_charge_cents ---------
def procedure_pellet_charge_cents(procedure):
    """One rounded line per distinct strength, large first, then summed."""
    rate = price_per_mg(procedure["hormone_type"])
    grouped = {}
    for row in allocations_of_procedure(procedure["id"]):
        if row["status"] != "CONSUMED":
            continue
        key = util.frac(row["strength_mg"])
        grouped[key] = grouped.get(key, 0) + row["quantity"]
    pellet_subtotal = 0
    for strength in sorted(grouped.keys(), reverse=True):
        count = grouped[strength]
        pellet_subtotal += util.round_half_up(util.frac(count) * strength * rate)
    return config.INSERTION_BASE_FEE_CENTS + pellet_subtotal


def membership_discount_rate(membership):
    """A membership supplies a discount only while it is ACTIVE."""
    if membership is None or membership.get("status") != "ACTIVE":
        return Fraction(0)
    return config.MEMBERSHIP_DISCOUNT_PCT[membership["tier"]]


# ------------------------------------- 8. visit_invoice_total_cents ---------
def visit_invoice_total_cents(procedure, membership):
    subtotal = procedure_pellet_charge_cents(procedure)
    rate = membership_discount_rate(membership)
    discount = util.round_half_up(util.frac(subtotal) * rate)
    discounted = subtotal - discount
    facility = (
        0
        if discounted >= config.FACILITY_FEE_WAIVER_THRESHOLD_CENTS
        else config.FACILITY_FEE_BASE_CENTS
    )
    return discounted + facility


# ---------------------------------------- 9. late_cancel_fee_cents ----------
def late_cancel_fee_cents(procedure, membership, now, variant="CANCEL_TIER"):
    if variant == "CLINIC_INITIATED":
        return "NONE", 0
    lead = util.hours_between(now, procedure["scheduled_start"])
    if lead >= config.LATE_CANCEL_TIER1_LEAD_HOURS:
        tier, base = "NONE", 0
    elif lead >= config.LATE_CANCEL_TIER2_LEAD_HOURS:
        tier, base = "TIER1", config.LATE_CANCEL_TIER1_FEE_CENTS
    elif lead > 0:
        tier, base = "TIER2", config.LATE_CANCEL_TIER2_FEE_CENTS
    else:
        tier, base = "NO_SHOW", config.NO_SHOW_FEE_CENTS
    rate = membership_discount_rate(membership)
    fee = util.round_half_up(util.frac(base) * (Fraction(1) - rate))
    return tier, fee


# --------------------------------------- 10. refund_settlement_cents --------
def wasted_pellet_charge_cents(procedure):
    rate = price_per_mg(procedure["hormone_type"])
    total = 0
    for row in allocations_of_procedure(procedure["id"]):
        if row["status"] != "WASTED":
            continue
        total += util.round_half_up(
            util.frac(row["quantity"]) * util.frac(row["strength_mg"]) * rate
        )
    return total


def plan_for_procedure(procedure_id):
    plans = store.where("FinancingPlan", procedure_id=procedure_id)
    return plans[0] if plans else None


def refund_settlement_cents(procedure, membership, now, variant, plan=None,
                            forced_tier=None, forced_fee=None):
    if plan is None:
        plan = plan_for_procedure(procedure["id"])
    paid_to_date = 0
    if plan is not None:
        paid_to_date = plan["down_payment_cents"] + plan["paid_installment_cents"]
    if forced_fee is None:
        tier, fee = late_cancel_fee_cents(procedure, membership, now)
    else:
        tier, fee = forced_tier, forced_fee
    wasted = wasted_pellet_charge_cents(procedure)
    if variant == "FINAL_SETTLEMENT":
        refund = paid_to_date - fee - wasted
    else:
        refund = paid_to_date - fee
    return {
        "paid_to_date_cents": paid_to_date,
        "cancel_tier": tier,
        "cancel_fee_cents": fee,
        "wasted_pellet_charge_cents": wasted,
        "refund_cents": max(0, refund),
    }


# ------------------------------------- 11. financing_schedule_cents ---------
def financing_schedule_cents(principal_cents, down_payment_cents, installment_count,
                            first_due_date):
    financed = principal_cents - down_payment_cents
    base = financed // installment_count
    residual = financed - base * installment_count
    schedule = []
    for index in range(1, installment_count + 1):
        amount = base + (residual if index == installment_count else 0)
        schedule.append({
            "index": index,
            "due_date": util.add_days(
                first_due_date, (index - 1) * config.FINANCING_INSTALLMENT_INTERVAL_DAYS
            ),
            "amount_cents": amount,
            "status": "PENDING",
        })
    return schedule


# --------------------------------- 12. membership_pause_credit_cents --------
def membership_pause_credit_cents(membership, now):
    elapsed_days = util.days_between(membership["period_start"], now)
    period_length_days = util.days_between(membership["period_start"], membership["period_end"])
    unused_days = max(0, period_length_days - elapsed_days)
    if period_length_days <= 0:
        return 0
    daily_rate = Fraction(membership["monthly_fee_cents"], period_length_days)
    credit = util.round_half_up(daily_rate * unused_days)
    return min(credit, membership["monthly_fee_cents"])


# ------------------------------------- 13. series_pack_price_cents ----------
def series_pack_price_cents(series_type):
    list_price = config.INJECTION_LIST_PRICE_CENTS[series_type]
    body = util.round_half_up(
        util.frac(config.SERIES_PACK_VISITS * list_price)
        * (Fraction(1) - config.SERIES_PACK_DISCOUNT_PCT)
    )
    price = body + config.SERIES_ENROLLMENT_FEE_CENTS
    per_visit = price // config.SERIES_PACK_VISITS
    return price, per_visit


# ------------------------------ 14. series_redemption_debit_cents -----------
def series_redemption_debit_cents(pack):
    """FINAL_RESIDUAL only when every other entitlement was really redeemed."""
    if pack["redeemed_visits"] == pack["purchased_visits"] - 1:
        return pack["price_cents"] - pack["per_visit_value_cents"] * (
            pack["purchased_visits"] - 1
        )
    return pack["per_visit_value_cents"]


# ---------------------------------------------- 15. series_refund_cents -----
def series_refund_cents(pack):
    return pack["remaining_visits"] * pack["per_visit_value_cents"]


# ------------------------------------------ 16. injection_payment_source ----
def injection_payment_source(visit, pack, membership):
    if visit.get("series_pack_id") is not None:
        return "SERIES"
    if (
        visit.get("membership_id") is not None
        and membership is not None
        and membership["status"] == "ACTIVE"
        and membership["included_visits_used"] < membership["included_visits_allowance"]
    ):
        return "MEMBERSHIP_INCLUDED"
    return "SELF_PAY"


def injection_charge_cents(visit, membership):
    list_price = config.INJECTION_LIST_PRICE_CENTS[visit["injection_type"]]
    rate = membership_discount_rate(membership) if visit.get("membership_id") else Fraction(0)
    return util.round_half_up(util.frac(list_price) * (Fraction(1) - rate))


# ------------------------------------------- 17. recall_impact_counts -------
def recall_impact_counts(lot, variant, assume_severity=None):
    rows = allocations_of_lot(lot["id"])
    if variant == "PROJECTION":
        released = [r for r in rows if r["status"] in ("RESERVED", "OPENED")]
        flagged = [r for r in rows if r["status"] == "CONSUMED"]
        affected = {r["procedure_id"] for r in flagged}
        held = set()
        for row in released:
            proc = store.get("Procedure", row["procedure_id"])
            if proc is not None and proc["status"] in ("SCHEDULED", "CONSENTED", "SUPPLY_OPENED"):
                held.add(proc["id"])
        affected_count = len(affected)
        return {
            "released_allocation_count": len(released),
            "flagged_allocation_count": len(flagged),
            "affected_procedure_count": affected_count,
            "held_procedure_count": len(held),
            "notification_count": affected_count,
            "surveillance_event_count": affected_count if assume_severity == "CLASS_I" else 0,
        }
    released = [r for r in rows if r["status"] == "RECALL_RELEASED"]
    flagged = [r for r in rows if r["status"] == "RECALL_FLAGGED"]
    owning = {r["procedure_id"] for r in rows}
    affected = set()
    held = set()
    for procedure_id in owning:
        proc = store.get("Procedure", procedure_id)
        if proc is None:
            continue
        if proc.get("recall_status") == "NOTIFIED":
            affected.add(procedure_id)
        if proc["status"] == "SUPPLY_HOLD" and proc.get("hold_reason") == "LOT_RECALL":
            held.add(procedure_id)
    notifications = [n for n in store.all_rows("PatientNotification") if n.get("lot_id") == lot["id"]]
    surveillance = [
        e for e in store.all_rows("AdverseEvent")
        if e.get("lot_id") == lot["id"] and e.get("source") == "RECALL_SURVEILLANCE"
    ]
    return {
        "released_allocation_count": len(released),
        "flagged_allocation_count": len(flagged),
        "affected_procedure_count": len(affected),
        "held_procedure_count": len(held),
        "notification_count": len(notifications),
        "surveillance_event_count": len(surveillance),
    }


# ------------------------------- 19. patient_eligibility_projection ---------
def patient_eligibility_projection(patient):
    clinical = bool(patient.get("clinical_hold"))
    financial = bool(patient.get("financial_hold"))
    if clinical and financial:
        return "DUAL_HOLD"
    if clinical:
        return "CLINICAL_HOLD"
    if financial:
        return "FINANCIAL_HOLD"
    return "CLEAR"
