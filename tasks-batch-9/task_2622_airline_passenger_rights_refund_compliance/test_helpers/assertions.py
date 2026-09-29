"""Domain assertions built on the framework's generic structural helpers.

These encode the PRD's own invariants: the identity/version fields of §2.4, the
immutability of the complaint activity trail, the conserved ledgers of §2.11 and
the money/minute conventions of §2.7.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ─── Identity, timestamps and versions (PRD §2.4) ─────


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """Every entity but the activity trail carries id, created_at, updated_at, version."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID with no type prefix: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC instant: {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC instant: {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version begins at 1 when the row is created"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_no_version_fields(row: Dict[str, Any]):
    """The complaint activity trail is immutable: no updated_at, no version."""
    assert "version" not in row, "an activity row must not carry a version"
    assert "updated_at" not in row, "an activity row must not carry updated_at"
    assert is_valid_uuid(row["id"])
    assert is_iso8601_timestamp(row["created_at"])


def assert_instant(value: Any, expected: str):
    """A stored domain instant must equal the supplied instant."""
    assert value == expected, f"expected instant {expected}, got {value!r}"


def assert_null(value: Any, field: str = "field"):
    assert value is None, f"{field} must be null, got {value!r}"


# ─── Envelope details (PRD §2.2) ──────────────────────


def assert_request_meta(body: Dict[str, Any]):
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_single_object(response):
    body = response.json()
    assert body["response_type"] == "object", "a single resource reads response_type 'object'"
    assert_request_meta(body)
    return body["data"]


def assert_list_meta(meta: Dict[str, Any], total_count: int, has_more: bool):
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )


# ─── Money and minutes (PRD §2.7) ─────────────────────


