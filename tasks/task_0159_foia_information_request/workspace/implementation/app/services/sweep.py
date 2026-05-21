"""Sweep — promotes overdue third-party notices to EXPIRED.

Run automatically after every POST /foia/_clock/advance and exposed
separately via POST /foia/_sweep/run.  Idempotent: a second run with no
clock advance produces no further state changes.
"""

from __future__ import annotations

from flask import g

from ..store import append_audit, store
from ..timeutil import clock, parse_iso


def _is_due(notice: dict, now_iso: str) -> bool:
    deadline = notice.get("response_deadline")
    if not deadline:
        return False
    return parse_iso(deadline) <= parse_iso(now_iso)


def run_sweep() -> int:
    """Promote all pending notices whose deadline has passed.  Returns count."""

    promoted = 0
    actor_role = getattr(g, "user_role", None)
    actor_id = getattr(g, "user_id", None)
    from ..timeutil import iso_now

    now_iso = iso_now(clock.now())

    with store.lock:
        for notice in list(store.third_party_notices.values()):
            if notice["status"] != "PENDING_RESPONSE":
                continue
            if not _is_due(notice, now_iso):
                continue
            notice["status"] = "EXPIRED"
            store.bump(notice)
            append_audit(
                subject_type="THIRD_PARTY_NOTICE",
                subject_id=notice["id"],
                event_code="THIRD_PARTY_RESPONDED",
                actor_role=actor_role,
                actor_id=actor_id,
                payload={"outcome": "EXPIRED"},
            )
            promoted += 1
    return promoted
