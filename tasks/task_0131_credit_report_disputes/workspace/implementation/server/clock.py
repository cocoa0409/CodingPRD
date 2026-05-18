"""Logical test clock: a monotonically advancing integer day counter."""
from __future__ import annotations

import threading


class Clock:
    def __init__(self) -> None:
        self._day = 0
        self._lock = threading.Lock()

    @property
    def day(self) -> int:
        return self._day

    def advance(self, days: int) -> int:
        with self._lock:
            self._day += days
            return self._day


# Singleton — there is only one logical clock per server process.
clock = Clock()
