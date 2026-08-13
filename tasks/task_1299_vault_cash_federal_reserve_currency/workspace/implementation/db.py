"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "vault_sites": {},
    "staff_members": {},
    "carriers": {},
    "atm_machines": {},
    "seasonal_windows": {},
    "fed_orders": {},
    "denomination_lines": {},   # order_id -> [line, ...]
    "cash_shipments": {},
    "fitness_batches": {},
    "counterfeit_cases": {},
    "cash_ledger_entries": {},  # entry_id -> entry
    "reconciliations": {},
    "atm_forecasts": {},
}

# Logical clock: server default before any set call is exactly 2026-08-01T00:00:00Z.
# Never falls back to wall clock for time-dependent rules.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
CLOCK = {"current_utc": DEFAULT_CLOCK}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp for meta.api_request_timestamp (3 fractional digits)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def clock_dt():
    """Current logical clock instant as an aware datetime."""
    text = CLOCK["current_utc"]
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def clock_iso_ms():
    """Logical clock instant rendered ISO 8601 UTC with three fractional digits."""
    dt = clock_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_date_str():
    """Logical clock value date (YYYY-MM-DD) for ledger business_date stamps."""
    return clock_dt().strftime("%Y-%m-%d")
