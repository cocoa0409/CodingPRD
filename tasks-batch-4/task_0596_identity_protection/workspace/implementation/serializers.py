"""Resource serialisation. Internal bookkeeping keys (prefixed `_`) never leak."""

from db import serialize
from services.calc import thaw_window_is_open


def ser(row):
    return serialize(row)


def ser_many(rows):
    return [serialize(r) for r in rows]


def ser_thaw_window(window):
    data = serialize(window)
    data["is_currently_open"] = thaw_window_is_open(window)
    return data


def ser_thaw_windows(windows):
    return [ser_thaw_window(w) for w in windows]
