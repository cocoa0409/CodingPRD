"""Expiry sweeps (clock set) and the monthly ops checkpoint (PRD 3.9).

Calculations covered: chargeback_ratio, program_threshold_evaluation,
program_fine_schedule.
"""

from db import db
from clock import CLOCK
from records import (
    new_education_assignment, new_fee_assessment, new_program_enrollment,
    new_ratio_snapshot, touch,
)
from services.cascade import cascade_expire
from services.reserve import account_for_merchant, recompute_target
from util import ZERO_DENOMINATOR_SENTINEL_BPS, month_of, rhu
from decimal import Decimal, ROUND_HALF_UP


VDMP_STANDARD_MIN_BPS = 90
VDMP_STANDARD_MIN_COUNT = 5
VDMP_EXCESSIVE_MIN_BPS = 180
VDMP_EXCESSIVE_MIN_COUNT = 10
ECM_MIN_BPS = 150
ECM_MIN_COUNT = 10
HECM_MIN_BPS = 300
HECM_MIN_COUNT = 10

BASE_FINE_CENTS = {
    "VDMP_STANDARD": 250000,
    "VDMP_EXCESSIVE": 500000,
    "ECM": 250000,
    "HECM": 500000,
}

THRESHOLD_BPS = {
    "VDMP_STANDARD": VDMP_STANDARD_MIN_BPS,
    "VDMP_EXCESSIVE": VDMP_EXCESSIVE_MIN_BPS,
    "ECM": ECM_MIN_BPS,
    "HECM": HECM_MIN_BPS,
}


def match_tier(network, count_ratio_bps, chargeback_count):
    """program_threshold_evaluation; inclusive boundaries; higher tier wins."""
    if network == "VISA":
        if count_ratio_bps >= VDMP_EXCESSIVE_MIN_BPS and chargeback_count >= VDMP_EXCESSIVE_MIN_COUNT:
            return "VDMP_EXCESSIVE"
        if count_ratio_bps >= VDMP_STANDARD_MIN_BPS and chargeback_count >= VDMP_STANDARD_MIN_COUNT:
            return "VDMP_STANDARD"
    elif network == "MASTERCARD":
        if count_ratio_bps >= HECM_MIN_BPS and chargeback_count >= HECM_MIN_COUNT:
            return "HECM"
        if count_ratio_bps >= ECM_MIN_BPS and chargeback_count >= ECM_MIN_COUNT:
            return "ECM"
    return None


