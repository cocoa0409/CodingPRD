"""In-memory data store.

Every store starts EMPTY on each fresh boot. The test harness restarts this
process (via start.sh) before every test, so there is no carry-over state.
The implementation never seeds, preloads, or hardcodes any entity.
"""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict


def new_uuid() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4).

    Used for created_at / updated_at and the response meta timestamp. This is
    server wall-clock time of the mutation; it is distinct from the logical
    clock used for deadline comparisons (PRD §2.6).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_ALPHANUM = string.ascii_letters + string.digits


def new_request_id() -> str:
    """Server-generated request id that starts with `req_` (PRD §2.2)."""
    suffix = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return "req_" + suffix


# ---- entity stores (keyed by id) --------------------------------------------
terms: Dict[str, Dict[str, Any]] = {}
students: Dict[str, Dict[str, Any]] = {}
programs: Dict[str, Dict[str, Any]] = {}
courses: Dict[str, Dict[str, Any]] = {}
course_requirements: Dict[str, Dict[str, Any]] = {}
instructors: Dict[str, Dict[str, Any]] = {}
sections: Dict[str, Dict[str, Any]] = {}
appointments: Dict[str, Dict[str, Any]] = {}
enrollments: Dict[str, Dict[str, Any]] = {}
holds: Dict[str, Dict[str, Any]] = {}
swap_requests: Dict[str, Dict[str, Any]] = {}
refund_transactions: Dict[str, Dict[str, Any]] = {}

# Monotonic counter to break created_at ties deterministically (created_at has
# only millisecond precision; waitlist ordering and list ordering rely on
# insertion order within the same millisecond).
_seq = {"n": 0}


def next_seq() -> int:
    _seq["n"] += 1
    return _seq["n"]


# ---- logical clock (PRD §2.6) -----------------------------------------------
# Holds the server's current UTC instant for deadline/window comparisons.
# Defaults to None; a Registrar sets it via POST /_clock/set. When unset, the
# server falls back to real wall-clock UTC.
logical_clock: Dict[str, Any] = {"now": None}
