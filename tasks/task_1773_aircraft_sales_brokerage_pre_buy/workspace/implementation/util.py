"""Shared helpers: ids, request ids, timestamps, datetime/date parsing."""
import random
import string
import uuid
from datetime import date, datetime, timezone


def new_id() -> str:
    """UUID identifier with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD 2.2/2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def today_iso() -> str:
    """Today's date (UTC) as an ISO 8601 date string."""
    return datetime.now(timezone.utc).date().isoformat()


def parse_datetime(s: str) -> datetime:
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s: str) -> date:
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s.strip())


def new_escrow_ref() -> str:
    return "ESC-" + uuid.uuid4().hex[:12].upper()
