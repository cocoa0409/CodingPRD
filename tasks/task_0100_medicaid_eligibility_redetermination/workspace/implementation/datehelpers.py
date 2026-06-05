"""ISO-8601 datetime parsing for coverage / redetermination interval math.

Coverage intervals are closed [coverage_start, coverage_end]; redetermination
windows are half-open [window_open, window_close). We parse to comparable
datetime objects. Inputs are well-formedness-checked as non-empty strings at
the route layer; here we tolerate date-only and 'Z'-suffixed forms.
"""
from __future__ import annotations

from datetime import datetime, timezone

from errors import APIError, ERR_INVALID_REQUEST


def parse_dt(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise APIError(ERR_INVALID_REQUEST, 422, "Invalid datetime")
    raw = value.strip()
    # Normalise trailing Z to +00:00 for fromisoformat.
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Try date-only.
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, 422, f"Invalid datetime: {value}")
    # Make naive datetimes UTC-aware for safe comparison.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