def fine_amount_cents(program_code, months_over_count):
    base = BASE_FINE_CENTS[program_code]
    if months_over_count <= 3:
        multiplier = Decimal("1.0")
    elif months_over_count <= 6:
        multiplier = Decimal("1.5")
    else:
        multiplier = Decimal("2.0")
    return int((Decimal(base) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ratio_bps(numerator, denominator):
    if denominator == 0:
        return ZERO_DENOMINATOR_SENTINEL_BPS if numerator > 0 else 0
    return rhu(10000 * numerator, denominator)


def education_modules_for(program_code):
    if program_code.startswith("VDMP_"):
        return ("CHARGEBACK_BASICS", "EVIDENCE_BEST_PRACTICE")
    return ("CHARGEBACK_BASICS", "FRAUD_PREVENTION")


def create_education_cascade(enrollment):
    for module_code in education_modules_for(enrollment["program_code"]):
        asg = new_education_assignment(enrollment["merchant_id"], enrollment["id"], module_code)
        db.education_assignments[asg["id"]] = asg


def enrollment_month_ranges_overlap(a_enrolled, a_exited, b_enrolled, b_exited):
    """CLOSED month intervals [enrolled_month, exited_month]; None exit = open-ended."""
    a_end = a_exited if a_exited is not None else "9999-12"
    b_end = b_exited if b_exited is not None else "9999-12"
    return a_enrolled <= b_end and b_enrolled <= a_end


def expiry_sweep():
    """Fires on every clock set: past-due OPEN alerts -> EXPIRED; past-due
    RECEIVED/MERCHANT_NOTIFIED chargebacks -> EXPIRED with cascades."""
    now = CLOCK.now()
    for alert in list(db.prevention_alerts.values()):
        if alert["status"] == "OPEN" and alert["response_due_at"] < now:
            alert["status"] = "EXPIRED"
            touch(alert)
    for cb in list(db.chargebacks.values()):
        if cb["case_status"] in ("RECEIVED", "MERCHANT_NOTIFIED") and cb["representment_due_at"] < now:
            cascade_expire(cb)


def refresh_current_ratio(merchant):
    """current_count_ratio_bps := count_ratio_bps of the most recent POSTED snapshot
    by period_month (tie-break: latest computed_at); null when none."""
    snaps = [s for s in db.ratio_snapshots.values() if s["merchant_id"] == merchant["id"]]
    if not snaps:
        new_value = None
    else:
        snaps.sort(key=lambda s: (s["period_month"], s["computed_at"], s["created_at"]))
        new_value = snaps[-1]["count_ratio_bps"]
    if merchant["current_count_ratio_bps"] != new_value:
        merchant["current_count_ratio_bps"] = new_value
        touch(merchant)


def _existing_open_enrollments(merchant_id, network):
    return [e for e in db.program_enrollments.values()
            if e["merchant_id"] == merchant_id and e["network"] == network
            and e["status"] in ("ACTIVE", "REMEDIATION")]


def advance_month(period_month, only_merchant_id=None):
    """Monthly ops checkpoint. Returns the tally object."""
    snapshots_created = 0
    snapshots_skipped = 0
    enrollments_created = 0
    fines_assessed = 0
    now = CLOCK.now()

    merchants = [m for m in db.merchants.values()
                 if only_merchant_id is None or m["id"] == only_merchant_id]

    for merchant in merchants:
        for network in ("VISA", "MASTERCARD"):
            txns = [t for t in db.transactions.values()
                    if t["merchant_id"] == merchant["id"] and t["network"] == network
                    and month_of(t["occurred_at"]) == period_month]
            cbs = [c for c in db.chargebacks.values()
                   if c["merchant_id"] == merchant["id"] and c["network"] == network
                   and month_of(c["received_at"]) == period_month]
            if not txns and not cbs:
                continue  # no activity -> no snapshot for this triple
            already = any(s for s in db.ratio_snapshots.values()
                          if s["merchant_id"] == merchant["id"] and s["network"] == network
                          and s["period_month"] == period_month)
            if already:
                snapshots_skipped += 1  # immutable once posted: repeat sweep skips
                continue

            sales_count = len(txns)
            sales_amount = sum(t["amount_cents"] for t in txns)
            posted_num = sum(1 for c in cbs if c["case_status"] != "REVERSED")
            gross_num = len(cbs)
            snap = new_ratio_snapshot(
                merchant_id=merchant["id"], network=network, period_month=period_month,
                sales_count=sales_count, sales_amount_cents=sales_amount,
                chargeback_count=posted_num, gross_chargeback_count=gross_num,
                count_ratio_bps=ratio_bps(posted_num, sales_count),
                gross_count_ratio_bps=ratio_bps(gross_num, sales_count),
                computed_at=now,
            )
            db.ratio_snapshots[snap["id"]] = snap
            snapshots_created += 1

            # Program threshold evaluation on the POSTED basis.
            tier = match_tier(network, snap["count_ratio_bps"], snap["chargeback_count"])
            open_enrollments = _existing_open_enrollments(merchant["id"], network)
            if tier is not None:
                if open_enrollments:
                    for en in open_enrollments:
                        # over threshold -> increment; fine computed from the
                        # ALREADY-INCREMENTED months_over_count
                        en["months_over_count"] += 1
                        touch(en)
                        if en["status"] == "ACTIVE":  # REMEDIATION enrollments are not fined
                            fine = new_fee_assessment(
                                merchant_id=merchant["id"], chargeback_id=None,
                                enrollment_id=en["id"], kind="PROGRAM_FINE",
                                amount_cents=fine_amount_cents(en["program_code"], en["months_over_count"]),
                                assessed_by="system")
                            db.fee_assessments[fine["id"]] = fine
                            fines_assessed += 1
                else:
                    en = new_program_enrollment(merchant["id"], network, tier, period_month)
                    db.program_enrollments[en["id"]] = en
                    enrollments_created += 1
                    create_education_cascade(en)
                    # The new enrollment is ACTIVE and its snapshot is over threshold:
                    # fined in the same sweep at months_over_count = 1 (multiplier 1.0).
                    fine = new_fee_assessment(
                        merchant_id=merchant["id"], chargeback_id=None,
                        enrollment_id=en["id"], kind="PROGRAM_FINE",
                        amount_cents=fine_amount_cents(en["program_code"], en["months_over_count"]),
                        assessed_by="system")
                    db.fee_assessments[fine["id"]] = fine
                    fines_assessed += 1

        # Per swept merchant: refresh the posted-basis ratio pointer + reserve target.
        refresh_current_ratio(merchant)
        acct = recompute_target(merchant)
        if acct is not None:
            touch(acct)

    return {
        "snapshots_created": snapshots_created,
        "snapshots_skipped": snapshots_skipped,
        "enrollments_created": enrollments_created,
        "fines_assessed": fines_assessed,
    }
