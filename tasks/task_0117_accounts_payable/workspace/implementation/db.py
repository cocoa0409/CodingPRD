"""In-memory data store for the Accounts Payable Automation API.

Every store is a plain dict keyed by entity id. All stores start EMPTY on each
fresh boot — the test harness restarts this process (via start.sh) before every
test, so there is no carry-over state and nothing is ever seeded at startup.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict


def new_uuid() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits and 'Z' (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    """`req_` prefix + 20 alphanumeric chars (PRD §2.2)."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# A monotonically increasing sequence used purely to give entities a stable,
# strictly-increasing creation order for the ascending-creation-time list sort
# (PRD §2.3). Wall-clock timestamps can collide at millisecond resolution.
_seq = 0


def next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


# ---- stores (cleared at module load on each fresh boot) ---------------------

vendors: Dict[str, Dict[str, Any]] = {}
gl_accounts: Dict[str, Dict[str, Any]] = {}
purchase_orders: Dict[str, Dict[str, Any]] = {}
goods_receipts: Dict[str, Dict[str, Any]] = {}
invoices: Dict[str, Dict[str, Any]] = {}
invoice_lines: Dict[str, Dict[str, Any]] = {}
match_exceptions: Dict[str, Dict[str, Any]] = {}
approval_routes: Dict[str, Dict[str, Any]] = {}
approval_steps: Dict[str, Dict[str, Any]] = {}
payment_batches: Dict[str, Dict[str, Any]] = {}
payments: Dict[str, Dict[str, Any]] = {}
accruals: Dict[str, Dict[str, Any]] = {}
audit_events: Dict[str, Dict[str, Any]] = {}
