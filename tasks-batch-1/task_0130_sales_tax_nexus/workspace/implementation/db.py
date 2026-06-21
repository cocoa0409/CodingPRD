"""In-memory data store for the Sales Tax Nexus API.

Every process boot starts with empty dictionaries. NO entity seeding happens
here or anywhere at startup — the test harness restarts the server before each
test and constructs all preconditions through the declared API surface.

State is held in plain Python dicts keyed by UUID id. There is no SQLite file,
no JSON dump, no /tmp cache; a fresh process wipes all state.
"""
import datetime
import secrets
import uuid

# ---------------------------------------------------------------------------
# Collections (one dict per entity type, keyed by id)
# ---------------------------------------------------------------------------
tax_jurisdictions = {}
product_categories = {}
sellers = {}
nexus_profiles = {}
exemption_certificates = {}
marketplace_facilitators = {}
transactions = {}
line_items = {}
use_tax_accruals = {}
tax_returns = {}
remittance_payments = {}
audit_log_entries = {}

# Monotonic insertion sequence so creation order (and thus created_at-ascending
# sort) is stable even when two records share an identical millisecond clock.
_seq = {"n": 0}

# ---------------------------------------------------------------------------
# Test-driving logical clock (§3.11). Defaults to real wall-clock UTC until a
# PlatformAdmin sets it via POST /_clock/set_current_utc.
# ---------------------------------------------------------------------------
_clock = {"override": None}


def reset():
    """Wipe every collection (used only for completeness; boot already empty)."""
    for coll in (
        tax_jurisdictions, product_categories, sellers, nexus_profiles,
        exemption_certificates, marketplace_facilitators, transactions,
        line_items, use_tax_accruals, tax_returns, remittance_payments,
        audit_log_entries,
    ):
        coll.clear()
    _seq["n"] = 0
    _clock["override"] = None


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def request_id():
    return "req_" + secrets.token_hex(12)


def now():
    """Current logical UTC time (override clock if set, else wall clock)."""
    if _clock["override"] is not None:
        return _clock["override"]
    return datetime.datetime.now(datetime.timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def set_clock(dt):
    _clock["override"] = dt
