"""Entity assertions for the API contract.

Each per-entity assertion validates structural invariants the PRD declares —
PRD §2.4 requires each top-level entity to carry (id, created_at, updated_at,
version), while PaymentApplication and Vote are append-only event records
carrying only id + created_at.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


_ASSESSMENT_STATES = {"DUE", "OVERDUE", "PAID", "WAIVED"}
_ASSESSMENT_KINDS = {"REGULAR", "SPECIAL"}
_PAYMENT_STATES = {"APPLIED", "REVERSED"}
_VIOLATION_STATES = {"OPEN", "CONTESTED", "UPHELD", "DISMISSED", "PAID", "ACTIVE"}
_VIOLATION_CATEGORIES = {"LANDSCAPING", "APPEARANCE", "NOISE", "PARKING"}
_ACC_STATES = {"SUBMITTED", "REVISION_REQUESTED", "APPROVED", "REJECTED", "WITHDRAWN"}
_ACC_SCOPES = {"APPEARANCE", "LANDSCAPING"}
_ELECTION_STATES = {
    "DRAFT", "OPEN", "CLOSED_QUORUM_MET", "CLOSED_NO_QUORUM",
    "CERTIFIED", "INVALIDATED",
}
_VOTE_STATES = {"CAST", "RETRACTED"}
_LIEN_STATES = {"FILED", "SATISFIED", "FORECLOSURE_INITIATED"}
_POSTURES = {"COMPLIANT", "UNDER_REVIEW", "SUSPENDED"}
_OWNER_STATES = {"ACTIVE", "INACTIVE"}
_RESERVE_METHODS = {"COMPONENT", "CASH_FLOW"}


def _assert_common_fields(data: dict, label: str) -> None:
    """Validate id + created_at + updated_at + version per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a valid UUID (got {data.get('id')!r})"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer (got {data.get('version')!r})"
    )


