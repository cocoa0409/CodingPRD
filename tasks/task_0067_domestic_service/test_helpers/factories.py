"""Payload factories for the Domestic Service Dispatch API.

One factory per input payload. Only `source: input` fields are emitted; system-
computed fields like `status`, `gross_price_cents`, or `tier` are never sent on
creation. All factory defaults conform to PRD-permitted input shapes so calls
hit the relevant rule rather than tripping ERR_VALIDATION_ERROR first.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ─────────────────────────────────────────────────────────────
# Logical-clock tracker — mirrors the server's clock offset so that
# `iso_in` produces timestamps relative to the server's current_time
# (PRD §3.11: /dsd/_clock/advance shifts the logical clock forward).
# advance_clock() in fixtures.py increments this counter after every
# successful sweep so subsequent scheduled_start_at values stay
# strictly in the server's future.
# ─────────────────────────────────────────────────────────────


class _LogicalClock:
    def __init__(self) -> None:
        self.offset_seconds: float = 0.0

    def add(self, seconds: float) -> None:
        self.offset_seconds += float(seconds)


logical_clock = _LogicalClock()


# ─────────────────────────────────────────────────────────────
# Time helpers — produce ISO 8601 strings with millisecond precision and Z suffix.
# ─────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=logical_clock.offset_seconds)


def _iso(ts: datetime) -> str:
    s = ts.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return s.replace("+00:00", "Z")


def iso_in(*, hours: float = 0.0, days: float = 0.0, seconds: float = 0.0) -> str:
    """Return an ISO 8601 UTC timestamp `hours`+`days`+`seconds` from the server's
    current_time (wall-clock + cumulative logical clock offset)."""
    return _iso(_now_utc() + timedelta(hours=hours, days=days, seconds=seconds))


# ─────────────────────────────────────────────────────────────
# ServicePersonnel (PRD §3.1)
# ─────────────────────────────────────────────────────────────


def create_personnel_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: create a ServicePersonnel profile.

    Required inputs: full_name, gender, age, languages, service_lat, service_lng,
    health_cert_expires_at. service_radius_km defaults to 10 per PRD §3.1.
    """
    payload: Dict[str, Any] = {
        "full_name": "Personnel Alpha",
        "gender": "FEMALE",
        "age": 30,
        "languages": ["zh", "en"],
        "service_lat": TEST_DEFAULTS["LAT"],
        "service_lng": TEST_DEFAULTS["LNG"],
        "service_radius_km": 10,
        # 365 days into the future so health_cert_expires_at > current_time
        "health_cert_expires_at": iso_in(days=365),
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# SkillCertification (PRD §3.2)
# ─────────────────────────────────────────────────────────────


def create_certification_payload(
    personnel_id: str,
    *,
    skill_tag: str = "CLEANING",
    training_hours: float = 12,
    expires_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: create a SkillCertification (PENDING)."""
    payload: Dict[str, Any] = {
        "personnel_id": personnel_id,
        "skill_tag": skill_tag,
        "training_hours": training_hours,
        "expires_at": expires_at if expires_at is not None else iso_in(days=365),
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# ServiceItem (PRD §3.3)
# ─────────────────────────────────────────────────────────────


def create_service_item_payload(
    *,
    name: str = "Standard Cleaning",
    required_skill_tag: str = "CLEANING",
    base_price_cents: int = TEST_DEFAULTS["BASE_PRICE_CENTS"],
    min_duration_hours: float = 1,
    service_areas: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: create a ServiceItem (active defaults to true).

    The PRD prose says `active` defaults to true; we omit it here so the
    server's default is exercised. Tests that need an inactive item should
    create it then PATCH `active=false`, or pass `active=False` explicitly.
    """
    payload: Dict[str, Any] = {
        "name": name,
        "required_skill_tag": required_skill_tag,
        "base_price_cents": base_price_cents,
        "min_duration_hours": min_duration_hours,
        "service_areas": service_areas
        if service_areas is not None
        else [TEST_DEFAULTS["AREA"]],
    }
    payload.update(overrides)
    return payload


def patch_service_item_payload(**fields: Any) -> Dict[str, Any]:
    """PATCH /dsd/service-items/{id} — only the fields the test wants to update."""
    return dict(fields)


# ─────────────────────────────────────────────────────────────
# Customer (PRD §3.3)
# ─────────────────────────────────────────────────────────────


def create_customer_payload(
    *,
    full_name: str = "Customer Alpha",
    area_code: str = TEST_DEFAULTS["AREA"],
    address_lat: float = TEST_DEFAULTS["LAT"],
    address_lng: float = TEST_DEFAULTS["LNG"],
    pref_gender: Optional[str] = None,
    pref_min_age: Optional[int] = None,
    pref_max_age: Optional[int] = None,
    pref_language: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: create a Customer profile. Preference fields default to null
    (no preference) per PRD."""
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "area_code": area_code,
        "address_lat": address_lat,
        "address_lng": address_lng,
        "pref_gender": pref_gender,
        "pref_min_age": pref_min_age,
        "pref_max_age": pref_max_age,
        "pref_language": pref_language,
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Order (PRD §3.4)
# ─────────────────────────────────────────────────────────────


def create_order_payload(
    *,
    customer_id: str,
    service_item_id: str,
    mode: str = "SINGLE",
    scheduled_start_at: Optional[str] = None,
    duration_hours: float = TEST_DEFAULTS["DURATION_HOURS"],
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: create an Order in DRAFT.

    Default `scheduled_start_at` is 48h into the future — outside the 12h
    modification window AND past the 1h lead-time floor, so submission with
    this default is permitted.
    """
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "service_item_id": service_item_id,
        "mode": mode,
        "scheduled_start_at": scheduled_start_at
        if scheduled_start_at is not None
        else iso_in(hours=48),
        "duration_hours": duration_hours,
    }
    payload.update(overrides)
    return payload


def patch_order_payload(**fields: Any) -> Dict[str, Any]:
    """PATCH /dsd/orders/{id} — only the fields the test wants to update.

    May include `scheduled_start_at`, `duration_hours`, and `version` (OCC).
    """
    return dict(fields)


# ─────────────────────────────────────────────────────────────
# RecurringOrder (PRD §3.4)
# ─────────────────────────────────────────────────────────────


def create_recurring_order_payload(
    *,
    customer_id: str,
    service_item_id: str,
    cadence_days: int = 7,
    first_start_at: Optional[str] = None,
    duration_hours: float = TEST_DEFAULTS["DURATION_HOURS"],
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: create a RecurringOrder (status ACTIVE)."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "service_item_id": service_item_id,
        "cadence_days": cadence_days,
        "first_start_at": first_start_at
        if first_start_at is not None
        else iso_in(hours=48),
        "duration_hours": duration_hours,
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Reassign (PRD §3.5)
# ─────────────────────────────────────────────────────────────


def reassign_payload(personnel_id: str) -> Dict[str, Any]:
    """POST /dsd/orders/{id}/reassign — body specifies the target personnel."""
    return {"personnel_id": personnel_id}


# ─────────────────────────────────────────────────────────────
# Check-in (PRD §3.6)
# ─────────────────────────────────────────────────────────────


def checkin_payload(
    *,
    checkin_lat: float = TEST_DEFAULTS["LAT"],
    checkin_lng: float = TEST_DEFAULTS["LNG"],
    checkin_face_passed: bool = True,
) -> Dict[str, Any]:
    """POST /dsd/orders/{id}/checkin — body holds GPS + face flag.

    Defaults are coincident with the Customer address so haversine ≤ 0.2 km.
    """
    return {
        "checkin_lat": checkin_lat,
        "checkin_lng": checkin_lng,
        "checkin_face_passed": checkin_face_passed,
    }


# ─────────────────────────────────────────────────────────────
# Execution patch (PRD §3.6)
# ─────────────────────────────────────────────────────────────


def patch_execution_payload(
    *,
    procedure_checklist: Optional[List[bool]] = None,
    before_photo_url: Optional[str] = None,
    after_photo_url: Optional[str] = None,
) -> Dict[str, Any]:
    """PATCH /dsd/orders/{id}/execution — only fields the caller wants to update."""
    payload: Dict[str, Any] = {}
    if procedure_checklist is not None:
        payload["procedure_checklist"] = procedure_checklist
    if before_photo_url is not None:
        payload["before_photo_url"] = before_photo_url
    if after_photo_url is not None:
        payload["after_photo_url"] = after_photo_url
    return payload


# ─────────────────────────────────────────────────────────────
# Abnormal event (PRD §3.7)
# ─────────────────────────────────────────────────────────────


def abnormal_event_payload(
    *,
    category: str = "OTHER",
    description: str = "Test abnormal report",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /dsd/orders/{id}/abnormal-events.

    PRD §3.7 says category is one of INJURY, PROPERTY_DAMAGE, NO_SHOW, OTHER.
    Note: reporter_role is derived from X-User-Role by the server, not from
    the body — the endpoint input table lists only `category` and `description`.
    """
    payload: Dict[str, Any] = {
        "category": category,
        "description": description,
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Rating (PRD §3.9)
# ─────────────────────────────────────────────────────────────


def rating_payload(
    *,
    quality_score: int = 5,
    punctuality_score: int = 5,
    attitude_score: int = 5,
    text_review: str = "Great service.",
    anonymous: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /dsd/orders/{id}/rate."""
    payload: Dict[str, Any] = {
        "quality_score": quality_score,
        "punctuality_score": punctuality_score,
        "attitude_score": attitude_score,
        "text_review": text_review,
        "anonymous": anonymous,
    }
    payload.update(overrides)
    return payload


# ─────────────────────────────────────────────────────────────
# Insurance / claims (PRD §3.7)
# ─────────────────────────────────────────────────────────────


def claim_evidence_payload(
    *,
    evidence_url: str = "https://evidence.example.com/img-1",
    description: str = "Photo evidence",
) -> Dict[str, Any]:
    """POST /dsd/claims/{id}/evidence."""
    return {"evidence_url": evidence_url, "description": description}


def insurance_decision_payload(
    *, claim_id: str, decision: str, amount_cents: int
) -> Dict[str, Any]:
    """POST /dsd/_events/insurance-decision (inbound webhook)."""
    return {
        "claim_id": claim_id,
        "decision": decision,
        "amount_cents": amount_cents,
    }


# ─────────────────────────────────────────────────────────────
# Test-driving system endpoints (PRD §3.11)
# ─────────────────────────────────────────────────────────────


def advance_clock_payload(*, seconds: int) -> Dict[str, Any]:
    """POST /dsd/_clock/advance — shift logical clock by N seconds."""
    return {"seconds": seconds}


def settlement_sweep_payload(*, cycle_id: str) -> Dict[str, Any]:
    """POST /dsd/_sweep/settlement — process a settlement cycle."""
    return {"cycle_id": cycle_id}


def payment_received_payload(
    *, order_id: str, amount_cents: int
) -> Dict[str, Any]:
    """POST /dsd/_events/payment-received."""
    return {"order_id": order_id, "amount_cents": amount_cents}
