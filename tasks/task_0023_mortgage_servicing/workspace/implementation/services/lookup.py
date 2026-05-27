"""Entity lookup helpers — raise scaffold-defined errors."""
from __future__ import annotations

from typing import Any

import db
from errors import ApiError, ERR_RESOURCE_NOT_FOUND, ERR_FK_NOT_FOUND


def get_or_404(store: dict[str, Any], resource_id: str, *, name: str = "Resource") -> dict[str, Any]:
    obj = store.get(resource_id)
    if obj is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, f"{name} not found.")
    return obj


def get_fk_or_404(store: dict[str, Any], resource_id: str, *, name: str = "FK") -> dict[str, Any]:
    obj = store.get(resource_id)
    if obj is None:
        raise ApiError(ERR_FK_NOT_FOUND, f"Referenced {name} does not exist.")
    return obj


# Convenience: typed lookups against the per-store dicts
def get_borrower(borrower_id: str) -> dict[str, Any]:
    return get_or_404(db.borrowers, borrower_id, name="Borrower")


def get_loan(loan_id: str) -> dict[str, Any]:
    return get_or_404(db.loans, loan_id, name="Loan")


def get_escrow_account(eid: str) -> dict[str, Any]:
    return get_or_404(db.escrow_accounts, eid, name="EscrowAccount")


def get_escrow_disbursement(eid: str) -> dict[str, Any]:
    return get_or_404(db.escrow_disbursements, eid, name="EscrowDisbursement")


def get_escrow_analysis(eid: str) -> dict[str, Any]:
    return get_or_404(db.escrow_analyses, eid, name="EscrowAnalysis")


def get_forbearance_plan(eid: str) -> dict[str, Any]:
    return get_or_404(db.forbearance_plans, eid, name="ForbearancePlan")


def get_foreclosure_case(eid: str) -> dict[str, Any]:
    return get_or_404(db.foreclosure_cases, eid, name="ForeclosureCase")


def get_mediation_session(eid: str) -> dict[str, Any]:
    return get_or_404(db.mediation_sessions, eid, name="MediationSession")


def get_pmi_removal_request(eid: str) -> dict[str, Any]:
    return get_or_404(db.pmi_removal_requests, eid, name="PMIRemovalRequest")


# ---------- Borrower ownership chain ----------
def loan_borrower_id(loan: dict[str, Any]) -> str:
    return loan.get("borrower_id", "")


def escrow_account_borrower_id(escrow_account: dict[str, Any]) -> str | None:
    loan = db.loans.get(escrow_account.get("loan_id", ""))
    if loan is None:
        return None
    return loan.get("borrower_id")


def borrower_owns_loan(loan: dict[str, Any], user_id: str) -> bool:
    return loan.get("borrower_id") == user_id


def borrower_owns_escrow_account(ea: dict[str, Any], user_id: str) -> bool:
    bid = escrow_account_borrower_id(ea)
    return bid is not None and bid == user_id


def borrower_owns_disbursement(d: dict[str, Any], user_id: str) -> bool:
    ea = db.escrow_accounts.get(d.get("escrow_account_id", ""))
    if ea is None:
        return False
    return borrower_owns_escrow_account(ea, user_id)


def borrower_owns_analysis(a: dict[str, Any], user_id: str) -> bool:
    loan = db.loans.get(a.get("loan_id", ""))
    if loan is None:
        return False
    return borrower_owns_loan(loan, user_id)


def borrower_owns_forbearance_plan(p: dict[str, Any], user_id: str) -> bool:
    loan = db.loans.get(p.get("loan_id", ""))
    if loan is None:
        return False
    return borrower_owns_loan(loan, user_id)


def borrower_owns_foreclosure_case(c: dict[str, Any], user_id: str) -> bool:
    loan = db.loans.get(c.get("loan_id", ""))
    if loan is None:
        return False
    return borrower_owns_loan(loan, user_id)


def borrower_owns_mediation_session(s: dict[str, Any], user_id: str) -> bool:
    case = db.foreclosure_cases.get(s.get("foreclosure_case_id", ""))
    if case is None:
        return False
    return borrower_owns_foreclosure_case(case, user_id)


def borrower_owns_pmi_request(r: dict[str, Any], user_id: str) -> bool:
    loan = db.loans.get(r.get("loan_id", ""))
    if loan is None:
        return False
    return borrower_owns_loan(loan, user_id)
