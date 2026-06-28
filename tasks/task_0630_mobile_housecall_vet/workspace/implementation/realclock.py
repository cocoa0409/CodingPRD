"""Wall-clock helper for response metadata timestamps (not business time)."""
from datetime import datetime, timezone


def wall_now():
    return datetime.now(timezone.utc)
