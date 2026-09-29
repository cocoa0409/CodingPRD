"""Record serialisation."""
import store
import timeutil
from constants import OPEN_FAULT_STATES


def plain(rec):
    return store.public(rec)


def fault_view(rec):
    out = store.public(rec)
    if rec["state"] in OPEN_FAULT_STATES:
        out["duration_seconds"] = max(0, timeutil.delta_seconds(rec["detected_utc"], store.clock()))
    return out


def item_view(rec):
    return store.public(rec)
