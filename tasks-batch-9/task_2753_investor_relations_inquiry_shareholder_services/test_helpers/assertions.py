"""Entity-shape assertions, timestamp canonicalisation and domain invariants."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import pytest

from .constants import (
    ALLOCATION_SCORE_THRESHOLD,
    HOLDER_CONTACT_TYPES,
    OPEN_INQUIRY_STATUSES,
    REQUEST_REQUESTED,
    SLA_HOURS_BY_QUEUE,
)

# ---------------------------------------------------------------------------
# Timestamp handling
# ---------------------------------------------------------------------------


def parse_ts(value: str) -> datetime:
    """Parse any ISO-8601 UTC instant the API may emit into a datetime."""
    assert isinstance(value, str) and value, f"expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_ts(value: str) -> str:
    """Render an instant as ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Sub-second precision is normalised here so that assertions compare instants
    rather than string widths.
    """
    moment = parse_ts(value)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def assert_ts_equals(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two instants after canonicalising both sides."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert canonical_ts(actual) == canonical_ts(expected), (
        f"{label}: expected {canonical_ts(expected)}, got {canonical_ts(actual)}"
    )


def assert_utc_timestamp(value: Any, label: str = "timestamp") -> None:
    """The value must be a parseable UTC instant."""
    assert value is not None, f"{label} must not be null"
    parse_ts(value)


def hours_after(instant: str, hours: int) -> str:
    """The canonical instant ``hours`` after ``instant``."""
    return canonical_ts(
        (parse_ts(instant) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    )


def days_after(instant: str, days: int) -> str:
    return hours_after(instant, days * 24)


def sla_due_at(written_at: str, routing_queue: str) -> str:
    """The deadline a write at ``written_at`` earns for ``routing_queue``."""
    return hours_after(written_at, SLA_HOURS_BY_QUEUE[routing_queue])


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def approx_2dp(expected: float):
    return pytest.approx(expected, abs=0.005)


def approx_4dp(expected: float):
    return pytest.approx(expected, abs=0.00005)


def assert_cents(value: Any, label: str = "amount_cents") -> None:
    """Money is carried in whole cents as an integer."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Common properties (PRD 2.5)
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity carries id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"missing universal property {field!r}"
    assert isinstance(entity["id"], str) and entity["id"], "id must be a non-empty string"
    assert "_" not in entity["id"], "id must be a bare UUID with no prefix"
    assert_utc_timestamp(entity["created_at"], "created_at")
    assert_utc_timestamp(entity["updated_at"], "updated_at")
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_version(entity: Dict[str, Any], expected: int, label: str = "entity") -> None:
    assert entity["version"] == expected, (
        f"{label}.version: expected {expected}, got {entity['version']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_company(company: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(company)
    for field in (
        "ticker",
        "legal_name",
        "shares_outstanding",
        "dividend_reserve_cents",
        "dividend_paid_cents",
        "disclosure_posture",
        "open_inquiry_count",
    ):
        assert field in company, f"Company is missing {field!r}"
    assert_cents(company["dividend_reserve_cents"], "dividend_reserve_cents")
    assert_cents(company["dividend_paid_cents"], "dividend_paid_cents")
    assert isinstance(company["open_inquiry_count"], int)
    _assert_expected(company, expected, "Company")


def assert_contact(contact: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(contact)
    for field in (
        "company_id",
        "contact_type",
        "display_name",
        "email",
        "shares_held",
        "ownership_pct",
        "target_tier",
        "nda_on_file",
        "coverage_status",
        "activist_flag",
        "model_access_status",
        "threat_level",
        "dividend_received_cents",
    ):
        assert field in contact, f"Contact is missing {field!r}"
    assert_cents(contact["dividend_received_cents"], "dividend_received_cents")
    assert isinstance(contact["shares_held"], int)
    _assert_expected(contact, expected, "Contact")


def assert_disclosure(disclosure: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(disclosure)
    for field in (
        "company_id",
        "disclosure_type",
        "fact_key",
        "metric",
        "period_label",
        "guidance_low",
        "guidance_high",
        "is_guidance",
        "status",
        "published_at",
    ):
        assert field in disclosure, f"Disclosure is missing {field!r}"
    _assert_expected(disclosure, expected, "Disclosure")


def assert_inquiry(inquiry: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(inquiry)
    for field in (
        "company_id",
        "contact_id",
        "topic_category",
        "subject",
        "requests_nonpublic_detail",
        "linked_prior_inquiry_id",
        "sensitivity_score",
        "routing_queue",
        "sla_due_at",
        "status",
        "answered_at",
    ):
        assert field in inquiry, f"InquiryTicket is missing {field!r}"
    assert isinstance(inquiry["sensitivity_score"], int), (
        "sensitivity_score is an integer and is never rounded"
    )
    _assert_expected(inquiry, expected, "InquiryTicket")


def assert_response_draft(draft: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(draft)
    for field in (
        "inquiry_id",
        "body_text",
        "disclosure_class",
        "cited_disclosure_id",
        "author_user_id",
        "reviewer_user_id",
        "reviewer_note",
        "pinned_disclosure_version",
        "blocked_reason",
        "revision_round",
        "status",
    ):
        assert field in draft, f"ResponseDraft is missing {field!r}"
    assert isinstance(draft["revision_round"], int)
    _assert_expected(draft, expected, "ResponseDraft")


def assert_estimate(estimate: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(estimate)
    for field in ("contact_id", "metric", "period_label", "value", "status", "submitted_at"):
        assert field in estimate, f"EstimateSubmission is missing {field!r}"
    _assert_expected(estimate, expected, "EstimateSubmission")


def assert_roadshow_event(event: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(event)
    for field in (
        "company_id",
        "event_type",
        "venue_city",
        "window_start",
        "window_end",
        "slot_minutes",
        "capacity_slots",
        "status",
        "allocated_count",
        "waitlisted_count",
        "released_count",
        "declined_count",
        "request_ledger_total",
    ):
        assert field in event, f"RoadshowEvent is missing {field!r}"
    assert event["allocated_count"] <= event["capacity_slots"], (
        "allocated_count may never exceed capacity_slots"
    )
    _assert_expected(event, expected, "RoadshowEvent")


def assert_meeting_request(request: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(request)
    for field in (
        "event_id",
        "contact_id",
        "requested_slot_start",
        "requested_slot_end",
        "provisional_priority_score",
        "final_priority_score",
        "status",
        "allocated_at",
        "release_reason",
        "promoted_from_waitlist",
    ):
        assert field in request, f"MeetingRequest is missing {field!r}"
    _assert_expected(request, expected, "MeetingRequest")


def assert_instruction(instruction: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(instruction)
    for field in (
        "company_id",
        "instruction_type",
        "funding_mode",
        "status",
        "submitted_by_user_id",
        "acknowledged_by_user_id",
        "executed_by_user_id",
        "snapshot_holder_count",
        "snapshot_shares_total",
        "payout_ledger",
        "total_payout_cents",
        "executed_at",
        "decision_reason",
    ):
        assert field in instruction, f"TransferAgentInstruction is missing {field!r}"
    _assert_expected(instruction, expected, "TransferAgentInstruction")


def assert_consensus(payload: Dict[str, Any], **expected: Any) -> None:
    for field in (
        "company_id",
        "metric",
        "period_label",
        "variant",
        "eligible_count",
        "simple_mean",
        "guidance_anchored",
        "band_low",
        "band_high",
        "outlier_excluded_count",
        "trimmed_applied",
        "consensus_mean",
        "dispersion_pct",
    ):
        assert field in payload, f"consensus payload is missing {field!r}"
    _assert_expected(payload, expected, "consensus")


def assert_allocation_summary(summary: Dict[str, Any], **expected: Any) -> None:
    for field in (
        "event_id",
        "event_status",
        "evaluated_count",
        "allocated_count",
        "waitlisted_count",
        "threshold_deferred_count",
    ):
        assert field in summary, f"allocation summary is missing {field!r}"
    _assert_expected(summary, expected, "allocation summary")


def _assert_expected(actual: Dict[str, Any], expected: Dict[str, Any], label: str) -> None:
    for key, value in expected.items():
        assert key in actual, f"{label} is missing {key!r}"
        assert actual[key] == value, f"{label}.{key}: expected {value!r}, got {actual[key]!r}"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_request_ledger_conserved(event: Dict[str, Any], still_requested: int) -> None:
    """request_ledger_total equals the sum of every terminal and pending state."""
    total = (
        event["allocated_count"]
        + event["waitlisted_count"]
        + event["released_count"]
        + event["declined_count"]
        + still_requested
    )
    assert event["request_ledger_total"] == total, (
        "request_ledger_total must equal allocated + waitlisted + released + declined "
        f"+ still-REQUESTED; got {event['request_ledger_total']} against {total}"
    )


def count_requested(requests: Iterable[Dict[str, Any]]) -> int:
    return sum(1 for row in requests if row["status"] == REQUEST_REQUESTED)


def assert_reserve_plus_paid_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Executing or reversing a dividend moves cash without creating it."""
    lhs = before["dividend_reserve_cents"] + before["dividend_paid_cents"]
    rhs = after["dividend_reserve_cents"] + after["dividend_paid_cents"]
    assert lhs == rhs, (
        f"dividend_reserve_cents + dividend_paid_cents changed from {lhs} to {rhs}"
    )


def assert_holder_credits_match_paid(
    company: Dict[str, Any], contacts: List[Dict[str, Any]]
) -> None:
    """Holder credits always add up to the issuer's dividend_paid_cents."""
    credited = sum(contact["dividend_received_cents"] for contact in contacts)
    assert credited == company["dividend_paid_cents"], (
        f"holders were credited {credited} but the issuer reports "
        f"{company['dividend_paid_cents']}"
    )


def assert_payout_ledger(
    instruction: Dict[str, Any], expected_rows: List[Dict[str, Any]]
) -> None:
    """The ledger rows, their order and the round-then-sum total."""
    ledger = instruction["payout_ledger"]
    assert isinstance(ledger, list), "payout_ledger must be a list once executed"
    assert len(ledger) == len(expected_rows), (
        f"expected {len(expected_rows)} payout rows, got {len(ledger)}"
    )
    for index, (row, expected) in enumerate(zip(ledger, expected_rows)):
        for key, value in expected.items():
            assert row[key] == value, (
                f"payout_ledger[{index}].{key}: expected {value!r}, got {row[key]!r}"
            )
        assert_cents(row["amount_cents"], f"payout_ledger[{index}].amount_cents")
    assert instruction["total_payout_cents"] == sum(
        row["amount_cents"] for row in ledger
    ), "total_payout_cents must be the sum of the rounded per-holder amounts"


def assert_open_inquiry_count(company: Dict[str, Any], inquiries: List[Dict[str, Any]]) -> None:
    """open_inquiry_count is a full recount of every non-ANSWERED inquiry."""
    expected = sum(1 for row in inquiries if row["status"] in OPEN_INQUIRY_STATUSES)
    assert company["open_inquiry_count"] == expected, (
        f"open_inquiry_count: expected {expected}, got {company['open_inquiry_count']}"
    )


def assert_snapshot_excludes_analysts(
    instruction: Dict[str, Any], contacts: List[Dict[str, Any]]
) -> None:
    """The acknowledgement snapshot counts only share-holding holders."""
    holders = [
        contact
        for contact in contacts
        if contact["contact_type"] in HOLDER_CONTACT_TYPES and contact["shares_held"] > 0
    ]
    assert instruction["snapshot_holder_count"] == len(holders)
    assert instruction["snapshot_shares_total"] == sum(c["shares_held"] for c in holders)


def assert_below_allocation_threshold(request: Dict[str, Any]) -> None:
    """A request scoring under the threshold is never allocated."""
    assert request["final_priority_score"] < ALLOCATION_SCORE_THRESHOLD
    assert request["status"] != "ALLOCATED"
