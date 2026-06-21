"""In-memory data store.

Stores start empty on every boot. Tests construct state via the API.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO-8601 UTC timestamp with three fractional digits, suffix 'Z'."""
    # Use logical clock for created_at/updated_at? No — those reflect wall time
    # of server-side mutation. The PRD only says "server-generated"; the logical
    # clock is for deadline comparisons. We use real wall time but in UTC with
    # millisecond precision.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    # `req_` prefix + 20 alphanumeric chars
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- stores (cleared at module load each fresh boot) ------------------------

applicants: Dict[str, Dict[str, Any]] = {}
schools: Dict[str, Dict[str, Any]] = {}
applications: Dict[str, Dict[str, Any]] = {}
essays: Dict[str, Dict[str, Any]] = {}
recommendation_requests: Dict[str, Dict[str, Any]] = {}
financial_aid_profiles: Dict[str, Dict[str, Any]] = {}
aid_packages: Dict[str, Dict[str, Any]] = {}
waitlist_entries: Dict[str, Dict[str, Any]] = {}

# Singleton clock (never seeded as an entity test pre-condition; it is system
# infrastructure with a fixed id "clock-singleton" required by the scaffold).
# Default starts at epoch-equivalent ISO; tests overwrite via /_clock/set_current_utc.
system_clock: Dict[str, Any] = {
    "id": "clock-singleton",
    "created_at": now_iso(),
    "current_utc": "1970-01-01T00:00:00.000Z",
}
