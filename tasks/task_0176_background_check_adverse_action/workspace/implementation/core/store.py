"""In-memory data store for all FCRA entities.

A single process-wide ``_Store`` instance holds every entity collection
plus the logical clock used for cooling-off arithmetic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional


class _Store:
    def __init__(self) -> None:
        self.candidates: Dict[str, dict] = {}
        self.consents: Dict[str, dict] = {}
        self.jurisdiction_policies: Dict[str, dict] = {}  # keyed by jurisdiction_code
        self.orders: Dict[str, dict] = {}
        self.verification_items: Dict[str, dict] = {}
        self.disputes: Dict[str, dict] = {}
        self.adverse_flows: Dict[str, dict] = {}  # keyed by AdverseActionFlow.id
        self.adverse_flow_by_order: Dict[str, str] = {}  # order_id -> flow_id
        self.audit_events: List[dict] = []  # ordered insertion

        # Logical clock: server "current time" = wall-clock now + an
        # accumulated offset that POST /fcra/_clock/advance pushes
        # forward (PRD §3.10). At startup the offset is zero, so the
        # server's current time is the wall clock; advancing by N
        # seconds moves the server time N seconds into the future
        # relative to wall clock. This satisfies PRD §3.2's "consent
        # timestamps must be <= server's current time" while allowing
        # cooling-off tests to fast-forward.
        from datetime import timedelta as _td
        self._clock_offset: _td = _td(seconds=0)

        # Track the order's order-opener user id separately so we can do
        # the SoD check at Pre-Adverse/Final-Adverse time.
        self.order_openers: Dict[str, str] = {}  # order_id -> X-User-ID

    # ------- Clock helpers --------------------------------------------------
    def logical_now(self) -> datetime:
        return datetime.now(tz=timezone.utc) + self._clock_offset

    def advance_logical_clock(self, seconds: int) -> None:
        from datetime import timedelta

        self._clock_offset = self._clock_offset + timedelta(seconds=int(seconds))

    # ------- Convenience accessors -----------------------------------------
    def list_items_for_order(self, order_id: str) -> List[dict]:
        return [i for i in self.verification_items.values() if i["order_id"] == order_id]

    def list_orders_for_candidate(self, candidate_id: str) -> List[dict]:
        return [o for o in self.orders.values() if o["candidate_id"] == candidate_id]

    def list_disputes_for_item(self, item_id: str) -> List[dict]:
        return [d for d in self.disputes.values() if d["verification_item_id"] == item_id]

    def adverse_flow_for_order(self, order_id: str) -> Optional[dict]:
        fid = self.adverse_flow_by_order.get(order_id)
        if fid is None:
            return None
        return self.adverse_flows.get(fid)


store = _Store()
