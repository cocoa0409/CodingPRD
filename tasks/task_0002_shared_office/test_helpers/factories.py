"""Payload factories for the Shared Office API.

One factory per endpoint that accepts a POST body. Only `source: input` fields are
emitted — system and computed fields are never sent.

Per PRD §2.6, reservation start_at/end_at must land on integer-minute boundaries and
arrive as ISO 8601 UTC with three fractional digits. The helpers in this file emit
strings of that exact shape.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ──────────────────────────────────────────────────────────
# Timestamp helpers — emit ISO 8601 UTC with three fractional digits.
# ──────────────────────────────────────────────────────────


def iso_utc(dt: datetime) -> str:
    """Render a timezone-aware datetime as ISO 8601 UTC with milliseconds and a 'Z'
    suffix, per PRD §2.4 and §2.6."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> str:
    """Construct an ISO 8601 UTC timestamp that lands on an integer-minute boundary
    when second == 0 (PRD §2.6)."""
    return iso_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


def add_hours(ts_iso: str, hours: float) -> str:
    dt = datetime.strptime(ts_iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z")
    return iso_utc(dt + timedelta(hours=hours))


def add_minutes(ts_iso: str, minutes: int) -> str:
    dt = datetime.strptime(ts_iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z")
    return iso_utc(dt + timedelta(minutes=minutes))


# ──────────────────────────────────────────────────────────
# Tenant / Member / Lease / Resource
# ──────────────────────────────────────────────────────────


_COUNTER = {"v": 0}


def _next() -> int:
    _COUNTER["v"] += 1
    return _COUNTER["v"]


def create_tenant_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /tenants body (PRD §3.1): legal_name (1..120), optional credit_limit_cents.

    Default legal_name is unique per call so tests do not collide on list/filter queries.
    """
    defaults = {
        "legal_name": f"{TEST_DEFAULTS['TENANT_LEGAL_NAME']} #{_next()}",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(tenant_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /members body (PRD §3.1): tenant_id, email (unique across all Members),
    full_name, optional role_in_tenant."""
    n = _next()
    defaults = {
        "tenant_id": tenant_id,
        "email": f"member.{n}@example.com",
        "full_name": f"{TEST_DEFAULTS['MEMBER_FULL_NAME']} #{n}",
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(
    tenant_id: str,
    billing_plan: str = "DAILY",
    term_start_date: str = "2026-01-01",
    term_end_date: str = "2026-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /leases body (PRD §3.1): tenant_id, billing_plan, optional
    monthly_rate_cents, term_start_date, term_end_date."""
    defaults = {
        "tenant_id": tenant_id,
        "billing_plan": billing_plan,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
    }
    if billing_plan == "MONTHLY":
        defaults["monthly_rate_cents"] = TEST_DEFAULTS["LEASE_MONTHLY_RATE_CENTS"]
    defaults.update(overrides)
    return defaults


def create_resource_payload(
    kind: str = "WORKSTATION", **overrides: Any
) -> Dict[str, Any]:
    """POST /resources body (PRD §3.2): kind, code (unique), capacity, rate fields."""
    n = _next()
    if kind == "WORKSTATION":
        code_prefix = "WS"
        defaults = {
            "kind": "WORKSTATION",
            "code": f"{code_prefix}-{n:04d}",
            "capacity": TEST_DEFAULTS["RESOURCE_CAPACITY"],
            "hourly_rate_cents": TEST_DEFAULTS["WORKSTATION_HOURLY_RATE_CENTS"],
            "daily_rate_cents": TEST_DEFAULTS["WORKSTATION_DAILY_RATE_CENTS"],
            "block_rate_cents": 0,
        }
    elif kind == "MEETING_ROOM":
        code_prefix = "MR"
        defaults = {
            "kind": "MEETING_ROOM",
            "code": f"{code_prefix}-{n:04d}",
            "capacity": TEST_DEFAULTS["RESOURCE_CAPACITY"],
            "hourly_rate_cents": TEST_DEFAULTS["MEETING_ROOM_HOURLY_RATE_CENTS"],
            "daily_rate_cents": 0,
            "block_rate_cents": 0,
        }
    elif kind == "EVENT_AREA":
        code_prefix = "EVT"
        defaults = {
            "kind": "EVENT_AREA",
            "code": f"{code_prefix}-{n:04d}",
            "capacity": 40,
            "hourly_rate_cents": 0,
            "daily_rate_cents": 0,
            "block_rate_cents": TEST_DEFAULTS["EVENT_AREA_BLOCK_RATE_CENTS"],
        }
    else:  # pragma: no cover — allowed only by defensive programming
        defaults = {
            "kind": kind,
            "code": f"UNK-{n:04d}",
            "capacity": TEST_DEFAULTS["RESOURCE_CAPACITY"],
            "hourly_rate_cents": 0,
            "daily_rate_cents": 0,
            "block_rate_cents": 0,
        }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(
    tenant_id: str,
    member_id: str,
    resource_id: str,
    start_at: str,
    end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /reservations body (PRD §3.3): tenant_id, member_id, resource_id,
    start_at, end_at."""
    defaults = {
        "tenant_id": tenant_id,
        "member_id": member_id,
        "resource_id": resource_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_visitor_payload(
    host_member_id: str,
    expected_arrival_at: str,
    expected_departure_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /visitors body (PRD §3.4): host_member_id, visitor_name,
    expected_arrival_at, expected_departure_at."""
    n = _next()
    defaults = {
        "host_member_id": host_member_id,
        "visitor_name": f"Visitor #{n}",
        "expected_arrival_at": expected_arrival_at,
        "expected_departure_at": expected_departure_at,
    }
    defaults.update(overrides)
    return defaults


def create_access_badge_payload(member_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /access-badges body (PRD §3.5): member_id, badge_serial (unique)."""
    n = _next()
    defaults = {
        "member_id": member_id,
        "badge_serial": f"BADGE-{n:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_access_event_payload(
    kind: str,
    reservation_id: Optional[str] = None,
    visitor_id: Optional[str] = None,
    badge_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /access-events body (PRD §3.3 / §3.4): kind and the id matching the kind."""
    defaults: Dict[str, Any] = {"kind": kind}
    if reservation_id is not None:
        defaults["reservation_id"] = reservation_id
    if visitor_id is not None:
        defaults["visitor_id"] = visitor_id
    if badge_id is not None:
        defaults["badge_id"] = badge_id
    defaults.update(overrides)
    return defaults
