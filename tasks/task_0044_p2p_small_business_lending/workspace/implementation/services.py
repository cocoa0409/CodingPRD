"""Business-logic services: state transitions, cascades, allocation."""
from decimal import Decimal

import calculations
import errors
from clock import clock, add_months, parse_iso8601
from db import db, make_common, touch
from errors import ApiError


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #

def get_borrower(borrower_id):
    return db.borrowers.get(borrower_id)


def get_application(app_id):
    return db.loan_applications.get(app_id)


def get_loan(loan_id):
    return db.loans.get(loan_id)


def get_investor(investor_id):
    return db.investors.get(investor_id)


def get_investment(investment_id):
    return db.investments.get(investment_id)


def get_repayment(repayment_id):
    return db.repayments.get(repayment_id)


def get_disclosure(disclosure_id):
    return db.compliance_disclosures.get(disclosure_id)


def committed_investments_for_loan(loan_id):
    """COMMITTED investments on a loan, sorted by creation sequence ASC."""
    rows = [inv for inv in db.investments.values()
            if inv["loan_id"] == loan_id and inv["status"] == "COMMITTED"]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def written_off_investments_for_loan(loan_id):
    rows = [inv for inv in db.investments.values()
            if inv["loan_id"] == loan_id and inv["status"] == "WRITTEN_OFF"]
    rows.sort(key=lambda r: r["_seq"])
    return rows


# --------------------------------------------------------------------------- #
# Scoring / pricing
# --------------------------------------------------------------------------- #

def score_application(app, scorer_user_id):
    """SUBMITTED -> SCORED. Caller has already validated state + borrower active."""
    credit_score, risk_grade = calculations.score_borrower(
        app["plaid_avg_monthly_revenue_cents"],
        app["plaid_monthly_debt_payment_cents"],
        app["plaid_nsf_count_90d"],
        app["plaid_account_age_months"],
    )
    app["credit_score"] = credit_score
    app["risk_grade"] = risk_grade
    app["offered_apr"] = calculations.apr_for_grade(risk_grade)
    app["scored_by_user_id"] = scorer_user_id
    app["status"] = "SCORED"
    touch(app)
    return app


def approve_application(app):
    """SCORED -> APPROVED; originate a Loan in FUNDING."""
    app["status"] = "APPROVED"
    touch(app)

    loan = make_common(common_fields=True)
    loan.update({
        "application_id": app["id"],
        "borrower_id": app["borrower_id"],
        "principal_cents": app["requested_principal_cents"],
        "apr": app["offered_apr"],
        "term_months": app["term_months"],
        "committed_cents": 0,
        "outstanding_principal_cents": 0,
        "late_fee_outstanding_cents": 0,
        "current_period_index": 0,
        "missed_payment_count": 0,
        "last_assessed_period_index": 0,
        "status": "FUNDING",
        "funded_at": None,
    })
    db.loans[loan["id"]] = loan
    return app, loan


def reject_application(app):
    app["status"] = "REJECTED"
    touch(app)
    return app


# --------------------------------------------------------------------------- #
# Investment commit
# --------------------------------------------------------------------------- #

