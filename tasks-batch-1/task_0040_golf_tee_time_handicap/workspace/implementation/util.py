import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_uuid():
    return str(uuid.uuid4())


def now_iso():
    """Current real-time ISO 8601 UTC with three fractional digits."""
    return iso_from_dt(datetime.now(timezone.utc))


def iso_from_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value, decimals):
    """round_half_up on a Decimal/number to the given number of decimals."""
    d = Decimal(str(value))
    if decimals == 0:
        q = Decimal("1")
    else:
        q = Decimal("1").scaleb(-decimals)
    return d.quantize(q, rounding=ROUND_HALF_UP)
