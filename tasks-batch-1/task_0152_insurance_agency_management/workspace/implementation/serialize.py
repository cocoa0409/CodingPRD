"""Serialize internal records into API output objects.

Strips internal-only keys (those starting with '_' plus a few bookkeeping
fields) and injects read-time computed fields.
"""
from services import derived
from services.calculations import compute_statement_figures

# Internal bookkeeping keys never exposed in API output.
_HIDDEN = {"_seq", "activated_at", "prior_return_premium_cents"}


def _public(rec):
    return {k: v for k, v in rec.items() if k not in _HIDDEN and not k.startswith("_")}


def carrier(rec):
    return _public(rec)


def product(rec):
    return _public(rec)


def producer(rec):
    return _public(rec)


def license(rec):
    out = _public(rec)
    out["status"] = derived.license_status(rec)  # computed at server-now
    return out


def appointment(rec):
    return _public(rec)


def account(rec):
    out = _public(rec)
    out["active_policy_count"] = derived.active_policy_count(rec["id"])
    return out


def policy(rec):
    return _public(rec)


def commission_split(rec):
    return _public(rec)


def trust_account(rec):
    out = _public(rec)
    out["balance_cents"] = derived.trust_balance(rec["id"])
    return out


def trust_ledger_entry(rec):
    return _public(rec)


def commission_statement(rec):
    out = _public(rec)
    if rec["status"] == "OPEN":
        gross, chargeback, net = compute_statement_figures(rec)
        out["gross_commission_cents"] = gross
        out["chargeback_cents"] = chargeback
        out["net_payable_cents"] = net
    # FINALIZED / PAID: return the frozen stored figures as-is.
    return out


def renewal_task(rec):
    return _public(rec)
