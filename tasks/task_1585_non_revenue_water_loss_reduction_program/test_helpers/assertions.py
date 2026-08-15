"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    """Primary resources carry id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_label}.version must be an integer"
    )


def assert_dma(data: dict):
    _assert_common_fields(data, "DistrictMeteredArea")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["connection_count"], int) and data["connection_count"] >= 1
    assert data["mains_length_km"] > 0
    assert 0 <= data["target_nrw_pct"] < 100
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["latest_nrw_pct"] is None or isinstance(
        data["latest_nrw_pct"], (int, float)
    )
    assert isinstance(data["open_leak_count"], int) and data["open_leak_count"] >= 0


def assert_water_balance_period(data: dict):
    _assert_common_fields(data, "WaterBalancePeriod")
    assert is_valid_uuid(data.get("dma_id", "")), "dma_id must be a UUID"
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["system_input_volume_m3"] > 0
    assert data["billed_authorized_m3"] >= 0
    assert data["unbilled_authorized_m3"] >= 0
    assert data["unauthorized_consumption_m3"] >= 0
    assert data["metering_inaccuracy_m3"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "FINALIZED", "SUPERSEDED")
    assert isinstance(data["nrw_volume_m3"], (int, float))
    assert isinstance(data["nrw_pct"], (int, float))
    assert isinstance(data["apparent_loss_m3"], (int, float))
    assert isinstance(data["real_loss_m3"], (int, float))
    assert data["real_loss_m3"] >= 0
    if data["status"] in ("FINALIZED", "SUPERSEDED"):
        assert isinstance(data["ili"], (int, float)), (
            "finalized periods carry a computed ili"
        )


def assert_night_flow_assessment(data: dict):
    _assert_common_fields(data, "NightFlowAssessment")
    assert is_valid_uuid(data.get("dma_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["measured_mnf_lps"] >= 0
    assert data["expected_legitimate_night_use_lps"] >= 0
    assert data["status"] in ("RECORDED", "ANALYZED", "VOID", "SUPERSEDED")


def assert_leak_survey(data: dict):
    _assert_common_fields(data, "LeakSurvey")
    assert is_valid_uuid(data.get("dma_id", ""))
    assert is_iso8601_timestamp(data.get("planned_start", ""))
    assert is_iso8601_timestamp(data.get("planned_end", ""))
    assert data["method"] in (
        "ACOUSTIC", "CORRELATOR", "SATELLITE", "STEP_TEST", "NOISE_LOGGER",
    )
    assert isinstance(data["crew_lead_user_id"], str)
    assert data["status"] in ("PLANNED", "IN_FIELD", "COMPLETED", "CANCELLED")
    assert isinstance(data["leaks_found_count"], int)


def assert_leak(data: dict):
    _assert_common_fields(data, "Leak")
    assert is_valid_uuid(data.get("survey_id", ""))
    assert isinstance(data["location_description"], str)
    assert data["estimated_loss_lps"] > 0
    assert data["repair_cost_estimate"] >= 0
    assert data["status"] in (
        "REPORTED", "VERIFIED", "REPAIR_SCHEDULED", "REPAIRED",
        "VERIFIED_REPAIR", "REOPENED", "WITHDRAWN",
    )
    assert isinstance(data["reported_by_user_id"], str)
    assert isinstance(data["repair_priority_score"], (int, float))
    assert data["priority_band"] in ("P1", "P2", "P3")
    assert isinstance(data["annualized_loss_m3"], (int, float))


def assert_customer_meter(data: dict):
    _assert_common_fields(data, "CustomerMeter")
    assert is_valid_uuid(data.get("dma_id", ""))
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["size_mm"] in (15, 20, 25, 40, 50, 100, 150)
    assert is_iso8601_timestamp(data.get("installed_at", ""))
    assert data["replacement_policy"] in ("AGE_BASED", "ACCURACY_BASED", "HYBRID")
    assert data["status"] in (
        "IN_SERVICE", "FLAGGED_FOR_REPLACEMENT", "REPLACED", "RETIRED",
    )
    assert data["last_test_accuracy_pct"] is None or isinstance(
        data["last_test_accuracy_pct"], (int, float)
    )
    assert isinstance(data["replacement_due"], bool)


def assert_meter_accuracy_test(data: dict):
    _assert_common_fields(data, "MeterAccuracyTest")
    assert is_valid_uuid(data.get("meter_id", ""))
    assert is_iso8601_timestamp(data.get("tested_at", ""))
    assert data["flow_rate_lps"] > 0
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_unauthorized_consumption_case(data: dict):
    _assert_common_fields(data, "UnauthorizedConsumptionCase")
    assert is_valid_uuid(data.get("dma_id", ""))
    assert isinstance(data["service_location_ref"], str)
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert data["investigation_status"] in (
        "OPEN", "EVIDENCE_GATHERING", "SUBSTANTIATED", "UNFOUNDED", "CLOSED",
    )
    assert data["billing_adjustment_status"] in (
        "NONE", "PROPOSED", "APPROVED", "REJECTED", "POSTED",
    )


def assert_pressure_project(data: dict):
    _assert_common_fields(data, "PressureProject")
    assert is_valid_uuid(data.get("dma_id", ""))
    assert isinstance(data["name"], str)
    assert data["baseline_pressure_m"] > 0
    assert 0 < data["target_pressure_m"] < data["baseline_pressure_m"]
    assert data["status"] in (
        "PROPOSED", "APPROVED", "REJECTED", "ACTIVE", "COMMISSIONED",
    )


def assert_intervention_proposal(data: dict):
    _assert_common_fields(data, "InterventionProposal")
    assert is_valid_uuid(data.get("dma_id", ""))
    assert data["kind"] in (
        "LEAK_REPAIR_PROGRAM", "METER_REPLACEMENT_PROGRAM",
        "PRESSURE_MANAGEMENT", "UNAUTHORIZED_USE_ENFORCEMENT",
    )
    assert data["capital_cost"] >= 0
    assert data["annual_om_cost"] >= 0
    assert data["expected_volume_saved_m3_per_year"] > 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "ARCHIVED")
    assert isinstance(data["benefit_cost_ratio"], (int, float))


def assert_benchmark_report(data: dict):
    _assert_common_fields(data, "BenchmarkReport")
    assert isinstance(data["reporting_year"], int) and data["reporting_year"] >= 2000
    assert is_iso8601_timestamp(data.get("reporting_period_start", ""))
    assert is_iso8601_timestamp(data.get("reporting_period_end", ""))
    assert isinstance(data["dma_ids"], list)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")


def assert_audit_event(data: dict):
    """Audit events are append-only: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "AuditEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "audit events must not carry updated_at"
    assert "version" not in data, "audit events must not carry version"
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)
