"""Payment ledger and derived balance logic."""
from decimal import Decimal, ROUND_HALF_UP
from db import store, new_id, now, now_iso
from errors import raise_err, ERR_PAYMENT_NOT_FOUND, ERR_INVALID_REQUEST, ERR_REFUND_EXCEEDS_PAID

DEBIT_KINDS = {"MANUAL_DEBIT", "RENTAL_FEE_DEBIT", "LATE_FEE_DEBIT", "CLEANING_FEE_DEBIT", "TRIP_SHARE_DEBIT"}
CREDIT_KINDS = {"PAYMENT", "WAIVER", "FUNDRAISING_CREDIT"}
CLIENT_POSTABLE_KINDS = {"PAYMENT", "REFUND", "WAIVER", "MANUAL_DEBIT"}
SYSTEM_ONLY_KINDS = {"RENTAL_FEE_DEBIT", "LATE_FEE_DEBIT", "CLEANING_FEE_DEBIT", "TRIP_SHARE_DEBIT", "FUNDRAISING_CREDIT"}


def round_half_up_cents(x):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def student_payments(student_id):
    return [p for p in store.payments.values() if p["student_id"] == student_id]


def account_balance(student_id):
    debits = sum(p["amount_cents"] for p in student_payments(student_id) if p["kind"] in DEBIT_KINDS)
    credits = sum(p["amount_cents"] for p in student_payments(student_id) if p["kind"] in CREDIT_KINDS)
    refunds = sum(p["amount_cents"] for p in student_payments(student_id) if p["kind"] == "REFUND")
    return debits - credits + refunds


def is_delinquent(student):
    program = store.programs.get(student["program_id"])
    if program is None:
        return False
    return student["account_balance_cents"] > program["delinquency_grace_cents"]


def recompute_student(student):
    student["account_balance_cents"] = account_balance(student["id"])
    student["is_delinquent"] = is_delinquent(student)


def touch_student(student):
    """Recompute balance and bump version (mutation side effect)."""
    recompute_student(student)
    student["version"] += 1
    student["updated_at"] = now_iso()


def applied_to_debit(debit_id):
    """Sum of allocations already applied against a debit row."""
    total = 0
    for p in store.payments.values():
        if p["kind"] != "PAYMENT":
            continue
        for alloc in p.get("allocations", []):
            if alloc["debit_payment_id"] == debit_id:
                total += alloc["applied_cents"]
    return total


def post_ledger(student_id, kind, amount_cents, trip_enrollment_id=None,
                reference_payment_id=None, fundraiser_id=None, note=None,
                allocations=None):
    """System/internal ledger post. Returns the new Payment row."""
    pid = new_id()
    row = {
        "id": pid,
        "student_id": student_id,
        "kind": kind,
        "amount_cents": int(amount_cents),
        "trip_enrollment_id": trip_enrollment_id,
        "fundraiser_id": fundraiser_id,
        "reference_payment_id": reference_payment_id,
        "allocations": allocations if allocations is not None else [],
        "note": note,
        "created_at": now_iso(),
    }
    store.payments[pid] = row
    # Recompute student derived fields
    student = store.students.get(student_id)
    if student is not None:
        recompute_student(student)
    # Recompute linked enrollment derived fields
    if trip_enrollment_id:
        enr = store.trip_enrollments.get(trip_enrollment_id)
        if enr is not None:
            recompute_enrollment(enr)
    return row


def recompute_enrollment(enr):
    rows = [p for p in store.payments.values() if p.get("trip_enrollment_id") == enr["id"]]
    pay = sum(p["amount_cents"] for p in rows if p["kind"] == "PAYMENT")
    ref = sum(p["amount_cents"] for p in rows if p["kind"] == "REFUND")
    enr["net_paid_cents"] = pay - ref
    enr["refunded_cents"] = ref
    # Recompute payment_status unless explicitly REFUNDED already
    if enr.get("payment_status") != "REFUNDED":
        if enr["net_paid_cents"] == 0:
            enr["payment_status"] = "UNPAID"
        elif enr["amount_due_cents"] > 0 and enr["net_paid_cents"] >= enr["amount_due_cents"]:
            enr["payment_status"] = "PAID"
        else:
            enr["payment_status"] = "PARTIAL"


def run_waterfall(student, payment_amount):
    """Run allocation waterfall over student's outstanding debits.
    Returns allocations list."""
    debits = [p for p in store.payments.values()
              if p["student_id"] == student["id"] and p["kind"] in DEBIT_KINDS]
    outstanding = []
    for d in debits:
        already = applied_to_debit(d["id"])
        remain = d["amount_cents"] - already
        if remain > 0:
            outstanding.append((d, remain))
    # order by created_at ASC, tie amount_cents ASC
    outstanding.sort(key=lambda t: (t[0]["created_at"], t[0]["amount_cents"]))
    allocations = []
    remaining = payment_amount
    for debit, remain in outstanding:
        if remaining <= 0:
            break
        applied = min(remaining, remain)
        allocations.append({"debit_payment_id": debit["id"], "applied_cents": applied})
        remaining -= applied
    return allocations


def net_cash_paid(student_id):
    rows = student_payments(student_id)
    pay = sum(p["amount_cents"] for p in rows if p["kind"] == "PAYMENT")
    ref = sum(p["amount_cents"] for p in rows if p["kind"] == "REFUND")
    return pay - ref
