"""Entity assertions and domain invariant checkers for the Flight Delay
Claims API.

Each `assert_<entity>` function validates the structural shape of a single
response payload — id format, timestamp format, presence of required fields
named verbatim in the PRD, status enums confined to PRD-listed values.

The helpers also expose convenience invariant checkers such as
`assert_reinsurance_invariant` (PRD §3.7: primary + reinsurer == final) and
`assert_reserve_invariant` (PRD §2.8: stored == sum-of-in-flight-approved).
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# Valid enum sets, mirroring PRD prose verbatim.

POLICY_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED"}
DELAY_BASES = {"DEPARTURE", "ARRIVAL"}
PAYOUT_MODES = {"FIXED", "ACTUAL_LOSS"}
DELAY_CAUSES = {"WEATHER", "ATC", "SECURITY", "AIRLINE", "OTHER"}

TICKET_STATUSES = {"ATTACHED", "CHANGED", "REFUNDED", "UNMATCHED"}
FLIGHT_STATUSES = {
    "SCHEDULED", "ACTIVE", "LANDED", "CANCELLED", "DIVERTED", "RETURNED", "ARCHIVED",
}
FLIGHT_EVENT_SOURCES = {"AIRLINE", "AIRPORT", "AVIATION_AUTHORITY"}
REPORTED_FLIGHT_STATUSES = {"ON_TIME", "DELAYED", "CANCELLED", "DIVERTED", "RETURNED"}

CLAIM_REVIEW_STATUSES = {"PENDING_MATCH", "MATCHED", "UNDER_REVIEW", "APPROVED", "REJECTED"}
CLAIM_PAYOUT_STATUSES = {"NOT_PAYABLE", "PAYABLE", "EXECUTING", "PAID", "REVERSED"}
TIER_VALUES = {"TIER_A", "TIER_B", "TIER_C", "NONE"}
SEGMENT_ELIGIBILITY = {
    "ELIGIBLE", "EXCLUDED_CAUSE", "WAITING_PERIOD", "DELAY_BELOW_THRESHOLD", "TICKET_NOT_BOUND",
}
REJECTION_REASONS = {
    "EXCLUDED_CAUSE", "WAITING_PERIOD", "DELAY_BELOW_THRESHOLD", "QUOTA_EXHAUSTED",
    "MATCHING_FAILED", "MANUAL_DENY", "DUPLICATE",
}
BATCH_REVIEW_PHASES = {"STAGED", "APPROVED", "REJECTED"}
BATCH_EXECUTION_PHASES = {"PENDING", "EXECUTING", "SETTLED", "EXCEPTIONS"}
MANUAL_REVIEW_STATUSES = {"OPEN", "RESOLVED_BIND", "RESOLVED_REJECT"}
RESERVE_REASONS = {"APPROVE_DEBIT", "SETTLE_RELEASE", "REJECT_RELEASE", "REVERSE_REBUILD"}
AUDIT_SUBJECT_TYPES = {"CLAIM", "PAYOUT_BATCH", "POLICY", "FLIGHT"}
AUDIT_ACTIONS = {
    "STATUS_CHANGE", "PAYOUT_RECORDED", "RESERVE_ADJUSTED", "EXTERNAL_EVENT_EMITTED",
}
OUTBOX_TARGETS = {"PAYMENT", "BANKING", "AIRLINE", "POLICY_ADMIN"}
OUTBOX_DISPATCH_STATUSES = {"PENDING", "DELIVERED", "FAILED"}


# ---------------------------------------------------------------------------
# Common-fields helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: Dict[str, Any], *, append_only: bool = False) -> None:
    """Verify id + created_at; for non-append-only entities also updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    if not append_only:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be int >= 1: {data.get('version')!r}"


# ---------------------------------------------------------------------------
# Insurer
# ---------------------------------------------------------------------------

