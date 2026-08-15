"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ActionItemStatus,
    ActionPlanStatus,
    BenchmarkSetStatus,
    CycleKind,
    Dimension,
    EmploymentStatus,
    Framework,
    InviteStatus,
    ItemBankStatus,
    OutcomeKind,
    SnapshotScope,
    SurveyCycleStatus,
    SurveyItemStatus,
)


def _assert_common_fields(data: dict):
    """PRD §2.4: server-minted UUID id, ISO 8601 created_at/updated_at,
    integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_immutable_record_fields(data: dict):
    """PRD §2.4: response rows, outcome linkages and reminder events carry only
    id and created_at — updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable record must not expose updated_at"
    assert "version" not in data, "immutable record must not expose version"


def assert_item_bank(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["framework"] in {f.value for f in Framework}
    assert data["status"] in {s.value for s in ItemBankStatus}


def assert_survey_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["item_code"], str) and len(data["item_code"]) > 0
    assert data["dimension"] in {d.value for d in Dimension}
    assert isinstance(data["weight"], (int, float))
    assert isinstance(data["has_free_text"], bool)
    assert data["status"] in {s.value for s in SurveyItemStatus}


def assert_org_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["manager_user_id"], str)
    assert isinstance(data["min_n_threshold"], int)
    assert isinstance(data["verbatim_n_threshold"], int)


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["external_ref"], str)
    assert isinstance(data["unit_id"], str)
    assert data["employment_status"] in {s.value for s in EmploymentStatus}
    assert is_iso8601_timestamp(data["hired_at"])


def assert_survey_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str)
    assert data["cycle_kind"] in {k.value for k in CycleKind}
    assert isinstance(data["bank_id"], str)
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["closes_at"])
    assert data["status"] in {s.value for s in SurveyCycleStatus}
    assert isinstance(data["invited_count"], int)
    assert isinstance(data["submitted_count"], int)
    assert isinstance(data["partial_count"], int)
    assert data["response_rate"] is None or isinstance(data["response_rate"], (int, float))
    assert data.get("attrition_risk") is None or isinstance(data["attrition_risk"], (int, float))


def assert_cycle_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["pinned_weight"], (int, float))
    assert isinstance(data["display_order"], int) and data["display_order"] >= 1


def assert_survey_invite(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["unit_id_at_invite"], str)
    assert data["status"] in {s.value for s in InviteStatus}
    assert isinstance(data["reminder_count"], int) and data["reminder_count"] >= 0


def assert_survey_response(data: dict):
    _assert_immutable_record_fields(data)
    assert isinstance(data["invite_id"], str)
    assert isinstance(data["answers"], list)
    assert isinstance(data["is_partial"], bool)


def assert_report_snapshot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["unit_id"], str)
    assert data["scope"] in {s.value for s in SnapshotScope}
    assert isinstance(data["submitted_n"], int)
    assert isinstance(data["dimension_scores"], dict)
    assert data["overall_score"] is None or isinstance(data["overall_score"], (int, float))
    assert data["benchmark_percentile"] is None or isinstance(
        data["benchmark_percentile"], (int, float)
    )
    assert isinstance(data["numeric_suppressed"], bool)
    assert isinstance(data["verbatim_suppressed"], bool)
    assert isinstance(data["generation"], int) and data["generation"] >= 1


def assert_benchmark_set(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["dimension_scores"], list)
    assert data["status"] in {s.value for s in BenchmarkSetStatus}


def assert_action_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["title"], str)
    assert data["focus_dimension"] in {d.value for d in Dimension}
    assert data["status"] in {s.value for s in ActionPlanStatus}
    assert is_iso8601_timestamp(data["due_at"])
    assert isinstance(data["progress_pct"], int) and 0 <= data["progress_pct"] <= 100


def assert_action_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["owner_user_id"], str)
    assert data["status"] in {s.value for s in ActionItemStatus}
    assert is_iso8601_timestamp(data["target_at"])


def assert_outcome_linkage(data: dict):
    _assert_immutable_record_fields(data)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["cycle_id"], str)
    assert data["outcome_kind"] in {k.value for k in OutcomeKind}


def assert_reminder_event(data: dict):
    _assert_immutable_record_fields(data)
    assert isinstance(data["invite_id"], str)
    assert is_iso8601_timestamp(data["sent_at"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
