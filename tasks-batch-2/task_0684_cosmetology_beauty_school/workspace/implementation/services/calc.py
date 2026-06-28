"""Calculation rules (PRD 3.2 / 3.5 / 3.6 / 3.7 / 3.8; scaffold §1.3).

Every derived figure is computed deterministically here. Monetary amounts are
integer cents; sub-cent intermediates are round-half-up. Several rules pin the
exact order of rounding versus summation — those orders are followed exactly.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from helpers import round_half_up, round2


def credit_hours(total_clock_hours, clock_hours_per_credit):
    """CALC clock_to_credit: floor(total_clock_hours / clock_hours_per_credit),
    truncating toward zero to an integer (PRD 3.1)."""
    return int(math.floor(total_clock_hours / clock_hours_per_credit))


def clinic_hours(start_dt, end_dt):
    """(end_iso - start_iso) in hours, rounded half up to 2 decimal places."""
    seconds = (end_dt - start_dt).total_seconds()
    hours = seconds / 3600.0
    return round2(hours)


def actual_hours(enrollment, db):
    """CALC actual_hours_accrual (PRD 3.3): full recompute from scratch.

      sum(AttendanceRecord.hours WHERE status == APPROVED AND enrollment matches)
      + sum(ClinicTicket.clinic_hours WHERE status IN {SIGNED_OFF, PAID})
    Rounded to 2 decimal places, round-half-up; recomputed (not incremental) so
    void/return compensation leaves no drift.
    """
    eid = enrollment["id"]
    total = Decimal("0")
    for ar in db.attendance_records.values():
        if ar["enrollment_id"] == eid and ar["status"] == "APPROVED":
            total += Decimal(str(ar["hours"]))
    for ct in db.clinic_tickets.values():
        if ct["enrollment_id"] == eid and ct["status"] in ("SIGNED_OFF", "PAID"):
            total += Decimal(str(ct["clinic_hours"]))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sap_pace(actual, scheduled_hours_to_date):
    """CALC sap_pace (PRD 3.2): actual / scheduled * 100, round-half-up 2dp.
    When scheduled_hours_to_date == 0, pace is fixed at 100.00."""
    if scheduled_hours_to_date == 0:
        return 100.00
    return round2(actual / scheduled_hours_to_date * 100)


def clinic_pos_total(line_items, clinic_discount_pct):
    """CALC clinic_pos_total (PRD 3.5): round EACH discounted line item to whole
    cents (round-half-up), THEN sum. NOT sum-then-round."""
    total = 0
    factor = Decimal("1") - Decimal(str(clinic_discount_pct))
    for li in line_items:
        salon = Decimal(str(li["salon_price_cents"]))
        line = (salon * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(line)
    return total


def disbursement_net(gross_amount_cents, origination_fee_cents):
    """CALC disbursement_net: gross - origination_fee, exact integer cents."""
    return gross_amount_cents - origination_fee_cents


def total_charges(program):
    """tuition + kit + lab, fixed at enrollment time."""
    return program["tuition_cents"] + program["kit_fee_cents"] + program["lab_fee_cents"]


def posted_credits(enrollment, db):
    """Sum of net_amount_cents over POSTED disbursements (CALC ledger_balance)."""
    eid = enrollment["id"]
    return sum(
        d["net_amount_cents"]
        for d in db.disbursements.values()
        if d["enrollment_id"] == eid and d["status"] == "POSTED"
    )


def projected_credits(enrollment, db):
    """CALC projected_ledger: sum of net over POSTED or SCHEDULED disbursements;
    SCHEDULED net is projected as gross - origination_fee."""
    eid = enrollment["id"]
    total = 0
    for d in db.disbursements.values():
        if d["enrollment_id"] != eid:
            continue
        if d["status"] == "POSTED":
            total += d["net_amount_cents"]
        elif d["status"] == "SCHEDULED":
            total += d["gross_amount_cents"] - d["origination_fee_cents"]
    return total


def exam_readiness_score(actual, total_clock_hours, mock_exam_avg, competency_signoff_pct):
    """CALC exam_readiness_score (PRD 3.7): round EACH weighted term to 2dp,
    THEN sum.

      hours_pct = round(actual / total_clock_hours * 100, 2dp)
      hours_factor = min(100, hours_pct)
      t1 = round_half_up(0.40 * hours_factor, 2dp)
      t2 = round_half_up(0.35 * mock_exam_avg, 2dp)
      t3 = round_half_up(0.25 * competency_signoff_pct, 2dp)
      readiness = t1 + t2 + t3
    """
    hours_pct = round2(actual / total_clock_hours * 100)
    hours_factor = min(100, hours_pct)
    t1 = round2(Decimal("0.40") * Decimal(str(hours_factor)))
    t2 = round2(Decimal("0.35") * Decimal(str(mock_exam_avg)))
    t3 = round2(Decimal("0.25") * Decimal(str(competency_signoff_pct)))
    # Sum already-rounded 2dp terms; quantize the sum to remove float artifacts.
    s = Decimal(str(t1)) + Decimal(str(t2)) + Decimal(str(t3))
    return float(s.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def r2t4(pct_completed, total_posted_net_cents):
    """CALC r2t4_return (PRD 3.6): >60% scheduled => 0 returned; otherwise
    aid_earned = round_half_up((pct/100) * total_posted_net), return =
    total_posted_net - aid_earned. The 60.00 boundary is strict (> 60.00)."""
    if pct_completed > 60.00:
        return 0
    aid_earned = round_half_up((Decimal(str(pct_completed)) / Decimal("100")) * Decimal(str(total_posted_net_cents)))
    return total_posted_net_cents - aid_earned


def pct_completed(scheduled_hours_to_date, total_clock_hours):
    """R2T4 completion percentage: scheduled / total * 100, round-half-up 2dp."""
    return round2(scheduled_hours_to_date / total_clock_hours * 100)


def institutional_refund(tuition_cents, admin_fee_cap_cents, actual, total_clock_hours):
    """CALC institutional_refund (PRD 3.6): uses ACTUAL hours.

      pct_used = actual / total_clock_hours
      refund_before_fee = round_half_up(tuition * (1 - pct_used))
      institutional_refund = max(0, refund_before_fee - admin_fee_cap)
    """
    pct_used = Decimal(str(actual)) / Decimal(str(total_clock_hours))
    refund_before_fee = round_half_up(Decimal(str(tuition_cents)) * (Decimal("1") - pct_used))
    return max(0, refund_before_fee - admin_fee_cap_cents)


def placement_rate(total_graduates, excluded_count, placed_count):
    """CALC placement_rate (PRD 3.8): denominator = total - excluded; if <= 0,
    rate is 0; otherwise placed / denominator * 100, round-half-up 2dp."""
    denominator = total_graduates - excluded_count
    if denominator <= 0:
        return 0
    return round2(placed_count / denominator * 100)