def assert_insurer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["currency"], str) and data["currency"]
    assert isinstance(data["now_epoch_ms"], int) and data["now_epoch_ms"] >= 0
    assert isinstance(data["total_outstanding_reserve_cents"], int)
    assert data["total_outstanding_reserve_cents"] >= 0


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def assert_policy(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in POLICY_STATUSES, f"status: {data['status']}"
    assert data["delay_basis"] in DELAY_BASES
    assert data["payout_mode"] in PAYOUT_MODES
    for f in (
        "effective_from_epoch_ms", "effective_to_epoch_ms",
        "waiting_period_ms", "deductible_cents", "policy_limit_cents",
        "claim_quota_total_cents", "claim_quota_used_cents", "reserve_balance_cents",
        "reimbursement_rate_bps",
    ):
        assert isinstance(data[f], int), f"{f} must be int: {data.get(f)!r}"
    assert data["effective_to_epoch_ms"] > data["effective_from_epoch_ms"]
    assert data["claim_quota_used_cents"] <= data["claim_quota_total_cents"], \
        "PRD §3.1: claim_quota_used_cents must be <= claim_quota_total_cents"
    assert data["reserve_balance_cents"] >= 0
    assert data["claim_quota_used_cents"] >= 0
    excluded = data.get("excluded_delay_causes") or []
    assert isinstance(excluded, list)
    for c in excluded:
        assert c in DELAY_CAUSES, f"excluded cause: {c}"
    assert isinstance(data["policy_holder_name"], str) and data["policy_holder_name"]
    assert isinstance(data["policy_holder_doc_id"], str) and data["policy_holder_doc_id"]


# ---------------------------------------------------------------------------
# Ticket
# ---------------------------------------------------------------------------

def assert_ticket(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in TICKET_STATUSES, f"status: {data['status']}"
    assert isinstance(data["passenger_name"], str)
    assert isinstance(data["passenger_doc_id"], str)
    assert isinstance(data["pnr_code"], str)
    assert isinstance(data["flight_id"], str)
    assert isinstance(data["scheduled_departure_epoch_ms"], int)
    assert isinstance(data["scheduled_arrival_epoch_ms"], int)


# ---------------------------------------------------------------------------
# Flight
# ---------------------------------------------------------------------------

def assert_flight(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in FLIGHT_STATUSES, f"status: {data['status']}"
    assert isinstance(data["carrier_code"], str)
    assert isinstance(data["flight_number"], str)
    assert isinstance(data["origin_airport"], str)
    assert isinstance(data["destination_airport"], str)
    assert isinstance(data["scheduled_departure_epoch_ms"], int)
    assert isinstance(data["scheduled_arrival_epoch_ms"], int)
    if data.get("classified_cause") is not None:
        assert data["classified_cause"] in DELAY_CAUSES


# ---------------------------------------------------------------------------
# FlightStatusEvent (append-only)
# ---------------------------------------------------------------------------

def assert_flight_status_event(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, append_only=True)
    assert data["source"] in FLIGHT_EVENT_SOURCES
    assert data["reported_status"] in REPORTED_FLIGHT_STATUSES
    assert isinstance(data["source_event_id"], str)
    assert isinstance(data["report_epoch_ms"], int)
    assert isinstance(data["ingested_epoch_ms"], int)


# ---------------------------------------------------------------------------
# Claim & ClaimSegment
# ---------------------------------------------------------------------------

def assert_claim_segment(seg: Dict[str, Any]) -> None:
    _assert_common_fields(seg)
    assert isinstance(seg["ticket_id"], str)
    assert isinstance(seg["flight_id"], str)
    assert isinstance(seg["claimed_actual_loss_cents"], int)
    assert isinstance(seg["gross_segment_payout_cents"], int)
    assert isinstance(seg["final_segment_payout_cents"], int)
    if seg.get("tier_selected") is not None:
        assert seg["tier_selected"] in TIER_VALUES
    if seg.get("eligibility") is not None:
        assert seg["eligibility"] in SEGMENT_ELIGIBILITY


def assert_claim(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["review_status"] in CLAIM_REVIEW_STATUSES, f"review_status: {data['review_status']}"
    assert data["payout_status"] in CLAIM_PAYOUT_STATUSES, f"payout_status: {data['payout_status']}"
    assert isinstance(data["ticket_ids"], list) and len(data["ticket_ids"]) >= 1
    assert isinstance(data["estimated_payout_cents"], int)
    assert isinstance(data["final_payout_cents"], int)
    if data.get("rejection_reason") is not None:
        assert data["rejection_reason"] in REJECTION_REASONS
    if data.get("segments") is not None:
        for seg in data["segments"]:
            assert_claim_segment(seg)


# ---------------------------------------------------------------------------
# PayoutBatch
# ---------------------------------------------------------------------------

def assert_payout_batch(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["review_phase"] in BATCH_REVIEW_PHASES, f"review_phase: {data['review_phase']}"
    assert data["execution_phase"] in BATCH_EXECUTION_PHASES, f"execution_phase: {data['execution_phase']}"
    assert isinstance(data["claim_ids"], list)
    assert isinstance(data["total_planned_payout_cents"], int)
    assert isinstance(data["total_settled_payout_cents"], int)
    assert isinstance(data["exception_claim_ids"], list)


# ---------------------------------------------------------------------------
# ManualReviewCase
# ---------------------------------------------------------------------------

def assert_manual_review_case(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in MANUAL_REVIEW_STATUSES
    assert isinstance(data["ticket_id"], str)
    assert isinstance(data["failure_reason"], str)


# ---------------------------------------------------------------------------
# Append-only ledger entries
# ---------------------------------------------------------------------------

def assert_reinsurance_allocation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, append_only=True)
    for f in ("primary_share_cents", "reinsurer_share_cents", "pinned_total_cents"):
        assert isinstance(data[f], int) and data[f] >= 0
    assert (data["primary_share_cents"] + data["reinsurer_share_cents"]
            == data["pinned_total_cents"]), \
        "PRD §3.7: primary_share_cents + reinsurer_share_cents must equal pinned_total_cents"


def assert_reserve_adjustment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, append_only=True)
    assert data["reason"] in RESERVE_REASONS
    assert isinstance(data["delta_cents"], int)
    assert isinstance(data["balance_after_cents"], int) and data["balance_after_cents"] >= 0


def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, append_only=True)
    assert data["subject_type"] in AUDIT_SUBJECT_TYPES
    assert data["action"] in AUDIT_ACTIONS
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert isinstance(data["subject_id"], str)


def assert_outbox_event(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, append_only=True)
    assert data["target_system"] in OUTBOX_TARGETS
    assert data["dispatch_status"] in OUTBOX_DISPATCH_STATUSES
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["subject_id"], str)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_reinsurance_invariant(allocation: Dict[str, Any], expected_total: int) -> None:
    """PRD §3.7: 'primary_share_cents + reinsurer_share_cents must equal
    pinned_total_cents, which itself equals the claim's final_payout_cents at
    the moment of settlement.'"""
    primary = allocation["primary_share_cents"]
    reinsurer = allocation["reinsurer_share_cents"]
    pinned = allocation["pinned_total_cents"]
    assert primary + reinsurer == pinned, (
        f"primary_share_cents ({primary}) + reinsurer_share_cents ({reinsurer}) "
        f"!= pinned_total_cents ({pinned})"
    )
    assert pinned == expected_total, (
        f"pinned_total_cents ({pinned}) != claim.final_payout_cents ({expected_total})"
    )


def assert_pessimistic_ge_optimistic(risk_view: Dict[str, Any]) -> None:
    """PRD §2.8: 'when at least one UNDER_REVIEW claim ... the pessimistic
    figure exceeds the optimistic figure; when every in-flight claim is
    already APPROVED, the two are equal.'"""
    optimistic = risk_view["optimistic_reserve_cents"]
    pessimistic = risk_view["pessimistic_reserve_cents"]
    assert pessimistic >= optimistic, (
        f"pessimistic_reserve_cents ({pessimistic}) must be "
        f">= optimistic_reserve_cents ({optimistic})"
    )


# ---------------------------------------------------------------------------
# Audit-log / outbox search helpers
# ---------------------------------------------------------------------------

def find_audit_logs(
    rows: Iterable[Dict[str, Any]],
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if subject_type is not None and r.get("subject_type") != subject_type:
            continue
        if subject_id is not None and r.get("subject_id") != subject_id:
            continue
        if action is not None and r.get("action") != action:
            continue
        out.append(r)
    return out


def find_outbox_events(
    rows: Iterable[Dict[str, Any]],
    *,
    target_system: Optional[str] = None,
    event_type: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if target_system is not None and r.get("target_system") != target_system:
            continue
        if event_type is not None and r.get("event_type") != event_type:
            continue
        if subject_id is not None and r.get("subject_id") != subject_id:
            continue
        out.append(r)
    return out
