"""Entity assertions and domain invariant checkers (PRD §2.2–§2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    ClusterGroupStatus,
    CostShareBasis,
    DeveloperType,
    LimitType,
    MilestoneStatus,
    MilestoneType,
    ProjectStatus,
    ServiceType,
    StudyStatus,
    Technology,
    TxType,
)


def assert_instant_equal(actual: str, expected: str):
    """Clock-stamped instants compare by value, not by string format.

    The PRD pins three fractional digits only for api_request_timestamp,
    created_at, and updated_at (§2.2, §2.4); domain fields stamped from the
    logical clock (issued_at, execution_deadline, target_cod) carry no
    declared string format, so equality is evaluated on the parsed instant.
    """
    def _parse(v):
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 UTC timestamp"
    assert _parse(actual) == _parse(expected), f"{actual!r} != {expected!r} as instants"


def _assert_versioned_common_fields(data: dict):
    """Fields carried by Developer, ClusterGroup, Project, MilestoneSubmission,
    Study, CostShare, and InterconnectionAgreement (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def _assert_append_only_common_fields(data: dict):
    """DepositTransaction, CurtailmentLimit, and TransparencyReport carry only
    id and created_at — updated_at and version are absent entirely (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resources must not carry updated_at"
    assert "version" not in data, "append-only resources must not carry version"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def assert_developer(data: dict):
    _assert_versioned_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["developer_type"] in [t.value for t in DeveloperType]


def assert_cluster_group(data: dict):
    _assert_versioned_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert is_iso8601_timestamp(data["application_window_open"])
    assert is_iso8601_timestamp(data["application_window_close"])
    assert _is_number(data["capacity_mw"]) and data["capacity_mw"] > 0
    assert _is_number(data["committed_mw"]) and data["committed_mw"] >= 0
    assert data["status"] in [s.value for s in ClusterGroupStatus]


def assert_project(data: dict):
    _assert_versioned_common_fields(data)
    assert is_valid_uuid(data["developer_id"])
    assert is_valid_uuid(data["cluster_group_id"])
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert data["technology"] in [t.value for t in Technology]
    assert _is_number(data["capacity_mw"]) and 0 < data["capacity_mw"] <= 500
    assert data["service_type"] in [s.value for s in ServiceType]
    assert isinstance(data["point_of_interconnection"], str)
    assert data["queue_position"] is None or (
        isinstance(data["queue_position"], int) and data["queue_position"] >= 1
    )
    assert isinstance(data["deposit_required_cents"], int)
    assert data["deposit_required_cents"] >= 0
    assert isinstance(data["deposit_posted_cents"], int)
    assert data["deposit_posted_cents"] >= 0
    assert isinstance(data["readiness_satisfied"], bool)
    assert data["status"] in [s.value for s in ProjectStatus]


def assert_deposit_transaction(data: dict):
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["tx_type"] in [t.value for t in TxType]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["balance_after_cents"], int)
    assert data["balance_after_cents"] >= 0


def assert_milestone_submission(data: dict):
    _assert_versioned_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["milestone_type"] in [t.value for t in MilestoneType]
    assert isinstance(data["evidence_uri"], str) and data["evidence_uri"]
    assert data["status"] in [s.value for s in MilestoneStatus]
    assert "review_note" in data  # null until reviewed


def assert_study(data: dict):
    _assert_versioned_common_fields(data)
    assert is_valid_uuid(data["cluster_group_id"])
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] > 0
    assert data["status"] in [s.value for s in StudyStatus]


def assert_cost_share(data: dict):
    _assert_versioned_common_fields(data)
    assert is_valid_uuid(data["study_id"])
    assert is_valid_uuid(data["project_id"])
    assert data["basis"] in [b.value for b in CostShareBasis]
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0


def assert_interconnection_agreement(data: dict):
    _assert_versioned_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["execution_deadline"])
    assert is_iso8601_timestamp(data["target_cod"])
    assert isinstance(data["extension_count"], int) and 0 <= data["extension_count"] <= 2
    assert _is_number(data["max_injection_mw"]) and data["max_injection_mw"] > 0
    assert isinstance(data["curtailment_hours_cap"], int)
    assert data["curtailment_hours_cap"] >= 0
    assert data["status"] in [s.value for s in AgreementStatus]


def assert_curtailment_limit(data: dict):
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["limit_type"] in [t.value for t in LimitType]
    assert _is_number(data["max_output_mw"]) and data["max_output_mw"] > 0
    assert is_iso8601_timestamp(data["effective_start"])
    assert is_iso8601_timestamp(data["effective_end"])
    assert isinstance(data["curtailment_hours_per_year"], int)
    assert data["curtailment_hours_per_year"] >= 0


def assert_transparency_report(data: dict):
    _assert_append_only_common_fields(data)
    assert isinstance(data["reporting_period"], str) and data["reporting_period"]
    assert isinstance(data["queued_project_count"], int)
    assert data["queued_project_count"] >= 0
    assert _is_number(data["queued_mw"]) and data["queued_mw"] >= 0
    assert isinstance(data["withdrawn_project_count"], int)
    assert data["withdrawn_project_count"] >= 0
    assert isinstance(data["commercial_operation_project_count"], int)
    assert data["commercial_operation_project_count"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def find_ledger_entry(entries: list, tx_type: str, amount_cents: int) -> dict:
    """Locate a ledger entry by (tx_type, amount_cents); fails the test when absent."""
    for entry in entries:
        if entry["tx_type"] == tx_type and entry["amount_cents"] == amount_cents:
            return entry
    raise AssertionError(
        f"No ledger entry with tx_type={tx_type} amount_cents={amount_cents}; "
        f"ledger={[(e['tx_type'], e['amount_cents']) for e in entries]}"
    )


def assert_cost_shares_conserved(shares: list, total_cost_cents: int):
    """After every allocation run, all shares of a study sum exactly to the
    study total (PRD §3.4 residual reconciliation invariant)."""
    total = sum(s["allocated_cents"] for s in shares)
    assert total == total_cost_cents, (
        f"sum of allocated_cents {total} != study total {total_cost_cents}"
    )
