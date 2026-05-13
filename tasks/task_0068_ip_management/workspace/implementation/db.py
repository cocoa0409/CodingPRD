"""In-memory data store and clock for the IP Management API."""
import uuid
import threading
from datetime import datetime, timezone, timedelta


_lock = threading.RLock()


def new_id() -> str:
    return str(uuid.uuid4())


# -------------------- Clock --------------------

# logical offset (timedelta) — added to wall-clock when computing now()
_clock_offset = timedelta(0)


def reset_clock():
    global _clock_offset
    _clock_offset = timedelta(0)


def advance_clock(seconds: int):
    global _clock_offset
    _clock_offset = _clock_offset + timedelta(seconds=seconds)


def now() -> datetime:
    return datetime.now(timezone.utc) + _clock_offset


def now_iso() -> str:
    n = now()
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def to_iso(dt: datetime) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime. Returns None for None.
    Accepts 'Z' suffix and offsets."""
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=timezone.utc)
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        # Try a fallback: drop fractional seconds if odd length
        try:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# -------------------- Stores --------------------

# Each store maps id -> entity dict.

business_units = {}
agents = {}
ip_rights = {}
jurisdiction_filings = {}
office_actions = {}
annual_fees = {}
contracts = {}
contract_templates = {}
royalty_schedules = {}
protection_cases = {}
evidences = {}
costs = {}
audit_entries = []  # list, ordered

# Idempotency keys
idempotency_payment = {}  # idempotency_key -> annual_fee_id (response cached)
idempotency_esign = {}    # idempotency_key -> contract dict (response cached)

# Unique-code indexes
business_unit_codes = set()
contract_template_codes = set()


def lock():
    return _lock


def reset_all():
    """Reset everything (test convenience)."""
    global _clock_offset
    with _lock:
        business_units.clear()
        agents.clear()
        ip_rights.clear()
        jurisdiction_filings.clear()
        office_actions.clear()
        annual_fees.clear()
        contracts.clear()
        contract_templates.clear()
        royalty_schedules.clear()
        protection_cases.clear()
        evidences.clear()
        costs.clear()
        audit_entries.clear()
        idempotency_payment.clear()
        idempotency_esign.clear()
        business_unit_codes.clear()
        contract_template_codes.clear()
        _clock_offset = timedelta(0)
