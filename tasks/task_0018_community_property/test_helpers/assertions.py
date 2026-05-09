"""Entity assertions and domain invariant checkers for the community property platform."""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AccessLogClassification,
    AccessLogDirection,
    AuditSubjectKind,
    DunningStage,
    FacilityType,
    FeeBillingRuleKind,
    FeeBillingRuleStatus,
    FeeBillStatus,
    OccupancyStatus,
    ParkingApplicationStatus,
    ParkingSpaceKind,
    ParkingSpaceStatus,
    PaymentChannel,
    PaymentReconciliationStatus,
    ProposalStatus,
    ProposalVotingMethod,
    ReservationStatus,
    ResidentLifecycleStatus,
    ResidentRelationKind,
    VoteChoice,
    VotingStatus,
    WorkOrderCategory,
    WorkOrderStatus,
)


# ──────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────

def _assert_id_and_created(data: Dict[str, Any]) -> None:
    """PRD §2.4: every entity carries id (UUID) and created_at (ISO 8601 UTC)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def _assert_common_audit(data: Dict[str, Any]) -> None:
    """PRD §2.4: most entities carry id, created_at, updated_at, and version (starts at 1)."""
    _assert_id_and_created(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def _enum_values(enum_cls) -> list:
    return [m.value for m in enum_cls]


def _assert_append_only(data: Dict[str, Any], entity_label: str) -> None:
    """PRD §2.4: PaymentRecord, Vote, AccessLog, AuditEntry are append-only —
    they carry only id + created_at, never updated_at or version."""
    _assert_id_and_created(data)
    assert "updated_at" not in data or data.get("updated_at") is None, (
        f"{entity_label} must not expose updated_at"
    )
    assert "version" not in data or data.get("version") is None, (
        f"{entity_label} must not expose version"
    )


# ──────────────────────────────────────────────────────────
# Entity assertions
# ──────────────────────────────────────────────────────────

def assert_owner(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["id_card_no"], str) and len(data["id_card_no"]) > 0
    assert isinstance(data["household_register_no"], str)
    assert isinstance(data["phone"], str)
    assert data["voting_status"] in _enum_values(VotingStatus), (
        f"bad voting_status: {data['voting_status']!r}"
    )


def assert_property(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["building_no"], str) and len(data["building_no"]) > 0
    assert isinstance(data["unit_no"], str) and len(data["unit_no"]) > 0
    assert isinstance(data["area_sqm"], (int, float)) and data["area_sqm"] > 0
    assert data["occupancy_status"] in _enum_values(OccupancyStatus), (
        f"bad occupancy_status: {data['occupancy_status']!r}"
    )
    assert isinstance(data["owner_id"], str) and is_valid_uuid(data["owner_id"])
    assert isinstance(data["parking_quota"], int) and data["parking_quota"] >= 0


def assert_resident(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["relation_kind"] in _enum_values(ResidentRelationKind)
    assert data["lifecycle_status"] in _enum_values(ResidentLifecycleStatus)


def assert_work_order(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["reporter_owner_id"], str)
    assert data["category"] in _enum_values(WorkOrderCategory), (
        f"bad category: {data['category']!r}"
    )
    assert data["status"] in _enum_values(WorkOrderStatus), (
        f"bad status: {data['status']!r}"
    )
    assert isinstance(data.get("photo_urls", []), list)


def assert_fee_billing_rule(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["rule_code"], str) and len(data["rule_code"]) > 0
    assert data["kind"] in _enum_values(FeeBillingRuleKind)
    assert isinstance(data["rate"], (int, float)) and data["rate"] >= 0
    assert isinstance(data["late_fee_daily_rate"], (int, float))
    assert 0.0 <= data["late_fee_daily_rate"] <= 0.01
    assert isinstance(data["late_fee_cap_pct"], (int, float))
    assert 0.0 <= data["late_fee_cap_pct"] <= 1.0
    assert data["rule_status"] in _enum_values(FeeBillingRuleStatus)


def assert_fee_bill(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["rule_id"], str)
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int)
    assert 1 <= data["period_month"] <= 12
    assert isinstance(data["principal_amount"], (int, float))
    assert isinstance(data["late_fee_amount"], (int, float))
    assert isinstance(data["total_due"], (int, float))
    assert is_iso8601_timestamp(data["due_date"]), "due_date must be ISO 8601"
    assert data["status"] in _enum_values(FeeBillStatus)
    assert isinstance(data["paid_amount"], (int, float))
    assert data["dunning_stage"] in _enum_values(DunningStage)


def assert_payment_record(data: Dict[str, Any]) -> None:
    """PRD §2.4: PaymentRecord is a write-once ledger entry — only id + created_at."""
    _assert_append_only(data, "PaymentRecord")
    assert isinstance(data["bill_id"], str)
    assert data["channel"] in _enum_values(PaymentChannel)
    assert isinstance(data["external_txn_id"], str) and len(data["external_txn_id"]) > 0
    assert isinstance(data["amount"], (int, float)) and data["amount"] > 0
    assert is_iso8601_timestamp(data["paid_at"])
    assert data["reconciliation_status"] in _enum_values(PaymentReconciliationStatus)


def assert_facility(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert data["facility_type"] in _enum_values(FacilityType)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["slot_minutes"] in (30, 60, 120, 180, 240)
    assert isinstance(data["capacity_per_slot"], int) and data["capacity_per_slot"] >= 1
    assert isinstance(data["cancellation_window_hours"], int)
    assert isinstance(data["damage_deposit"], (int, float)) and data["damage_deposit"] >= 0


def assert_reservation(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["owner_id"], str)
    assert is_iso8601_timestamp(data["slot_start_at"])
    assert is_iso8601_timestamp(data["slot_end_at"])
    assert data["status"] in _enum_values(ReservationStatus)
    assert isinstance(data["deposit_held"], (int, float)) and data["deposit_held"] >= 0


def assert_proposal(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["voting_method"] in _enum_values(ProposalVotingMethod)
    assert isinstance(data["pass_threshold_pct"], (int, float))
    assert 0.5 <= data["pass_threshold_pct"] <= 1.0
    assert is_iso8601_timestamp(data["voting_starts_at"])
    assert is_iso8601_timestamp(data["voting_ends_at"])
    assert data["status"] in _enum_values(ProposalStatus)


def assert_vote(data: Dict[str, Any]) -> None:
    """PRD §2.4: Vote is an immutable ballot once cast — only id + created_at."""
    _assert_append_only(data, "Vote")
    assert isinstance(data["proposal_id"], str)
    assert isinstance(data["voter_owner_id"], str)
    assert isinstance(data["property_id"], str)
    assert data["choice"] in _enum_values(VoteChoice)
    assert isinstance(data["weight"], (int, float)) and data["weight"] >= 0


def assert_parking_space(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["space_no"], str) and len(data["space_no"]) > 0
    assert data["kind"] in _enum_values(ParkingSpaceKind)
    assert isinstance(data["monthly_fee"], (int, float)) and data["monthly_fee"] >= 0
    assert data["status"] in _enum_values(ParkingSpaceStatus)


def assert_parking_application(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["owner_id"], str)
    assert isinstance(data["property_id"], str)
    assert data["requested_kind"] in _enum_values(ParkingSpaceKind)
    assert isinstance(data["license_plate"], str) and len(data["license_plate"]) > 0
    assert data["status"] in _enum_values(ParkingApplicationStatus)


def assert_access_log(data: Dict[str, Any]) -> None:
    """PRD §2.4: AccessLog is a write-once gate-event ingest record — only id + created_at."""
    _assert_append_only(data, "AccessLog")
    assert isinstance(data["license_plate"], str)
    assert data["direction"] in _enum_values(AccessLogDirection)
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["classification"] in _enum_values(AccessLogClassification)


def assert_audit_entry(data: Dict[str, Any]) -> None:
    """PRD §2.4: AuditEntry is a write-once audit row — only id + created_at."""
    _assert_append_only(data, "AuditEntry")
    assert data["subject_kind"] in _enum_values(AuditSubjectKind)
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["action"], str) and len(data["action"]) > 0
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)


# ──────────────────────────────────────────────────────────
# Domain invariant checkers
# ──────────────────────────────────────────────────────────

def assert_money_two_decimals(value: Any, label: str = "amount") -> None:
    """PRD §2.8: every emitted monetary amount is fixed at two decimals on persist
    and on read. Accepts integer floats and values whose hundredths-place representation
    rounds cleanly. We compare via abs(value*100 - round(value*100)) < 1e-6 to dodge
    binary-float artefacts."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    cents = round(value * 100)
    assert abs(value * 100 - cents) < 1e-6, (
        f"{label}={value!r} must be fixed at two decimals per PRD §2.8"
    )


def assert_deposit_invariant(initial_deposit: float, refund: float, forfeit: float) -> None:
    """PRD §3.7: "the originally-held deposit equals the sum of the refund and the
    forfeit; the spillover is a separate bill, not a deposit allocation." """
    assert abs(initial_deposit - (refund + forfeit)) < 1e-6, (
        f"Deposit invariant violated: {initial_deposit} != {refund} + {forfeit}"
    )
