"""Calculations: patient responsibility split, foundation split,
PDC adherence, foundation pool selector, outcome report metrics.

All monetary math is integer cents (Decimal used only for the
half-up percentage rounding paths).
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, logical_today
from services.common import touch


MAX_APPEAL_ROUNDS = 2
AE_REPORT_WINDOW_HOURS = 24
REFILL_MIN_PDC_PCT = Decimal("80.0")


# ---------- Serializers ----------

def serialize_program(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "manufacturer_name": p["manufacturer_name"],
        "diagnosis_code": p["diagnosis_code"],
        "requires_injection_training": p["requires_injection_training"],
        "requires_cold_chain": p["requires_cold_chain"],
        "max_transit_hours": p["max_transit_hours"],
        "min_days_between_fills": p["min_days_between_fills"],
        "copay_card_per_fill_cap_cents": p["copay_card_per_fill_cap_cents"],
        "copay_card_annual_cap_cents": p["copay_card_annual_cap_cents"],
        "default_days_supply": p["default_days_supply"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_pool(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "diagnosis_code": p["diagnosis_code"],
        "total_funding_cents": p["total_funding_cents"],
        "grant_amount_cents": p["grant_amount_cents"],
        "coverage_pct": p["coverage_pct"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "remaining_balance_cents": p["remaining_balance_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_enrollment(e):
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "patient_ref": e["patient_ref"],
        "diagnosis_code": e["diagnosis_code"],
        "case_manager_id": e["case_manager_id"],
        "status": e["status"],
        "training_sessions_completed": e["training_sessions_completed"],
        "fills_delivered_count": e["fills_delivered_count"],
        "therapy_start_date": e["therapy_start_date"],
        "payer_accumulated_oop_cents": e["payer_accumulated_oop_cents"],
        "remaining_oop_cents": e["remaining_oop_cents"],
        "pdc_confirmed_pct": compute_pdc(e, confirmed=True),
        "pdc_provisional_pct": compute_pdc(e, confirmed=False),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_bi(b):
    # BenefitsInvestigation is immutable: no updated_at, no version.
    return {
        "id": b["id"],
        "enrollment_id": b["enrollment_id"],
        "payer_name": b["payer_name"],
        "member_id": b["member_id"],
        "requires_prior_auth": b["requires_prior_auth"],
        "plan_has_accumulator": b["plan_has_accumulator"],
        "patient_cost_share_cents": b["patient_cost_share_cents"],
        "oop_max_cents": b["oop_max_cents"],
        "created_at": b["created_at"],
    }


def serialize_pa(p):
    return {
        "id": p["id"],
        "enrollment_id": p["enrollment_id"],
        "clinical_notes": p["clinical_notes"],
        "payer_reference": p["payer_reference"],
        "status": p["status"],
        "appeal_round": p["appeal_round"],
        "decision_rationale": p["decision_rationale"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_assistance(a):
    return {
        "id": a["id"],
        "enrollment_id": a["enrollment_id"],
        "assistance_type": a["assistance_type"],
        "foundation_pool_id": a["foundation_pool_id"],
        "matched_by_user_id": a["matched_by_user_id"],
        "status": a["status"],
        "per_fill_cap_cents": a["per_fill_cap_cents"],
        "coverage_pct": a["coverage_pct"],
        "annual_benefit_cap_cents": a["annual_benefit_cap_cents"],
        "remaining_annual_benefit_cents": a["remaining_annual_benefit_cents"],
        "disbursed_cents": a["disbursed_cents"],
        "returned_cents": a["returned_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_shipment(s):
    return {
        "id": s["id"],
        "enrollment_id": s["enrollment_id"],
        "fill_number": s["fill_number"],
        "fill_type": s["fill_type"],
        "requested_delivery_date": s["requested_delivery_date"],
        "transit_hours": s["transit_hours"],
        "days_supply": s["days_supply"],
        "status": s["status"],
        "patient_cost_share_cents": s["patient_cost_share_cents"],
        "assistance_pay_cents": s["assistance_pay_cents"],
        "patient_pay_cents": s["patient_pay_cents"],
        "payer_accumulator_delta_cents": s["payer_accumulator_delta_cents"],
        "delivered_date": s["delivered_date"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_visit(v):
    return {
        "id": v["id"],
        "enrollment_id": v["enrollment_id"],
        "nurse_id": v["nurse_id"],
        "window_start": v["window_start"],
        "window_end": v["window_end"],
        "status": v["status"],
        "completed_by_user_id": v["completed_by_user_id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_ae(a):
    return {
        "id": a["id"],
        "enrollment_id": a["enrollment_id"],
        "awareness_at": a["awareness_at"],
        "seriousness": a["seriousness"],
        "description": a["description"],
        "reported_by_user_id": a["reported_by_user_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_report(r):
    return {
        "id": r["id"],
        "enrollment_id": r["enrollment_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "created_by_user_id": r["created_by_user_id"],
        "status": r["status"],
        "fills_delivered_count": r["fills_delivered_count"],
        "adverse_event_count": r["adverse_event_count"],
        "total_assistance_cents": r["total_assistance_cents"],
        "pdc_pct": r["pdc_pct"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------- Lookups ----------

def bi_for_enrollment(enrollment_id):
    for b in store.benefits_investigations.values():
        if b["enrollment_id"] == enrollment_id:
            return b
    return None


def pas_for_enrollment(enrollment_id):
    return [p for p in store.prior_authorizations.values()
            if p["enrollment_id"] == enrollment_id]


def assistances_for_enrollment(enrollment_id):
    return [a for a in store.copay_assistances.values()
            if a["enrollment_id"] == enrollment_id]


def nonterminal_assistance(enrollment_id):
    """The unique non-terminal assistance for the enrollment, if any."""
    for a in store.copay_assistances.values():
        if a["enrollment_id"] == enrollment_id and a["status"] != "RELEASED":
            return a
    return None


def shipments_for_enrollment(enrollment_id):
    return [s for s in store.shipments.values()
            if s["enrollment_id"] == enrollment_id]


def visits_for_enrollment(enrollment_id):
    return [v for v in store.nurse_visits.values()
            if v["enrollment_id"] == enrollment_id]


def aes_for_enrollment(enrollment_id):
    return [a for a in store.adverse_events.values()
            if a["enrollment_id"] == enrollment_id]


def reports_for_enrollment(enrollment_id):
    return [r for r in store.outcome_reports.values()
            if r["enrollment_id"] == enrollment_id]


# ---------- PDC adherence ----------

def _round_half_up_1dp(value_decimal):
    """Round a Decimal to exactly one decimal place, half-up."""
    return float(value_decimal.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_pdc(enrollment, confirmed, evaluation_date=None):
    """Proportion of days covered.

    confirmed=True  -> DELIVERED shipments only
    confirmed=False -> SHIPPED + DELIVERED shipments
    Returns None when therapy_start_date is null.
    """
    tsd_str = enrollment.get("therapy_start_date")
    if tsd_str is None:
        return None
    therapy_start = date.fromisoformat(tsd_str)
    if evaluation_date is None:
        evaluation_date = logical_today()
    window_days = (evaluation_date - therapy_start).days
    if window_days < 1:
        window_days = 1
    statuses = ("DELIVERED",) if confirmed else ("SHIPPED", "DELIVERED")
    covered = sum(
        s["days_supply"]
        for s in shipments_for_enrollment(enrollment["id"])
        if s["status"] in statuses
    )
    covered_days = min(window_days, covered)
    pct = Decimal(100) * Decimal(covered_days) / Decimal(window_days)
    return _round_half_up_1dp(pct)


def compute_pdc_for_report(enrollment, period_end):
    """Confirmed-variant PDC with evaluation_date = period_end.

    Null when therapy_start_date is null or period_end <= therapy_start_date.
    """
    tsd_str = enrollment.get("therapy_start_date")
    if tsd_str is None:
        return None
    therapy_start = date.fromisoformat(tsd_str)
    if period_end <= therapy_start:
        return None
    return compute_pdc(enrollment, confirmed=True, evaluation_date=period_end)


# ---------- Splits ----------

def run_split(shipment, assistance, bi):
    """Run the ship-time financial split.

    Returns (assistance_pay_cents, patient_pay_cents,
             payer_accumulator_delta_cents).
    """
    cost_share = shipment["patient_cost_share_cents"]

    if assistance is not None and assistance["remaining_annual_benefit_cents"] > 0:
        if assistance["assistance_type"] == "COPAY_CARD":
            assistance_pay = min(
                assistance["per_fill_cap_cents"],
                assistance["remaining_annual_benefit_cents"],
                cost_share,
            )
        else:  # FOUNDATION
            raw = Decimal(cost_share) * Decimal(assistance["coverage_pct"]) / Decimal(100)
            rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            assistance_pay = min(rounded, assistance["remaining_annual_benefit_cents"])
        if assistance_pay < 0:
            assistance_pay = 0
    else:
        assistance_pay = 0

    patient_pay = cost_share - assistance_pay
    if bi["plan_has_accumulator"]:
        delta = patient_pay
    else:
        delta = patient_pay + assistance_pay
    return assistance_pay, patient_pay, delta


# ---------- Cascades ----------

def activate_reserved_assistance(enrollment):
    """RESERVED -> ACTIVE when enrollment reaches APPROVED/ACTIVE.

    Then chain: REQUESTED shipments with clearance now open -> SCHEDULED.
    """
    a = nonterminal_assistance(enrollment["id"])
    if a is not None and a["status"] == "RESERVED" and \
            enrollment["status"] in ("APPROVED", "ACTIVE"):
        a["status"] = "ACTIVE"
        touch(a)
    schedule_cleared_shipments(enrollment)


def schedule_cleared_shipments(enrollment):
    """REQUESTED shipments -> SCHEDULED when enrollment is APPROVED/ACTIVE
    and no RESERVED assistance blocks financial clearance."""
    if enrollment["status"] not in ("APPROVED", "ACTIVE"):
        return
    a = nonterminal_assistance(enrollment["id"])
    if a is not None and a["status"] == "RESERVED":
        return
    for s in shipments_for_enrollment(enrollment["id"]):
        if s["status"] == "REQUESTED":
            s["status"] = "SCHEDULED"
            touch(s)


def release_assistance(a):
    """Release a non-terminal assistance, returning undisbursed funds.

    Computes returned_cents = annual_benefit_cap_cents - disbursed_cents
    and, for FOUNDATION grants, credits the pool.
    """
    a["returned_cents"] = a["annual_benefit_cap_cents"] - a["disbursed_cents"]
    a["status"] = "RELEASED"
    touch(a)
    if a["assistance_type"] == "FOUNDATION" and a["foundation_pool_id"]:
        pool = store.foundation_pools.get(a["foundation_pool_id"])
        if pool is not None:
            pool["remaining_balance_cents"] += a["returned_cents"]
            touch(pool)


def cancel_pending_shipments(enrollment):
    """REQUESTED/SCHEDULED shipments -> CANCELLED (termination cascade)."""
    for s in shipments_for_enrollment(enrollment["id"]):
        if s["status"] in ("REQUESTED", "SCHEDULED"):
            s["status"] = "CANCELLED"
            touch(s)


def release_all_nonterminal_assistances(enrollment):
    for a in assistances_for_enrollment(enrollment["id"]):
        if a["status"] != "RELEASED":
            release_assistance(a)
