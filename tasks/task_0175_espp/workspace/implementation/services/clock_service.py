"""SystemClock service: read and advance."""
from __future__ import annotations

from typing import Any, Dict

from core.errors import APIError, err_clock_not_advancing
from core.store import store
from core.utils import format_iso, lock, parse_iso


def get_clock_snapshot() -> dict:
    return dict(store.clock)


def advance_clock(payload: Dict[str, Any]) -> dict:
    to_timestamp = payload.get("to_timestamp")
    if to_timestamp is None:
        raise APIError(
            "ERR_CLOCK_NOT_ADVANCING",
            "to_timestamp is required.",
            422,
        )
    try:
        target = parse_iso(to_timestamp)
    except Exception:
        raise APIError(
            "ERR_CLOCK_NOT_ADVANCING",
            "to_timestamp must be ISO 8601.",
            422,
        )

    with lock():
        current = parse_iso(store.clock["current_time"])
        if target <= current:
            raise err_clock_not_advancing()
        store.clock["current_time"] = format_iso(target)

    return get_clock_snapshot()


def _set_last_sweep(timestamp_iso: str) -> None:
    store.clock["last_sweep_at"] = timestamp_iso
