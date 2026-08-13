"""Shared helpers: ids, timestamps (ISO 8601 UTC, 3 fractional digits),
decimal hour arithmetic (round-half-up, 2dp), entity plumbing."""

import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import clock
import db

UTC = timezone.utc
CENT = Decimal("0.01")


def new_id():
    """Server-minted UUID with no type prefix. The first segment carries a
    zero-padded monotonic counter so that id ascending is a valid
    chronological tiebreaker for same-timestamp ledger entries (PRD §2.4)."""
    seq = db.next_seq()
    rand = uuid.uuid4()
    return (
        f"{seq:08x}-{rand.int >> 96 & 0xFFFF:04x}-{rand.int >> 80 & 0xFFFF:04x}-"
        f"{rand.int >> 64 & 0xFFFF:04x}-{rand.int & 0xFFFFFFFFFFFF:012x}"
    )


def new_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime. Naive values are treated as UTC."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_dec(value):
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(value))


def round2(d):
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def num(d):
    """Serialize a Decimal hour amount as a JSON number with 2dp."""
    if isinstance(d, Decimal):
        return float(round2(d))
    return d


def td_hours(td):
    """Exact fractional hours in a timedelta, as Decimal."""
    total = (
        Decimal(td.days) * Decimal(86400)
        + Decimal(td.seconds)
        + Decimal(td.microseconds) / Decimal(1000000)
    )
    return total / Decimal(3600)


def base_entity():
    ts = clock.now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Bump updated_at and optimistic-concurrency version on a mutation."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 1) + 1
