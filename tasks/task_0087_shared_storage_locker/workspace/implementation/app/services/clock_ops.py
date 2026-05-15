"""Test-driver clock and sweep operations."""
from __future__ import annotations

from typing import Any

from ..clock import CLOCK, parse_iso, format_iso, now_dt
from ..errors import ApiError
from .rentals import sweep_cabinets, sweep_rentals
from .validation import require_field, require_str


def advance_clock(body: dict[str, Any]) -> dict[str, Any]:
    to_ts = require_str(require_field(body, "to_timestamp"), "to_timestamp")
    try:
        target = parse_iso(to_ts)
    except ValueError as exc:
        raise ApiError("ERR_BAD_REQUEST", str(exc))
    CLOCK.set(target)
    return {"server_time": format_iso(CLOCK.now)}


def run_sweep() -> dict[str, Any]:
    now = now_dt()
    transitions = 0
    transitions += sweep_cabinets(now)
    transitions += sweep_rentals(now)
    return {"transitions_count": transitions}
