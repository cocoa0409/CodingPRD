"""Row -> response payload projection.

PRD 2.4: "Every stored attribute of a resource is response-visible: input
fields, server-computed fields and system-maintained fields alike."  Only the
internal insertion counter is hidden, and `coverage_status` is derived at read
time because PRD 3.3 says it "is derived, not stored by the client, and it is
recomputed whenever the row is read or written."
"""

from . import store
from .calc import coverage_status_of

_HIDDEN = ("_seq",)


def _base(row):
    return {k: v for k, v in row.items() if k not in _HIDDEN}


def employer(row):
    return _base(row)


def site(row):
    return _base(row)


def contract(row):
    return _base(row)


def provider(row):
    return _base(row)


def shift(row):
    return _base(row)


def eligibility(row):
    out = _base(row)
    out["coverage_status"] = coverage_status_of(row, store.now_date())
    return out


def participant(row):
    return _base(row)


def appointment(row):
    return _base(row)


def visit(row):
    return _base(row)


def assessment(row):
    return _base(row)


def referral(row):
    return _base(row)


def alt_standard(row):
    return _base(row)


def award(row):
    return _base(row)


def period(row):
    return _base(row)


BY_KIND = {
    "employer": employer,
    "site": site,
    "contract": contract,
    "provider": provider,
    "shift": shift,
    "eligibility": eligibility,
    "participant": participant,
    "appointment": appointment,
    "visit": visit,
    "assessment": assessment,
    "referral": referral,
    "alt_standard": alt_standard,
    "award": award,
    "period": period,
}


def dump(kind, row):
    out = BY_KIND[kind](row)
    store.register_projection(out, row)
    return out


def dump_many(kind, rows):
    fn = BY_KIND[kind]
    out = []
    for r in rows:
        projection = fn(r)
        store.register_projection(projection, r)
        out.append(projection)
    return out
