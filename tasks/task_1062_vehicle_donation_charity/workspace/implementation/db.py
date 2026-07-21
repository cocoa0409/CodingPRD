"""In-memory store, logical clock and record helpers.

The store starts empty on every boot; nothing is seeded here.
"""

import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- constants
GROSS_PROCEEDS_THRESHOLD_CENTS = 50000
FMV_SAFE_HARBOR_CENTS = 50000
MIN_FMV_CENTS = 10000
SALVAGE_FMV_CAP_CENTS = 75000
PROGRAM_FEE_TIER_1_MAX_CENTS = 100000
PROGRAM_FEE_TIER_1_RATE = "0.15"
PROGRAM_FEE_TIER_2_MAX_CENTS = 500000
PROGRAM_FEE_TIER_2_RATE = "0.12"
PROGRAM_FEE_TIER_3_RATE = "0.10"
MIN_PROGRAM_FEE_CENTS = 5000
TOW_ALLOWANCE_PCT = "0.25"
ADMIN_FLAT_FEE_CENTS = 2500
PICKUP_BUFFER_MINUTES = 90
MAX_PICKUP_ATTEMPTS = 3
VENUE_DAILY_LOT_CAPACITY = 5
TITLE_RESUBMIT_LIMIT = 2
STALE_TITLE_DAYS = 45
RECEIPT_DUE_DAYS = 30
REMITTANCE_FOLLOWUP_DAYS = 15
AUTO_BATCH_THRESHOLD_CENTS = 500000
AUTO_BATCH_PERIOD_DAYS = 30
ODOMETER_TIER_1_MAX_MILES = 75000
ODOMETER_TIER_2_MAX_MILES = 150000
MAX_REMITTANCE_FEE_PCT = "0.30"
DEFAULT_CLOCK_UTC = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = [
    "Donor",
    "CharityAdmin",
    "IntakeAgent",
    "TitleClerk",
    "AuctionManager",
    "FinanceOfficer",
    "ProgramAdmin",
]

# ---------------------------------------------------------------- store
donors = {}
charities = {}
donations = {}
vehicles = {}
title_records = {}
tow_vendors = {}
pickup_orders = {}
venues = {}
auction_lots = {}
ledger_entries = {}
tax_receipts = {}
remittance_batches = {}
follow_up_tasks = {}

_state = {"clock": DEFAULT_CLOCK_UTC, "seq": 0, "control_number": 0}


def reset():
    for store in (
        donors,
        charities,
        donations,
        vehicles,
        title_records,
        tow_vendors,
        pickup_orders,
        venues,
        auction_lots,
        ledger_entries,
        tax_receipts,
        remittance_batches,
        follow_up_tasks,
    ):
        store.clear()
    _state["clock"] = DEFAULT_CLOCK_UTC
    _state["seq"] = 0
    _state["control_number"] = 0


# ---------------------------------------------------------------- clock
def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt
    return dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def next_control_number():
    _state["control_number"] += 1
    return "CN-{:06d}".format(_state["control_number"])


# ---------------------------------------------------------------- helpers
def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


def new_record(with_common=True):
    rec = {"id": new_id(), "_seq": next_seq()}
    if with_common:
        stamp = now()
        rec["created_at"] = stamp
        rec["updated_at"] = stamp
        rec["version"] = 1
    else:
        rec["created_at"] = now()
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and advance version by one."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def ordered(rows):
    """Default list ordering: created_at ascending, insertion order breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
