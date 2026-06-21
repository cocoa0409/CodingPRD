"""Shared domain helpers: computed-field recomputation, delinquency/hold
evaluation, term-total-days, and lookups. Routes call into these.
"""
import db
from services import calc, dates


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find_institution(institution_id):
    return db.institutions.get(institution_id)


def installments_of(enrollment_id):
    return [i for i in db.installments.values()
            if i["enrollment_id"] == enrollment_id]


def charges_of(enrollment_id):
    return [c for c in db.charges.values()
            if c["enrollment_id"] == enrollment_id]


def aids_of(enrollment_id):
    return [a for a in db.aids.values()
            if a["enrollment_id"] == enrollment_id]


def late_fees_of(enrollment_id):
    return [f for f in db.late_fees.values()
            if f["enrollment_id"] == enrollment_id]


def active_hold_for_enrollment(enrollment_id):
    for h in db.holds.values():
        if h["enrollment_id"] == enrollment_id and h["status"] == "ACTIVE":
            return h
    return None


def term_total_days(term):
    start = dates.parse_iso(term["term_start"])
    end = dates.parse_iso(term["term_end"])
    return (dates.day_number(end) - dates.day_number(start)) + 1


# ---------------------------------------------------------------------------
# Ledger recomputation (PRD §2.9, §3.6)
# ---------------------------------------------------------------------------

def recompute_gross_and_aid(enrollment):
    """Recompute gross_charges_cents, total_aid_cents, net_after_aid_cents."""
    eid = enrollment["id"]
    gross = sum(c["amount_cents"] for c in charges_of(eid) if c["status"] == "POSTED")
    aid = sum(a["amount_cents"] for a in aids_of(eid) if a["status"] == "APPLIED")
    enrollment["gross_charges_cents"] = gross
    enrollment["total_aid_cents"] = aid
    enrollment["net_after_aid_cents"] = max(0, gross - aid)


def recompute_scheduled_balance(enrollment):
    """scheduled_balance_cents = sum(amount over SCHEDULED + OVERDUE) (PRD §3.6)."""
    eid = enrollment["id"]
    bal = sum(i["amount_cents"] for i in installments_of(eid)
              if i["status"] in ("SCHEDULED", "OVERDUE"))
    enrollment["scheduled_balance_cents"] = bal


def recompute_paid_principal(enrollment):
    """paid_principal_cents = sum(amount over PAID installments) +
    down_payment_cents once collected (PRD §3.6).
    """
    eid = enrollment["id"]
    paid = sum(i["amount_cents"] for i in installments_of(eid)
               if i["status"] == "PAID")
    if enrollment.get("down_payment_collected"):
        paid += enrollment["down_payment_cents"]
    enrollment["paid_principal_cents"] = paid


def recompute_late_fee_balance(enrollment):
    """late_fee_balance_cents = sum(amount over ASSESSED late fees) (PRD §3.7)."""
    eid = enrollment["id"]
    bal = sum(f["amount_cents"] for f in late_fees_of(eid)
              if f["status"] == "ASSESSED")
    enrollment["late_fee_balance_cents"] = bal


def recompute_delinquent_count(enrollment):
    eid = enrollment["id"]
    enrollment["delinquent_installment_count"] = sum(
        1 for i in installments_of(eid) if i["status"] == "OVERDUE")


def total_overdue_amount(enrollment):
    eid = enrollment["id"]
    return sum(i["amount_cents"] - i["paid_amount_cents"]
               for i in installments_of(eid) if i["status"] == "OVERDUE")


# ---------------------------------------------------------------------------
# has_active_hold recompute (PRD §3.8)
# ---------------------------------------------------------------------------

def recompute_student_hold(student):
    has = any(h["status"] == "ACTIVE" for h in db.holds.values()
              if h["student_id"] == student["id"])
    student["has_active_hold"] = has


# ---------------------------------------------------------------------------
# Delinquency evaluation (PRD §3.8) — may create or release a hold.
# ---------------------------------------------------------------------------

def delinquency_evaluation(enrollment):
    """Re-evaluate thresholds; create/release hold accordingly. Caller is
    responsible for any enrollment.version bump from the surrounding operation.
    """
    count = enrollment["delinquent_installment_count"]
    total = total_overdue_amount(enrollment)
    tripped, reason = calc.delinquency_tripped(count, total)
    existing = active_hold_for_enrollment(enrollment["id"])
    student = db.students[enrollment["student_id"]]

    if tripped and existing is None:
        hold = db.stamp_new({
            "institution_id": enrollment["institution_id"],
            "student_id": enrollment["student_id"],
            "enrollment_id": enrollment["id"],
            "reason": reason,
            "status": "ACTIVE",
        })
        db.holds[hold["id"]] = hold
        recompute_student_hold(student)
        db.touch(student)
    elif not tripped and existing is not None:
        existing["status"] = "RELEASED"
        db.touch(existing)
        recompute_student_hold(student)
        db.touch(student)


def release_hold_for_enrollment(enrollment):
    """Unconditionally release any ACTIVE hold for this enrollment and
    recompute the student's flag (used by completion and withdrawal).
    """
    existing = active_hold_for_enrollment(enrollment["id"])
    if existing is not None:
        existing["status"] = "RELEASED"
        db.touch(existing)
        student = db.students[enrollment["student_id"]]
        recompute_student_hold(student)
        db.touch(student)


# ---------------------------------------------------------------------------
# Completion bubble-up (PRD §3.6)
# ---------------------------------------------------------------------------

def down_payment_settled(enrollment):
    """The down payment obligation is satisfied: a zero down payment is settled
    by construction; a positive down payment must have been collected.
    """
    if enrollment["down_payment_cents"] == 0:
        return True
    return bool(enrollment.get("down_payment_collected"))


def maybe_complete(enrollment):
    """If every installment is PAID and the down payment has been collected,
    bubble ACTIVE -> COMPLETED.
    """
    if enrollment["status"] != "ACTIVE":
        return
    insts = installments_of(enrollment["id"])
    if not insts:
        return
    if not all(i["status"] == "PAID" for i in insts):
        return
    if not down_payment_settled(enrollment):
        return
    enrollment["status"] = "COMPLETED"
    recompute_scheduled_balance(enrollment)  # -> 0
    db.touch(enrollment)
    # On completion, release an ACTIVE hold for this enrollment if any.
    release_hold_for_enrollment(enrollment)
