"""In-memory data store. Starts empty on every boot. No seeding, no disk.

The whole store lives in a single process-local singleton, re-created on every
process boot (the test harness re-launches the server before each test under
per-test-server isolation).
"""
from datetime import datetime, timezone


def wall_now_iso() -> str:
    """Real wall-clock ISO 8601 UTC with millisecond precision (3 fractional digits).

    Used only for response envelope api_request_timestamp. Entity-bearing
    timestamps (created_at/updated_at and the clock-derived computed timestamps)
    trace to the logical server clock, see ``Store.current_utc``.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    """Pure in-memory dict store keyed by id."""

    def __init__(self):
        self.students = {}           # id -> Student dict
        self.evaluations = {}        # id -> Evaluation dict
        self.ieps = {}               # id -> IEP dict
        self.goals = {}              # id -> Goal dict
        self.progress_reports = {}   # id -> ProgressReport dict
        self.related_services = {}   # id -> RelatedService dict
        self.consent_requests = {}   # id -> ConsentRequest dict
        self.transition_plans = {}   # id -> TransitionPlan dict
        # Monotonic creation sequence used as a stable secondary sort key so that
        # items created within the same logical-clock millisecond keep insertion
        # order (creation timestamps can collide when the clock is pinned).
        self.seq = 0
        # Server logical clock, ISO 8601 UTC string. Defaults to the real wall
        # clock; the test-driving endpoint pins it to a supplied instant.
        self.current_utc = wall_now_iso()

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


# Module-level singleton (per process). Re-created on every process boot.
store = Store()
