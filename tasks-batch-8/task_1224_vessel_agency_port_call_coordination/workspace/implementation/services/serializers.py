"""Entity serializers: full field sets plus common system fields."""
from utils import fmt_dt, fmt_ts

_DT_FIELDS = {
    "eta", "etd", "actual_arrival_at", "actual_sailed_at", "start_at", "end_at",
    "occupied_at", "released_at", "window_start", "window_end", "passport_expiry",
    "shore_pass_expires_at", "needed_by", "effective_from", "submitted_at",
    "received_at",
}


def _serialize(ent):
    out = {}
    for key, value in ent.items():
        if key == "_seq":
            continue
        if key in ("created_at", "updated_at"):
            out[key] = fmt_ts(value)
        elif key in _DT_FIELDS:
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out


def serialize(ent):
    return _serialize(ent)


def serialize_many(ents):
    return [_serialize(e) for e in ents]
