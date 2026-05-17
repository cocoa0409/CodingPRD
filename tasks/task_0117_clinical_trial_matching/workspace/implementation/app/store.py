"""In-memory data store with row tables keyed by id.

Rows are plain dicts. Every common-fielded entity has `id`, `created_at`, `updated_at`, `version`.
ConsentVersion and Payment are immutable-after-write: they have only `id` and `created_at`.
"""
from __future__ import annotations

from threading import RLock
from typing import Any


class _Tables:
    """A bundle of tables holding the system's state."""

    def __init__(self) -> None:
        self.trials: dict[str, dict[str, Any]] = {}
        self.arms: dict[str, dict[str, Any]] = {}
        self.consent_versions: dict[str, dict[str, Any]] = {}
        self.participants: dict[str, dict[str, Any]] = {}
        self.visits: dict[str, dict[str, Any]] = {}
        self.adverse_events: dict[str, dict[str, Any]] = {}
        self.payments: dict[str, dict[str, Any]] = {}
        self.irb_reviews: dict[str, dict[str, Any]] = {}
        # protocol_code → trial_id, for the uniqueness check (case/whitespace-trimmed).
        self.protocol_code_index: dict[str, str] = {}
        # global lock; the system is small and correctness > throughput.
        self.lock: RLock = RLock()


# Module-level singleton; reset_store() rebinds.
_store = _Tables()


def store() -> _Tables:
    return _store


def reset_store() -> None:
    global _store
    _store = _Tables()
    # Also reset the logical clock so each app instance / test boots clean.
    from . import clock as _clock
    _clock.clock.reset()
