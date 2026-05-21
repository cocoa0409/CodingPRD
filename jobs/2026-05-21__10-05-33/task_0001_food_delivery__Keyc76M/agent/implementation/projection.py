"""Convert internal entity dicts into the JSON shape returned to clients.

Internal entity dicts are stored as Python primitives plus datetimes; this
module renders timestamps and strips any internal-only keys so HTTP
responses match the PRD exactly.
"""

import state


_DATE_FIELDS = {
    "created_at", "updated_at",
    "offered_at", "accepted_at", "picked_up_at", "delivered_at",
    "promised_delivery_time", "actual_delivery_time",
    "merged_at",
}


def render(entity, drop=()):
    if entity is None:
        return None
    out = {}
    for k, v in entity.items():
        if k.startswith("_") or k in drop:
            continue
        if k in _DATE_FIELDS:
            out[k] = state.fmt_dt(v) if v is not None else None
        else:
            out[k] = v
    return out


def render_list(entities, drop=()):
    return [render(e, drop=drop) for e in entities]
