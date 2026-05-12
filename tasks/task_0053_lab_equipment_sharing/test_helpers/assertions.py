"""Entity assertions and domain invariant checkers.

Field names in these assertions mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (id + created_at + updated_at + version):
  Lab, User, Equipment, MaintenanceWindow, Authorization, Reservation.

- Append-only entities (id + created_at ONLY; NO updated_at, NO version):
  BillingRule, UsageLog, AuditEvent.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Enumerated state sets (PRD §3)
# ---------------------------------------------------------------------------
EQUIPMENT_STATES = {"AVAILABLE", "MAINTENANCE", "RETIRED"}
BILLING_RULE_STATES = {"DRAFT", "PUBLISHED", "SUPERSEDED"}
MAINTENANCE_STATES = {
    "SCHEDULED", "IN_PROGRESS", "AWAITING_ACCEPTANCE", "ACCEPTED", "REJECTED",
}
AUTHORIZATION_STATES = {
    "PENDING_OWNER", "PENDING_PLATFORM", "APPROVED",
    "REJECTED", "EXPIRED", "REVOKED",
}
RESERVATION_STATES = {
    "BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW",
}
AFFILIATIONS = {"WITHIN_SCHOOL", "INTER_SCHOOL", "EXTERNAL"}
SHARING_SCOPES = {"WITHIN_SCHOOL", "INTER_SCHOOL", "EXTERNAL"}
VALUE_TIERS = {"STANDARD", "HIGH_VALUE"}
SLOT_GRANULARITIES = {"HOUR", "HALF_DAY", "DAY"}
BILLING_MODES = {"BY_TIME", "BY_SAMPLE", "HYBRID"}
URGENCIES = {"NORMAL", "URGENT"}
MAINTENANCE_KINDS = {"PERIODIC", "AD_HOC"}
PRIORITY_TIERS = {"PEAK", "OFF_PEAK"}
STATUS_HANDOVERS = {"NORMAL", "ABNORMAL"}
AUDIT_SUBJECT_TYPES = {"RESERVATION", "AUTHORIZATION"}
AUDIT_ACTIONS = {
    "CREATE", "APPROVE", "REJECT", "CANCEL", "REVOKE",
    "CHECK_IN", "CHECK_OUT", "EXPIRE", "RESCHEDULE",
}


# ---------------------------------------------------------------------------
# Versioned-entity common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_versioned(data: Dict[str, Any]) -> None:
    """PRD §2.4: id (UUID, no prefix), created_at + updated_at (ISO 8601
    UTC with three fractional digits), version (monotonic int starting at 1).
    """
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int: {data.get('version')!r}"


def _assert_common_append_only(data: Dict[str, Any]) -> None:
    """PRD §2.4: append-only entities carry id + created_at ONLY."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Lab
