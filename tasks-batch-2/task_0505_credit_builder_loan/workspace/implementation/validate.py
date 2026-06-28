"""Cross-cutting validation helpers used by routes.

Validation priority order (PRD §2.5):
 1 auth(unauthenticated) 2 forbidden(role) 3 forbidden(ownership) 4 not_found
 5 account_not_eligible 6 invalid_state 7 quote_expired 8 disclosure_not_ack
 9 apr_cap 10 sod 11 graduation 12 deposit_releasable 13 credit_limit
 14 deposit_cap 15 temporal/range 16 insufficient_wallet 17 body 18 occ
"""
from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_REQUEST,
)


def get_account_or_404(account_id):
    a = store.accounts.get(account_id)
    if a is None:
        raise err(ERR_NOT_FOUND, "Account not found")
    return a


def get_disclosure_or_404(disclosure_id):
    d = store.disclosures.get(disclosure_id)
    if d is None:
        raise err(ERR_NOT_FOUND, "Disclosure not found")
    return d


def get_loan_or_404(loan_id):
    l = store.loans.get(loan_id)
    if l is None:
        raise err(ERR_NOT_FOUND, "Loan not found")
    return l


def get_card_or_404(card_id):
    c = store.secured_cards.get(card_id)
    if c is None:
        raise err(ERR_NOT_FOUND, "Secured card not found")
    return c


def get_payment_or_404(payment_id):
    p = store.payments.get(payment_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Payment not found")
    return p


def get_enrollment_or_404(enr_id):
    e = store.autopay_enrollments.get(enr_id)
    if e is None:
        raise err(ERR_NOT_FOUND, "Autopay enrollment not found")
    return e


def get_quote_or_404(quote_id):
    q = store.payoff_quotes.get(quote_id)
    if q is None:
        raise err(ERR_NOT_FOUND, "Payoff quote not found")
    return q


def require_ownership(role, user_id, owning_account_id):
    """Priority-3 ownership check: entity-backed Borrower must own the resource
    (PRD §2.1)."""
    if role == "Borrower" and user_id != owning_account_id:
        raise err(ERR_FORBIDDEN, "Borrower does not own this resource")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v
