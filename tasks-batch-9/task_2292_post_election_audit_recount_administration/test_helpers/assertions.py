"""Entity assertions and domain invariant checkers."""

from datetime import datetime
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AuditBatchRetrievalStatus,
    AuditBatchTallyStatus,
    AuditRoundStatus,
    AuditStatus,
    AuditType,
    BallotBatchCustodyStatus,
    BallotInterpretationStatus,
    ContestStatus,
    ContestType,
    CorrectiveActionCategory,
    CorrectiveActionStatus,
    CustodyEventType,
    DepositStatus,
    DiscrepancyStatus,
    DiscrepancyType,
    ElectionStatus,
    ManualTallyStatus,
    MeasureVariant,
    ObserverCredentialStatus,
    RecountScope,
    RecountStatus,
    RecountTriggerType,
    RefundVariant,
    TallyTeamStatus,
    TimelineStatus,
)


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_fields(data: Dict[str, Any]) -> None:
    """id, created_at, updated_at and version, carried by every versioned entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_four_decimal_places(value: float, label: str = "value") -> None:
    """A rate carried to exactly four decimal places."""
    assert value is not None, f"{label} must be present"
    assert round(float(value), 4) == float(
        value
    ), f"{label} must carry at most 4 decimal places, got {value}"


def assert_two_decimal_places(value: float, label: str = "value") -> None:
    """An hour figure carried to exactly two decimal places."""
    assert value is not None, f"{label} must be present"
    assert round(float(value), 2) == float(
        value
    ), f"{label} must carry at most 2 decimal places, got {value}"


def assert_same_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Two ISO 8601 UTC instants name the same moment.

    Stamped timestamps carry three fractional digits, so a stamped value is
    compared by instant rather than by string.
    """
    assert isinstance(actual, str) and actual, f"{label} must be a timestamp, got {actual!r}"

    def _parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert _parse(actual) == _parse(expected), (
        f"{label} must name the instant {expected}, got {actual}"
    )


def assert_integer_cents(value: Any, label: str = "amount") -> None:
    """A money field, which the PRD holds as an integer number of cents."""
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{label} must be an integer number of cents, got {value!r}"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_election(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["election_name"], str) and data["election_name"]
    assert isinstance(data["election_date"], str) and data["election_date"]
    assert is_iso8601_timestamp(data["certification_deadline_at"])
    assert is_iso8601_timestamp(data["effective_certification_deadline_at"])
    assert is_iso8601_timestamp(data["contest_window_ends_at"])
    assert data["status"] in _values(ElectionStatus), data["status"]
    assert data["timeline_status"] in _values(TimelineStatus), data["timeline_status"]
    assert isinstance(data["certification_risk_flag"], bool)
    assert isinstance(data["open_audit_count"], int) and data["open_audit_count"] >= 0
    assert isinstance(data["open_recount_count"], int) and data["open_recount_count"] >= 0


def assert_contest(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["election_id"])
    assert isinstance(data["contest_label"], str) and data["contest_label"]
    assert isinstance(data["office_name"], str) and data["office_name"]
    assert data["contest_type"] in _values(ContestType), data["contest_type"]
    assert isinstance(data["candidate_names"], list) and data["candidate_names"]
    assert isinstance(data["ballots_cast"], int) and data["ballots_cast"] >= 0
    assert isinstance(data["cvr_available"], bool)
    assert data["status"] in _values(ContestStatus), data["status"]
    assert isinstance(data["automatic_recount_required"], bool)
    assert isinstance(data["open_recount_count"], int) and data["open_recount_count"] >= 0
    if data.get("margin_pct") is not None:
        assert_four_decimal_places(data["margin_pct"], "margin_pct")