def commit_investment(investor, loan, amount_cents, expected_loan_version):
    """Run the fixed guard order (PRD §3.4) and create the COMMITTED investment.

    Guards (in order, after auth/existence handled by caller):
      - loan FUNDING and investor & borrower ACTIVE   -> ERR_LOAN_NOT_FUNDING (409)
      - OCC expected_loan_version == loan.version     -> ERR_STALE_LOAN_VERSION (412)
      - committed_cents + amount <= principal_cents   -> ERR_FUNDING_EXCEEDED (422)
      - amount <= capital_base - committed_capital     -> ERR_INSUFFICIENT_CAPITAL (422)
      - single-loan exposure <= pct * capital_base     -> ERR_DIVERSIFICATION_BREACH (422)
    """
    borrower = db.borrowers.get(loan["borrower_id"])

    # Guard 1: loan FUNDING + investor & borrower ACTIVE
    if (loan["status"] != "FUNDING"
            or investor["status"] != "ACTIVE"
            or borrower is None
            or borrower["status"] != "ACTIVE"):
        raise ApiError(errors.ERR_LOAN_NOT_FUNDING, 409,
                       "Investment requires a FUNDING loan with ACTIVE investor and borrower.")

    # Guard 2: OCC
    if expected_loan_version != loan["version"]:
        raise ApiError(errors.ERR_STALE_LOAN_VERSION, 412,
                       "expected_loan_version does not match the loan's current version.")

    # Guard 3: over-subscription
    if loan["committed_cents"] + amount_cents > loan["principal_cents"]:
        raise ApiError(errors.ERR_FUNDING_EXCEEDED, 422,
                       "Investment would push committed_cents above principal_cents.")

    # Guard 4: uncommitted capital
    uncommitted = investor["capital_base_cents"] - investor["committed_capital_cents"]
    if amount_cents > uncommitted:
        raise ApiError(errors.ERR_INSUFFICIENT_CAPITAL, 422,
                       "Investment exceeds the investor's uncommitted capital.")

    # Guard 5: diversification cap (this investor's COMMITTED exposure on this loan,
    # including the new commit) <= max_single_loan_pct * capital_base_cents.
    existing_exposure = sum(
        inv["amount_cents"] for inv in db.investments.values()
        if inv["investor_id"] == investor["id"]
        and inv["loan_id"] == loan["id"]
        and inv["status"] == "COMMITTED"
    )
    resulting_exposure = existing_exposure + amount_cents
    pct = investor["max_single_loan_pct"]
    pct_dec = pct if isinstance(pct, Decimal) else Decimal(str(pct))
    cap = pct_dec * Decimal(investor["capital_base_cents"])
    if Decimal(resulting_exposure) > cap:
        raise ApiError(errors.ERR_DIVERSIFICATION_BREACH, 422,
                       "Investment would breach the investor's diversification cap.")

    # All guards passed: create the investment + reconcile cascades.
    investment = make_common(common_fields=True)
    investment.update({
        "investor_id": investor["id"],
        "loan_id": loan["id"],
        "amount_cents": amount_cents,
        "outstanding_principal_cents": 0,
        "charged_off_basis_cents": 0,
        "status": "COMMITTED",
        "expected_loan_version": expected_loan_version,
    })
    db.investments[investment["id"]] = investment

    loan["committed_cents"] += amount_cents
    touch(loan)  # bumps loan.version

    investor["committed_capital_cents"] += amount_cents
    touch(investor)

    return investment


# --------------------------------------------------------------------------- #
# Disburse: FUNDING -> ACTIVE -> REPAYMENT
# --------------------------------------------------------------------------- #

def has_filed_prospectus(loan_id):
    return any(
        d["loan_id"] == loan_id
        and d["document_type"] == "SERIES_NOTE_PROSPECTUS"
        and d["status"] == "FILED"
        for d in db.compliance_disclosures.values()
    )


def disburse_loan(loan):
    """Caller has validated state==FUNDING. Run funding + disclosure guards then disburse."""
    # Fully funded, exact.
    if loan["committed_cents"] != loan["principal_cents"]:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Loan is not exactly fully funded.")

    # Disclosure gate.
    if not has_filed_prospectus(loan["id"]):
        raise ApiError(errors.ERR_DISCLOSURE_MISSING, 422,
                       "A FILED SERIES_NOTE_PROSPECTUS disclosure is required to disburse.")

    loan["outstanding_principal_cents"] = loan["principal_cents"]
    loan["current_period_index"] = 1
    loan["funded_at"] = _now_iso()

    for inv in committed_investments_for_loan(loan["id"]):
        inv["outstanding_principal_cents"] = inv["amount_cents"]
        touch(inv)

    # ACTIVE is transient; auto-transition to REPAYMENT in the same request.
    loan["status"] = "REPAYMENT"
    touch(loan)
    return loan


def _now_iso():
    from db import now_iso
    return now_iso()


# --------------------------------------------------------------------------- #
# Scheduled repayment: allocation waterfall + pro-rata distribution
# --------------------------------------------------------------------------- #

def _schedule_for_loan(loan):
    return calculations.amortization_schedule(
        loan["principal_cents"], loan["apr"], loan["term_months"])


def total_payoff(loan):
    """late_fee_outstanding + remaining interest_due (current period) + outstanding_principal."""
    _level, periods = _schedule_for_loan(loan)
    cpi = loan["current_period_index"]
    interest_due = 0
    if 1 <= cpi <= len(periods):
        interest_due = periods[cpi - 1]["interest_due_cents"]
    return (loan["late_fee_outstanding_cents"]
            + interest_due
            + loan["outstanding_principal_cents"])


