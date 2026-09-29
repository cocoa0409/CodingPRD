"""Domain services: lookups, roll-ups, cascades and the liquidation waterfall.

Everything here is derived from PRD sections 2.11, 3.4, 3.5 and 3.8.
"""
from decimal import Decimal

from calc import (advance_interest, appraisal_reduction_amount,
                  ara_adjusted_advance_obligation,
                  controlling_class_control_test, liquidation_fee_amount)
from datetimes import iso
from db import base_row, db, touch
from errors import ApiError
from money import D, ZERO, dmin, q2, q6

ACTIVE_ADVANCE_STATUSES = ("OUTSTANDING", "PARTIALLY_REIMBURSED")
IN_SPECIAL_SERVICING_STATUSES = ("SPECIAL_SERVICING", "IN_WORKOUT", "REO")


# ----------------------------------------------------------------- lookups
def find(collection, row_id, error_id):
    """Resolve a stored row or raise the collection's not-found error."""
    table = getattr(db, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def rows_of(collection):
    return list(getattr(db, collection).values())


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def children(collection, key, value):
    return sort_created([r for r in rows_of(collection) if r.get(key) == value])


def trust_of_loan(loan):
    return db.trusts.get(loan["trust_id"])


def loan_of(row):
    return db.loans.get(row.get("loan_id"))


def advances_of(loan_id):
    return children("advances", "loan_id", loan_id)


def active_advances_of(loan_id):
    return [a for a in advances_of(loan_id) if a["status"] in ACTIVE_ADVANCE_STATUSES]


def reductions_of(loan_id):
    return children("appraisal_reductions", "loan_id", loan_id)


def effective_reduction_of(loan_id):
    for row in reductions_of(loan_id):
        if row["status"] == "EFFECTIVE":
            return row
    return None


def appraisals_of(loan_id):
    return children("appraisals", "loan_id", loan_id)


def accepted_appraisal_of(loan_id):
    for row in appraisals_of(loan_id):
        if row["status"] == "ACCEPTED":
            return row
    return None


def alternatives_of(plan_id):
    return children("workout_alternatives", "workout_plan_id", plan_id)


def has_current_accepted_appraisal(loan_id):
    """PRD 3.6 / 3.7: an ACCEPTED appraisal whose HALF-OPEN window holds the clock."""
    now = db.now()
    for row in appraisals_of(loan_id):
        if row["status"] != "ACCEPTED":
            continue
        start = row.get("_coverage_start_dt")
        end = row.get("_coverage_end_dt")
        if start is None or end is None:
            continue
        if start <= now < end:
            return True
    return False


# ----------------------------------------------------- advance interest
def refresh_advance(advance, trust=None):
    """Accrue simple interest on an active advance up to the logical clock."""
    if advance["status"] not in ACTIVE_ADVANCE_STATUSES:
        return advance
    if trust is None:
        loan = loan_of(advance)
        trust = trust_of_loan(loan) if loan else None
    rate = trust["advance_interest_rate_pct"] if trust else ZERO
    now = db.now()
    accrued, _days = advance_interest(
        advance["amount_usd"],
        advance["reimbursed_principal_usd"],
        advance["_advanced_on_dt"],
        now,
        rate,
    )
    advance["accrued_interest_usd"] = accrued
    advance["interest_accrued_through"] = iso(now)
    return advance


def refresh_loan_advances(loan):
    trust = trust_of_loan(loan)
    for advance in advances_of(loan["id"]):
        refresh_advance(advance, trust)


def total_advance_interest(loan, trust=None):
    if trust is None:
        trust = trust_of_loan(loan)
    total = ZERO
    for advance in active_advances_of(loan["id"]):
        refresh_advance(advance, trust)
        total += D(advance["accrued_interest_usd"])
    return q2(total)


def outstanding_advance_principal(loan_id):
    total = ZERO
    for advance in active_advances_of(loan_id):
        total += D(advance["amount_usd"]) - D(advance["reimbursed_principal_usd"])
    return q2(total)


# --------------------------------------------------------------- roll-ups
def recompute_loan(loan):
    """Derived Loan fields (PRD 3.4). Never bumps the version by itself."""
    loan["advances_outstanding_usd"] = outstanding_advance_principal(loan["id"])

    fees = ZERO
    for accrual in rows_of("fee_accruals"):
        if accrual["loan_id"] == loan["id"] and accrual["status"] == "ACCRUED":
            fees += D(accrual["amount_usd"])
    loan["fees_payable_usd"] = q2(fees)

    reduction = effective_reduction_of(loan["id"])
    loan["ara_amount_usd"] = q2(reduction["ara_amount_usd"]) if reduction else ZERO

    appraisal = accepted_appraisal_of(loan["id"])
    loan["last_appraised_value_usd"] = (
        q2(appraisal["value_usd"]) if appraisal and appraisal.get("value_usd") is not None else None
    )

    loan["required_monthly_pi_advance_usd"] = ara_adjusted_advance_obligation(
        loan["monthly_debt_service_usd"],
        loan["current_principal_balance_usd"],
        loan["ara_amount_usd"],
    )
    return loan


def recompute_trust(trust, cascade=True):
    """Derived Trust fields plus the control-termination cascade (PRD 3.5)."""
    loan_ids = set(
        loan["id"] for loan in rows_of("loans") if loan["trust_id"] == trust["id"]
    )

    total_ara = ZERO
    for reduction in rows_of("appraisal_reductions"):
        if reduction["loan_id"] in loan_ids and reduction["status"] == "EFFECTIVE":
            total_ara += D(reduction["ara_amount_usd"])
    trust["total_ara_usd"] = q2(total_ara)

    total_advances = ZERO
    for advance in rows_of("advances"):
        if advance["loan_id"] in loan_ids and advance["status"] in ACTIVE_ADVANCE_STATUSES:
            total_advances += D(advance["amount_usd"]) - D(advance["reimbursed_principal_usd"])
    trust["total_advances_outstanding_usd"] = q2(total_advances)

    trust["loans_in_special_servicing_count"] = sum(
        1
        for loan in rows_of("loans")
        if loan["trust_id"] == trust["id"]
        and loan["servicing_status"] in IN_SPECIAL_SERVICING_STATUSES
    )

    previous = trust["control_status"]
    notional, _threshold, status = controlling_class_control_test(
        trust["original_controlling_class_balance_usd"],
        trust["total_ara_usd"],
        trust["realized_loss_usd"],
    )
    trust["controlling_class_notional_usd"] = notional
    trust["control_status"] = status

    if cascade and previous == "CONTROLLING" and status == "CONSULTING_ONLY":
        control_termination_cascade(trust)
    return trust


# --------------------------------------------------------------- cascades
def control_termination_cascade(trust):
    """CONTROLLING -> CONSULTING_ONLY downgrades every open consent right."""
    pending = [
        row
        for row in rows_of("consultations")
        if row["trust_id"] == trust["id"]
        and row["status"] == "PENDING"
        and row["rights_type"] == "CONSENT_RIGHT"
    ]
    pending.sort(key=lambda r: (r["_deadline_dt"], r["created_at"], r["_seq"]))
    for consultation in pending:
        consultation["rights_type"] = "CONSULTATION_ONLY"
        consultation["status"] = "WAIVED"
        touch(consultation)
        apply_consultation_outcome(consultation)


def apply_consultation_outcome(consultation):
    """Propagate a resolved consultation onto its subject (PRD 3.8)."""
    if consultation["subject_type"] != "WORKOUT_PLAN":
        return None
    plan = db.workout_plans.get(consultation.get("workout_plan_id"))
    if plan is None or plan["status"] != "CONSULTATION":
        return None
    if consultation["status"] == "OBJECTED" and consultation["rights_type"] == "CONSENT_RIGHT":
        plan["status"] = "OBJECTED"
    else:
        plan["status"] = "CONSENT_SATISFIED"
    plan["consent_requirement"] = consultation["rights_type"]
    touch(plan)
    return plan


def consultation_satisfied_for(subject_type, key, value):
    """True when the controlling class's rights on the subject are satisfied.

    A CONSENT_RIGHT needs an affirmative outcome; a CONSULTATION_ONLY right is
    satisfied by any resolution at all, an objection included (PRD 3.6).
    """
    for row in rows_of("consultations"):
        if row["subject_type"] != subject_type or row.get(key) != value:
            continue
        if row["rights_type"] == "CONSENT_RIGHT":
            if row["status"] in ("CONSENTED", "DEEMED_CONSENTED", "WAIVED"):
                return True
        elif row["status"] != "PENDING":
            return True
    return False


def open_consultation_for(subject_type, key, value):
    for row in sort_created(rows_of("consultations")):
        if row["subject_type"] == subject_type and row.get(key) == value and row["status"] == "PENDING":
            return row
    return None


def create_provisional_reduction(appraisal, loan, trust, user_id):
    """Cascade fired when an appraisal is ACCEPTED (PRD 3.3 / 3.7)."""
    principal = outstanding_advance_principal(loan["id"])
    interest = total_advance_interest(loan, trust)
    result = appraisal_reduction_amount(
        loan["current_principal_balance_usd"],
        loan["accrued_unpaid_interest_usd"],
        principal,
        interest,
        appraisal["appraisal_type"],
        appraisal["value_usd"],
        appraisal["estimated_liquidation_expenses_usd"],
    )
    row = base_row()
    row.update(
        {
            "loan_id": loan["id"],
            "appraisal_id": appraisal["id"],
            "calculation_basis": result["calculation_basis"],
            "deficiency_base_usd": result["deficiency_base_usd"],
            "appraisal_credit_usd": result["appraisal_credit_usd"],
            "ara_amount_usd": result["ara_amount_usd"],
            "ara_percentage": result["ara_percentage"],
            "calculated_on": iso(db.now()),
            "status": "PROVISIONAL",
            "effective_on": None,
            "made_effective_by_user_id": None,
            "reversal_reason": None,
            "advance_reduction_applies": False,
        }
    )
    db.appraisal_reductions[row["id"]] = row
    return row


def supersede_prior_appraisals(appraisal, loan):
    for other in appraisals_of(loan["id"]):
        if other["id"] != appraisal["id"] and other["status"] == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            touch(other)


def recalculate_prior_reductions(loan, exclude_id):
    """A newly EFFECTIVE reduction supersedes the incumbent (RECALCULATED)."""
    for row in reductions_of(loan["id"]):
        if row["id"] != exclude_id and row["status"] == "EFFECTIVE":
            row["status"] = "RECALCULATED"
            row["advance_reduction_applies"] = False
            touch(row)


def new_fee_accrual(loan, fee_type, period_start, period_end, basis, rate, amount,
                    user_id, collection_amount=None):
    row = base_row()
    row.update(
        {
            "loan_id": loan["id"],
            "fee_type": fee_type,
            "period_start": period_start,
            "period_end": period_end,
            "collection_amount_usd": collection_amount,
            "basis_amount_usd": q2(basis),
            "rate_pct": q6(rate),
            "amount_usd": q2(amount),
            "status": "ACCRUED",
            "accrued_by_user_id": user_id,
            "collected_on": None,
            "waived_reason": None,
        }
    )
    db.fee_accruals[row["id"]] = row
    return row


# ------------------------------------------------- liquidation waterfall
def run_liquidation_waterfall(loan, trust, gross_proceeds, liquidation_expenses,
                              period_start=None, period_end=None):
    """The seven-step waterfall of PRD 3.8 / calculations.liquidation_proceeds_waterfall."""
    gross = q2(gross_proceeds)
    expenses = q2(liquidation_expenses)

    # Step 1 -- liquidation fee, capped, booked as an ACCRUED FeeAccrual.
    fee = liquidation_fee_amount(gross, trust["liquidation_fee_rate_pct"])
    accrual = new_fee_accrual(
        loan,
        "LIQUIDATION_FEE",
        period_start,
        period_end,
        gross,
        trust["liquidation_fee_rate_pct"],
        fee,
        "system",
    )

    # Step 2 -- proceeds available to the trust.
    available = q2(gross - expenses - fee)
    if available < ZERO:
        available = ZERO

    # Step 3 -- advance reimbursement, interest before principal, oldest first.
    advances = sorted(
        active_advances_of(loan["id"]),
        key=lambda a: (a["_advanced_on_dt"], a["created_at"], a["_seq"]),
    )
    for advance in advances:
        refresh_advance(advance, trust)
        interest_due = q2(D(advance["accrued_interest_usd"]) - D(advance["reimbursed_interest_usd"]))
        principal_due = q2(D(advance["amount_usd"]) - D(advance["reimbursed_principal_usd"]))
        if interest_due < ZERO:
            interest_due = ZERO
        if principal_due < ZERO:
            principal_due = ZERO
        pay_interest = dmin(available, interest_due)
        available = q2(available - pay_interest)
        pay_principal = dmin(available, principal_due)
        available = q2(available - pay_principal)
        advance["reimbursed_interest_usd"] = q2(
            D(advance["reimbursed_interest_usd"]) + pay_interest
        )
        advance["reimbursed_principal_usd"] = q2(
            D(advance["reimbursed_principal_usd"]) + pay_principal
        )
        if pay_interest >= interest_due and pay_principal >= principal_due:
            advance["status"] = "REIMBURSED"
            touch(advance)
        elif (pay_interest + pay_principal) > ZERO:
            advance["status"] = "PARTIALLY_REIMBURSED"
            touch(advance)

    # Step 4 -- accrued unpaid interest on the loan.
    pay = dmin(available, q2(loan["accrued_unpaid_interest_usd"]))
    available = q2(available - pay)
    loan["accrued_unpaid_interest_usd"] = q2(D(loan["accrued_unpaid_interest_usd"]) - pay)

    # Step 5 -- principal.
    pay = dmin(available, q2(loan["current_principal_balance_usd"]))
    available = q2(available - pay)
    loan["current_principal_balance_usd"] = q2(D(loan["current_principal_balance_usd"]) - pay)

    # Step 6 -- realized loss and non-recoverable determinations.
    shortfall = ZERO
    still_short = []
    for advance in advances_of(loan["id"]):
        if advance["status"] in ACTIVE_ADVANCE_STATUSES:
            shortfall += D(advance["amount_usd"]) - D(advance["reimbursed_principal_usd"])
            still_short.append(advance)
    loan["realized_loss_usd"] = q2(D(loan["current_principal_balance_usd"]) + shortfall)
    trust["realized_loss_usd"] = q2(
        D(trust["realized_loss_usd"]) + D(loan["realized_loss_usd"])
    )
    for advance in still_short:
        advance["status"] = "DEEMED_NONRECOVERABLE"
        touch(advance)

    # Step 7 -- residue to the trust.
    trust["excess_liquidation_proceeds_usd"] = q2(
        D(trust["excess_liquidation_proceeds_usd"]) + available
    )
    return {"fee_accrual": accrual, "liquidation_fee_usd": fee, "available_usd": available}


def finalize_liquidation(loan, trust):
    """Common tail for LIQUIDATED: reverse the ARA, re-roll loan and trust."""
    loan["servicing_status"] = "LIQUIDATED"
    for reduction in reductions_of(loan["id"]):
        if reduction["status"] == "EFFECTIVE":
            reduction["status"] = "REVERSED"
            reduction["advance_reduction_applies"] = False
            touch(reduction)
    recompute_loan(loan)
    recompute_trust(trust)


def write_off_loan(loan, trust):
    """REO WRITTEN_OFF cascade (PRD 3.8)."""
    loan["realized_loss_usd"] = q2(
        D(loan["current_principal_balance_usd"]) + D(loan["advances_outstanding_usd"])
    )
    loan["current_principal_balance_usd"] = ZERO
    trust["realized_loss_usd"] = q2(
        D(trust["realized_loss_usd"]) + D(loan["realized_loss_usd"])
    )
    for advance in active_advances_of(loan["id"]):
        advance["status"] = "DEEMED_NONRECOVERABLE"
        touch(advance)
    for reduction in reductions_of(loan["id"]):
        if reduction["status"] == "EFFECTIVE":
            reduction["status"] = "REVERSED"
            reduction["advance_reduction_applies"] = False
            touch(reduction)
    loan["servicing_status"] = "WRITTEN_OFF"
    recompute_loan(loan)
    recompute_trust(trust)
