"""Shared domain services: derived-field reconciliation and cascades."""

from decimal import Decimal

from store import db, now, touch
import calc

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def charges_of_case(case_id):
    return [c for c in db.charges.values() if c["case_id"] == case_id]


def account_of_case(case_id):
    for a in db.ledger_accounts.values():
        if a["case_id"] == case_id:
            return a
    return None


def payments_of_account(account_id):
    return [p for p in db.payments.values() if p["ledger_account_id"] == account_id]


def plans_of_account(account_id):
    return [p for p in db.installment_plans.values() if p["ledger_account_id"] == account_id]


def assignments_of_diversion(diversion_id):
    return [a for a in db.service_assignments.values() if a["diversion_id"] == diversion_id]


def diversion_of_case(case_id):
    for d in db.diversion_agreements.values():
        if d["case_id"] == case_id:
            return d
    return None


def warrants_of_case(case_id):
    return [w for w in db.warrants.values() if w["case_id"] == case_id]


# ---------------------------------------------------------------------------
# Ledger account recomputation
# ---------------------------------------------------------------------------
def recompute_assessed(account):
    account["assessed_amount"] = calc.q2(
        account["_fines"] + account["_court_fee"] + account["_surcharge"]
        + account["_program_fee"] + account["_penalty"]
    )


def recompute_account(account):
    """Recompute collected_amount and balance from source payment rows."""
    recompute_assessed(account)
    collected = Decimal("0")
    for p in payments_of_account(account["id"]):
        if not p["reversed"]:
            collected += calc.to_decimal(p["amount"])
    account["collected_amount"] = calc.q2(collected)
    account["balance"] = calc.q2(account["assessed_amount"] - account["collected_amount"])


def bucket_outstanding(account):
    """Outstanding per waterfall bucket = bucket assessed - already allocated (non-reversed)."""
    alloc = {"fines": Decimal("0"), "court_fee": Decimal("0"),
             "surcharge": Decimal("0"), "program_fee": Decimal("0")}
    for p in payments_of_account(account["id"]):
        if p["reversed"]:
            continue
        alloc["fines"] += calc.to_decimal(p["allocated_fines"])
        alloc["court_fee"] += calc.to_decimal(p["allocated_court_fee"])
        alloc["surcharge"] += calc.to_decimal(p["allocated_surcharge"])
        alloc["program_fee"] += calc.to_decimal(p["allocated_program_fee"])
    return {
        "fines": account["_fines"] - alloc["fines"],
        "court_fee": account["_court_fee"] - alloc["court_fee"],
        "surcharge": account["_surcharge"] - alloc["surcharge"],
        "program_fee": account["_program_fee"] - alloc["program_fee"],
    }


# ---------------------------------------------------------------------------
# Diversion agreement recomputation
# ---------------------------------------------------------------------------
def recompute_agreement(agreement):
    assignments = assignments_of_diversion(agreement["id"])
    account = account_of_case(agreement["case_id"])

    assigned = sum((calc.to_decimal(a["required_hours"]) for a in assignments
                    if a["status"] != "WAIVED"), Decimal("0"))
    completed = sum((calc.to_decimal(a["completed_hours"]) for a in assignments
                     if a["status"] == "COMPLETED"), Decimal("0"))
    completed_sessions = sum(1 for a in assignments
                             if a["assignment_type"] == "EDUCATION_CLASS" and a["status"] == "COMPLETED")

    agreement["assigned_service_hours"] = assigned
    agreement["completed_service_hours"] = completed
    agreement["completed_class_sessions"] = completed_sessions
    agreement["provisional_compliance_pct"] = calc.compliance_pct(
        agreement, assignments, account, "provisional")
    agreement["final_compliance_pct"] = calc.compliance_pct(
        agreement, assignments, account, "final")


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def try_settle_account(account):
    """If balance hit zero, ASSESSED -> SETTLED and ACTIVE plan -> PAID_OFF."""
    if account["status"] == "ASSESSED" and account["balance"] == Decimal("0.00"):
        account["status"] = "SETTLED"
        touch(account, bump_version=False)
        for plan in plans_of_account(account["id"]):
            if plan["status"] == "ACTIVE":
                plan["status"] = "PAID_OFF"
                touch(plan)


def maybe_complete_diversion(agreement):
    """Bubble DiversionAgreement -> COMPLETED and Case -> COMPLIED when gates pass.

    Raises ERR_LEDGER_NOT_SETTLED when service gates pass but the ledger is not SETTLED.
    Returns True if the agreement completed.
    """
    from errors import ApiError
    if agreement["status"] != "IN_PROGRESS":
        return False
    assignments = assignments_of_diversion(agreement["id"])
    if not assignments:
        return False
    if any(a["status"] not in ("COMPLETED", "WAIVED") for a in assignments):
        return False
    if agreement["completed_service_hours"] < calc.to_decimal(agreement["mandated_service_hours"]):
        return False
    if agreement["completed_class_sessions"] < int(agreement["required_class_sessions"]):
        return False
    account = account_of_case(agreement["case_id"])
    if account is None or account["status"] != "SETTLED":
        raise ApiError("ERR_LEDGER_NOT_SETTLED",
                       "ledger account must be SETTLED before diversion may complete")
    # complete
    agreement["status"] = "COMPLETED"
    recompute_agreement(agreement)
    touch(agreement)
    # bubble case -> COMPLIED and create expungement referral
    case = db.cases[agreement["case_id"]]
    case["status"] = "COMPLIED"
    touch(case)
    from store import base_fields
    ref = base_fields()
    ref.update({
        "case_id": case["id"],
        "eligible_date": now(),
        "status": "PENDING",
    })
    db.expungement_referrals[ref["id"]] = ref
    return True
