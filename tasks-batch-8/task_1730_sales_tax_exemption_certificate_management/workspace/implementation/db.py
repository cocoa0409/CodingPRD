"""In-memory data store. Module-level dicts only — no disk, no external
persistence. Every start.sh re-invocation boots with empty state; nothing is
seeded here or anywhere else."""

import random
import string
import uuid
from datetime import datetime, timezone

stores = {
    "tenants": {},
    "jurisdiction_rules": {},
    "exemption_reasons": {},
    "customers": {},
    "certificates": {},
    "certificate_versions": {},
    "orders": {},
    "order_lines": {},
    "drop_ship_links": {},
    "audit_campaigns": {},
    "audit_samples": {},
    "remediation_actions": {},
    "outreach_campaigns": {},
    "outreach_notices": {},
    "defense_packets": {},
}

_seq = 0


def next_seq():
    """Monotonic creation-order counter used for deterministic created_at-ASC
    ordering even when two records share a millisecond timestamp."""
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.5)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_record(fields=None):
    """Record with the common system-managed fields of PRD §2.5."""
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    if fields:
        rec.update(fields)
    return rec


def make_notice(fields=None):
    """OutreachNotice: immutable emission record; carries only id and
    created_at from the common set — no updated_at, no version (PRD §2.5)."""
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}
    if fields:
        rec.update(fields)
    return rec


def pub(rec):
    """Public view of a record: internal underscore-prefixed keys stripped."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
