"""Utility helpers: datetime handling, serial normalization, string distances,
and half-up decimal rounding (money / basis-point precision)."""
import re
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_ALNUM = set(string.ascii_uppercase + string.digits)
_CONFUSABLE = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6", "Q": "0"}
_PHOTO_HASH_RE = re.compile(r"^[0-9a-f]{16}$")


def normalize_serial(raw):
    """PRD §2.7 canonical serial: uppercase, drop non [A-Z0-9], confusable map."""
    if raw is None:
        return ""
    out = []
    for ch in str(raw).upper():
        if ch in _ALNUM:
            out.append(_CONFUSABLE.get(ch, ch))
    return "".join(out)


def levenshtein(a, b):
    """Classic edit distance between two strings."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def hamming64(hash_a, hash_b):
    """Hamming distance between two 64-bit perceptual hashes (16 hex chars)."""
    try:
        xa = int(hash_a, 16)
        xb = int(hash_b, 16)
    except (TypeError, ValueError):
        return 64
    return bin(xa ^ xb).count("1")


def valid_photo_hash(value):
    return isinstance(value, str) and bool(_PHOTO_HASH_RE.match(value))


def rhu(dec_value):
    """Round-half-up a Decimal to an integer."""
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_dt(value):
    """Parse an ISO-8601 datetime into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Serialize an aware datetime as ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    """Envelope meta timestamp: real UTC wall clock, three fractional digits."""
    return fmt_dt(datetime.now(timezone.utc))


def whole_days_between(earlier, later):
    """floor of whole 86400-second days between two datetimes (may be negative)."""
    return int((later - earlier).total_seconds() // 86400)
