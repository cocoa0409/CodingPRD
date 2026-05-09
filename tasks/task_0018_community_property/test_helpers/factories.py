"""Payload factories — one per entity, input fields only.

Each factory emits the exact payload schema specified in PRD §3 / §4 for the
corresponding endpoint. Required fields are present by default; optional
fields (PRD-marked "optional" or carrying a default) are omitted unless the
caller passes them as overrides.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _unique_suffix() -> str:
    """Short random suffix to keep uniqueness-constrained fields independent across tests."""
    return uuid.uuid4().hex[:10]


def iso_utc(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits, per PRD §2.4."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{s}{millis}Z"


def iso_utc_offset_seconds(seconds: int, base: Optional[datetime] = None) -> str:
    """Return an ISO 8601 UTC string offset by *seconds* from *base* (default: now)."""
    if base is None:
        base = datetime.now(timezone.utc)
    return iso_utc(base + timedelta(seconds=seconds))


# ──────────────────────────────────────────────────────────
# Owner
# ──────────────────────────────────────────────────────────

def create_owner_payload(**overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/owners (PRD §3.1).

    Required: full_name, id_card_no (unique), household_register_no, phone.
    """
    suffix = _unique_suffix()
    defaults: Dict[str, Any] = {
        "full_name": "Owner Name",
        "id_card_no": f"ID-{suffix}",
        "household_register_no": f"HR-{suffix}",
        "phone": f"+1555{suffix[:7]}",
    }
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Property
# ──────────────────────────────────────────────────────────

