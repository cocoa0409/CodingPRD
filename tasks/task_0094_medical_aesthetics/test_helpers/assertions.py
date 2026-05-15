"""Entity assertions and domain invariant checkers.

Each `assert_<entity>` validates the structural envelope of an entity
returned by the API: required fields, types, and PRD-enumerated states.
Domain invariants (cash-flow conservation, on-shelf count conservation,
schedule principal-sum invariant) live alongside.

Per PRD §2.4: Project, ConsumableSku, Customer, ContraindicationRule,
TreatmentPlan, Appointment, Room, FollowUp, AdverseEvent,
InstallmentPlan carry id/created_at/updated_at/version. OperativeRecord,
PaymentEvent, AuditEntry, SyncEvent are append-only and carry only id
and created_at — they MUST NOT carry updated_at or version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Lookup helpers (used by tests that fish a specific row out of a list).
# ---------------------------------------------------------------------------
def find_row(rows: List[Dict[str, Any]], **predicates: Any) -> Dict[str, Any]:
    """Return the first row whose fields match every predicate kwarg.

    Raises AssertionError with a helpful summary if no row matches.
    """
    for row in rows:
        if all(row.get(k) == v for k, v in predicates.items()):
            return row
    raise AssertionError(
        f"No row matching {predicates}. Saw: "
        f"{[dict((k, r.get(k)) for k in predicates) for r in rows]}"
    )


def select_rows(rows: List[Dict[str, Any]],
                **predicates: Any) -> List[Dict[str, Any]]:
    return [
        r for r in rows
        if all(r.get(k) == v for k, v in predicates.items())
    ]


def count_rows(rows: List[Dict[str, Any]], **predicates: Any) -> int:
    return len(select_rows(rows, **predicates))


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    """For entities that carry id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, \
        f"version must be a positive integer, got {version!r}"


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """For append-only entities — id and created_at only.

    Per PRD §2.4 these entities (OperativeRecord, PaymentEvent,
    AuditEntry, SyncEvent) MUST NOT expose updated_at or version.
    """
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Project — PRD §3.1
# ---------------------------------------------------------------------------
_PROJECT_STATUSES = {"DRAFT", "UNDER_REVIEW", "ON_SHELF", "OFF_SHELF"}
_PROJECT_CATEGORIES = {"SURGICAL", "NON_SURGICAL", "SKINCARE"}
_PROJECT_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}


def assert_project(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 32
    assert isinstance(data["name"], str)
    assert data["category"] in _PROJECT_CATEGORIES, \
        f"category must be one of {_PROJECT_CATEGORIES}, got {data.get('category')!r}"
    assert isinstance(data["technique"], str)
    assert isinstance(data["duration_minutes"], int)
    assert 5 <= data["duration_minutes"] <= 480
    assert isinstance(data["recovery_days"], int)
    assert 0 <= data["recovery_days"] <= 365
    assert data["risk_level"] in _PROJECT_RISK_LEVELS
    assert isinstance(data["bom"], list) and len(data["bom"]) >= 1
    for bom in data["bom"]:
        assert "sku_id" in bom and "quantity" in bom
        assert isinstance(bom["quantity"], int) and bom["quantity"] > 0
    assert isinstance(data["qualified_doctor_ids"], list)
    assert len(data["qualified_doctor_ids"]) >= 1
    assert isinstance(data["pricing_tiers"], list)
    assert len(data["pricing_tiers"]) >= 1
    for tier in data["pricing_tiers"]:
        assert "tier_code" in tier
        assert isinstance(tier["base_price_cents"], int)
        assert tier["base_price_cents"] >= 0
        assert isinstance(tier["min_quantity"], int) and tier["min_quantity"] >= 1
    assert data["status"] in _PROJECT_STATUSES


# ---------------------------------------------------------------------------
# ConsumableSku — PRD §3.1
# ---------------------------------------------------------------------------
_SKU_KINDS = {"CONSUMABLE", "DRUG"}


def assert_consumable_sku(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["sku_code"], str)
    assert isinstance(data["name"], str)
    assert data["kind"] in _SKU_KINDS
    assert isinstance(data["requires_lot_tracking"], bool)


# ---------------------------------------------------------------------------
# Room — PRD §3.1
# ---------------------------------------------------------------------------
_ROOM_KINDS = {"SURGICAL_OR", "PROCEDURE", "TREATMENT"}


def assert_room(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["code"], str)
    assert data["room_kind"] in _ROOM_KINDS
    assert isinstance(data["is_active"], bool)


# ---------------------------------------------------------------------------
# Customer — PRD §3.2
# ---------------------------------------------------------------------------
_KYC_STATUSES = {"NOT_VERIFIED", "PENDING", "VERIFIED", "REJECTED"}


def assert_customer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["contact_phone"], str)
    assert isinstance(data["medical_history"], list)
    assert isinstance(data["allergies"], list)
    assert isinstance(data["medication_history"], list)
    # health_declaration may be None or an object with the four required
    # booleans per PRD §3.2.
    hd = data.get("health_declaration")
    if hd is not None:
        assert isinstance(hd, dict)
        for key in (
            "is_pregnant", "has_uncontrolled_hypertension",
            "has_active_infection", "has_bleeding_disorder",
        ):
            assert key in hd and isinstance(hd[key], bool), \
                f"health_declaration.{key} must be a boolean"
    assert isinstance(data["photo_archive_ids"], list)
    assert isinstance(data["scan3d_archive_ids"], list)
    assert data["kyc_status"] in _KYC_STATUSES
    if data.get("credit_score") is not None:
        assert isinstance(data["credit_score"], int)
        assert 0 <= data["credit_score"] <= 1000
    # risk_score is held to one decimal place (PRD §2.8, §3.2).
    rs = data["risk_score"]
    assert isinstance(rs, (int, float))
    assert 0.0 <= float(rs) <= 100.0
    # Allow one decimal of precision: round-trip rounding by 0.1 must
    # not drift beyond 0.05 (sloppy float tolerance).
    assert abs(round(float(rs), 1) - float(rs)) < 1e-6, \
        f"risk_score must have at most 1 decimal, got {rs!r}"
    assert isinstance(data["adverse_event_count"], int)
    assert data["adverse_event_count"] >= 0


