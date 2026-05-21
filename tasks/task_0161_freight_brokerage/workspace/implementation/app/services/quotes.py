"""Quote-expiry sweep.

A QuoteRequest in OPEN or QUOTED whose ``pickup_window_end`` is now earlier
than the brokerage clock transitions to EXPIRED.  Used by both
``/_clock/advance`` and the standalone ``/_sweep/expire-quotes`` capability.
"""

from __future__ import annotations

from ..store import store
from ..timeutil import parse_iso


def expire_quotes(brokerage_id: str) -> list[dict]:
    bk = store.brokerages.get(brokerage_id)
    if bk is None:
        return []
    clock_now = parse_iso(bk["clock_now_iso"])

    swept: list[dict] = []
    for q in store.quote_requests.values():
        if q.get("brokerage_id") != brokerage_id:
            continue
        if q.get("status") not in ("OPEN", "QUOTED"):
            continue
        try:
            pwe = parse_iso(q["pickup_window_end"])
        except Exception:  # noqa: BLE001
            continue
        if pwe < clock_now:
            q["status"] = "EXPIRED"
            store.bump(q)
            swept.append(q)
    return swept
