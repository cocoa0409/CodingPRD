from datetime import datetime, timezone, timedelta


_offset_seconds = 0


def now():
    return datetime.now(timezone.utc) + timedelta(seconds=_offset_seconds)


def advance(seconds):
    global _offset_seconds
    _offset_seconds += seconds


def format_timestamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def is_peak(dt):
    hour = dt.hour
    return (11 <= hour < 13) or (18 <= hour < 20)
