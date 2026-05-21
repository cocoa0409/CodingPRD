"""Peak window determination."""
from __future__ import annotations

import datetime as _dt


def is_peak_time(t: _dt.datetime) -> bool:
    """11:00-13:00 UTC or 18:00-20:00 UTC, inclusive of start, exclusive of end."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    else:
        t = t.astimezone(_dt.timezone.utc)
    h = t.hour
    return (11 <= h < 13) or (18 <= h < 20)
