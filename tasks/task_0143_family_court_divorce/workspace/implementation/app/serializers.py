"""Convert internal resource dicts into the public JSON shape.

Internal records keep `created_at` and `updated_at` as datetime objects so the
service layer can do arithmetic on them; this module renders the public
ISO-8601 string form right before returning to the client.
"""
from app.store import fmt_ts


_DT_FIELDS = {
    "created_at",
    "updated_at",
    "served_at",
    "answer_deadline_at",
    "response_received_at",
    "marriage_date",
    "separation_date",
    "date_of_birth",
    "effective_from",
    "superseded_at",
    "scheduled_start_at",
    "scheduled_end_at",
}


def _serialize(record: dict) -> dict:
    if record is None:
        return None
    out = {}
    for k, v in record.items():
        if k in _DT_FIELDS:
            out[k] = fmt_ts(v) if v is not None else None
        else:
            out[k] = v
    return out


def case(c):
    return _serialize(c)


def party(p):
    return _serialize(p)


def disclosure(d):
    return _serialize(d)


def parenting_plan(pp):
    return _serialize(pp)


def mediation_session(ms):
    return _serialize(ms)


def support_order(so):
    return _serialize(so)


def temp_order(to):
    return _serialize(to)


def final_judgment(fj):
    return _serialize(fj)


def clock_view(now_dt):
    return {"now": fmt_ts(now_dt)}
