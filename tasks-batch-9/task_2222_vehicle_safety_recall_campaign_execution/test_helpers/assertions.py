"""
Per-entity shape assertions plus the domain's two conservation invariants.

The entity assertions check the common-field contract of PRD §2.4 and the
presence of each entity's own required fields. The invariant checkers
re-derive the equalities of PRD §2.9 and §2.10 from live reads.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .types import AllocationStatus, ClaimStatus, ReimbursementStatus


# ─── Common-field contract ────────────────────────────

def assert_common_fields(record: Dict[str, Any], *, versioned: bool = True) -> None:
    """
    PRD §2.4: every persisted record exposes `id` (a server-minted UUID with no
    type prefix) and `created_at`; most records additionally expose `updated_at`
    and `version`, an integer starting at 1.
    """
    assert is_valid_uuid(record.get("id")), f"id must be a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"created_at must be ISO 8601 UTC: {record.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(record.get("updated_at")), (
            f"updated_at must be ISO 8601 UTC: {record.get('updated_at')!r}"
        )
        assert isinstance(record.get("version"), int), "version must be an integer"
        assert record["version"] >= 1, "version starts at 1"


def _require(record: Dict[str, Any], fields: List[str]) -> None:
    for field in fields:
        assert field in record, f"missing field {field!r} in {sorted(record.keys())}"


# ─── Per-entity assertions ────────────────────────────

def assert_campaign(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_number",
            "defect_type",
            "defect_description",
            "risk_severity",
            "campaign_status",
            "remedy_status",
            "stop_sale_flag",
            "do_not_drive_flag",
            "remedy_revision_count",
            "quarterly_filing_count",
            "reimbursement_obligation_cents",
            "completion_rate_pct",
            "remedy_effectiveness_score",
            "late_filing_flag",
            "days_late",
        ],
    )


def assert_vehicle(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "vin",
            "plant_code",
            "model_code",
            "model_year",
            "production_date",
            "suspect_part_number",
            "region_code",
            "sale_status",
            "owner_address_valid",
            "stop_sale_hold",
        ],
    )


def assert_population_rule(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "inclusion_mode",
            "plant_code",
            "model_code",
            "model_year",
            "production_start_date",
            "production_end_date",
            "part_number_low",
            "part_number_high",
            "matched_vehicle_count",
        ],
    )


def assert_affected_vehicle(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "vehicle_id",
            "remedy_status",
            "notice_count",
            "approved_claim_count",
            "outreach_attempt_count",
            "requires_renotification",
        ],
    )


def assert_filing(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "filing_type",
            "narrative",
            "status",
            "filed_at",
            "filed_by_user_id",
            "completion_rate_snapshot_pct",
            "remedied_count_snapshot",
            "recall_population_snapshot",
            "effectiveness_score_snapshot",
            "days_late",
        ],
    )


def assert_notification_wave(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "wave_type",
            "target_region_code",
            "scheduled_mail_date",
            "sequence_number",
            "status",
            "auto_created",
            "eligible_vehicle_count",
            "parts_capacity_qty",
            "provisional_coverage_ratio",
            "coverage_tier_factor",
            "planned_vehicle_count",
            "parts_coverage_ratio",
            "mailed_vehicle_count",
        ],
    )


def assert_dealer(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "dealer_code",
            "name",
            "region_code",
            "labor_rate_per_hour",
            "monthly_repair_capacity",
            "status",
        ],
    )


def assert_remedy_part(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "part_number",
            "unit_cost",
            "total_procured_qty",
            "unallocated_qty",
            "consumed_qty",
            "lead_time_days",
        ],
    )


def assert_labor_operation(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "labor_op_code",
            "description",
            "flat_hours",
            "rate_type",
            "effective_from",
            "effective_to",
            "claim_count",
        ],
    )


def assert_parts_allocation(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "remedy_part_id",
            "dealer_id",
            "requested_qty",
            "allocated_qty",
            "consumed_qty",
            "partially_granted",
            "status",
        ],
    )


def assert_repair_claim(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "affected_vehicle_id",
            "dealer_id",
            "labor_operation_id",
            "repair_date",
            "claimed_labor_hours",
            "parts_used_qty",
            "is_repeat_repair",
            "status",
            "provisional_amount_cents",
        ],
    )


def assert_outreach_attempt(record: Dict[str, Any]) -> None:
    """
    PRD §2.4: "an outreach attempt is an immutable audit entry, so it carries
    only `id` and `created_at`, and neither `updated_at` nor `version` is
    present on it at all."
    """
    assert_common_fields(record, versioned=False)
    assert "updated_at" not in record, "outreach attempt must not expose updated_at"
    assert "version" not in record, "outreach attempt must not expose version"
    _require(record, ["channel", "outcome", "attempt_number", "attempted_at"])


def assert_owner_reimbursement(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    _require(
        record,
        [
            "campaign_id",
            "vehicle_id",
            "invoice_date",
            "invoice_amount",
            "labor_hours_claimed",
            "parts_amount",
            "towing_amount",
            "documentation_complete",
            "status",
            "document_round",
        ],
    )


# ─── Domain invariant checkers ────────────────────────

def assert_parts_conservation(
    part: Dict[str, Any], allocations: List[Dict[str, Any]]
) -> None:
    """
    PRD §2.9: `total_procured_qty` equals `unallocated_qty`, plus the sum over
    the part's allocations still in status `ALLOCATED` of that allocation's
    `allocated_qty` minus its `consumed_qty`, plus the part's own
    `consumed_qty`. Allocations in status `REVOKED` contribute nothing.
    """
    live = [
        a
        for a in allocations
        if a.get("remedy_part_id") == part["id"] and a.get("status") == AllocationStatus.ALLOCATED
    ]
    outstanding = sum(a["allocated_qty"] - a["consumed_qty"] for a in live)
    total = part["unallocated_qty"] + outstanding + part["consumed_qty"]
    assert total == part["total_procured_qty"], (
        f"parts conservation broken: total_procured_qty={part['total_procured_qty']} "
        f"but unallocated_qty={part['unallocated_qty']} + outstanding={outstanding} "
        f"+ consumed_qty={part['consumed_qty']} = {total}"
    )


def assert_obligation_conservation(
    campaign: Dict[str, Any],
    claims: List[Dict[str, Any]],
    reimbursements: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    PRD §2.10: `reimbursement_obligation_cents` equals the sum of
    `final_amount_cents` over that campaign's repair claims in status
    `APPROVED`, plus the sum of `approved_amount_cents` over that campaign's
    owner reimbursement requests in status `APPROVED`.
    """
    claim_total = sum(
        c["final_amount_cents"] or 0 for c in claims if c.get("status") == ClaimStatus.APPROVED
    )
    reimb_total = sum(
        r["approved_amount_cents"] or 0
        for r in (reimbursements or [])
        if r.get("status") == ReimbursementStatus.APPROVED
    )
    expected = claim_total + reimb_total
    assert campaign["reimbursement_obligation_cents"] == expected, (
        f"obligation ledger broken: campaign carries "
        f"{campaign['reimbursement_obligation_cents']} but approved claims sum to "
        f"{claim_total} and approved reimbursements to {reimb_total}"
    )


def assert_no_version_drift(before: Dict[str, Any], after: Dict[str, Any], expected_delta: int = 1) -> None:
    """PRD §2.4: `version` increments by exactly 1 on every mutation."""
    assert after["version"] == before["version"] + expected_delta, (
        f"expected version {before['version']} + {expected_delta}, got {after['version']}"
    )


# ─── Small read helpers built on the framework validators ──

def read_list(response, expected_total: Optional[int] = None):
    """Validate a paginated response and optionally pin its `total_count`."""
    data, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']}"
        )
    return data, meta


def read_object(response, expected_status: int = 200) -> Dict[str, Any]:
    """Validate a single-object response and return its `data`."""
    return validate_success(response, expected_status)
