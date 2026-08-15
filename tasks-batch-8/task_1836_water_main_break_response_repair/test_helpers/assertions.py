"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdvisoryStatus,
    BreakStatus,
    BreakType,
    ClampKit,
    ColiformResult,
    ConditionStatus,
    ControlPlan,
    CorrelationStatus,
    CrewStatus,
    EquipmentClass,
    IsolationStatus,
    IssueReason,
    Material,
    PermitStatus,
    ClaimStatus,
    RestorationStatus,
    Severity,
    TestOutcome,
    ValveStatus,
    WorkStatus,
    BreakSource,
    AnomalyType,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def assert_pipe_segment(data: dict):
    _assert_common(data)
    assert isinstance(data.get("segment_ref"), str) and data["segment_ref"]
    assert data.get("material") in {m.value for m in Material}
    assert isinstance(data.get("diameter_inches"), int)
    assert isinstance(data.get("install_year"), int)
    assert data.get("condition_status") in {s.value for s in ConditionStatus}
    assert isinstance(data.get("repeat_break_count_36mo"), int)
    assert isinstance(data.get("provisional_break_count_36mo"), int)
    if data.get("replaced_at") is not None:
        assert is_iso8601_timestamp(data["replaced_at"])


def assert_valve(data: dict):
    _assert_common(data)
    assert isinstance(data.get("valve_code"), str) and data["valve_code"]
    assert is_valid_uuid(data.get("pipe_segment_id", ""))
    assert isinstance(data.get("coverage_zone"), str) and data["coverage_zone"]
    assert isinstance(data.get("customers_served"), int) and data["customers_served"] > 0
    assert data.get("valve_status") in {s.value for s in ValveStatus}


def assert_pressure_anomaly(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pipe_segment_id", ""))
    assert data.get("anomaly_type") in {t.value for t in AnomalyType}
    assert is_iso8601_timestamp(data.get("observed_at", ""))
    assert isinstance(data.get("magnitude_pct"), int)
    assert 1 <= data["magnitude_pct"] <= 100
    assert data.get("correlation_status") in {s.value for s in CorrelationStatus}
    if data.get("correlated_break_report_id") is not None:
        assert is_valid_uuid(data["correlated_break_report_id"])


def assert_break_report(data: dict):
    _assert_common(data)
    assert isinstance(data.get("location_description"), str)
    assert data.get("source") in {s.value for s in BreakSource}
    assert data.get("break_status") in {s.value for s in BreakStatus}
    if data.get("pipe_segment_id") is not None:
        assert is_valid_uuid(data["pipe_segment_id"])
    if data.get("break_type") is not None:
        assert data["break_type"] in {t.value for t in BreakType}
    if data.get("severity") is not None:
        assert data["severity"] in {s.value for s in Severity}
    if data.get("confirmed_at") is not None:
        assert is_iso8601_timestamp(data["confirmed_at"])
    if data.get("repaired_at") is not None:
        assert is_iso8601_timestamp(data["repaired_at"])
    for f in (
        "customers_out_of_service",
        "total_repair_cost_cents",
        "total_restoration_cost_cents",
        "claims_liability_cents",
        "total_claims_paid_cents",
        "total_cost_cents",
    ):
        assert isinstance(data.get(f), int), f"{f} must be int, got {data.get(f)!r}"


def assert_isolation_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("break_report_id", ""))
    assert isinstance(data.get("valve_ids"), list) and len(data["valve_ids"]) >= 1
    assert data.get("isolation_status") in {s.value for s in IsolationStatus}
    if data.get("outage_extent_customers") is not None:
        assert isinstance(data["outage_extent_customers"], int)
    if data.get("executed_at") is not None:
        assert is_iso8601_timestamp(data["executed_at"])
    if data.get("restored_at") is not None:
        assert is_iso8601_timestamp(data["restored_at"])


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data.get("crew_name"), str) and data["crew_name"]
    assert isinstance(data.get("crew_size"), int) and data["crew_size"] > 0
    assert data.get("equipment_class") in {c.value for c in EquipmentClass}
    assert isinstance(data.get("hourly_rate_cents"), int) and data["hourly_rate_cents"] > 0
    assert data.get("crew_status") in {s.value for s in CrewStatus}
    assert isinstance(data.get("completed_job_count"), int)


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("break_report_id", ""))
    assert isinstance(data.get("est_pipe_length_ft"), int) and data["est_pipe_length_ft"] > 0
    assert data.get("work_status") in {s.value for s in WorkStatus}
    if data.get("crew_id") is not None:
        assert is_valid_uuid(data["crew_id"])
    if data.get("required_equipment_class") is not None:
        assert data["required_equipment_class"] in {c.value for c in EquipmentClass}
    if data.get("required_clamp_kit") is not None:
        assert data["required_clamp_kit"] in {k.value for k in ClampKit}
    for f in ("estimated_cost_cents", "actual_cost_cents", "cost_variance_cents"):
        if data.get(f) is not None:
            assert isinstance(data[f], int), f"{f} must be int cents"
    for f in ("dispatch_window_start", "dispatch_window_end"):
        if data.get(f) is not None:
            assert is_iso8601_timestamp(data[f])


def assert_boil_water_advisory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("break_report_id", ""))
    assert data.get("issue_reason") in {r.value for r in IssueReason}
    assert data.get("advisory_status") in {s.value for s in AdvisoryStatus}
    assert isinstance(data.get("issued_by_user_id"), str) and data["issued_by_user_id"]
    if data.get("lifted_by_user_id") is not None:
        assert isinstance(data["lifted_by_user_id"], str)
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    if data.get("lifted_at") is not None:
        assert is_iso8601_timestamp(data["lifted_at"])
    assert isinstance(data.get("consecutive_pass_count"), int)
    if data.get("last_sample_at") is not None:
        assert is_iso8601_timestamp(data["last_sample_at"])


def assert_water_quality_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("advisory_id", ""))
    assert is_iso8601_timestamp(data.get("sampled_at", ""))
    assert isinstance(data.get("chlorine_residual_mg_l"), (int, float))
    assert data.get("coliform_result") in {r.value for r in ColiformResult}
    assert data.get("test_outcome") in {o.value for o in TestOutcome}


def assert_restoration_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert data.get("restoration_status") in {s.value for s in RestorationStatus}
    for f in ("scheduled_start", "scheduled_end", "completed_at"):
        if data.get(f) is not None:
            assert is_iso8601_timestamp(data[f])
    if data.get("traffic_permit_id") is not None:
        assert is_valid_uuid(data["traffic_permit_id"])
    if data.get("patch_cost_cents") is not None:
        assert isinstance(data["patch_cost_cents"], int)


def assert_traffic_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("break_report_id", ""))
    assert isinstance(data.get("street_block"), str) and data["street_block"]
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_to", ""))
    assert data.get("control_plan") in {p.value for p in ControlPlan}
    assert data.get("permit_status") in {s.value for s in PermitStatus}


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("break_report_id", ""))
    assert isinstance(data.get("claimant_name"), str) and data["claimant_name"]
    assert isinstance(data.get("claimed_amount_cents"), int)
    assert data.get("claim_status") in {s.value for s in ClaimStatus}
    if data.get("approved_amount_cents") is not None:
        assert isinstance(data["approved_amount_cents"], int)
