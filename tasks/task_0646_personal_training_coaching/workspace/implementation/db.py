"""In-memory data store (PRD §2.4).

The store starts EMPTY on every process boot. No entity seeding occurs at
startup; every entity a test needs is constructed via the declared API surface.
"""

import uuid

from clock import clock, format_iso8601_ms


class Store:
    def __init__(self):
        self.trainers = {}
        self.clients = {}
        self.engagements = {}
        self.session_packs = {}
        self.bookings = {}
        self.program_assignments = {}
        self.macro_plans = {}
        self.check_ins = {}
        self.habit_logs = {}
        self.messages = {}
        # Monotonic insertion sequence so created_at ties keep a stable
        # creation order even when the logical clock has not advanced.
        self._seq = 0

    def reset(self):
        self.__init__()

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Creation/mutation timestamps are stamped from the logical clock so that
    list ordering by created_at is deterministic and clock-driven."""
    return format_iso8601_ms(clock.now())
