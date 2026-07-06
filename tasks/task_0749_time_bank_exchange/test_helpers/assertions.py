"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


VALID_TRUST_TIERS = {"UNVERIFIED", "BASIC", "TRUSTED", "ANCHOR"}
VALID_OFFER_STATUS = {"ACTIVE", "PAUSED", "ARCHIVED"}
VALID_REQUEST_STATUS = {"OPEN", "MATCHED", "EXPIRED", "CANCELLED", "CLOSED"}
VALID_EXCHANGE_STATUS = {"SCHEDULED", "DELIVERED", "DISPUTED", "SETTLED", "CANCELLED"}
VALID_REDEMPTION_STATUS = {"REQUESTED", "FULFILLED", "VOIDED"}
VALID_CREDENTIAL_STATUS = {"SUBMITTED", "REVISION_REQUESTED", "VERIFIED", "REJECTED"}
VALID_CREDENTIAL_TYPE = {"ID_CHECK", "SKILL_ATTEST", "REFERENCE_ATTEST"}
VALID_PROJECT_STATE = {"PLANNING", "OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
VALID_SHIFT_STATUS = {"OPEN", "FILLED", "COMPLETED", "CANCELLED"}
VALID_ASSIGNMENT_STATUS = {"CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"}
VALID_DISPUTE_STATUS = {"OPEN", "RESOLVED_UPHELD", "RESOLVED_REJECTED", "WITHDRAWN"}
VALID_DISPUTE_REASON = {"NO_SHOW", "INCOMPLETE_SERVICE", "WRONG_DURATION", "OTHER"}
VALID_ENTRY_KIND = {"EARNED", "SPENT", "REDEMPTION", "ADMIN_ADJUSTMENT", "DISPUTE_REVERSAL"}


def _assert_common_fields(data: dict, entity_label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_label}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_label}.version must be an integer >= 1, got {data.get('version')!r}"


def assert_member(data: dict) -> None:
    _assert_common_fields(data, "Member")
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["display_name"], str)
    assert isinstance(data["home_neighborhood"], str)
    assert data["trust_tier"] in VALID_TRUST_TIERS, \
        f"Member.trust_tier must be one of {VALID_TRUST_TIERS}, got {data['trust_tier']!r}"
    assert isinstance(data["verified_credential_count"], int)
    assert isinstance(data["completed_exchange_count"], int)
    assert isinstance(data["chronological_balance_minutes"], int)
    assert isinstance(data["forward_looking_balance_minutes"], int)
    assert isinstance(data["lifetime_earned_minutes"], int) and data["lifetime_earned_minutes"] >= 0
    assert isinstance(data["lifetime_redeemed_minutes"], int) and data["lifetime_redeemed_minutes"] >= 0
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert isinstance(data["is_suspended"], bool)


def assert_skill_offer(data: dict) -> None:
    _assert_common_fields(data, "SkillOffer")
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["skill_code"], str) and len(data["skill_code"]) > 0
    assert isinstance(data["title"], str)
    assert isinstance(data["minutes_per_session"], int)
    assert data["required_trust_tier"] in VALID_TRUST_TIERS
    assert data["status"] in VALID_OFFER_STATUS


def assert_skill_request(data: dict) -> None:
    _assert_common_fields(data, "SkillRequest")
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["needed_minutes"], int)
    assert is_iso8601_timestamp(data["earliest_start_utc"])
    assert is_iso8601_timestamp(data["latest_start_utc"])
    assert data["latest_start_utc"] > data["earliest_start_utc"]
    assert data["status"] in VALID_REQUEST_STATUS


def assert_exchange(data: dict) -> None:
    _assert_common_fields(data, "Exchange")
    assert is_valid_uuid(data["offer_id"])
    assert is_valid_uuid(data["request_id"])
    assert is_valid_uuid(data["provider_member_id"])
    assert is_valid_uuid(data["requester_member_id"])
    assert data["provider_member_id"] != data["requester_member_id"], \
        "Exchange.provider_member_id and requester_member_id must differ"
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert isinstance(data["committed_minutes"], int) and data["committed_minutes"] > 0
    assert data["status"] in VALID_EXCHANGE_STATUS
    if data.get("settled_at_utc") is not None:
        assert is_iso8601_timestamp(data["settled_at_utc"])


def assert_ledger_entry(data: dict) -> None:
    # LedgerEntry has common_fields:false → NO updated_at, NO version.
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_valid_uuid(data["member_id"])
    assert data["entry_kind"] in VALID_ENTRY_KIND
    assert isinstance(data["delta_minutes"], int)
    assert is_iso8601_timestamp(data["posted_at"])


def assert_redemption(data: dict) -> None:
    _assert_common_fields(data, "Redemption")
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["reward_code"], str)
    assert isinstance(data["minutes_cost"], int) and data["minutes_cost"] > 0
    assert data["status"] in VALID_REDEMPTION_STATUS
    if data.get("fulfilled_at_utc") is not None:
        assert is_iso8601_timestamp(data["fulfilled_at_utc"])


def assert_credential(data: dict) -> None:
    _assert_common_fields(data, "VerificationCredential")
    assert is_valid_uuid(data["subject_member_id"])
    assert data["credential_type"] in VALID_CREDENTIAL_TYPE
    assert isinstance(data["evidence_url"], str)
    assert data["status"] in VALID_CREDENTIAL_STATUS
    assert isinstance(data["revision_round"], int)
    assert 0 <= data["revision_round"] <= 2


def assert_group_project(data: dict) -> None:
    _assert_common_fields(data, "GroupProject")
    assert is_valid_uuid(data["organizer_member_id"])
    assert isinstance(data["title"], str)
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["window_end_utc"] > data["window_start_utc"]
    assert 0 < float(data["minimum_completed_ratio"]) <= 1
    assert data["aggregate_state"] in VALID_PROJECT_STATE
    assert isinstance(data["total_committed_minutes"], int)


def assert_project_shift(data: dict) -> None:
    _assert_common_fields(data, "ProjectShift")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert data["status"] in VALID_SHIFT_STATUS


def assert_shift_assignment(data: dict) -> None:
    _assert_common_fields(data, "ShiftAssignment")
    assert is_valid_uuid(data["shift_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in VALID_ASSIGNMENT_STATUS
    if data.get("check_in_utc") is not None:
        assert is_iso8601_timestamp(data["check_in_utc"])


def assert_dispute(data: dict) -> None:
    _assert_common_fields(data, "Dispute")
    assert is_valid_uuid(data["exchange_id"])
    assert is_valid_uuid(data["raised_by_member_id"])
    assert data["reason_code"] in VALID_DISPUTE_REASON
    assert isinstance(data["claimed_delta_minutes"], int) and data["claimed_delta_minutes"] > 0
    assert data["claimed_delta_minutes"] % 15 == 0
    assert data["status"] in VALID_DISPUTE_STATUS


def assert_impact_report(data: dict) -> None:
    _assert_common_fields(data, "ImpactReport")
    assert isinstance(data["report_month"], str)
    assert len(data["report_month"]) == 7 and data["report_month"][4] == "-"
    assert isinstance(data["total_hours_exchanged"], (int, float))
    assert isinstance(data["unique_active_members"], int)


def assert_ledger_conservation(before_sum: int, after_sum: int, expected_delta: int = 0) -> None:
    """The sum of member chronological balances shifts by expected_delta across
    an operation; assert against arithmetic drift."""
    assert after_sum - before_sum == expected_delta, \
        f"Ledger conservation broke: sum went {before_sum} -> {after_sum} " \
        f"(delta {after_sum - before_sum}, expected {expected_delta})"
