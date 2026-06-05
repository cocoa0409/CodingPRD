"""Serializers: project each stored entity dict into its public API shape.

Every entity exposes id, created_at, updated_at, version (PRD §2.4) plus its
own fields. We store entities as plain dicts already in API shape, so these
return copies to avoid leaking mutable internal references.
"""


def _copy(obj):
    # Strip internal bookkeeping keys (e.g. _seq creation-order tiebreaker) so
    # they never leak into the public API response shape.
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def test_center(o):
    return _copy(o)


def test_session(o):
    return _copy(o)


def candidate(o):
    return _copy(o)


def registration(o):
    return _copy(o)


def accommodation_request(o):
    return _copy(o)


def standby_entry(o):
    return _copy(o)


def score_report(o):
    return _copy(o)


def score_send(o):
    return _copy(o)


def clep_claim(o):
    return _copy(o)


def id_verification(o):
    return _copy(o)