def process_scheduled_repayment(loan, amount_cents):
    """Validate against payoff, allocate the waterfall, distribute pro-rata, and
    create the Repayment + RepaymentAllocation rows. Returns the Repayment dict.
    """
    payoff = total_payoff(loan)
    if amount_cents > payoff:
        raise ApiError(errors.ERR_PAYMENT_EXCEEDS_PAYOFF, 422,
                       "Scheduled repayment exceeds the loan's total payoff.")

    _level, periods = _schedule_for_loan(loan)
    cpi = loan["current_period_index"]
    if 1 <= cpi <= len(periods):
        interest_due = periods[cpi - 1]["interest_due_cents"]
        principal_due = periods[cpi - 1]["principal_due_cents"]
    else:
        interest_due = 0
        principal_due = 0

    rem = amount_cents

    # Bucket 1: outstanding late fees.
    late_fee_paid = min(rem, loan["late_fee_outstanding_cents"])
    rem -= late_fee_paid

    # Bucket 2: current-period accrued interest.
    interest_paid = min(rem, interest_due)
    rem -= interest_paid

    # Bucket 3: current-period scheduled principal.
    sched_principal = min(rem, principal_due)
    rem -= sched_principal

    # Bucket 4: prepayment against principal beyond the current period.
    prepay_cap = loan["outstanding_principal_cents"] - principal_due
    if prepay_cap < 0:
        prepay_cap = 0
    prepay = min(rem, prepay_cap)
    rem -= prepay

    principal_paid = sched_principal + prepay

    # Servicing fee from the interest bucket only.
    platform_fee, net_interest = calculations.compute_servicing_fee(interest_paid)

    # Create the repayment record.
    repayment = make_common(common_fields=True)
    repayment.update({
        "loan_id": loan["id"],
        "amount_cents": amount_cents,
        "kind": "SCHEDULED",
        "late_fee_paid_cents": late_fee_paid,
        "interest_paid_cents": interest_paid,
        "principal_paid_cents": principal_paid,
        "platform_fee_cents": platform_fee,
    })
    db.repayments[repayment["id"]] = repayment

    # Update loan balances.
    loan["late_fee_outstanding_cents"] -= late_fee_paid
    loan["outstanding_principal_cents"] -= principal_paid

    # Advance current_period_index when both interest and principal of the
    # current period are fully covered.
    if interest_paid >= interest_due and sched_principal >= principal_due:
        loan["current_period_index"] += 1

    # Distribute principal and net-interest independently across COMMITTED
    # investments, pro-rata by original funded principal (amount_cents).
    investments = committed_investments_for_loan(loan["id"])
    weights = [(inv["id"], inv["amount_cents"], inv["_seq"]) for inv in investments]

    principal_alloc = calculations.distribute_largest_remainder(principal_paid, weights)
    interest_alloc = calculations.distribute_largest_remainder(net_interest, weights)

    inv_by_id = {inv["id"]: inv for inv in investments}
    for inv in investments:
        p_share = principal_alloc.get(inv["id"], 0)
        i_share = interest_alloc.get(inv["id"], 0)
        alloc = make_common(common_fields=False)
        alloc.update({
            "repayment_id": repayment["id"],
            "investment_id": inv["id"],
            "principal_amount_cents": p_share,
            "interest_amount_cents": i_share,
        })
        db.repayment_allocations[alloc["id"]] = alloc
        # Debit each investment's outstanding principal by its principal share.
        if p_share:
            inv["outstanding_principal_cents"] -= p_share
            touch(inv)

    # PAID_OFF check.
    if loan["outstanding_principal_cents"] == 0 and loan["late_fee_outstanding_cents"] == 0:
        loan["status"] = "PAID_OFF"

    touch(loan)
    return repayment


# --------------------------------------------------------------------------- #
# Late fee / default
# --------------------------------------------------------------------------- #

