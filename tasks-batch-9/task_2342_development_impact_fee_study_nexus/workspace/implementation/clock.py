"""The logical clock every timestamp in this service reads (PRD 2.4)."""

from datetime import datetime

from util import UTC

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

_current = DEFAULT_NOW


def now():
    return _current


def set_now(moment):
    global _current
    _current = moment
    return _current