def assert_cents(value: Any, expected: int, field: str = "amount_cents"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"expected {field} == {expected}, got {value}"


def assert_hours(value: Any, expected: float, field: str = "delivery_delay_hours"):
    """delivery_delay_hours is rounded half up to two decimal places."""
    assert value == pytest.approx(expected, abs=0.005), (
        f"expected {field} == {expected}, got {value}"
    )


# ─── Conserved ledgers (PRD §2.11) ────────────────────


def assert_obligated_ledger(booking: Dict[str, Any], obligations: List[Dict[str, Any]]):
    """total_refund_obligated_cents == sum of amount_cents over non-voided rows."""
    expected = sum(
        o["amount_cents"] for o in obligations if o["settlement_status"] != "VOIDED"
    )
    assert booking["total_refund_obligated_cents"] == expected, (
        "total_refund_obligated_cents must equal the sum of amount_cents over the "
        f"booking's non-voided obligations: expected {expected}, got "
        f"{booking['total_refund_obligated_cents']}"
    )


def assert_travel_credit_ledger(
    passenger: Dict[str, Any], obligations: List[Dict[str, Any]]
):
    """travel_credit_balance_cents == sum of payable_total_cents over settled credit rows."""
    expected = sum(
        o["payable_total_cents"]
        for o in obligations
        if o.get("settlement_method") == "TRAVEL_CREDIT"
        and o["settlement_status"] == "SETTLED"
    )
    assert passenger["travel_credit_balance_cents"] == expected, (
        "travel_credit_balance_cents must equal the sum of payable_total_cents over "
        f"settled travel-credit obligations: expected {expected}, got "
        f"{passenger['travel_credit_balance_cents']}"
    )
    assert passenger["travel_credit_balance_cents"] >= 0, "the balance is never negative"


def assert_booking_ledger(
    booking: Dict[str, Any],
    collected_total_cents: Optional[int] = None,
    total_refund_obligated_cents: Optional[int] = None,
    earliest_refund_deadline_utc: Any = "__unset__",
    disruption_posture: Optional[str] = None,
    segment_count: Optional[int] = None,
    unused_segment_count: Optional[int] = None,
    travel_commenced: Optional[bool] = None,
    suppressed_obligation_count: Optional[int] = None,
    itinerary_scope: Optional[str] = None,
    version: Optional[int] = None,
):
    """Check any subset of the derived booking fields of PRD §2.11."""
    if collected_total_cents is not None:
        assert_cents(booking["collected_total_cents"], collected_total_cents,
                     "collected_total_cents")
    if total_refund_obligated_cents is not None:
        assert_cents(booking["total_refund_obligated_cents"],
                     total_refund_obligated_cents, "total_refund_obligated_cents")
    if earliest_refund_deadline_utc != "__unset__":
        assert booking["earliest_refund_deadline_utc"] == earliest_refund_deadline_utc, (
            f"expected earliest_refund_deadline_utc {earliest_refund_deadline_utc!r}, "
            f"got {booking['earliest_refund_deadline_utc']!r}"
        )
    if disruption_posture is not None:
        assert booking["disruption_posture"] == disruption_posture, (
            f"expected disruption_posture {disruption_posture}, "
            f"got {booking['disruption_posture']}"
        )
    if segment_count is not None:
        assert booking["segment_count"] == segment_count
    if unused_segment_count is not None:
        assert booking["unused_segment_count"] == unused_segment_count
    if travel_commenced is not None:
        assert booking["travel_commenced"] is travel_commenced
    if suppressed_obligation_count is not None:
        assert booking["suppressed_obligation_count"] == suppressed_obligation_count
    if itinerary_scope is not None:
        assert booking["itinerary_scope"] == itinerary_scope
    if version is not None:
        assert booking["version"] == version, (
            f"expected Booking.version {version}, got {booking['version']}"
        )


# ─── Obligation shape (PRD §3.6, §3.7) ────────────────


def assert_obligation_amounts(
    obligation: Dict[str, Any],
    gross_entitlement_cents: Optional[int] = None,
    headroom_at_creation_cents: Optional[int] = None,
    amount_cents: Optional[int] = None,
    credit_bonus_cents: Optional[int] = None,
    payable_total_cents: Optional[int] = None,
):
    if gross_entitlement_cents is not None:
        assert_cents(obligation["gross_entitlement_cents"], gross_entitlement_cents,
                     "gross_entitlement_cents")
    if headroom_at_creation_cents is not None:
        assert_cents(obligation["headroom_at_creation_cents"],
                     headroom_at_creation_cents, "headroom_at_creation_cents")
    if amount_cents is not None:
        assert_cents(obligation["amount_cents"], amount_cents, "amount_cents")
    if credit_bonus_cents is not None:
        assert_cents(obligation["credit_bonus_cents"], credit_bonus_cents,
                     "credit_bonus_cents")
    if payable_total_cents is not None:
        assert_cents(obligation["payable_total_cents"], payable_total_cents,
                     "payable_total_cents")


def assert_obligation_axes(
    obligation: Dict[str, Any],
    election_status: Optional[str] = None,
    election_source: Any = "__unset__",
    settlement_status: Optional[str] = None,
    settlement_method: Any = "__unset__",
    settlement_attempt_count: Optional[int] = None,
):
    """The election and settlement axes advance independently (PRD §3.7)."""
    if election_status is not None:
        assert obligation["election_status"] == election_status, (
            f"expected election_status {election_status}, "
            f"got {obligation['election_status']}"
        )
    if election_source != "__unset__":
        assert obligation["election_source"] == election_source, (
            f"expected election_source {election_source!r}, "
            f"got {obligation['election_source']!r}"
        )
    if settlement_status is not None:
        assert obligation["settlement_status"] == settlement_status, (
            f"expected settlement_status {settlement_status}, "
            f"got {obligation['settlement_status']}"
        )
    if settlement_method != "__unset__":
        assert obligation["settlement_method"] == settlement_method, (
            f"expected settlement_method {settlement_method!r}, "
            f"got {obligation['settlement_method']!r}"
        )
    if settlement_attempt_count is not None:
        assert obligation["settlement_attempt_count"] == settlement_attempt_count, (
            f"expected settlement_attempt_count {settlement_attempt_count}, "
            f"got {obligation['settlement_attempt_count']}"
        )


def assert_obligation_deadlines(
    obligation: Dict[str, Any],
    obligation_start_utc: Optional[str] = None,
    deadline_utc: Optional[str] = None,
    election_deadline_utc: Optional[str] = None,
    deadline_breached: Optional[bool] = None,
):
    if obligation_start_utc is not None:
        assert_instant(obligation["obligation_start_utc"], obligation_start_utc)
    if deadline_utc is not None:
        assert_instant(obligation["deadline_utc"], deadline_utc)
    if election_deadline_utc is not None:
        assert_instant(obligation["election_deadline_utc"], election_deadline_utc)
    if deadline_breached is not None:
        assert obligation["deadline_breached"] is deadline_breached, (
            f"expected deadline_breached {deadline_breached}, "
            f"got {obligation['deadline_breached']}"
        )


# ─── Segment shape (PRD §3.2) ─────────────────────────


def assert_segment_state(
    segment: Dict[str, Any],
    status: Optional[str] = None,
    disruption_type: Optional[str] = None,
    revised_arrival_utc: Any = "__unset__",
    delay_minutes: Optional[int] = None,
    is_significant_delay: Optional[bool] = None,
    disruption_declared_at_utc: Any = "__unset__",
    cumulative_tarmac_minutes: Optional[int] = None,
    exempted_tarmac_event_count: Optional[int] = None,
):
    if status is not None:
        assert segment["status"] == status, (
            f"expected segment status {status}, got {segment['status']}"
        )
    if disruption_type is not None:
        assert segment["disruption_type"] == disruption_type
    if revised_arrival_utc != "__unset__":
        assert segment["revised_arrival_utc"] == revised_arrival_utc
    if delay_minutes is not None:
        assert segment["delay_minutes"] == delay_minutes, (
            f"expected delay_minutes {delay_minutes}, got {segment['delay_minutes']}"
        )
    if is_significant_delay is not None:
        assert segment["is_significant_delay"] is is_significant_delay, (
            f"expected is_significant_delay {is_significant_delay}, "
            f"got {segment['is_significant_delay']}"
        )
    if disruption_declared_at_utc != "__unset__":
        assert segment["disruption_declared_at_utc"] == disruption_declared_at_utc
    if cumulative_tarmac_minutes is not None:
        assert segment["cumulative_tarmac_minutes"] == cumulative_tarmac_minutes, (
            f"expected cumulative_tarmac_minutes {cumulative_tarmac_minutes}, "
            f"got {segment['cumulative_tarmac_minutes']}"
        )
    if exempted_tarmac_event_count is not None:
        assert segment["exempted_tarmac_event_count"] == exempted_tarmac_event_count


# ─── Sweep and exposure reads ─────────────────────────


def assert_sweep_counters(
    result: Dict[str, Any],
    deadline_breach_flagged_count: Optional[int] = None,
    election_auto_defaulted_count: Optional[int] = None,
    complaint_ack_breach_flagged_count: Optional[int] = None,
    complaint_answer_breach_flagged_count: Optional[int] = None,
    complaint_auto_closed_count: Optional[int] = None,
    open_violation_count: Optional[int] = None,
    policy_profile_version: Optional[int] = None,
):
    checks = {
        "deadline_breach_flagged_count": deadline_breach_flagged_count,
        "election_auto_defaulted_count": election_auto_defaulted_count,
        "complaint_ack_breach_flagged_count": complaint_ack_breach_flagged_count,
        "complaint_answer_breach_flagged_count": complaint_answer_breach_flagged_count,
        "complaint_auto_closed_count": complaint_auto_closed_count,
        "open_violation_count": open_violation_count,
        "policy_profile_version": policy_profile_version,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert result[field] == expected, (
                f"expected {field} == {expected}, got {result[field]}"
            )


def assert_exposure(
    exposure: Dict[str, Any],
    proactive_full_itinerary_cents: Optional[int] = None,
    request_based_proration_cents: Optional[int] = None,
    variant_delta_cents: Optional[int] = None,
    obligated_total_cents: Optional[int] = None,
    remaining_headroom_cents: Optional[int] = None,
    collected_total_cents: Optional[int] = None,
    segment_count: Optional[int] = None,
    unused_segment_count: Optional[int] = None,
    travel_commenced: Optional[bool] = None,
):
    checks = {
        "proactive_full_itinerary_cents": proactive_full_itinerary_cents,
        "request_based_proration_cents": request_based_proration_cents,
        "variant_delta_cents": variant_delta_cents,
        "obligated_total_cents": obligated_total_cents,
        "remaining_headroom_cents": remaining_headroom_cents,
        "collected_total_cents": collected_total_cents,
        "segment_count": segment_count,
        "unused_segment_count": unused_segment_count,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert exposure[field] == expected, (
                f"expected {field} == {expected}, got {exposure[field]}"
            )
    if travel_commenced is not None:
        assert exposure["travel_commenced"] is travel_commenced


# ─── Trail ordering (PRD §3.8) ────────────────────────


def assert_activity_types(rows: List[Dict[str, Any]], expected_types: List[str]):
    actual = [r["activity_type"] for r in rows]
    assert actual == expected_types, (
        f"expected the trail to read {expected_types}, got {actual}"
    )
