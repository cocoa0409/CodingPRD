"""Entity serializers — produce the public JSON representation.

Computed fields are recomputed at read time for the entities that expose them
(Worker counters, Employer posture/exposure). Internal bookkeeping keys (prefixed
'_', plus 'written_off_amount_cents') are stripped.
"""
import db
from services import domain


_INTERNAL_KEYS = {"written_off_amount_cents", "approved_by_user_id"}


def _public(entity, extra=None):
    out = {
        k: v for k, v in entity.items()
        if not k.startswith("_") and k not in _INTERNAL_KEYS
    }
    if extra:
        out.update(extra)
    return out


def employer(e):
    return _public(e, {
        "posture": domain.derive_posture(e),
        "outstanding_principal_cents": domain.outstanding_principal(e["id"]),
    })


def advance_policy(p):
    return _public(p)


def fee_schedule(f):
    return _public(f)


def pay_period(p):
    return _public(p)


def worker(w):
    tenure = domain.compute_tenure_days(w)
    return _public(w, {
        "tenure_days": tenure,
        "period_advance_count": domain.period_advance_count(w),
        "net_available_earnings_cents": domain.net_available_earnings(w),
        "lifetime_advanced_cents": domain.lifetime_advanced(w),
    })


def time_entry(te):
    # write-once ledger row: id, created_at only (no version/updated_at)
    return _public(te)


def advance(a):
    return _public(a)


def repayment_batch(b):
    return _public(b)


def repayment(r):
    return _public(r)


def reconciliation_statement(s):
    return _public(s)
