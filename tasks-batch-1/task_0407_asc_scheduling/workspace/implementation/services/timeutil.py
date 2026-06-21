"""Deterministic time helpers (PRD §2.7, §3.8). Never reads wall clock for
domain windows — uses the facility clock and supplied ISO instants."""
from datetime import datetime, timezone


def parse_iso(s):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises on invalid input.
    """
    if not isinstance(s, str) or not s:
        raise ValueError("invalid iso")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hp_is_fresh(hp_signed_at, service_date, hp_validity_days):
    """PRD §3.8 — H&P fresh when days from hp_signed_at to midnight UTC of the
    case's service_date is at most hp_validity_days (boundary inclusive).

    service_date is 'YYYY-MM-DD'. Returns True/False. A missing hp_signed_at is
    handled by the caller (treated as not-fresh).
    """
    signed = parse_iso(hp_signed_at)
    # midnight UTC of service_date
    sd = datetime.strptime(service_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    delta_days = (sd - signed).total_seconds() / 86400.0
    return delta_days <= hp_validity_days
