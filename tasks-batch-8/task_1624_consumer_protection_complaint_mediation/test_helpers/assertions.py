"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AlertStatus,
    AllocationMethod,
    CaseStatus,
    EventType,
    MediatorStatus,
    OfferStatus,
    PaymentStatus,
    PublicationStatus,
    RatingMethod,
    RatingTier,
    ReferralStatus,
    ResponseStatus,
    RoomStatus,
    SessionStatus,
    SettlementStatus,
    SizeTier,
    WatchStatus,
)

# Strict "three fractional digits" form required by PRD §2.4 for created_at/updated_at.
import re

_MILLIS_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_millis_timestamp(value: str, label: str = "timestamp") -> None:
    """Assert ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    assert isinstance(value, str) and _MILLIS_ISO_RE.match(value), (
        f"{label} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def assert_iso_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 UTC timestamps as instants, tolerating whether the
    serializer renders fractional seconds (e.g. '...:00Z' vs '...:00.000Z')."""

    def _parse(v):
        assert isinstance(v, str), f"{label}: expected str, got {type(v)}"
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)

    assert _parse(actual) == _parse(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_consumer(data: dict) -> None:
    _assert_common_fields(data, "Consumer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_business(data: dict) -> None:
    _assert_common_fields(data, "Business")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["home_state"], str) and len(data["home_state"]) == 2
    assert isinstance(data["operates_in_states"], list)
    assert data["size_tier"] in SizeTier._value2member_map_
    assert data["rating_method"] in RatingMethod._value2member_map_
    assert data["watch_status"] in WatchStatus._value2member_map_
    assert isinstance(data["pattern_score"], int)
    assert isinstance(data["published_complaint_count"], int)
    assert isinstance(data["rating_score"], int)
    assert data["rating_tier"] in RatingTier._value2member_map_
    assert isinstance(data["overdue_response_count"], int)
    assert isinstance(data["next_filing_seq"], int)


def assert_complaint(data: dict) -> None:
    _assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data.get("consumer_id", "")), "Complaint.consumer_id must be a UUID"
    assert is_valid_uuid(data.get("business_id", "")), "Complaint.business_id must be a UUID"
    assert data["case_status"] in CaseStatus._value2member_map_
    assert data["publication_status"] in PublicationStatus._value2member_map_
    assert isinstance(data["filing_seq"], int)
    assert isinstance(data["response_attempts"], int)
    assert isinstance(data["appeal_used"], bool)
    assert isinstance(data["ever_response_overdue"], bool)
    assert isinstance(data["amount_in_dispute_cents"], int)


def assert_complaint_event(data: dict) -> None:
    """Append-only audit entry: id + created_at only; no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "ComplaintEvent.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "ComplaintEvent.created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only events must not carry updated_at"
    assert "version" not in data, "append-only events must not carry version"
    assert data["event_type"] in EventType._value2member_map_


def assert_business_response(data: dict) -> None:
    _assert_common_fields(data, "BusinessResponse")
    assert is_valid_uuid(data.get("complaint_id", "")), "BusinessResponse.complaint_id must be a UUID"
    assert is_valid_uuid(data.get("business_id", "")), "BusinessResponse.business_id must be a UUID"
    assert data["response_status"] in ResponseStatus._value2member_map_
    assert isinstance(data["attempt_number"], int)
    assert isinstance(data["is_late"], bool)


def assert_mediator(data: dict) -> None:
    _assert_common_fields(data, "Mediator")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert data["mediator_status"] in MediatorStatus._value2member_map_
    assert isinstance(data["max_concurrent_cases"], int)
    assert isinstance(data["active_case_count"], int)


def assert_mediation_room(data: dict) -> None:
    _assert_common_fields(data, "MediationRoom")
    assert isinstance(data["room_name"], str) and data["room_name"]
    assert isinstance(data["capacity"], int)
    assert data["room_status"] in RoomStatus._value2member_map_


def assert_mediation_session(data: dict) -> None:
    _assert_common_fields(data, "MediationSession")
    assert data["session_status"] in SessionStatus._value2member_map_
    assert isinstance(data["consumer_confirmed"], bool)
    assert isinstance(data["business_confirmed"], bool)


def assert_settlement_offer(data: dict) -> None:
    _assert_common_fields(data, "SettlementOffer")
    assert data["offer_status"] in OfferStatus._value2member_map_
    assert isinstance(data["offer_seq"], int)
    assert isinstance(data["restitution_amount_cents"], int)
    assert data["restitution_amount_cents"] >= 0


def assert_settlement(data: dict) -> None:
    _assert_common_fields(data, "Settlement")
    assert data["settlement_status"] in SettlementStatus._value2member_map_
    assert isinstance(data["restitution_amount_cents"], int)
    assert isinstance(data["mediation_fee_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["fulfilled_cents"], int)
    assert isinstance(data["outstanding_cents"], int)


def assert_restitution_payment(data: dict) -> None:
    _assert_common_fields(data, "RestitutionPayment")
    assert data["payment_status"] in PaymentStatus._value2member_map_
    assert isinstance(data["amount_cents"], int)
    assert data["allocation_method"] in AllocationMethod._value2member_map_
    assert isinstance(data["allocations"], list)


def assert_enforcement_referral(data: dict) -> None:
    _assert_common_fields(data, "EnforcementReferral")
    assert data["referral_status"] in ReferralStatus._value2member_map_
    assert isinstance(data["pattern_score_at_referral"], int)


def assert_scam_alert(data: dict) -> None:
    _assert_common_fields(data, "ScamAlert")
    assert data["alert_status"] in AlertStatus._value2member_map_
    assert isinstance(data["title"], str) and data["title"]


def assert_settlement_conservation(settlement: dict) -> None:
    """Domain invariant (PRD §3.6): while a settlement stands in DRAFT, EXECUTED,
    FULFILLED, or BREACHED, outstanding_cents == restitution - fulfilled_cents."""
    if settlement["settlement_status"] in (
        SettlementStatus.DRAFT.value,
        SettlementStatus.EXECUTED.value,
        SettlementStatus.FULFILLED.value,
        SettlementStatus.BREACHED.value,
    ):
        total = settlement["fulfilled_cents"] + settlement["outstanding_cents"]
        assert total == settlement["restitution_amount_cents"], (
            f"restitution conservation violated: fulfilled {settlement['fulfilled_cents']} + "
            f"outstanding {settlement['outstanding_cents']} != restitution "
            f"{settlement['restitution_amount_cents']}"
        )
