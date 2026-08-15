"""Entity assertions and domain invariant checkers.

Every assertion here enforces only rules the PRD states verbatim: envelope-common
fields (id/created_at/updated_at/version), enum membership, and the case ledger
conservation invariant.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    BlackoutStatus,
    DistributionStatus,
    DLRStatus,
    ElectionStatus,
    ForfeitureStatus,
    LocateStatus,
    NoticeType,
    PayoutStatus,
    PBGCTransferStatus,
    SearchCaseStatus,
    TerminationCaseStatus,
)


def _parse_instant(value):
    """Parse an ISO 8601 instant (with or without fractional digits) to UTC."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equal(actual, expected_iso, label="timestamp"):
    """Assert two ISO 8601 strings denote the same instant.

    The PRD pins clock *values* (e.g., issued_at == the completion clock time);
    rendering (fractional digits) is an implementation choice, so compare the
    parsed instants rather than the raw strings.
    """
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_append_only_fields(data, label):
    """Append-only log rows carry id and created_at only (PRD: neither
    updated_at nor version)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def _assert_optional_instant(data, field, label):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{label}.{field} must be null or ISO 8601 UTC"
    )


def assert_termination_case(data):
    _assert_common_fields(data, "TerminationCase")
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert isinstance(data["sponsor_ein"], str) and len(data["sponsor_ein"]) == 9
    assert isinstance(data["plan_number"], str) and len(data["plan_number"]) == 3
    assert data["restoration_policy"] in ("NOMINAL", "EARNINGS_ADJUSTED")
    assert data["status"] in {s.value for s in TerminationCaseStatus}
    for field in (
        "total_participant_count",
        "resolved_participant_count",
        "missing_participant_count",
        "total_plan_assets_cents",
        "sponsor_contribution_cents",
        "paid_out_cents",
        "pbgc_transferred_cents",
        "forfeited_cents",
        "expense_paid_cents",
        "remaining_undistributed_cents",
    ):
        assert isinstance(data[field], int), f"TerminationCase.{field} must be int"
    assert isinstance(data["all_participants_resolved"], bool)
    assert isinstance(data["blackout_active"], bool)
    _assert_optional_instant(data, "default_treatment_date", "TerminationCase")


def assert_participant(data):
    _assert_common_fields(data, "Participant")
    assert is_valid_uuid(data.get("termination_case_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ssn"], str) and len(data["ssn"]) == 9
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["vested_pct"], int) and 0 <= data["vested_pct"] <= 100
    for field in (
        "vested_balance_cents",
        "termination_expense_share_cents",
        "net_distributable_cents",
        "restoration_credit_cents",
    ):
        assert isinstance(data[field], int), f"Participant.{field} must be int"
    assert data["locate_status"] in {s.value for s in LocateStatus}
    assert data["distribution_status"] in {s.value for s in DistributionStatus}
    for field in ("flagged_at", "declared_missing_at", "located_at"):
        _assert_optional_instant(data, field, "Participant")
    assert "active_search_case_id" in data


def assert_search_case(data):
    _assert_common_fields(data, "MissingSearchCase")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert is_valid_uuid(data.get("termination_case_id", ""))
    assert data["status"] in {s.value for s in SearchCaseStatus}
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    for field in ("resolved_at", "exhausted_at"):
        _assert_optional_instant(data, field, "MissingSearchCase")
    assert "exhausted_by_user_id" in data
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_search_attempt(data):
    _assert_append_only_fields(data, "SearchAttempt")
    assert is_valid_uuid(data.get("search_case_id", ""))
    assert data["method"] in (
        "COMMERCIAL_LOCATOR",
        "PUBLIC_RECORDS",
        "CREDIT_BUREAU",
        "CERTIFIED_MAIL",
    )
    assert data["outcome"] in ("NO_RESULT", "LOCATED")
    assert is_iso8601_timestamp(data.get("attempted_at", ""))


def assert_notice(data):
    _assert_common_fields(data, "ParticipantNotice")
    assert is_valid_uuid(data.get("termination_case_id", ""))
    assert data["notice_type"] in {t.value for t in NoticeType}
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("action_effective_date", ""))
    assert "superseded_by_id" in data


def assert_blackout_period(data):
    _assert_common_fields(data, "BlackoutPeriod")
    assert is_valid_uuid(data.get("termination_case_id", ""))
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in {s.value for s in BlackoutStatus}
    _assert_optional_instant(data, "activated_at", "BlackoutPeriod")
    _assert_optional_instant(data, "completed_at", "BlackoutPeriod")


def assert_election(data):
    _assert_common_fields(data, "DistributionElection")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert data["election_method"] in (
        "LUMP_SUM_CHECK",
        "DIRECT_ROLLOVER_IRA",
        "DIRECT_ROLLOVER_QUALIFIED_PLAN",
    )
    assert data["status"] in {s.value for s in ElectionStatus}


def assert_payout(data):
    _assert_common_fields(data, "Payout")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert "distribution_election_id" in data
    assert data["source"] in ("ELECTION", "DEFAULT_TREATMENT")
    assert data["method"] in (
        "LUMP_SUM_CHECK",
        "DIRECT_ROLLOVER_IRA",
        "DIRECT_ROLLOVER_QUALIFIED_PLAN",
        "AUTO_ROLLOVER_IRA",
    )
    for field in ("gross_cents", "withholding_cents", "net_cents"):
        assert isinstance(data[field], int), f"Payout.{field} must be int"
    assert data["status"] in {s.value for s in PayoutStatus}
    for field in ("issued_at", "cleared_at", "stale_marked_at"):
        _assert_optional_instant(data, field, "Payout")


def assert_pbgc_transfer(data):
    _assert_common_fields(data, "PBGCTransfer")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert data["amount_basis"] in ("SUBMISSION_NET", "EXHAUSTION_SNAPSHOT")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in {s.value for s in PBGCTransferStatus}
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    _assert_optional_instant(data, "confirmed_at", "PBGCTransfer")


def assert_forfeiture(data):
    _assert_common_fields(data, "Forfeiture")
    assert is_valid_uuid(data.get("participant_id", ""))
    assert isinstance(data["rationale"], str) and data["rationale"]
    assert isinstance(data["forfeited_amount_cents"], int)
    assert data["status"] in {s.value for s in ForfeitureStatus}
    _assert_optional_instant(data, "restored_at", "Forfeiture")


def assert_determination_letter_request(data):
    _assert_common_fields(data, "DeterminationLetterRequest")
    assert is_valid_uuid(data.get("termination_case_id", ""))
    assert is_iso8601_timestamp(data.get("intended_filing_date", ""))
    _assert_optional_instant(data, "filed_at", "DeterminationLetterRequest")
    assert data["status"] in {s.value for s in DLRStatus}


def assert_fiduciary_log_entry(data):
    _assert_append_only_fields(data, "FiduciaryLogEntry")
    assert is_valid_uuid(data.get("termination_case_id", ""))
    assert data["entry_type"] in (
        "SEARCH_PROTOCOL_SUMMARY",
        "NOTICE_DECISION",
        "DISTRIBUTION_DECISION",
        "FORFEITURE_RATIONALE",
        "PBGC_TRANSFER_RATIONALE",
        "CLOSURE_SIGNOFF",
    )
    assert isinstance(data["narrative"], str) and len(data["narrative"]) >= 50
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]
    assert isinstance(data["author_role"], str) and data["author_role"]


def assert_expense_allocation(data):
    _assert_common_fields(data, "ExpenseAllocation")
    assert is_valid_uuid(data.get("termination_case_id", ""))
    assert data["method"] in ("PRO_RATA_BY_BALANCE", "EQUAL_PER_CAPITA")
    assert isinstance(data["total_expense_cents"], int) and data["total_expense_cents"] > 0
    assert isinstance(data["eligible_participant_count"], int)
    assert "remainder_recipient_participant_id" in data


def assert_fund_conservation(case, label="TerminationCase"):
    """PRD: at every moment total_plan_assets_cents equals the sum of
    paid_out + pbgc_transferred + forfeited + expense_paid + remaining."""
    total = case["total_plan_assets_cents"]
    buckets = (
        case["paid_out_cents"]
        + case["pbgc_transferred_cents"]
        + case["forfeited_cents"]
        + case["expense_paid_cents"]
        + case["remaining_undistributed_cents"]
    )
    assert total == buckets, (
        f"{label} ledger drift: total_plan_assets_cents {total} != bucket sum {buckets}"
    )
