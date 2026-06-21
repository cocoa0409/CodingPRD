"""Convert internal resource dicts into public JSON payloads.

Internal records carry private bookkeeping keys (prefixed with '_'). Public
output excludes those. APR / offered_apr are stored as Decimal fractions and
must serialize as JSON numbers.
"""
from decimal import Decimal


def _num(value):
    """Render a Decimal as a JSON number (float) or pass through None / ints."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        # credit_score has 2 dp; apr fractions have up to 4 dp. float is fine
        # for transport because the canonical store is the Decimal.
        return float(value)
    return value


def _public(resource):
    return {k: v for k, v in resource.items() if not k.startswith("_")}


def serialize_borrower(b):
    out = _public(b)
    return out


def serialize_application(a):
    out = _public(a)
    out["credit_score"] = _num(a.get("credit_score"))
    out["offered_apr"] = _num(a.get("offered_apr"))
    return out


def serialize_loan(loan):
    out = _public(loan)
    out["apr"] = _num(loan.get("apr"))
    return out


def serialize_investor(inv):
    out = _public(inv)
    out["max_single_loan_pct"] = _num(inv.get("max_single_loan_pct"))
    return out


def serialize_investment(inv):
    return _public(inv)


def serialize_repayment(r):
    return _public(r)


def serialize_allocation(a):
    return _public(a)


def serialize_disclosure(d):
    return _public(d)