def create_property_payload(owner_id: str, **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/properties (PRD §3.1).

    Required: building_no, unit_no, area_sqm, owner_id.
    Optional: parking_quota (defaults to 1 per PRD §3.1 if omitted).
    """
    suffix = _unique_suffix()
    defaults: Dict[str, Any] = {
        "building_no": f"B-{suffix[:4]}",
        "unit_no": f"U-{suffix[4:8]}",
        "area_sqm": 80.00,
        "owner_id": owner_id,
    }
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Resident
# ──────────────────────────────────────────────────────────

def create_resident_payload(
    property_id: str,
    relation_kind: str = "FAMILY",
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/residents (PRD §3.1).

    Required: property_id, full_name, id_card_no, relation_kind, phone.
    For TENANT: lease_end_at is required; for FAMILY it is ignored.
    """
    suffix = _unique_suffix()
    defaults: Dict[str, Any] = {
        "property_id": property_id,
        "full_name": "Resident Name",
        "id_card_no": f"RID-{suffix}",
        "relation_kind": relation_kind,
        "phone": f"+1666{suffix[:7]}",
    }
    if relation_kind == "TENANT" and "lease_end_at" not in overrides:
        # PRD §3.1: lease_end_at must be strictly later than now() for tenant move-in.
        defaults["lease_end_at"] = iso_utc(datetime.now(timezone.utc) + timedelta(days=365))
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Work Order
# ──────────────────────────────────────────────────────────

def create_work_order_payload(
    property_id: str,
    category: str = "PLUMBING",
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/work-orders (PRD §3.2).

    Required: property_id, category, location_tag.
    Optional: photo_urls (defaults to []).
    """
    defaults: Dict[str, Any] = {
        "property_id": property_id,
        "category": category,
        "location_tag": "kitchen sink",
    }
    defaults.update(overrides)
    return defaults


def dispatch_work_order_payload(assigned_staff_id: str, **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/work-orders/{id}/dispatch (PRD §3.2).

    Required: assigned_staff_id (the opaque MaintenanceStaff id who will receive
    the work — PRD §3.2 says this id is then enforced on subsequent transitions).
    """
    defaults: Dict[str, Any] = {"assigned_staff_id": assigned_staff_id}
    defaults.update(overrides)
    return defaults


def reject_work_order_payload(**overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/work-orders/{id}/reject (PRD §3.2).

    Required: rejection_reason.
    """
    defaults: Dict[str, Any] = {"rejection_reason": "out of scope"}
    defaults.update(overrides)
    return defaults


def confirm_work_order_payload(satisfaction_score: int = 5, **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/work-orders/{id}/confirm (PRD §3.2).

    Required: satisfaction_score (1..5 inclusive).
    """
    defaults: Dict[str, Any] = {"satisfaction_score": satisfaction_score}
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Fee billing rule
# ──────────────────────────────────────────────────────────

def create_fee_billing_rule_payload(
    kind: str = "PER_SQM_MONTHLY",
    rate: float = 2.50,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/fee-billing-rules (PRD §3.3).

    Required: rule_code (unique among ACTIVE), kind, rate (>= 0).
    Optional: late_fee_daily_rate (defaults to 0.0005), late_fee_cap_pct (defaults to 0.30).
    """
    defaults: Dict[str, Any] = {
        "rule_code": f"RC-{_unique_suffix()}",
        "kind": kind,
        "rate": rate,
    }
    defaults.update(overrides)
    return defaults


def patch_fee_billing_rule_payload(**overrides: Any) -> Dict[str, Any]:
    """Input fields for PATCH /communities/fee-billing-rules/{id} (PRD §3.3).

    All fields optional: rate, late_fee_daily_rate, late_fee_cap_pct, version.
    """
    return dict(overrides)


# ──────────────────────────────────────────────────────────
# Fee bills
# ──────────────────────────────────────────────────────────

def issue_fee_bills_payload(period_year: int, period_month: int, **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/fee-bills/issue (PRD §3.3).

    Required: period_year, period_month.
    """
    defaults: Dict[str, Any] = {"period_year": period_year, "period_month": period_month}
    defaults.update(overrides)
    return defaults


def waive_fee_bill_payload(reason: str = "hardship", **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/fee-bills/{id}/waive (PRD §3.5).

    Required: reason.
    """
    defaults: Dict[str, Any] = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Payment
# ──────────────────────────────────────────────────────────

def create_payment_payload(
    bill_id: str,
    amount: float,
    channel: str = "WECHAT",
    external_txn_id: Optional[str] = None,
    paid_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/payments (PRD §3.6).

    Required: bill_id, channel, external_txn_id (idempotency key per channel),
    amount (> 0), paid_at (timestamp from upstream provider).
    """
    defaults: Dict[str, Any] = {
        "bill_id": bill_id,
        "channel": channel,
        "external_txn_id": external_txn_id or f"tx-{_unique_suffix()}",
        "amount": amount,
        "paid_at": paid_at or iso_utc(datetime.now(timezone.utc)),
    }
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Facility
# ──────────────────────────────────────────────────────────

def create_facility_payload(
    facility_type: str = "MEETING_ROOM",
    slot_minutes: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/facilities (PRD §3.7).

    Required: facility_type, name (unique), slot_minutes (one of 30/60/120/180/240).
    Optional: capacity_per_slot (default 1), cancellation_window_hours (default 24),
    damage_deposit (default 0).
    """
    defaults: Dict[str, Any] = {
        "facility_type": facility_type,
        "name": f"Facility-{_unique_suffix()}",
        "slot_minutes": slot_minutes,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(
    facility_id: str,
    slot_start_at: str,
    slot_end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/reservations (PRD §3.7).

    Required: facility_id, slot_start_at, slot_end_at.
    """
    defaults: Dict[str, Any] = {
        "facility_id": facility_id,
        "slot_start_at": slot_start_at,
        "slot_end_at": slot_end_at,
    }
    defaults.update(overrides)
    return defaults


def close_reservation_payload(damage_amount: float = 0.0, **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/reservations/{id}/close (PRD §3.7).

    Optional: damage_amount (omitted or 0 → COMPLETED; > 0 → DAMAGED).
    """
    defaults: Dict[str, Any] = {"damage_amount": damage_amount}
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Proposal & Vote
# ──────────────────────────────────────────────────────────

def create_proposal_payload(
    voting_method: str = "PER_HOUSEHOLD",
    voting_starts_at: Optional[str] = None,
    voting_ends_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/proposals (PRD §3.8).

    Required: title, voting_method, voting_starts_at, voting_ends_at.
    Optional: pass_threshold_pct (defaults to 0.6667).
    """
    now = datetime.now(timezone.utc)
    defaults: Dict[str, Any] = {
        "title": f"Proposal {_unique_suffix()}",
        "voting_method": voting_method,
        "voting_starts_at": voting_starts_at or iso_utc(now - timedelta(seconds=10)),
        "voting_ends_at": voting_ends_at or iso_utc(now + timedelta(days=7)),
    }
    defaults.update(overrides)
    return defaults


def cast_vote_payload(property_id: str, choice: str = "YES", **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/proposals/{id}/votes (PRD §3.8).

    Required: property_id, choice (YES | NO | ABSTAIN).
    """
    defaults: Dict[str, Any] = {"property_id": property_id, "choice": choice}
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Parking
# ──────────────────────────────────────────────────────────

def create_parking_space_payload(
    kind: str = "FIXED",
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/parking-spaces (PRD §3.9).

    Required: space_no (unique), kind.
    Optional: monthly_fee (defaults 0; meaningful only for FIXED).
    """
    defaults: Dict[str, Any] = {
        "space_no": f"S-{_unique_suffix()[:6]}",
        "kind": kind,
    }
    defaults.update(overrides)
    return defaults


def create_parking_application_payload(
    property_id: str,
    requested_kind: str = "FIXED",
    license_plate: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/parking-applications (PRD §3.9).

    Required: property_id, requested_kind, license_plate.
    """
    defaults: Dict[str, Any] = {
        "property_id": property_id,
        "requested_kind": requested_kind,
        "license_plate": license_plate or f"PLATE{_unique_suffix()[:5].upper()}",
    }
    defaults.update(overrides)
    return defaults


def approve_parking_application_payload(allocated_space_id: str, **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/parking-applications/{id}/approve (PRD §3.9).

    Required: allocated_space_id.
    """
    defaults: Dict[str, Any] = {"allocated_space_id": allocated_space_id}
    defaults.update(overrides)
    return defaults


def reject_parking_application_payload(**overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /communities/parking-applications/{id}/reject (PRD §3.9).

    Required: rejection_reason.
    """
    defaults: Dict[str, Any] = {"rejection_reason": "no quota"}
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Access logs
# ──────────────────────────────────────────────────────────

def create_access_log_payload(
    license_plate: str,
    direction: str = "ENTRY",
    occurred_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /communities/access-logs (PRD §3.9).

    Required: license_plate, direction, occurred_at.
    """
    defaults: Dict[str, Any] = {
        "license_plate": license_plate,
        "direction": direction,
        "occurred_at": occurred_at or iso_utc(datetime.now(timezone.utc)),
    }
    defaults.update(overrides)
    return defaults
