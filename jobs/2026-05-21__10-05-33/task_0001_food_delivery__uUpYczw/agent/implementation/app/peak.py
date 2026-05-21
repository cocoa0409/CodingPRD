"""Peak-window classification.

Two windows on each calendar day are designated peak: 11:00–13:00 UTC and
18:00–20:00 UTC. The boundary semantics — inclusive on the lower bound,
exclusive on the upper — match the spirit of the PRD "11:00 through 13:00".
"""
from __future__ import annotations

import datetime


def is_peak(dt: datetime.datetime) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    h, m = dt.hour, dt.minute
    minutes = h * 60 + m
    # 11:00 through 13:00 UTC
    if 11 * 60 <= minutes < 13 * 60:
        return True
    # 18:00 through 20:00 UTC
    if 18 * 60 <= minutes < 20 * 60:
        return True
    return False
