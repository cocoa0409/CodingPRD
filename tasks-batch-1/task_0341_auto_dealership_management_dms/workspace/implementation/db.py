"""In-memory data store. All state lives in module-level dicts keyed by id.

A fresh process (start.sh re-invocation) wipes every byte of state. NOTHING is
seeded, preloaded, or hardcoded here — the store starts completely empty.
"""
import threading
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id.
vehicles = {}
floor_plan_lines = {}
customers = {}
trade_ins = {}
deals = {}
lender_programs = {}
finance_products = {}
deal_products = {}
finance_contracts = {}
oem_incentives = {}
test_drives = {}
repair_orders = {}
title_registrations = {}
deal_jacket_documents = {}

_lock = threading.RLock()

# Deterministic server clock. None => use real wall clock. Set via /_clock/set_current_utc.
_current_utc = None


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_dt():
    """Current server instant as an aware datetime (UTC)."""
    if _current_utc is not None:
        return _current_utc
    return datetime.now(timezone.utc)


def set_current_utc(dt):
    global _current_utc
    _current_utc = dt


def iso_now():
    """ISO 8601 UTC timestamp with exactly three fractional digits, Z suffix."""
    return format_iso(now_dt())


def format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
