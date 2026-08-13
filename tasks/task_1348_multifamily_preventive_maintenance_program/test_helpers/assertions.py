"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_append_only_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} is append-only and must not carry updated_at"
    assert "version" not in data, f"{entity} is append-only and must not carry version"


def assert_property(data: dict):
    _assert_common_fields(data, "Property")
    assert isinstance(data["property_code"], str) and data["property_code"]
    assert isinstance(data["display_name"], str)
    assert isinstance(data["notice_lead_hours"], int) and data["notice_lead_hours"] >= 24
    assert isinstance(data["default_labor_rate_cents_per_hour"], int) and data["default_labor_rate_cents_per_hour"] > 0
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_building(data: dict):
    _assert_common_fields(data, "Building")
    assert isinstance(data["property_id"], str)
    assert isinstance(data["building_label"], str)
    assert isinstance(data["floors"], int) and data["floors"] >= 1


def assert_unit(data: dict):
    _assert_common_fields(data, "Unit")
    assert isinstance(data["building_id"], str)
    assert isinstance(data["unit_number"], str)
    assert data["occupancy_status"] in ("OCCUPIED", "VACANT")


def assert_asset(data: dict):
    _assert_common_fields(data, "Asset")
    assert isinstance(data["unit_id"], str)
    assert data["component_type"] in ("HVAC", "WATER_HEATER", "APPLIANCE")
    assert isinstance(data["installed_on"], str)
    assert isinstance(data["warranty_months"], int) and data["warranty_months"] >= 0
    assert isinstance(data["expected_life_months"], int) and data["expected_life_months"] > 0
    assert isinstance(data["replacement_cost_cents"], int) and data["replacement_cost_cents"] > 0
    assert data["operational_status"] in ("IN_SERVICE", "OUT_OF_SERVICE", "DECOMMISSIONED")
    assert data["compliance_status"] in ("COMPLIANT", "DUE", "OVERDUE", "NON_COMPLIANT")
    score = data.get("condition_score")
    assert score is None or (isinstance(score, int) and 1 <= score <= 5)
    assert isinstance(data["age_months"], int) and data["age_months"] >= 0
    assert isinstance(data["warranty_active"], bool)
    assert "superseded_by_asset_id" in data


def assert_template(data: dict):
    _assert_common_fields(data, "PMTaskTemplate")
    assert isinstance(data["property_id"], str)
    assert data["component_type"] in ("HVAC", "WATER_HEATER", "APPLIANCE")
    assert isinstance(data["task_name"], str)
    assert isinstance(data["frequency_days"], int) and data["frequency_days"] >= 1
    assert isinstance(data["estimated_labor_minutes"], int) and data["estimated_labor_minutes"] > 0
    assert isinstance(data["requires_evidence"], bool)
    assert isinstance(data["effective_from"], str)
    assert "retired_at" in data


def assert_plan(data: dict):
    _assert_common_fields(data, "PMPlan")
    assert isinstance(data["property_id"], str)
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert data["status"] in ("DRAFT", "ADOPTED", "CLOSED")
    assert isinstance(data["planned_labor_hours"], int) and data["planned_labor_hours"] >= 0
    assert isinstance(data["actual_labor_minutes"], int) and data["actual_labor_minutes"] >= 0
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0


def assert_batch(data: dict):
    _assert_common_fields(data, "EntryBatch")
    assert isinstance(data["property_id"], str)
    assert isinstance(data["batch_label"], str)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "LOCKED", "EXECUTED", "CANCELLED")
    assert "notice_sent_at" in data


def assert_visit(data: dict):
    _assert_common_fields(data, "PMVisit")
    for key in ("batch_id", "unit_id", "template_id", "asset_id", "plan_id"):
        assert isinstance(data[key], str)
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["technician_id"], str)
    assert data["visit_status"] in ("SCHEDULED", "NOTIFIED", "IN_PROGRESS", "COMPLETED", "NO_ACCESS", "CANCELLED")
    assert isinstance(data["visit_cost_cents"], int) and data["visit_cost_cents"] >= 0


def assert_evidence(data: dict):
    _assert_append_only_fields(data, "ComplianceEvidence")
    assert isinstance(data["visit_id"], str)
    assert data["evidence_type"] in ("FILTER_REPLACEMENT", "DETECTOR_TEST", "BATTERY_REPLACEMENT")
    assert isinstance(data["serial_or_lot"], str)
    assert isinstance(data.get("notes", ""), str)
    assert isinstance(data["recorded_by"], str)


def assert_deficiency(data: dict):
    _assert_common_fields(data, "Deficiency")
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["asset_id"], str)
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "EMERGENCY")
    assert isinstance(data["description"], str)
    assert data["status"] in ("RECORDED", "TRIAGED", "CONVERTED", "WAIVED")
    assert "work_order_id" in data


def assert_work_order(data: dict):
    _assert_common_fields(data, "CorrectiveWorkOrder")
    for key in ("property_id", "deficiency_id", "plan_id", "asset_id"):
        assert isinstance(data[key], str)
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] > 0
    assert isinstance(data["assigned_technician_id"], str)
    assert isinstance(data["replace_asset"], bool)
    assert data["status"] in ("OPEN", "IN_REVIEW", "APPROVED", "IN_PROGRESS", "COMPLETED", "VERIFIED", "REJECTED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_ledger_entry(data: dict):
    _assert_append_only_fields(data, "BudgetLedgerEntry")
    assert isinstance(data["plan_id"], str)
    assert data["entry_kind"] in (
        "VISIT_COMMIT", "VISIT_SETTLE", "VISIT_RELEASE", "WO_COMMIT", "WO_SETTLE", "WO_RELEASE",
    )
    assert isinstance(data["amount_cents"], int)
    assert "source_visit_id" in data
    assert "source_work_order_id" in data


def assert_forecast_snapshot(data: dict):
    _assert_append_only_fields(data, "CapitalForecastSnapshot")
    assert isinstance(data["property_id"], str)
    assert isinstance(data["horizon_years"], int) and 1 <= data["horizon_years"] <= 10
    assert data["variant"] in ("AGE_BASED", "CONDITION_BASED")
    assert isinstance(data["total_projected_cents"], int)
    assert isinstance(data["per_year_cents"], list)
    assert len(data["per_year_cents"]) == data["horizon_years"]
    assert all(isinstance(v, int) for v in data["per_year_cents"])
    assert isinstance(data["asset_count_projected"], int) and data["asset_count_projected"] >= 0
    assert isinstance(data["computed_at"], str)


def assert_audit(data: dict):
    _assert_append_only_fields(data, "CompletionAudit")
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["auditor_id"], str)
    assert data["outcome"] in ("PASS", "FAIL")
    if data["outcome"] == "FAIL":
        assert isinstance(data.get("fail_reason"), str) and data["fail_reason"]
    assert isinstance(data["audited_at"], str)


def assert_ledger_entries_exactly(entries: list, expected_kind_amounts: list):
    """Assert a ledger listing equals the expected multiset of (entry_kind, amount_cents)."""
    actual = sorted((e["entry_kind"], e["amount_cents"]) for e in entries)
    expected = sorted(expected_kind_amounts)
    assert actual == expected, f"ledger entries {actual} != expected {expected}"
