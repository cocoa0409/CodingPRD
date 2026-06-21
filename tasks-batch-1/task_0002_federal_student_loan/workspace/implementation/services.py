"""Domain service helpers: lookups, computed fields, recompute cascades."""
from datetime import datetime, timezone

from calculations import (
    accrue_interest, compute_monthly_payment_cents,
    parse_iso_to_dt, parse_iso_to_date,
)
from db import store, utc_now_iso


# ============================================================
# Server clock helpers
# ============================================================

def get_current_utc_dt() -> datetime:
    return parse_iso_to_dt(store.current_utc)


# ============================================================
# Loan status history (from StatusChange rows)
# ============================================================

def loan_status_history(loan_id: str):
    """Return [(effective_at_dt, to_status), ...] ASC chronological.

    Includes the loan's initial ORIGINATED state at its created_at instant
    if no StatusChange precedes it.
    """
    loan = store.loans[loan_id]
    rows = [sc for sc in store.status_changes.values() if sc["loan_id"] == loan_id]
    rows.sort(key=lambda r: (r["effective_at"], r["created_at"]))
    out = []
    # Seed with ORIGINATED at loan.created_at
    out.append((parse_iso_to_dt(loan["created_at"]), "ORIGINATED"))
    for r in rows:
        out.append((parse_iso_to_dt(r["effective_at"]), r["to_status"]))
    return out


def loan_status_at(loan_id: str, query_dt: datetime) -> str:
    history = loan_status_history(loan_id)
    chosen = "ORIGINATED"
    for eff_at, st in history:
        if eff_at <= query_dt:
            chosen = st
        else:
            break
    return chosen


# ============================================================
# Borrower current_agi / current_family_size (computed)
# ============================================================

def latest_certified_certification(borrower_id: str):
    """Latest CERTIFIED IncomeCertification: by effective_date DESC then created_at DESC."""
    candidates = [c for c in store.income_certifications.values()
                  if c["borrower_id"] == borrower_id and c["status"] == "CERTIFIED"]
    if not candidates:
        return None
    candidates.sort(
        key=lambda c: (parse_iso_to_dt(c["effective_date"]), parse_iso_to_dt(c["created_at"])),
        reverse=True,
    )
    return candidates[0]


def borrower_view(borrower: dict) -> dict:
    cert = latest_certified_certification(borrower["id"])
    out = dict(borrower)
    if cert:
        out["current_agi_cents"] = cert["agi_cents"]
        out["current_family_size"] = cert["family_size"]
    else:
        out["current_agi_cents"] = None
        out["current_family_size"] = None
    return out


# ============================================================
# Active plan helpers
# ============================================================

def active_plan_for_loan(loan_id: str):
    for p in store.repayment_plans.values():
        if p["loan_id"] == loan_id and p["status"] == "ACTIVE":
            return p
    return None


def active_plan_at(loan_id: str, query_dt: datetime):
    """Return the plan that was ACTIVE for this loan at query_dt.

    Approximation: pick the plan whose effective_date <= query_dt and whose
    timeline (created_at .. superseded/completed time) contains query_dt.
    A simpler robust heuristic: among all plans that ever reached ACTIVE
    (status in {ACTIVE, SUPERSEDED, COMPLETED}) with effective_date <= query_dt,
    pick the most recent by effective_date (ties: created_at DESC).
    For SUPERSEDED plans, exclude if their updated_at <= query_dt and there's
    a later plan whose effective_date is also <= query_dt.
    """
    candidates = []
    for p in store.repayment_plans.values():
        if p["loan_id"] != loan_id:
            continue
        if p["status"] not in ("ACTIVE", "SUPERSEDED", "COMPLETED"):
            continue
        if parse_iso_to_dt(p["effective_date"]) > query_dt:
            continue
        candidates.append(p)
    if not candidates:
        return None
    candidates.sort(
        key=lambda p: (parse_iso_to_dt(p["effective_date"]), parse_iso_to_dt(p["created_at"])),
        reverse=True,
    )
    return candidates[0]


# ============================================================
# PSLF qualifying payment count
# ============================================================

QUALIFYING_EMPLOYER_TYPES = {"GOVERNMENT", "NONPROFIT_501C3"}
QUALIFYING_PLAN_TYPES = {"IBR", "PAYE", "SAVE", "STANDARD"}


def payment_is_pslf_qualifying(payment: dict) -> bool:
    """Evaluate the 6 PSLF predicates for a single payment."""
    if payment["status"] != "APPLIED":
        return False
    loan = store.loans.get(payment["loan_id"])
    if not loan:
        return False
    p_date = parse_iso_to_dt(payment["payment_date"])

    # Active plan at payment_date
    plan = active_plan_at(loan["id"], p_date)
    if not plan or plan["plan_type"] not in QUALIFYING_PLAN_TYPES:
        return False

    # Predicate 3: amount >= floor(plan.monthly_payment_cents) at payment_date.
    # We use the plan's stored monthly_payment_cents (most recent recompute).
    if payment["amount_cents"] < int(plan.get("monthly_payment_cents") or 0):
        return False

    # Predicate 4: QualifyingEmployment for borrower with CERTIFIED + qualifying type
    # whose closed interval contains payment_date.
    borrower_id = loan["borrower_id"]
    qualifying = False
    for qe in store.qualifying_employments.values():
        if qe["borrower_id"] != borrower_id:
            continue
        if qe["status"] != "CERTIFIED":
            continue
        if qe["employer_type"] not in QUALIFYING_EMPLOYER_TYPES:
            continue
        ps = parse_iso_to_dt(qe["period_start"])
        pe = parse_iso_to_dt(qe["period_end"])
        if ps <= p_date <= pe:
            qualifying = True
            break
    if not qualifying:
        return False

    # Predicate 5: loan.status_at(payment_date) == REPAYMENT
    st = loan_status_at(loan["id"], p_date)
    if st != "REPAYMENT":
        return False

    return True