def assert_ballot_batch(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["election_id"])
    assert is_valid_uuid(data["contest_id"])
    assert isinstance(data["batch_label"], str) and data["batch_label"]
    assert isinstance(data["storage_location_code"], str) and data["storage_location_code"]
    assert isinstance(data["ballot_count"], int) and data["ballot_count"] >= 1
    assert isinstance(data["machine_votes"], dict) and data["machine_votes"]
    assert isinstance(data["current_seal_number"], str) and data["current_seal_number"]
    assert data["custody_status"] in _values(BallotBatchCustodyStatus), data[
        "custody_status"
    ]
    assert data["open_checkout_count"] in (
        0,
        1,
    ), f"open_checkout_count is always 0 or 1, got {data['open_checkout_count']}"
    assert isinstance(data["checkout_cycle_count"], int)
    assert data["checkout_cycle_count"] >= 0


def assert_custody_event(data: Dict[str, Any]) -> None:
    """The custody log is append-only: no updated_at and no version dimension."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an append-only custody event carries no updated_at"
    assert "version" not in data, "an append-only custody event carries no version"
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert is_valid_uuid(data["ballot_batch_id"])
    assert data["event_type"] in _values(CustodyEventType), data["event_type"]
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_audit(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["contest_id"])
    assert data["audit_type"] in _values(AuditType), data["audit_type"]
    assert data["measure_variant"] in _values(MeasureVariant), data["measure_variant"]
    assert data["status"] in _values(AuditStatus), data["status"]
    assert data["timeline_status"] in _values(TimelineStatus), data["timeline_status"]
    assert isinstance(data["escalation_level"], int) and data["escalation_level"] >= 0
    assert isinstance(data["cumulative_sampled_batches"], int)
    assert isinstance(data["counted_ballots"], int)
    assert isinstance(data["cumulative_net_error_votes"], int)
    assert isinstance(data["extension_days_granted"], int)
    assert isinstance(data["public_report_published"], bool)
    assert_four_decimal_places(data["discrepancy_measure"], "discrepancy_measure")
    if data.get("slack_hours") is not None:
        assert_two_decimal_places(data["slack_hours"], "slack_hours")
    if data.get("effective_slack_hours") is not None:
        assert_two_decimal_places(data["effective_slack_hours"], "effective_slack_hours")


def assert_audit_round(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["audit_id"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["is_full_hand_count"], bool)
    assert isinstance(data["sample_size_batches"], int) and data["sample_size_batches"] >= 1
    assert isinstance(data["selection_sequence"], list)
    assert isinstance(data["counted_ballots"], int)
    assert isinstance(data["discrepancy_count"], int)
    assert isinstance(data["cumulative_net_error_votes"], int)
    assert data["status"] in _values(AuditRoundStatus), data["status"]
    assert_four_decimal_places(data["round_measure"], "round_measure")


def assert_audit_batch(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["audit_round_id"])
    assert is_valid_uuid(data["ballot_batch_id"])
    assert isinstance(data["selection_index"], int) and data["selection_index"] >= 0
    assert isinstance(data["ballot_count"], int) and data["ballot_count"] >= 1
    assert data["retrieval_status"] in _values(AuditBatchRetrievalStatus), data[
        "retrieval_status"
    ]
    assert data["tally_status"] in _values(AuditBatchTallyStatus), data["tally_status"]


def assert_tally_team(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["election_id"])
    assert isinstance(data["team_label"], str) and data["team_label"]
    assert isinstance(data["room_code"], str) and data["room_code"]
    assert isinstance(data["members"], list)
    assert len(data["members"]) <= 6, "a tally team never carries more than six members"
    assert isinstance(data["party_counts"], dict)
    assert isinstance(data["is_bipartisan"], bool)
    assert data["status"] in _values(TallyTeamStatus), data["status"]


def assert_manual_tally(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["audit_batch_id"])
    assert is_valid_uuid(data["tally_team_id"])
    assert is_iso8601_timestamp(data["session_start_at"])
    assert is_iso8601_timestamp(data["session_end_at"])
    assert data["session_start_at"] < data["session_end_at"], (
        "session_start_at must be strictly before session_end_at"
    )
    assert isinstance(data["ambiguous_ballot_count"], int)
    assert isinstance(data["no_vote_count"], int)
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data["status"] in _values(ManualTallyStatus), data["status"]
    if data.get("relative_taint") is not None:
        assert_four_decimal_places(data["relative_taint"], "relative_taint")


def assert_discrepancy(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["manual_tally_id"])
    assert data["discrepancy_type"] in _values(DiscrepancyType), data["discrepancy_type"]
    assert isinstance(data["magnitude_votes"], int)
    assert data["status"] in _values(DiscrepancyStatus), data["status"]
    assert_four_decimal_places(data["relative_taint"], "relative_taint")


def assert_ballot_interpretation(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["manual_tally_id"])
    assert isinstance(data["ballot_ref"], str) and data["ballot_ref"]
    assert isinstance(data["board_votes"], list)
    assert isinstance(data["votes_cast"], int) and data["votes_cast"] >= 0
    assert isinstance(data["accept_count"], int) and data["accept_count"] >= 0
    assert isinstance(data["reject_count"], int) and data["reject_count"] >= 0
    assert isinstance(data["quorum_met"], bool)
    assert data["status"] in _values(BallotInterpretationStatus), data["status"]


def assert_recount(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["contest_id"])
    assert data["trigger_type"] in _values(RecountTriggerType), data["trigger_type"]
    assert data["scope"] in _values(RecountScope), data["scope"]
    assert data["status"] in _values(RecountStatus), data["status"]
    assert data["deposit_status"] in _values(DepositStatus), data["deposit_status"]
    assert data["refund_variant"] in _values(RefundVariant), data["refund_variant"]
    for money_field in (
        "required_deposit_cents",
        "deposit_paid_cents",
        "refunded_cents",
        "forfeited_cents",
        "admin_retained_cents",
        "actual_cost_cents",
    ):
        assert_integer_cents(data[money_field], money_field)
    assert isinstance(data["ballots_in_scope"], int) and data["ballots_in_scope"] >= 0


def assert_corrective_action(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["discrepancy_id"])
    assert data["category"] in _values(CorrectiveActionCategory), data["category"]
    assert isinstance(data["description"], str) and data["description"]
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in _values(CorrectiveActionStatus), data["status"]


def assert_observer_credential(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["election_id"])
    assert isinstance(data["organization_name"], str) and data["organization_name"]
    assert isinstance(data["room_code"], str) and data["room_code"]
    assert is_iso8601_timestamp(data["access_start_at"])
    assert is_iso8601_timestamp(data["access_end_at"])
    assert data["access_start_at"] < data["access_end_at"], (
        "access_start_at must be strictly before access_end_at"
    )
    assert data["status"] in _values(ObserverCredentialStatus), data["status"]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_deposit_ledger_conserved(recount: Dict[str, Any]) -> None:
    """deposit_paid_cents == refunded_cents + forfeited_cents + admin_retained_cents."""
    total = (
        recount["refunded_cents"]
        + recount["forfeited_cents"]
        + recount["admin_retained_cents"]
    )
    assert recount["deposit_paid_cents"] == total, (
        "the deposit ledger must balance: "
        f"deposit_paid_cents {recount['deposit_paid_cents']} != "
        f"refunded {recount['refunded_cents']} + forfeited {recount['forfeited_cents']} "
        f"+ admin_retained {recount['admin_retained_cents']}"
    )


def assert_ballot_accounting_identity(
    manual_tally: Dict[str, Any], batch_ballot_count: int
) -> None:
    """Counted votes plus ambiguous plus blank ballots equal the batch ballot count."""
    counted = sum((manual_tally.get("counted_votes") or {}).values())
    total = (
        counted
        + manual_tally["ambiguous_ballot_count"]
        + manual_tally["no_vote_count"]
    )
    assert total == batch_ballot_count, (
        f"ballot accounting must sum to {batch_ballot_count}, got {total} "
        f"(counted {counted}, ambiguous {manual_tally['ambiguous_ballot_count']}, "
        f"blank {manual_tally['no_vote_count']})"
    )


def assert_custody_log_ordered(events: list) -> None:
    """The custody log reads in ascending sequence_no starting at 1."""
    for index, event in enumerate(events, start=1):
        assert event["sequence_no"] == index, (
            f"custody log must be numbered consecutively from 1: "
            f"position {index} carries sequence_no {event['sequence_no']}"
        )