def assess_late_fee(loan):
    """REPAYMENT -> REPAYMENT (or -> DEFAULTED on the third assessment).

    Caller has validated state == REPAYMENT.
    Timing guard: target = last_assessed_period_index + 1 must be unpaid
    (>= current_period_index) AND its due date (funded_at + target months) must
    be strictly before the current clock time. Else ERR_LATE_FEE_NOT_DUE (409).
    """
    target = loan["last_assessed_period_index"] + 1

    # Unpaid: target must be at or beyond current_period_index.
    if target < loan["current_period_index"]:
        raise ApiError(errors.ERR_LATE_FEE_NOT_DUE, 409,
                       "The target period has already been paid.")

    # Due-date timing.
    funded_at = loan["funded_at"]
    if funded_at is None:
        raise ApiError(errors.ERR_LATE_FEE_NOT_DUE, 409,
                       "The loan has not been funded yet.")
    due_date = add_months(parse_iso8601(funded_at), target)
    if not (due_date < clock.now()):
        raise ApiError(errors.ERR_LATE_FEE_NOT_DUE, 409,
                       "The target period's due date is not yet in the past.")

    level_payment_cents, _periods = _schedule_for_loan(loan)
    fee = calculations.compute_late_fee(level_payment_cents)

    loan["late_fee_outstanding_cents"] += fee
    loan["last_assessed_period_index"] = target
    loan["missed_payment_count"] += 1

    if loan["missed_payment_count"] >= 3:
        loan["status"] = "DEFAULTED"

    touch(loan)
    return loan


# --------------------------------------------------------------------------- #
# Charge-off cascade (depth 3)
# --------------------------------------------------------------------------- #

def charge_off_loan(loan):
    """DEFAULTED -> CHARGED_OFF. Caller has validated state == DEFAULTED."""
    loan["status"] = "CHARGED_OFF"
    # outstanding_principal_cents preserved as the charged-off basis.

    for inv in committed_investments_for_loan(loan["id"]):
        inv["status"] = "WRITTEN_OFF"
        inv["charged_off_basis_cents"] = inv["outstanding_principal_cents"]

        investor = db.investors.get(inv["investor_id"])
        if investor is not None:
            investor["committed_capital_cents"] -= inv["amount_cents"]
            investor["capital_base_cents"] -= inv["outstanding_principal_cents"]
            touch(investor)

        inv["outstanding_principal_cents"] = 0
        touch(inv)

    touch(loan)
    return loan


# --------------------------------------------------------------------------- #
# Recovery repayment on a CHARGED_OFF loan
# --------------------------------------------------------------------------- #

def process_recovery_repayment(loan, amount_cents):
    """CHARGED_OFF -> CHARGED_OFF. Caller has validated state == CHARGED_OFF."""
    if amount_cents > loan["outstanding_principal_cents"]:
        raise ApiError(errors.ERR_RECOVERY_EXCEEDS_BASIS, 422,
                       "Recovery exceeds the charged-off outstanding basis.")

    repayment = make_common(common_fields=True)
    repayment.update({
        "loan_id": loan["id"],
        "amount_cents": amount_cents,
        "kind": "RECOVERY",
        "late_fee_paid_cents": 0,
        "interest_paid_cents": 0,
        "principal_paid_cents": amount_cents,
        "platform_fee_cents": 0,
    })
    db.repayments[repayment["id"]] = repayment

    investments = written_off_investments_for_loan(loan["id"])
    weights = [(inv["id"], inv["charged_off_basis_cents"], inv["_seq"]) for inv in investments]
    principal_alloc = calculations.distribute_largest_remainder(amount_cents, weights)

    for inv in investments:
        p_share = principal_alloc.get(inv["id"], 0)
        alloc = make_common(common_fields=False)
        alloc.update({
            "repayment_id": repayment["id"],
            "investment_id": inv["id"],
            "principal_amount_cents": p_share,
            "interest_amount_cents": 0,
        })
        db.repayment_allocations[alloc["id"]] = alloc
        # Recovery does not change Investment.status; investments stay WRITTEN_OFF.

    loan["outstanding_principal_cents"] -= amount_cents
    touch(loan)
    return repayment


# --------------------------------------------------------------------------- #
# Compliance disclosure filing (supersession)
# --------------------------------------------------------------------------- #

def file_disclosure(loan_id, document_type, filed_by_user_id):
    # Supersede any prior FILED disclosure of same (loan_id, document_type).
    for d in db.compliance_disclosures.values():
        if (d["loan_id"] == loan_id
                and d["document_type"] == document_type
                and d["status"] == "FILED"):
            d["status"] = "SUPERSEDED"
            touch(d)

    disclosure = make_common(common_fields=True)
    disclosure.update({
        "loan_id": loan_id,
        "document_type": document_type,
        "filed_by_user_id": filed_by_user_id,
        "status": "FILED",
    })
    db.compliance_disclosures[disclosure["id"]] = disclosure
    return disclosure
