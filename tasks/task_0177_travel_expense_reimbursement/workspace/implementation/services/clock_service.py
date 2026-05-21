"""Logical clock service — supports /_clock/advance for time-gated transitions."""
from __future__ import annotations

from datetime import datetime

from core.store import store
from core.utils import format_iso


def get_now() -> datetime:
    return store.logical_now


def get_now_iso() -> str:
    return format_iso(store.logical_now)


def set_now(dt: datetime) -> None:
    store.logical_now = dt