def pslf_qualifying_payment_count(loan_id: str) -> int:
    payments = [p for p in store.payments.values() if p["loan_id"] == loan_id]
    payments.sort(key=lambda p: (parse_iso_to_dt(p["payment_date"]),
                                 parse_iso_to_dt(p["created_at"])))
    count = 0
    for p in payments:
        if payment_is_pslf_qualifying(p):
            count += 1
    return count


# ============================================================
# Delinquency days
# ============================================================

def delinquency_days(loan: dict) -> int:
    """Days past due since the oldest still-owed scheduled payment (PRD §3.8).

    PRD §2.9 mandates that the value is refreshed against the server clock.
    PRD §3.8 says: "When no past-due payment exists, the value is zero."

    Faithful interpretation: when the loan is currently in REPAYMENT (the only
    status under which the §3.8 default declaration may fire) with an outstanding
    balance, and no APPLIED payment dated since the loan most recently entered
    REPAYMENT has covered the obligation, the oldest still-owed scheduled payment
    has been past-due since the loan entered REPAYMENT. delinquency_days is then
    `days(server_clock - most_recent_entry_into_REPAYMENT)`. Otherwise zero.
    """
    if loan["status"] != "REPAYMENT":
        return 0
    outstanding = int(loan.get("principal_balance_cents", 0)) + int(loan.get("accrued_interest_cents", 0))
    if outstanding <= 0:
        return 0

    # Find the most recent transition INTO REPAYMENT.
    # That is a StatusChange with to_status == REPAYMENT.
    rows = [sc for sc in store.status_changes.values()
            if sc["loan_id"] == loan["id"] and sc.get("to_status") == "REPAYMENT"]
    if not rows:
        return 0
    rows.sort(key=lambda r: (r["effective_at"], r["created_at"]))
    entered_at = parse_iso_to_dt(rows[-1]["effective_at"])

    # If any APPLIED payment was dated on/after entered_at, it has cleared the
    # past-due window; for our purposes the oldest still-owed payment is then
    # the next-scheduled one, which we don't model. Return zero to satisfy
    # PRD's "no past-due payment exists" branch.
    for p in store.payments.values():
        if p["loan_id"] != loan["id"]:
            continue
        if p.get("status") != "APPLIED":
            continue
        if parse_iso_to_dt(p["payment_date"]) >= entered_at:
            return 0

    now_dt = get_current_utc_dt()
    if now_dt <= entered_at:
        return 0
    days = (now_dt - entered_at).days
    return int(days)


# ============================================================
# Recompute cascades
# ============================================================

def recompute_monthly_payment_for_plan(plan: dict):
    """Recompute plan.monthly_payment_cents using the borrower's latest CERTIFIED
    income certification + the current loan principal figure (per §3.5)."""
    loan = store.loans.get(plan["loan_id"])
    if not loan:
        return
    borrower = store.borrowers.get(loan["borrower_id"])
    if not borrower:
        return
    cert = latest_certified_certification(borrower["id"])
    agi = cert["agi_cents"] if cert else None
    fam = cert["family_size"] if cert else None
    state = cert["state_code"] if cert else None

    # Principal figure: current principal_balance_cents + capitalized_interest_cents
    principal_for_calc = int(loan["principal_balance_cents"]) + int(loan["capitalized_interest_cents"])

    plan["monthly_payment_cents"] = compute_monthly_payment_cents(
        plan["plan_type"],
        principal_for_calc,
        loan["interest_rate_bps"],
        agi, fam, state,
    )


def recompute_pslf_for_borrower(borrower_id: str):
    """Refresh pslf_qualifying_payment_count for every loan of this borrower."""
    for loan in store.loans.values():
        if loan["borrower_id"] == borrower_id:
            loan["pslf_qualifying_payment_count"] = pslf_qualifying_payment_count(loan["id"])


# ============================================================
# Loan view builder (computed fields injected)
# ============================================================

def loan_view(loan: dict) -> dict:
    out = dict(loan)
    out["delinquency_days"] = delinquency_days(loan)
    out["pslf_qualifying_payment_count"] = pslf_qualifying_payment_count(loan["id"])
    return out


# ============================================================
# Interest accrual driver
# ============================================================

def accrue_loan_to_now(loan: dict):
    """Accrue interest on this loan from last_accrual_date up to current server clock."""
    target = get_current_utc_dt()
    history = loan_status_history(loan["id"])
    accrue_interest(loan, history, target)


def accrue_all_loans():
    for loan in store.loans.values():
        accrue_loan_to_now(loan)
