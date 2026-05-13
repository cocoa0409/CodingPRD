"""Live Stream Schedule — payload factories (one per entity, input fields only).

Field names match PRD §3 verbatim. Defaults are chosen so each factory yields a
PRD-valid payload out of the box; callers override only the fields a particular
test cares about.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with milliseconds — PRD §2.4 format."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Force UTC, strip microseconds beyond milliseconds
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Streamer
# ---------------------------------------------------------------------------


def create_streamer_payload(**overrides) -> Dict[str, Any]:
    """Per PRD §3.1: admin supplies legal_name, id_card_number, real_name_verified,
    health_cert_expires_at, professional_cert_categories, content_category_tags.
    """
    # Default: health cert expires well in the future so it never invalidates submit
    far_future = datetime(2030, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
    defaults: Dict[str, Any] = {
        "legal_name": "Test Streamer",
        "id_card_number": _unique("ID"),
        "real_name_verified": True,
        "health_cert_expires_at": iso(far_future),
        "professional_cert_categories": ["FOOD", "FASHION"],
        "content_category_tags": ["FOOD", "FASHION"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Studio
# ---------------------------------------------------------------------------


def create_studio_payload(**overrides) -> Dict[str, Any]:
    """Per PRD §3.2: admin supplies name, location, equipment_inventory, capacity,
    studio_type, slot_tier, base_hour_price_cents.
    """
    defaults: Dict[str, Any] = {
        "name": "Test Studio",
        "location": "BJ-CBD",
        "equipment_inventory": ["camera", "lighting", "audio", "teleprompter"],
        "capacity": 4,
        "studio_type": "SELF_OPERATED",
        "slot_tier": "A",
        "base_hour_price_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_time_slot_payload(**overrides) -> Dict[str, Any]:
    """Per PRD §3.2: per-studio AVAILABLE / MAINTENANCE window."""
    now = datetime.now(timezone.utc)
    defaults: Dict[str, Any] = {
        "kind": "AVAILABLE",
        "starts_at": iso(now),
        "ends_at": iso(now + timedelta(days=365)),
        "weekday_mask": 0,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------


def create_product_payload(**overrides) -> Dict[str, Any]:
    """Per PRD §3.3: admin supplies name, category, requires_professional_cert,
    unit_price_cents, available_stock.
    """
    defaults: Dict[str, Any] = {
        "name": "Test Product",
        "category": "FOOD",
        "requires_professional_cert": False,
        "unit_price_cents": 5_000,
        "available_stock": 100,
    }
    defaults.update(overrides)
    return defaults


def update_product_payload(**overrides) -> Dict[str, Any]:
    """Per PRD §3.3: admin moves stock / listing via PATCH with optional version."""
    return dict(overrides)


def update_studio_payload(**overrides) -> Dict[str, Any]:
    return dict(overrides)


# ---------------------------------------------------------------------------
# ScheduleApplication
# ---------------------------------------------------------------------------


def create_application_payload(
    streamer_id: str,
    studio_id: str,
    starts_at: datetime,
    ends_at: datetime,
    **overrides,
) -> Dict[str, Any]:
    """Per PRD §3.4: streamer supplies streamer_id, studio_id, starts_at, ends_at,
    declared_content_categories, declared_product_categories, package_code.
    """
    defaults: Dict[str, Any] = {
        "streamer_id": streamer_id,
        "studio_id": studio_id,
        "starts_at": iso(starts_at),
        "ends_at": iso(ends_at),
        "declared_content_categories": ["FOOD"],
        "declared_product_categories": ["FOOD"],
        "package_code": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ProductAssociation
# ---------------------------------------------------------------------------


def associate_product_payload(product_id: str, reserved_quantity: int = 1, **overrides) -> Dict[str, Any]:
    """Per PRD §3.3: streamer supplies product_id and reserved_quantity (>=1)."""
    defaults: Dict[str, Any] = {
        "product_id": product_id,
        "reserved_quantity": reserved_quantity,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Review decisions
# ---------------------------------------------------------------------------


def approve_decision_payload(decision: str = "APPROVE", reason: Optional[str] = None,
                              version: Optional[int] = None) -> Dict[str, Any]:
    """Per PRD §3.4: ops-approve / compliance-approve accept decision and optional reason
    (required on REJECT). Compliance-approve also accepts an optional version for OCC.
    """
    body: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        body["reason"] = reason
    if version is not None:
        body["version"] = version
    return body


def cancel_payload(reason: str = "schedule change") -> Dict[str, Any]:
    """Per PRD §3.7: cancel requires non-empty reason."""
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Violation, appeal
# ---------------------------------------------------------------------------


def create_violation_payload(
    streamer_id: str,
    violation_type: str = "FALSE_ADVERTISING",
    evidence_refs: Optional[List[str]] = None,
    application_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Per PRD §3.9: reviewer supplies streamer_id, optional application_id,
    violation_type, evidence_refs.
    """
    if evidence_refs is None:
        evidence_refs = ["evi-a", "evi-b"]
    payload: Dict[str, Any] = {
        "streamer_id": streamer_id,
        "violation_type": violation_type,
        "evidence_refs": evidence_refs,
    }
    if application_id is not None:
        payload["application_id"] = application_id
    payload.update(overrides)
    return payload


def file_appeal_payload(argument: str = "I dispute the violation finding.") -> Dict[str, Any]:
    """Per PRD §3.9: appeal carries argument."""
    return {"argument": argument}


def decide_appeal_payload(decision: str = "OVERTURN") -> Dict[str, Any]:
    """Per PRD §3.9: compliance decides via OVERTURN or UPHOLD."""
    return {"decision": decision}


# ---------------------------------------------------------------------------
# External events / clock advance
# ---------------------------------------------------------------------------


def emit_event_payload(
    source: str,
    kind: str,
    occurred_at: datetime,
    application_id: Optional[str] = None,
    streamer_id: Optional[str] = None,
    amount_cents: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """Per PRD §3.10: events carry source, kind, optional ids, optional amount, occurred_at."""
    payload: Dict[str, Any] = {
        "source": source,
        "kind": kind,
        "occurred_at": iso(occurred_at),
    }
    if application_id is not None:
        payload["application_id"] = application_id
    if streamer_id is not None:
        payload["streamer_id"] = streamer_id
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    payload.update(overrides)
    return payload


def advance_clock_payload(to: datetime) -> Dict[str, Any]:
    """Per PRD §2.5: advance the simulated clock to a supplied `to` ISO 8601 timestamp."""
    return {"to": iso(to)}