def _assert_append_only_fields(data: dict, label: str) -> None:
    """Validate id + created_at only — used for PaymentApplication and Vote
    which PRD §2.4 explicitly states carry no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a valid UUID (got {data.get('id')!r})"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )


def assert_community(data: dict) -> None:
    _assert_common_fields(data, "Community")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("fiscal_year_start_month"), int)
    assert 1 <= data["fiscal_year_start_month"] <= 12
    assert isinstance(data.get("regular_assessment_cents"), int)
    assert data["regular_assessment_cents"] >= 0
    assert isinstance(data.get("late_fee_grace_days"), int)
    assert isinstance(data.get("late_fee_flat_cents"), int)
    assert isinstance(data.get("late_fee_pct_bps"), int)
    assert isinstance(data.get("lien_threshold_cents"), int)
    assert isinstance(data.get("election_quorum_pct"), int)
    assert isinstance(data.get("reserve_inflation_bps"), int)
    assert is_iso8601_timestamp(data.get("current_utc", ""))


def assert_owner(data: dict) -> None:
    _assert_common_fields(data, "Owner")
    assert isinstance(data.get("community_id"), str)
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("is_eligible_voter"), bool)
    assert data.get("status") in _OWNER_STATES


def assert_property(data: dict) -> None:
    _assert_common_fields(data, "Property")
    assert isinstance(data.get("community_id"), str)
    assert isinstance(data.get("owner_id"), str)
    assert isinstance(data.get("unit_label"), str) and len(data["unit_label"]) > 0
    assert isinstance(data.get("account_balance_cents"), int)
    assert data["account_balance_cents"] >= 0
    assert data.get("compliance_posture") in _POSTURES


def assert_assessment(data: dict) -> None:
    _assert_common_fields(data, "Assessment")
    assert isinstance(data.get("property_id"), str)
    assert data.get("kind") in _ASSESSMENT_KINDS
    assert isinstance(data.get("principal_cents"), int)
    assert data["principal_cents"] >= 0
    assert isinstance(data.get("late_fee_cents"), int)
    assert data["late_fee_cents"] >= 0
    assert isinstance(data.get("paid_cents"), int)
    assert data["paid_cents"] >= 0
    assert isinstance(data.get("outstanding_cents"), int)
    assert data["outstanding_cents"] >= 0
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert data.get("status") in _ASSESSMENT_STATES


def assert_payment_application(data: dict) -> None:
    """PRD §2.4: PaymentApplication carries only id + created_at."""
    _assert_append_only_fields(data, "PaymentApplication")
    assert isinstance(data.get("assessment_id"), str)
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert data.get("state") in _PAYMENT_STATES
    assert is_iso8601_timestamp(data.get("applied_at", ""))


def assert_violation(data: dict) -> None:
    _assert_common_fields(data, "Violation")
    assert isinstance(data.get("property_id"), str)
    assert data.get("category") in _VIOLATION_CATEGORIES
    assert isinstance(data.get("tier"), int) and data["tier"] >= 1
    assert isinstance(data.get("fine_cents"), int) and data["fine_cents"] >= 0
    assert data.get("status") in _VIOLATION_STATES
    assert is_iso8601_timestamp(data.get("opened_at", ""))


def assert_acc_request(data: dict) -> None:
    _assert_common_fields(data, "ACCRequest")
    assert isinstance(data.get("property_id"), str)
    assert data.get("scope") in _ACC_SCOPES
    assert isinstance(data.get("description"), str)
    assert data.get("status") in _ACC_STATES
    assert isinstance(data.get("revision_count"), int)
    assert 0 <= data["revision_count"] <= 3
    decided = data.get("decided_at")
    assert decided is None or is_iso8601_timestamp(decided)


def assert_board_election(data: dict) -> None:
    _assert_common_fields(data, "BoardElection")
    assert isinstance(data.get("community_id"), str)
    assert isinstance(data.get("cycle_label"), str) and len(data["cycle_label"]) > 0
    assert is_iso8601_timestamp(data.get("opens_at", ""))
    assert is_iso8601_timestamp(data.get("closes_at", ""))
    assert data.get("status") in _ELECTION_STATES
    assert isinstance(data.get("eligible_voter_count"), int)
    assert isinstance(data.get("votes_cast"), int)


def assert_vote(data: dict) -> None:
    """PRD §2.4: Vote carries only id + created_at."""
    _assert_append_only_fields(data, "Vote")
    assert isinstance(data.get("election_id"), str)
    assert isinstance(data.get("owner_id"), str)
    assert isinstance(data.get("candidate_name"), str)
    assert data.get("state") in _VOTE_STATES
    assert is_iso8601_timestamp(data.get("cast_at", ""))


def assert_lien(data: dict) -> None:
    _assert_common_fields(data, "Lien")
    assert isinstance(data.get("property_id"), str)
    assert isinstance(data.get("principal_at_filing_cents"), int)
    assert data.get("status") in _LIEN_STATES
    assert is_iso8601_timestamp(data.get("filed_at", ""))


def assert_reserve_study(data: dict) -> None:
    _assert_common_fields(data, "ReserveStudy")
    assert isinstance(data.get("community_id"), str)
    assert isinstance(data.get("fiscal_year"), int)
    assert data.get("method") in _RESERVE_METHODS
    assert isinstance(data.get("accumulated_funds_cents"), int)
    assert isinstance(data.get("projected_obligation_cents"), int)
    assert isinstance(data.get("percent_funded_bps"), int)


def assert_reserve_component(data: dict) -> None:
    _assert_common_fields(data, "ReserveComponent")
    assert isinstance(data.get("community_id"), str)
    assert isinstance(data.get("label"), str) and len(data["label"]) > 0
    assert isinstance(data.get("useful_life_years"), int)
    assert data["useful_life_years"] > 0
    assert isinstance(data.get("remaining_life_years"), int)
    assert data["remaining_life_years"] >= 0
    assert isinstance(data.get("replacement_cost_cents"), int)
    assert data["replacement_cost_cents"] >= 0
