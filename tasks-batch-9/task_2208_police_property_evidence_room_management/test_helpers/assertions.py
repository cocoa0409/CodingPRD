"""Entity assertions and domain invariant checks."""

from decimal import Decimal
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Common field shape (PRD section 2.4) ────────────────────────────────────

def assert_common_fields(data: dict) -> None:
    """id, created_at, updated_at and version, as PRD section 2.4 requires."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 with three fractional digits: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 with three fractional digits: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer: {data.get('version')!r}"
    )


def assert_millisecond_timestamp(value: Optional[str], allow_null: bool = False) -> None:
    """PRD section 2.4 renders instants as e.g. ``2026-08-01T00:00:00.000Z``."""
    if value is None:
        assert allow_null, "timestamp unexpectedly null"
        return
    assert isinstance(value, str), f"timestamp must be a string: {value!r}"
    assert value.endswith("Z"), f"timestamp must be a UTC instant ending in Z: {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"timestamp must carry exactly three fractional digits: {value!r}"
    )


def assert_two_decimal_exactness(value) -> None:
    """PRD section 2.8: risk scoring is carried to exactly two decimal places."""
    quantised = Decimal(str(value)).quantize(Decimal("0.01"))
    assert Decimal(str(value)) == quantised, (
        f"value must carry at most two decimals: {value!r}"
    )


# ─── Per-entity assertions ───────────────────────────────────────────────────

def assert_property_room(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["agency_code"], str) and 3 <= len(data["agency_code"]) <= 5
    assert data["posture"] in ("OPEN", "RESTRICTED", "LOCKED_DOWN")
    for counter in (
        "open_discrepancy_count",
        "missing_high_risk_count",
        "sealed_location_count",
        "disposal_eligible_count",
        "escrow_balance_cents",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer: {data[counter]!r}"
        )
    assert_millisecond_timestamp(data.get("last_sweep_at"), allow_null=True)


def assert_offense_statute(data: dict) -> None:
    assert_common_fields(data)
    assert data["preservation_class"] in (
        "STANDARD",
        "DRUG_SCHEDULE",
        "BIOLOGICAL_INDEFINITE",
        "HOMICIDE_PERMANENT",
    )
    assert 0 <= data["statutory_retention_days"] <= 36500
    assert 0 <= data["appeal_window_days"] <= 3650
    assert isinstance(data["destruction_requires_court_order"], bool)


def assert_storage_location(data: dict) -> None:
    assert_common_fields(data)
    assert data["category"] in (
        "GENERAL",
        "REFRIGERATED",
        "HIGH_VALUE_VAULT",
        "OVERSIZED_YARD",
    )
    assert 1 <= data["capacity_slots"] <= 1000
    assert data["status"] in ("OPEN", "SEALED_FOR_AUDIT")
    assert isinstance(data["requires_dual_signature"], bool)
    if data["category"] == "REFRIGERATED":
        assert data["temperature_c"] is not None, (
            "a refrigerated location must supply temperature_c"
        )
        assert -30.0 <= float(data["temperature_c"]) <= 30.0
    else:
        assert data["temperature_c"] is None, (
            "every non-refrigerated category must leave temperature_c null"
        )
    assert_occupancy_invariant(data)


def assert_custodian(data: dict) -> None:
    assert_common_fields(data)
    assert data["role_type"] in ("EVIDENCE_TECH", "INVESTIGATOR", "LAB_ANALYST", "AUDITOR")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_escort_count"], int) and data["open_escort_count"] >= 0
    assert_millisecond_timestamp(data["certification_expires_at"])


def assert_case(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "CHARGED", "ADJUDICATED", "APPEAL_PENDING", "CLOSED")
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0
    assert isinstance(data["undisposed_item_count"], int)
    assert 0 <= data["undisposed_item_count"] <= data["item_count"], (
        "undisposed_item_count may never exceed item_count"
    )
    for stamp in ("charged_at", "adjudicated_at", "appeal_opened_at", "closed_at"):
        assert_millisecond_timestamp(data.get(stamp), allow_null=True)


def assert_evidence_item(data: dict) -> None:
    assert_common_fields(data)
    assert data["category"] in (
        "GENERAL",
        "BIOLOGICAL",
        "CURRENCY",
        "FIREARM",
        "NARCOTICS",
        "OVERSIZED",
    )
    assert data["packaging_type"] in (
        "SEALED_ENVELOPE",
        "PAPER_BAG",
        "RIGID_BOX",
        "SHARPS_TUBE",
        "PALLET_WRAP",
        "CHAIN_TAG_ONLY",
    )
    assert 0 <= data["appraised_value_cents"] <= 100000000
    assert isinstance(data["is_found_property"], bool)
    assert data["custody_state"] in ("LOGGED", "STORED", "CHECKED_OUT", "MISSING", "PURGED")
    assert data["disposition_state"] in (
        "RETAINED",
        "DISPOSAL_ELIGIBLE",
        "UNCLAIMED_ELIGIBLE",
        "COURT_HOLD",
        "ORDER_PENDING",
        "DISPOSED",
    )
    assert data["retention_basis"] in ("PRELIMINARY", "FINAL", "INDEFINITE", "COURT_HOLD")
    assert data["required_storage_category"] in (
        "GENERAL",
        "REFRIGERATED",
        "HIGH_VALUE_VAULT",
        "OVERSIZED_YARD",
    )
    assert isinstance(data["item_sequence"], int) and data["item_sequence"] >= 1
    assert isinstance(data["barcode"], str) and len(data["barcode"]) > 0
    assert isinstance(data["open_transfer_count"], int) and data["open_transfer_count"] >= 0
    assert_millisecond_timestamp(data["intake_at"])
    assert_millisecond_timestamp(data["seized_at"])
    assert_millisecond_timestamp(data.get("retention_release_at"), allow_null=True)


def assert_retention_determination(data: dict) -> None:
    assert_common_fields(data)
    assert data["resolved_basis"] in ("PRELIMINARY", "FINAL", "INDEFINITE", "COURT_HOLD")
    assert isinstance(data["statute_days_applied"], int) and data["statute_days_applied"] >= 0
    assert isinstance(data["superseded"], bool)
    assert_millisecond_timestamp(data.get("anchor_at"), allow_null=True)
    assert_millisecond_timestamp(data.get("computed_release_at"), allow_null=True)


def assert_custody_transfer(data: dict) -> None:
    assert_common_fields(data)
    assert data["purpose"] in ("LAB_ANALYSIS", "COURT_PRESENTATION", "INVESTIGATIVE_REVIEW")
    assert data["status"] in (
        "REQUESTED",
        "RELEASED",
        "OVERDUE",
        "RETURNED",
        "DENIED",
        "LOST",
    )
    assert_millisecond_timestamp(data["released_at"])
    assert_millisecond_timestamp(data["due_back_at"])
    assert_millisecond_timestamp(data.get("returned_at"), allow_null=True)


def assert_disposition_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["type"] in ("RETURN_TO_OWNER", "AUCTION", "DESTRUCTION", "CONVERSION")
    assert data["status"] in (
        "PENDING_COURT_AUTH",
        "AUTHORIZED",
        "REJECTED",
        "EXECUTED",
        "SETTLED",
        "DISBURSED",
    )
    assert data["settlement_status"] in ("NONE", "HELD", "DISBURSED")
    assert isinstance(data["auto_authorized"], bool)
    assert isinstance(data["estimated_net_proceeds_cents"], int)
    for money in ("gross_sale_cents", "commission_cents", "storage_recovery_cents",
                  "settled_net_proceeds_cents", "reserve_price_cents"):
        value = data.get(money)
        assert value is None or isinstance(value, int), (
            f"{money} must be integer cents or null: {value!r}"
        )
    for stamp in ("authorized_at", "executed_at", "settled_at", "settlement_deadline_at"):
        assert_millisecond_timestamp(data.get(stamp), allow_null=True)


def assert_owner_claim(data: dict) -> None:
    assert_common_fields(data)
    assert data["notice_method"] in ("CERTIFIED_MAIL", "PUBLICATION", "IN_PERSON")
    assert data["status"] in ("NOTICE_SENT", "CLAIM_FILED", "VERIFIED", "RELEASED", "EXPIRED")
    assert_millisecond_timestamp(data["notified_at"])
    assert_millisecond_timestamp(data["claim_deadline_at"])
    assert_millisecond_timestamp(data.get("verified_at"), allow_null=True)


def assert_audit_session(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "RECONCILED", "CLOSED")
    assert isinstance(data["expected_evidence_item_ids"], list)
    assert isinstance(data["scanned_evidence_item_ids"], list)
    assert data["expected_item_count"] == len(data["expected_evidence_item_ids"])
    assert data["scanned_item_count"] == len(data["scanned_evidence_item_ids"])
    assert isinstance(data["missing_count"], int) and data["missing_count"] >= 0
    assert isinstance(data["misplaced_count"], int) and data["misplaced_count"] >= 0
    assert_two_decimal_exactness(data["risk_index"])
    assert float(data["risk_index"]) >= 0
    for stamp in ("started_at", "reconciled_at", "closed_at"):
        assert_millisecond_timestamp(data.get(stamp), allow_null=True)


def assert_discrepancy(data: dict) -> None:
    assert_common_fields(data)
    assert data["kind"] in ("MISSING", "MISPLACED")
    assert data["status"] in (
        "OPEN",
        "UNDER_INVESTIGATION",
        "RESOLVED_FOUND",
        "RESOLVED_WRITTEN_OFF",
    )
    assert_two_decimal_exactness(data["weight_contribution"])
    assert_millisecond_timestamp(data.get("resolved_at"), allow_null=True)


def assert_chain_event(data: dict) -> None:
    """PRD section 2.4: a ChainEvent carries only ``id`` and ``created_at`` — it has
    neither ``updated_at`` nor ``version``."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data or data["updated_at"] is None, (
        "a chain of custody entry must not carry updated_at"
    )
    assert "version" not in data or data["version"] is None, (
        "a chain of custody entry must not carry version"
    )
    assert data["event_type"] in (
        "INTAKE",
        "STORAGE_ASSIGN",
        "RELEASE",
        "RECEIPT",
        "AUDIT_SCAN",
        "DISCREPANCY_RAISED",
        "RETENTION_SET",
        "NOTICE_SENT",
        "DISPOSITION_EXECUTED",
    )
    assert data["actor_role"] in (
        "PropertyRoomManager",
        "EvidenceTechnician",
        "Investigator",
        "LabAnalyst",
        "CourtClerk",
        "InternalAuditor",
        "SYSTEM",
    )
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert_millisecond_timestamp(data["occurred_at"])


# ─── Conservation invariants (PRD section 2.7) ───────────────────────────────

def assert_occupancy_invariant(location: dict) -> None:
    """``occupied_slots`` must be at least 0 and at most ``capacity_slots``."""
    assert 0 <= location["occupied_slots"] <= location["capacity_slots"], (
        f"occupied_slots {location['occupied_slots']} outside "
        f"[0, {location['capacity_slots']}] for location {location.get('code')}"
    )


def assert_chain_sequence_gapless(events: list) -> None:
    """PRD section 2.12: ``sequence_no`` is 1-based and gapless per evidence item."""
    numbers = sorted(event["sequence_no"] for event in events)
    assert numbers == list(range(1, len(events) + 1)), (
        f"chain sequence must be 1-based and gapless, got {numbers}"
    )
