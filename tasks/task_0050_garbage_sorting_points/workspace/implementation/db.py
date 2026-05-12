"""In-memory data store for the Garbage Sorting Points API.

All entities live in dictionaries keyed by id. Single-process; serialised
via a global RLock acquired in Flask before/teardown_request hooks.

The "logical clock" lives here too: it is the canonical "now()" used for
every business-rule comparison. SystemOperator can advance it via
POST /_clock/advance.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid


def gen_id() -> str:
    return str(uuid.uuid4())


def _iso_z_from_dt(d: dt.datetime) -> str:
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits, suffix 'Z'."""
    d_utc = d.astimezone(dt.timezone.utc)
    return d_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d_utc.microsecond // 1000:03d}Z"


class DB:
    def __init__(self):
        self.lock = threading.RLock()

        # Top-level collections keyed by id
        self.communities: dict[str, dict] = {}
        self.households: dict[str, dict] = {}
        self.residents: dict[str, dict] = {}
        self.point_rules: dict[str, dict] = {}
        self.disposals: dict[str, dict] = {}
        self.points_transactions: dict[str, dict] = {}
        self.mall_items: dict[str, dict] = {}
        self.redemption_orders: dict[str, dict] = {}
        self.violations: dict[str, dict] = {}
        self.ranking_periods: dict[str, dict] = {}
        self.audit_logs: dict[str, dict] = {}

        # Logical clock — naive UTC datetime; advanced by SystemOperator.
        self._logical_now: dt.datetime = dt.datetime.now(dt.timezone.utc).replace(
            microsecond=0
        )

    # ---------- clock ----------

    def now(self) -> dt.datetime:
        """Current logical 'now' as a tz-aware UTC datetime."""
        return self._logical_now

    def now_iso(self) -> str:
        return _iso_z_from_dt(self._logical_now)

    def advance_clock(self, to: dt.datetime) -> dt.datetime:
        """Advance the logical clock to `to` (must be tz-aware UTC). Never moves backwards."""
        if to.tzinfo is None:
            to = to.replace(tzinfo=dt.timezone.utc)
        if to > self._logical_now:
            self._logical_now = to
        return self._logical_now

    # ---------- stamp helpers ----------

    def stamp_create(self, obj: dict, *, with_version: bool = True) -> dict:
        ts = self.now_iso()
        if "id" not in obj:
            obj["id"] = gen_id()
        obj["created_at"] = ts
        if with_version:
            obj["updated_at"] = ts
            obj["version"] = 1
        return obj

    def stamp_update(self, obj: dict):
        obj["updated_at"] = self.now_iso()
        obj["version"] = obj.get("version", 1) + 1


db = DB()
