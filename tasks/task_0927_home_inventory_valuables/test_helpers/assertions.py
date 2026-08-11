"""Entity assertions, instant comparison helpers and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ---------------------------------------------------------------------------
# Instant handling
#
# PRD 2.5 rule 5: "All instant comparisons are semantic: two strings that
# denote the same instant compare equal regardless of how many fractional
# digits either carries."  Every timestamp assertion in this suite therefore
# parses both sides and compares instants, never raw strings.
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    """Assert two ISO 8601 strings denote the same instant (PRD 2.5 rule 5)."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected!r}, got {actual!r}"
    )


def assert_three_digit_utc(value: str, label: str = "timestamp"):
    """Server-written instants carry exactly three fractional digits (PRD 2.5 rule 1)."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must end with Z, got {value!r}"
    assert len(value) == len("2026-05-01T00:00:00.000Z"), (
        f"{label} must render exactly three fractional digits, got {value!r}"
    )
    assert value[19] == ".", f"{label} must render exactly three fractional digits, got {value!r}"


def assert_echoed_verbatim(actual: str, submitted: str, label: str = "caller-supplied instant"):
    """Caller-supplied instants echo back byte-for-byte (PRD 2.5 rule 3)."""
    assert actual == submitted, f"{label}: expected {submitted!r} echoed verbatim, got {actual!r}"


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------


def assert_common_fields(data: Dict[str, Any], label: str = "resource"):
    """id / created_at / updated_at / version, per PRD 2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_light_fields(data: Dict[str, Any], label: str = "resource"):
    """id + created_at only; no updated_at and no version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, f"{label} must expose no updated_at field"
    assert "version" not in data, f"{label} must expose no version field"


# ---------------------------------------------------------------------------
# Per-entity assertions (field sets from PRD 2.11)
# ---------------------------------------------------------------------------


def _require_keys(data: Dict[str, Any], keys, label: str):
    missing = [k for k in keys if k not in data]
    assert not missing, f"{label} is missing projected fields {missing}"


def assert_member(data: Dict[str, Any]):
    assert_common_fields(data, "Member")
    _require_keys(data, ["email", "full_name", "member_role", "household_id"], "Member")
    assert data["member_role"] in {"OWNER", "LIMITED", "EXECUTOR", "HEIR"}


def assert_household(data: Dict[str, Any]):
    assert_common_fields(data, "Household")
    _require_keys(
        data,
        [
            "name",
            "address_label",
            "write_gate_state",
            "records_freeze_active",
            "item_count",
            "asset_count",
            "asset_bytes_used",
            "frozen_item_count",
            "active_share_count",
            "total_effective_value_cents",
        ],
        "Household",
    )
    assert data["write_gate_state"] in {"OPEN", "RESTRICTED", "READ_ONLY"}
    assert isinstance(data["records_freeze_active"], bool)
    for counter in (
        "item_count",
        "asset_count",
        "asset_bytes_used",
        "frozen_item_count",
        "active_share_count",
        "total_effective_value_cents",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Household.{counter} must be a non-negative integer, got {data[counter]!r}"
        )


def assert_subscription(data: Dict[str, Any]):
    assert_common_fields(data, "Subscription")
    _require_keys(
        data,
        [
            "household_id",
            "tier",
            "status",
            "refresh_state",
            "period_start_at",
            "period_end_at",
            "past_due_since_at",
            "last_attested_at",
            "refresh_due_at",
            "appraisal_credits_remaining",
            "packages_used_this_period",
            "monthly_fee_cents",
            "last_proration_charge_cents",
        ],
        "Subscription",
    )
    assert data["tier"] in {"BASIC", "PLUS", "ESTATE"}
    assert data["status"] in {"TRIAL", "ACTIVE", "PAST_DUE", "LAPSED", "CLOSED"}
    assert data["refresh_state"] in {"CURRENT", "DUE", "GRACE", "OVERDUE"}


def assert_room(data: Dict[str, Any]):
    assert_common_fields(data, "Room")
    _require_keys(data, ["household_id", "name", "floor_label", "item_count"], "Room")


def assert_item(data: Dict[str, Any]):
    assert_common_fields(data, "Item")
    _require_keys(
        data,
        [
            "household_id",
            "room_id",
            "name",
            "category",
            "quantity",
            "serial_number",
            "acquired_at",
            "purchase_price_cents",
            "replacement_cost_cents",
            "declared_value_cents",
            "declared_by_member_id",
            "lifecycle_state",
            "evidence_tier",
            "valuation_state",
            "effective_value_cents",
            "effective_value_basis",
            "acv_value_cents",
            "coverage_mode",
            "scheduled_policy_id",
            "scheduled_value_cents",
            "replaces_item_id",
            "serial_chain_intact",
            "allocated_quantity",
            "frozen_by_claim_id",
        ],
        "Item",
    )
    assert data["lifecycle_state"] in {
        "DRAFT",
        "CATALOGED",
        "FROZEN",
        "REPLACED",
        "DISPOSED",
    }
    assert data["evidence_tier"] in {"NONE", "PHOTO_ONLY", "PHOTO_SERIAL", "DOCUMENTED"}
    assert data["valuation_state"] in {
        "UNVALUED",
        "DECLARED_ONLY",
        "APPRAISAL_REQUIRED",
        "CERTIFIED",
    }
    assert data["effective_value_basis"] in {"NONE", "DECLARED", "ACV", "APPRAISAL"}
    assert data["coverage_mode"] in {"BLANKET", "SCHEDULED"}
    assert isinstance(data["effective_value_cents"], int)
    assert isinstance(data["acv_value_cents"], int)
    assert isinstance(data["scheduled_value_cents"], int)
    assert isinstance(data["serial_chain_intact"], bool)


def assert_asset(data: Dict[str, Any]):
    assert_light_fields(data, "Asset")
    _require_keys(
        data,
        ["item_id", "asset_kind", "byte_size", "checksum", "captured_at", "status"],
        "Asset",
    )
    assert data["asset_kind"] in {
        "PHOTO",
        "SERIAL_PLATE",
        "RECEIPT",
        "PROVENANCE_DOC",
        "APPRAISAL_PDF",
    }
    assert data["status"] in {"STORED", "DELETED"}


def assert_category_schedule(data: Dict[str, Any]):
    assert_light_fields(data, "CategorySchedule")
    _require_keys(
        data,
        [
            "category",
            "useful_life_months",
            "annual_depreciation_pct",
            "salvage_floor_pct",
            "blanket_sublimit_cents",
            "appraisal_scope",
            "serial_required",
        ],
        "CategorySchedule",
    )


def assert_appraiser(data: Dict[str, Any]):
    assert_common_fields(data, "Appraiser")
    _require_keys(
        data,
        ["display_name", "credential_id", "scope_categories", "linked_member_id", "status"],
        "Appraiser",
    )
    assert data["status"] in {"ACTIVE", "SUSPENDED"}
    assert isinstance(data["scope_categories"], list) and data["scope_categories"]


def assert_appraisal(data: Dict[str, Any]):
    assert_common_fields(data, "Appraisal")
    _require_keys(
        data,
        [
            "item_id",
            "appraiser_id",
            "requested_by_member_id",
            "status",
            "inspection_start_at",
            "inspection_end_at",
            "appraised_value_cents",
            "certified_at",
            "valid_until_at",
            "credit_consumed",
            "void_reason",
        ],
        "Appraisal",
    )
    assert data["status"] in {"REQUESTED", "CERTIFIED", "VOIDED", "EXPIRED"}
    assert isinstance(data["credit_consumed"], bool)


def assert_policy(data: Dict[str, Any]):
    assert_common_fields(data, "Policy")
    _require_keys(
        data,
        [
            "household_id",
            "carrier_name",
            "policy_number",
            "deductible_cents",
            "scheduled_allowance_cents",
            "scheduled_consumed_cents",
            "scheduled_remaining_cents",
            "coverage_gap_cents",
            "total_effective_value_cents",
            "effective_from",
        ],
        "Policy",
    )
    assert_policy_ledger_invariant(data)


def assert_policy_ledger_invariant(data: Dict[str, Any]):
    """PRD 2.12 invariant 1: remaining always equals allowance minus consumed."""
    assert data["scheduled_consumed_cents"] >= 0, "scheduled_consumed_cents must be >= 0"
    assert (
        data["scheduled_remaining_cents"]
        == data["scheduled_allowance_cents"] - data["scheduled_consumed_cents"]
    ), (
        "scheduled_remaining_cents must equal scheduled_allowance_cents minus "
        f"scheduled_consumed_cents; got {data['scheduled_remaining_cents']} vs "
        f"{data['scheduled_allowance_cents']} - {data['scheduled_consumed_cents']}"
    )


def assert_package(data: Dict[str, Any]):
    assert_common_fields(data, "DocumentationPackage")
    _require_keys(
        data,
        [
            "household_id",
            "policy_id",
            "status",
            "recipient_ref",
            "generated_at",
            "delivered_at",
            "expires_at",
            "line_count",
            "snapshot_total_effective_cents",
            "snapshot_total_covered_cents",
            "snapshot_coverage_gap_cents",
            "stale_line_count",
            "superseded_by_package_id",
        ],
        "DocumentationPackage",
    )
    assert data["status"] in {"DRAFT", "GENERATED", "DELIVERED", "SUPERSEDED", "EXPIRED"}


def assert_package_line(data: Dict[str, Any]):
    assert_light_fields(data, "PackageLine")
    _require_keys(
        data,
        [
            "package_id",
            "item_id",
            "snapshot_name",
            "snapshot_category",
            "snapshot_evidence_tier",
            "snapshot_effective_value_cents",
            "snapshot_effective_value_basis",
            "snapshot_covered_cents",
            "snapshot_coverage_mode",
            "stale",
        ],
        "PackageLine",
    )
    assert isinstance(data["stale"], bool)


def assert_claim(data: Dict[str, Any]):
    assert_common_fields(data, "LossClaim")
    _require_keys(
        data,
        [
            "household_id",
            "package_id",
            "policy_id",
            "loss_date",
            "peril",
            "settlement_basis",
            "deductible_mode",
            "affected_room_ids",
            "status",
            "submitted_at",
            "frozen_item_count",
            "line_count",
            "approved_line_count",
            "denied_line_count",
            "blocked_line_count",
            "total_settlement_cents",
        ],
        "LossClaim",
    )
    assert data["status"] in {
        "OPEN",
        "SUBMITTED",
        "UNDER_REVIEW",
        "SUPPLEMENT_REQUESTED",
        "SETTLED",
        "DENIED",
        "WITHDRAWN",
    }
    assert isinstance(data["affected_room_ids"], list) and data["affected_room_ids"]


def assert_claim_line(data: Dict[str, Any]):
    assert_common_fields(data, "ClaimLine")
    _require_keys(
        data,
        [
            "claim_id",
            "item_id",
            "claimed_quantity",
            "status",
            "gross_value_cents",
            "capped_value_cents",
            "deductible_share_cents",
            "net_settlement_cents",
            "appeal_count",
            "settlement_hold",
            "basis_downgraded",
            "denial_reason",
        ],
        "ClaimLine",
    )
    assert data["status"] in {"PENDING", "APPROVED", "DENIED", "APPEALED"}
    assert isinstance(data["settlement_hold"], bool)
    assert isinstance(data["basis_downgraded"], bool)
    assert data["net_settlement_cents"] >= 0, "net_settlement_cents is floored at zero"


def assert_estate_plan(data: Dict[str, Any]):
    assert_common_fields(data, "EstatePlan")
    _require_keys(
        data,
        [
            "household_id",
            "executor_member_id",
            "status",
            "valuation_mode",
            "proposed_at",
            "approved_at",
            "executed_at",
            "approved_by_member_id",
            "heir_count",
            "balance_spread_pct",
            "balanced",
            "unallocated_item_count",
        ],
        "EstatePlan",
    )
    assert data["status"] in {"DRAFT", "PROPOSED", "APPROVED", "EXECUTED"}
    assert data["valuation_mode"] in {"GROSS", "NET"}
    assert isinstance(data["balanced"], bool)


def assert_allocation(data: Dict[str, Any]):
    assert_common_fields(data, "Allocation")
    _require_keys(
        data,
        [
            "estate_plan_id",
            "item_id",
            "heir_member_id",
            "disposition",
            "quantity",
            "allocated_value_cents",
            "blocked",
        ],
        "Allocation",
    )
    assert data["disposition"] in {"KEEP", "SELL", "DONATE", "DISCARD"}
    assert isinstance(data["blocked"], bool)


def assert_share_grant(data: Dict[str, Any]):
    assert_common_fields(data, "ShareGrant")
    _require_keys(
        data,
        [
            "household_id",
            "scope_kind",
            "scope_room_id",
            "scope_package_id",
            "scope_claim_id",
            "recipient_ref",
            "redaction_level",
            "share_token",
            "starts_at",
            "expires_at",
            "access_cap",
            "access_count",
            "status",
            "voided_reason",
        ],
        "ShareGrant",
    )
    assert data["scope_kind"] in {"HOUSEHOLD", "ROOM", "PACKAGE", "CLAIM"}
    assert data["redaction_level"] in {"VALUES_HIDDEN", "SERIALS_HIDDEN", "FULL"}
    assert data["status"] in {
        "ACTIVE",
        "REVOKED",
        "EXPIRED",
        "EXHAUSTED",
        "VOIDED_BY_SCOPE",
    }
    assert isinstance(data["share_token"], str) and data["share_token"]


def assert_coverage_gap_read(data: Dict[str, Any]):
    """Shape of the computed coverage-gap read (PRD 2.11)."""
    _require_keys(
        data,
        [
            "policy_id",
            "basis",
            "total_value_cents",
            "total_covered_cents",
            "coverage_gap_cents",
            "item_count",
            "schedule_required_unscheduled_count",
        ],
        "coverage-gap read",
    )
    assert (
        data["coverage_gap_cents"]
        == data["total_value_cents"] - data["total_covered_cents"]
    ), "coverage_gap_cents must equal total_value_cents minus total_covered_cents"


def assert_share_redemption(data: Dict[str, Any]):
    """Shape of the share-link redemption read (PRD 2.11)."""
    _require_keys(
        data,
        [
            "share_grant_id",
            "scope_kind",
            "redaction_level",
            "access_count",
            "access_cap",
            "household_name",
            "rows",
        ],
        "share redemption",
    )
    assert isinstance(data["rows"], list)


def assert_household_freeze_invariant(household: Dict[str, Any]):
    """PRD 2.12 invariant 2: records_freeze_active mirrors frozen_item_count > 0."""
    assert household["records_freeze_active"] == (household["frozen_item_count"] > 0), (
        "records_freeze_active must be true exactly when frozen_item_count is above zero; "
        f"got {household['records_freeze_active']} with count {household['frozen_item_count']}"
    )
