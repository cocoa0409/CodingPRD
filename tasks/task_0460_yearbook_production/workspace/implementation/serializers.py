"""Serialize internal entity dicts into public JSON (drop internal-only keys)."""

_COMMON = ("id", "created_at", "updated_at", "version")


def _public(record):
    """Return a shallow copy with internal-only fields removed."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def yearbook(yb):
    return _public(yb)


def ladder_page(p):
    return _public(p)


def submission(s):
    return _public(s)


def staff_assignment(a):
    return _public(a)


def ad_contract(c):
    return _public(c)


def proof(pr):
    return _public(pr)


def presale_order(o):
    return _public(o)


def print_run(r):
    return _public(r)


def distribution_record(d):
    return _public(d)
