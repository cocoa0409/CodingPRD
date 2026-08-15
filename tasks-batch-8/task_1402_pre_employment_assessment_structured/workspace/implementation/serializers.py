"""Serializers — render stored records to their public JSON form.
Records internally carry created_at/updated_at as datetimes plus a _seq and
_created ordering helper; those internals are stripped on output.
"""
from util import fmt_dt


def _base(rec, common=True):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if k in ("created_at", "updated_at", "terminated_at", "validity_expires_at",
                 "filed_at", "closed_at", "scheduled_for", "started_at",
                 "completed_at", "retention_expires_at", "purged_at", "decided_at",
                 "trained_at", "certified_at", "scheduled_start", "scheduled_end",
                 "submitted_at", "voided_at", "finalized_at", "computed_at",
                 "effective_from", "effective_until", "retention_expires_at_snapshot"):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def vendor(rec):
    return _base(rec)


def ledger_event(rec):
    return _base(rec)


def instrument(rec):
    return _base(rec)


def evidence(rec):
    return _base(rec)


def guide(rec):
    return _base(rec)


def requisition(rec):
    return _base(rec)


def cycle(rec):
    return _base(rec)


def candidate(rec):
    return _base(rec)


def assessment(rec):
    return _base(rec)


def accommodation(rec):
    return _base(rec)


def interviewer(rec):
    return _base(rec)


def calibration(rec):
    return _base(rec)


def session(rec):
    return _base(rec)


def scorecard(rec):
    return _base(rec)


def decision(rec):
    return _base(rec)


def snapshot(rec):
    return _base(rec)


def purge_event(rec):
    return _base(rec)
