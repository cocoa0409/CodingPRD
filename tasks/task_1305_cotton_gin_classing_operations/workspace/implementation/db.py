"""In-memory data store. Starts empty on every boot; no seeding."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock timestamp for meta.api_request_timestamp and created_at/updated_at.

    ISO 8601 UTC with three fractional digits.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5). Before any clock call, reads 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.growers = {}            # id -> Grower dict
        self.grade_schedules = {}    # id -> GradeSchedule
        self.warehouses = {}         # id -> Warehouse
        self.gin_shifts = {}         # id -> GinShift
        self.modules = {}            # id -> ModuleReceipt
        self.bales = {}              # id -> Bale
        self.classing_results = {}   # id -> ClassingResult
        self.warehouse_receipts = {} # id -> WarehouseReceipt
        self.loan_pledges = {}       # id -> LoanPledge
        self.seed_sales = {}         # id -> SeedSale
        self.shipping_orders = {}    # id -> ShippingOrder
        self.settlements = {}        # id -> Settlement
        self.ledger_entries = {}     # id -> LedgerEntry
        self.receipt_seq = 0
        self.clock_iso = _DEFAULT_CLOCK

    # -- logical clock -------------------------------------------------------
    def clock_datetime(self):
        return parse_dt(self.clock_iso)

    def clock_date_str(self):
        """Logical-clock date at 00:00:00Z."""
        dt = self.clock_datetime()
        return dt.strftime("%Y-%m-%dT00:00:00Z")


db = Store()


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO-8601 datetime/date string into an aware UTC datetime.

    Accepts 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SSZ', fractional seconds, and
    explicit offsets. Naive values are assumed UTC.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Try date-only
            dt = datetime.strptime(str(value).strip(), "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_date_z(dt):
    return dt.strftime("%Y-%m-%dT00:00:00Z")


def is_valid_datetime(value):
    try:
        parse_dt(value)
        return True
    except (ValueError, TypeError):
        return False
