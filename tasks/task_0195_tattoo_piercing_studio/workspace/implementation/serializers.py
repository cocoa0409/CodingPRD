"""Entity -> public JSON serializers.

Each serializer returns the full stored record plus any computed-on-read fields
(e.g. reliability_score_lenient on an Artist). Records are stored already
shaped, so most serializers return a shallow copy; the artist serializer adds
the lenient reliability score per PRD §3.9.
"""
from services import lenient_reliability_score


def serialize_artist(a):
    out = dict(a)
    out["reliability_score_lenient"] = lenient_reliability_score(a)
    return out


def serialize_client(c):
    return dict(c)


def serialize_flash(f):
    return dict(f)


def serialize_custom_request(r):
    return dict(r)


def serialize_appointment(a):
    return dict(a)


def serialize_chair(c):
    return dict(c)


def serialize_deposit(d):
    return dict(d)


def serialize_waiver(w):
    return dict(w)


def serialize_touchup(t):
    return dict(t)


def serialize_portfolio_item(p):
    return dict(p)
