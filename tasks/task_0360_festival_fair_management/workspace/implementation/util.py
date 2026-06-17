"""Shared utilities: ids, timestamps, money rounding."""
import uuid
import random
import string
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP


def new_id():
    """Server-minted UUID, no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """req_ + random alphanum (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def round2(value):
    """Round to 2dp, half-up, returning a float for JSON serialization."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def parse_iso_date(s):
    """Parse a YYYY-MM-DD date (the date portion of any ISO string is accepted)."""
    return date.fromisoformat(s[:10])