# ---------------------------------------------------------------------------
def assert_lab(data: Dict[str, Any]) -> None:
    """PRD §3.1: Lab carries name, institution, department,
    contact_user_id, revenue_share_bps (0..10000),
    settlement_balance_cents (start 0), lifetime_settled_cents (start 0)."""
    _assert_common_versioned(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["institution"], str)
    assert isinstance(data["department"], str)
    assert isinstance(data["contact_user_id"], str)
    assert isinstance(data["revenue_share_bps"], int)
    assert 0 <= data["revenue_share_bps"] <= 10000, \
        f"revenue_share_bps must be in 0..10000: {data['revenue_share_bps']}"
    assert isinstance(data["settlement_balance_cents"], int)
    assert isinstance(data["lifetime_settled_cents"], int)
    assert data["lifetime_settled_cents"] >= 0


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
def assert_user(data: Dict[str, Any]) -> None:
    """PRD §3.1: User has external_user_id, full_name, department,
    affiliation, training_certificates list, identity_verified bool."""
    _assert_common_versioned(data)
    assert isinstance(data["external_user_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["department"], str)
    assert data["affiliation"] in AFFILIATIONS, \
        f"affiliation must be one of {AFFILIATIONS}: {data['affiliation']!r}"
    assert isinstance(data["training_certificates"], list)
    assert isinstance(data["identity_verified"], bool)


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------
def assert_equipment(data: Dict[str, Any]) -> None:
    """PRD §3.1: Equipment carries owner lab_id, model, specification,
    value_tier, sharing_scope, slot_granularity, lead_time_hours,
    single_user_duration_limit_hours, peak window bounds, certificates,
    status (AVAILABLE/MAINTENANCE/RETIRED), and active_billing_rule_id."""
    _assert_common_versioned(data)
    assert isinstance(data["lab_id"], str)
    assert isinstance(data["model"], str)
    assert isinstance(data["specification"], str)
    assert data["value_tier"] in VALUE_TIERS
    assert data["sharing_scope"] in SHARING_SCOPES
    assert data["slot_granularity"] in SLOT_GRANULARITIES
    assert isinstance(data["lead_time_hours"], int)
    assert data["lead_time_hours"] >= 0
    assert isinstance(data["single_user_duration_limit_hours"], int)
    assert data["single_user_duration_limit_hours"] >= 1
    assert isinstance(data["peak_window_start_hour"], int)
    assert 0 <= data["peak_window_start_hour"] <= 23
    assert isinstance(data["peak_window_end_hour"], int)
    assert 1 <= data["peak_window_end_hour"] <= 24
    assert data["status"] in EQUIPMENT_STATES
    assert isinstance(data["calibration_cert_id"], str)
    assert is_iso8601_timestamp(data["calibration_expires_at"])
    assert isinstance(data["safety_inspection_cert_id"], str)
    assert is_iso8601_timestamp(data["safety_inspection_expires_at"])
    assert isinstance(data["photo_uri"], str)
    assert isinstance(data["operation_manual_uri"], str)
    assert isinstance(data["required_training_codes"], list)
    assert isinstance(data["allowed_sample_types"], list)
    # active_billing_rule_id is null until the first PUBLISHED rule.
    assert (data.get("active_billing_rule_id") is None
            or isinstance(data["active_billing_rule_id"], str))


# ---------------------------------------------------------------------------
# BillingRule (append-only)
# ---------------------------------------------------------------------------
def assert_billing_rule(data: Dict[str, Any]) -> None:
    """PRD §3.5: BillingRule carries equipment_id, mode, six rate fields,
    peak_multiplier_bps, consumables_flat_cents, platform_fee_bps, status,
    published_at, and (post-publish) rule_version. PRD §2.4: BillingRule
    is append-only — id + created_at ONLY."""
    _assert_common_append_only(data)
    assert isinstance(data["equipment_id"], str)
    assert data["mode"] in BILLING_MODES
    for fld in (
        "internal_rate_per_hour_cents", "external_rate_per_hour_cents",
        "inter_school_rate_per_hour_cents",
        "internal_rate_per_sample_cents", "external_rate_per_sample_cents",
        "inter_school_rate_per_sample_cents",
        "consumables_flat_cents",
    ):
        assert isinstance(data[fld], int) and data[fld] >= 0, \
            f"{fld} must be a non-negative int: {data.get(fld)!r}"
    assert isinstance(data["peak_multiplier_bps"], int)
    assert isinstance(data["platform_fee_bps"], int)
    assert 0 <= data["platform_fee_bps"] <= 10000
    assert data["status"] in BILLING_RULE_STATES
    # PRD §3.5: 'The draft is created with status DRAFT and no assigned
    # rule_version'. Published rules carry a published_at timestamp.
    if data["status"] == "DRAFT":
        assert data.get("published_at") is None
    else:
        assert is_iso8601_timestamp(data["published_at"])
    # No updated_at / version on append-only.
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None


# ---------------------------------------------------------------------------
# MaintenanceWindow
# ---------------------------------------------------------------------------
def assert_maintenance_window(data: Dict[str, Any]) -> None:
    """PRD §3.7: MaintenanceWindow carries equipment_id, kind, start_at,
    end_at, status, maintenance_notes, acceptance_notes, archived_record_uri.
    """
    _assert_common_versioned(data)
    assert isinstance(data["equipment_id"], str)
    assert data["kind"] in MAINTENANCE_KINDS
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in MAINTENANCE_STATES


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def assert_authorization(data: Dict[str, Any]) -> None:
    """PRD §3.2: Authorization carries equipment_id, user_id, sample_type,
    urgency (NORMAL|URGENT), status (PENDING_OWNER|PENDING_PLATFORM|
    APPROVED|REJECTED|EXPIRED|REVOKED), approved_at, expires_at,
    owner_decision_user_id, platform_decision_user_id."""
    _assert_common_versioned(data)
    assert isinstance(data["equipment_id"], str)
    assert isinstance(data["user_id"], str)
    assert isinstance(data["sample_type"], str)
    assert data["urgency"] in URGENCIES
    assert data["status"] in AUTHORIZATION_STATES
    if data["status"] == "APPROVED":
        assert is_iso8601_timestamp(data["approved_at"])
        assert is_iso8601_timestamp(data["expires_at"])


# ---------------------------------------------------------------------------
# Reservation
# ---------------------------------------------------------------------------
def assert_reservation(data: Dict[str, Any]) -> None:
    """PRD §3.3: Reservation carries equipment_id, user_id, authorization_id,
    start_at, end_at, requested_sample_count, priority_tier (PEAK|OFF_PEAK),
    status (BOOKED|CHECKED_IN|COMPLETED|CANCELLED|NO_SHOW),
    billing_rule_id_pinned, estimated_fee_cents and partner fields,
    final_fee_cents and partner fields, cancellation_refund_bps."""
    _assert_common_versioned(data)
    assert isinstance(data["equipment_id"], str)
    assert isinstance(data["user_id"], str)
    assert isinstance(data["authorization_id"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["requested_sample_count"], int)
    assert data["requested_sample_count"] >= 0
    assert data["priority_tier"] in PRIORITY_TIERS
    assert data["status"] in RESERVATION_STATES
    for fld in (
        "estimated_fee_cents", "estimated_platform_fee_cents",
        "estimated_owner_share_cents",
        "final_fee_cents", "final_platform_fee_cents",
        "final_owner_share_cents",
        "cancellation_refund_bps",
    ):
        assert isinstance(data[fld], int), f"{fld} must be int: {data[fld]!r}"
        assert data[fld] >= 0, f"{fld} must be non-negative: {data[fld]}"


# ---------------------------------------------------------------------------
# UsageLog (append-only)
# ---------------------------------------------------------------------------
def assert_usage_log(data: Dict[str, Any]) -> None:
    """PRD §3.6: UsageLog has reservation_id, check_in_at, check_out_at,
    actual_duration_minutes, actual_sample_count, abnormal_event_code,
    status_handover. Append-only: no updated_at, no version."""
    _assert_common_append_only(data)
    assert isinstance(data["reservation_id"], str)
    assert is_iso8601_timestamp(data["check_in_at"])
    if data.get("check_out_at") is not None:
        assert is_iso8601_timestamp(data["check_out_at"])
    assert isinstance(data["actual_duration_minutes"], int)
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None


# ---------------------------------------------------------------------------
# AuditEvent (append-only)
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]) -> None:
    """PRD §2.8: AuditEvent carries subject_type (RESERVATION|AUTHORIZATION),
    subject_id, actor_role, actor_user_id, action verb, from_state, to_state,
    payload_json. Append-only entity (id + created_at only)."""
    _assert_common_append_only(data)
    assert data["subject_type"] in AUDIT_SUBJECT_TYPES
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_user_id"], str)
    assert data["action"] in AUDIT_ACTIONS, \
        f"action must be one of {AUDIT_ACTIONS}: {data['action']!r}"
    assert isinstance(data["to_state"], str)


# ---------------------------------------------------------------------------
# Helper search over a list of audit-events responses
# ---------------------------------------------------------------------------
def find_audit_events(events: List[Dict[str, Any]],
                      *, subject_type: Optional[str] = None,
                      subject_id: Optional[str] = None,
                      action: Optional[str] = None,
                      from_state: Optional[str] = None,
                      to_state: Optional[str] = None,
                      ) -> List[Dict[str, Any]]:
    out = []
    for ev in events:
        if subject_type is not None and ev.get("subject_type") != subject_type:
            continue
        if subject_id is not None and ev.get("subject_id") != subject_id:
            continue
        if action is not None and ev.get("action") != action:
            continue
        if from_state is not None and ev.get("from_state") != from_state:
            continue
        if to_state is not None and ev.get("to_state") != to_state:
            continue
        out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_lab_balance_invariants(lab: Dict[str, Any]) -> None:
    """Settlement balance and lifetime totals must be integers, lifetime
    monotone non-decreasing (caller ensures progression)."""
    assert isinstance(lab["settlement_balance_cents"], int)
    assert isinstance(lab["lifetime_settled_cents"], int)
    assert lab["lifetime_settled_cents"] >= 0


def assert_reservation_fee_consistency(reservation: Dict[str, Any]) -> None:
    """Sanity: when a reservation is BOOKED/CHECKED_IN, final fields are
    zero; once COMPLETED they reflect the chronological calculation."""
    if reservation["status"] in {"BOOKED", "CHECKED_IN"}:
        assert reservation["final_fee_cents"] == 0
        assert reservation["final_owner_share_cents"] == 0
        assert reservation["final_platform_fee_cents"] == 0


__all__ = [
    "EQUIPMENT_STATES", "BILLING_RULE_STATES", "MAINTENANCE_STATES",
    "AUTHORIZATION_STATES", "RESERVATION_STATES",
    "AFFILIATIONS", "SHARING_SCOPES", "VALUE_TIERS", "SLOT_GRANULARITIES",
    "BILLING_MODES", "URGENCIES", "MAINTENANCE_KINDS", "PRIORITY_TIERS",
    "STATUS_HANDOVERS", "AUDIT_SUBJECT_TYPES", "AUDIT_ACTIONS",
    "assert_lab", "assert_user", "assert_equipment",
    "assert_billing_rule", "assert_maintenance_window",
    "assert_authorization", "assert_reservation",
    "assert_usage_log", "assert_audit_event",
    "find_audit_events",
    "assert_lab_balance_invariants",
    "assert_reservation_fee_consistency",
]
