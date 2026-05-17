"""Public serialisation of each entity. Returns plain dicts (envelope is applied at the route layer)."""

from copy import deepcopy
from decimal import Decimal


def _dec_to_serialisable(value):
    if isinstance(value, Decimal):
        # ratios — render as float at the stored precision
        return float(value)
    return value


def _serialise(entity: dict) -> dict:
    out = deepcopy(entity)
    for k, v in list(out.items()):
        # Strip internal-snapshot fields (e.g., _snapshot_le_version on
        # UDAAPReview) — they are server-side bookkeeping and never
        # part of the public envelope per PRD §2.4.
        if isinstance(k, str) and k.startswith("_"):
            del out[k]
            continue
        out[k] = _dec_to_serialisable(v)
    return out


def borrower(b: dict) -> dict:
    return _serialise(b)


def loan_application(a: dict) -> dict:
    return _serialise(a)


def income_verification(iv: dict) -> dict:
    return _serialise(iv)


def asset_verification(av: dict) -> dict:
    return _serialise(av)


def appraisal(a: dict) -> dict:
    return _serialise(a)


def title_search(t: dict) -> dict:
    return _serialise(t)


def rate_lock(rl: dict) -> dict:
    return _serialise(rl)


def rate_lock_extension(rle: dict) -> dict:
    return _serialise(rle)


def disclosure(d: dict) -> dict:
    return _serialise(d)


def udaap_review(r: dict) -> dict:
    return _serialise(r)


def system_clock(sc: dict) -> dict:
    return _serialise(sc)