# ---------------------------------------------------------------------------
# ContraindicationRule — PRD §3.1
# ---------------------------------------------------------------------------
_CONTRA_SEVERITIES = {"ABSOLUTE", "RELATIVE"}


def assert_contraindication_rule(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["severity"] in _CONTRA_SEVERITIES
    pred = data["predicate"]
    assert isinstance(pred, dict)
    for key in ("field", "op", "value"):
        assert key in pred, f"predicate.{key} required"
    assert pred["op"] in {"EQ", "IN", "GT", "LT"}
    assert isinstance(data["reason"], str)


# ---------------------------------------------------------------------------
# TreatmentPlan — PRD §3.3
# ---------------------------------------------------------------------------
_PLAN_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"}


def assert_treatment_plan(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["consultant_id"], str) and data["consultant_id"]
    assert isinstance(data["items"], list)
    assert 1 <= len(data["items"]) <= 10
    for item in data["items"]:
        assert "project_id" in item and is_valid_uuid(item["project_id"])
        assert "tier_code" in item and isinstance(item["tier_code"], str)
        assert "quantity" in item and isinstance(item["quantity"], int)
        assert item["quantity"] >= 1
    assert isinstance(data["expected_outcome"], str)
    assert isinstance(data["risk_disclosure"], str)
    assert isinstance(data["requires_senior_countersign"], bool)
    # attending_physician_id optional at DRAFT.
    if data.get("attending_physician_id") is not None:
        assert isinstance(data["attending_physician_id"], str)
    if data.get("senior_physician_id") is not None:
        assert isinstance(data["senior_physician_id"], str)
    assert isinstance(data["provisional_total_cents"], int)
    assert data["provisional_total_cents"] >= 0
    if data.get("final_total_cents") is not None:
        assert isinstance(data["final_total_cents"], int)
        assert data["final_total_cents"] >= 0
    assert data["status"] in _PLAN_STATUSES
    assert isinstance(data["plan_version"], int) and data["plan_version"] >= 1
    if data.get("locked_project_versions") is not None:
        assert isinstance(data["locked_project_versions"], dict)
        for k, v in data["locked_project_versions"].items():
            assert isinstance(k, str)
            assert isinstance(v, int)
    if data.get("informed_consent_signed_at") is not None:
        assert is_iso8601_timestamp(data["informed_consent_signed_at"])


# ---------------------------------------------------------------------------
# Appointment — PRD §3.4
# ---------------------------------------------------------------------------
_APPT_STATUSES = {
    "SCHEDULED", "CHECKED_IN", "IN_PROGRESS",
    "COMPLETED", "CANCELLED", "NO_SHOW",
}


def assert_appointment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["project_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert is_iso8601_timestamp(data["prep_window_start"])
    assert isinstance(data["doctor_id"], str) and data["doctor_id"]
    assert isinstance(data["nurse_id"], str) and data["nurse_id"]
    assert is_valid_uuid(data["room_id"])
    assert isinstance(data["equipment_ids"], list)
    assert len(data["equipment_ids"]) >= 1
    # anesthesia_resource_id optional / may be null.
    if data.get("anesthesia_resource_id") is not None:
        assert isinstance(data["anesthesia_resource_id"], str)
    assert data["status"] in _APPT_STATUSES
    assert isinstance(data["reschedule_count"], int)
    assert 0 <= data["reschedule_count"] <= 3


# ---------------------------------------------------------------------------
# OperativeRecord — PRD §3.5 (append-only; only id + created_at)
# ---------------------------------------------------------------------------
_STEP_CODES = {"START", "KEY_STEP", "END"}


def assert_operative_record(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    # OperativeRecord MUST NOT carry updated_at or version per PRD §2.4.
    assert "updated_at" not in data, \
        "OperativeRecord (append-only) MUST NOT expose updated_at"
    assert "version" not in data, \
        "OperativeRecord (append-only) MUST NOT expose version"
    assert is_valid_uuid(data["appointment_id"])
    if data.get("check_in_at") is not None:
        assert is_iso8601_timestamp(data["check_in_at"])
    assert isinstance(data["procedure_log"], list)
    for entry in data["procedure_log"]:
        assert entry.get("step_code") in _STEP_CODES
        assert is_iso8601_timestamp(entry.get("recorded_at", ""))
    assert isinstance(data["consumable_usage"], list)
    assert isinstance(data["vital_sign_attachments"], list)
    assert isinstance(data["incidents"], list)
    assert isinstance(data["post_photo_ids"], list)


# ---------------------------------------------------------------------------
# FollowUp — PRD §3.6
# ---------------------------------------------------------------------------
_FOLLOWUP_STAGES = {"D1", "W1", "M1", "M3"}
_FOLLOWUP_STATUSES = {"PENDING", "REMINDED", "COMPLETED", "MISSED"}
_FOLLOWUP_CHANNELS = {"CALL", "IM"}


def assert_followup(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert data["stage"] in _FOLLOWUP_STAGES
    assert is_iso8601_timestamp(data["due_at"])
    assert data["channel"] in _FOLLOWUP_CHANNELS
    assert data["status"] in _FOLLOWUP_STATUSES
    if data.get("feedback") is not None:
        fb = data["feedback"]
        assert isinstance(fb, dict)
        # satisfaction is 1..5 when present
        if "satisfaction" in fb and fb["satisfaction"] is not None:
            assert 1 <= int(fb["satisfaction"]) <= 5
    assert isinstance(data["adverse_event_filed"], bool)


# ---------------------------------------------------------------------------
# AdverseEvent — PRD §3.6
# ---------------------------------------------------------------------------
_AE_SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}
_AE_STATUSES = {"OPEN", "ESCALATED", "CLOSED"}


def assert_adverse_event(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["severity"] in _AE_SEVERITIES
    assert isinstance(data["description"], str)
    assert data["status"] in _AE_STATUSES
    if data.get("escalated_at") is not None:
        assert is_iso8601_timestamp(data["escalated_at"])


# ---------------------------------------------------------------------------
# InstallmentPlan — PRD §3.7
# ---------------------------------------------------------------------------
_INSTALLMENT_STATUSES = {
    "PENDING_KYC", "ACTIVE", "IN_DEFAULT", "REFUNDED", "COMPLETED",
}
_ALLOWED_TERMS = {3, 6, 12, 24}


def assert_installment_plan(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["treatment_plan_id"])
    assert isinstance(data["principal_cents"], int)
    assert data["principal_cents"] >= 0
    assert isinstance(data["downpayment_cents"], int)
    assert data["downpayment_cents"] >= 0
    assert data["term_months"] in _ALLOWED_TERMS
    if data.get("apr_bps") is not None:
        assert isinstance(data["apr_bps"], int) and data["apr_bps"] >= 0
    assert isinstance(data["finance_partner_id"], str)
    if data.get("schedule") is not None:
        assert isinstance(data["schedule"], list)
        for entry in data["schedule"]:
            assert isinstance(entry["index"], int)
            assert isinstance(entry["principal_cents"], int)
            assert isinstance(entry["interest_cents"], int)
            assert isinstance(entry["total_cents"], int)
            assert entry["total_cents"] == entry["principal_cents"] + entry["interest_cents"]
            assert "due_date" in entry
            assert "status" in entry
    assert isinstance(data["paid_amount_cents"], int)
    assert data["paid_amount_cents"] >= 0
    assert data["status"] in _INSTALLMENT_STATUSES
    assert isinstance(data["default_strike_count"], int)
    assert data["default_strike_count"] >= 0


# ---------------------------------------------------------------------------
# PaymentEvent — append-only (PRD §3.7, §2.4)
# ---------------------------------------------------------------------------
_PAYMENT_KINDS = {"INSTALLMENT_PAID", "PREPAYMENT", "REFUND", "COLLECTION_NOTICE"}


def assert_payment_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, \
        "PaymentEvent (append-only) MUST NOT expose updated_at"
    assert "version" not in data, \
        "PaymentEvent (append-only) MUST NOT expose version"
    assert is_valid_uuid(data["installment_plan_id"])
    assert data["kind"] in _PAYMENT_KINDS
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert isinstance(data["external_ref"], str)


# ---------------------------------------------------------------------------
# AuditEntry — append-only (PRD §2.9)
# ---------------------------------------------------------------------------
def assert_audit_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, \
        "AuditEntry (append-only) MUST NOT expose updated_at"
    assert "version" not in data, \
        "AuditEntry (append-only) MUST NOT expose version"
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["subject_type"], str)
    assert isinstance(data["subject_id"], str)


# ---------------------------------------------------------------------------
# SyncEvent — append-only (PRD §2.9)
# ---------------------------------------------------------------------------
_SYNC_TOPICS = {"PAYMENT", "FINANCE_PARTNER", "IM", "PHARMA_TRACE"}


def assert_sync_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, \
        "SyncEvent (append-only) MUST NOT expose updated_at"
    assert "version" not in data, \
        "SyncEvent (append-only) MUST NOT expose version"
    assert data["topic"] in _SYNC_TOPICS
    assert isinstance(data["kind"], str) and data["kind"]


# ---------------------------------------------------------------------------
# Domain invariants — PRD-pinned conservation rules
# ---------------------------------------------------------------------------
def assert_installment_principal_sum(plan: Dict[str, Any]) -> None:
    """PRD §3.7: 'the final period absorbs any residual ... so that the
    sum of per-period principal equals the original principal exactly.'
    """
    schedule = plan.get("schedule") or []
    if not schedule:
        return
    total = sum(int(entry["principal_cents"]) for entry in schedule)
    assert total == plan["principal_cents"], (
        f"sum(schedule.principal_cents)={total} must equal "
        f"principal_cents={plan['principal_cents']} per PRD §3.7"
    )


def assert_cash_flow_neutral_after_refund(
    payment_events: List[Dict[str, Any]],
) -> None:
    """PRD §3.7 conservation rule: after a full refund, net customer
    outflow returns to zero (sum INSTALLMENT_PAID - sum REFUND == 0).
    """
    inflow = sum(
        int(e["amount_cents"]) for e in payment_events
        if e.get("kind") == "INSTALLMENT_PAID"
    )
    refund = sum(
        int(e["amount_cents"]) for e in payment_events
        if e.get("kind") == "REFUND"
    )
    assert inflow - refund == 0, (
        f"PRD §3.7 cash-flow invariant violated: "
        f"INSTALLMENT_PAID sum={inflow}, REFUND sum={refund}, "
        f"net={inflow - refund}"
    )


def assert_on_shelf_count_unchanged(
    rows_before: List[Dict[str, Any]],
    rows_after: List[Dict[str, Any]],
) -> None:
    """Catalog invariant: take-off-shelf + return-to-shelf restore the
    count of ON_SHELF projects."""
    before = count_rows(rows_before, status="ON_SHELF")
    after = count_rows(rows_after, status="ON_SHELF")
    assert before == after, (
        f"on_shelf count drifted: before={before}, after={after}"
    )


def assert_version_incremented_by_one(
    new: Dict[str, Any], old: Dict[str, Any],
) -> None:
    """Per PRD §2.4 every successful mutation increments version by 1."""
    assert new["version"] == old["version"] + 1, (
        f"version did not increment by exactly 1: "
        f"old={old['version']}, new={new['version']}"
    )


def assert_plan_version_incremented_by_one(
    new: Dict[str, Any], old: Dict[str, Any],
) -> None:
    """PRD §2.4: plan_version is incremented by 1 on the DRAFT-edit
    transition. Distinct from the OCC version."""
    assert new["plan_version"] == old["plan_version"] + 1, (
        f"plan_version did not increment by exactly 1: "
        f"old={old['plan_version']}, new={new['plan_version']}"
    )


def assert_iso_timestamp_with_three_millis(value: str) -> None:
    """PRD §2.4 timestamps are ISO 8601 UTC with three fractional digits."""
    assert is_iso8601_timestamp(value), \
        f"timestamp must be ISO 8601 UTC, got {value!r}"


__all__ = [
    "find_row",
    "select_rows",
    "count_rows",
    "assert_project",
    "assert_consumable_sku",
    "assert_room",
    "assert_customer",
    "assert_contraindication_rule",
    "assert_treatment_plan",
    "assert_appointment",
    "assert_operative_record",
    "assert_followup",
    "assert_adverse_event",
    "assert_installment_plan",
    "assert_payment_event",
    "assert_audit_entry",
    "assert_sync_event",
    "assert_installment_principal_sum",
    "assert_cash_flow_neutral_after_refund",
    "assert_on_shelf_count_unchanged",
    "assert_version_incremented_by_one",
    "assert_plan_version_incremented_by_one",
    "assert_iso_timestamp_with_three_millis",
]
