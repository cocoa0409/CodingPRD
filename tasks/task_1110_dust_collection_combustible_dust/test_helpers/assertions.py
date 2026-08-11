"""Entity assertions and domain invariant checkers for the Dust Compliance API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every entity carries id + created_at + updated_at + version (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_site(data: dict):
    """Validate a Site resource representation."""
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str)
    assert isinstance(data["ahj_authority"], str)
    assert isinstance(data["insurer_id"], str)
    assert data["posture"] in ("COMPLIANT", "CONDITIONAL", "DEFICIENT", "STOP_WORK")
    assert isinstance(data["posture_score"], (int, float))
    assert 0 <= data["posture_score"] <= 100
    assert isinstance(data["open_critical_findings"], int)
    assert isinstance(data["open_overdue_housekeeping"], int)
    assert isinstance(data["hot_work_in_progress"], int)


def assert_dust_sample(data: dict):
    """Validate a DustSample resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["material_name"], str) and data["material_name"]
    assert isinstance(data["kst_bar_m_per_s"], (int, float))
    assert data["kst_bar_m_per_s"] >= 0
    assert isinstance(data["pmax_bar_g"], (int, float)) and data["pmax_bar_g"] > 0
    assert isinstance(data["mie_mj"], (int, float)) and data["mie_mj"] > 0
    assert data["sample_class"] in ("ST0", "ST1", "ST2", "ST3")
    assert isinstance(data["combustible"], bool)
    assert isinstance(data["lab_report_ref"], str)


def assert_collector(data: dict):
    """Validate a Collector resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["tag"], str) and data["tag"]
    assert is_valid_uuid(data.get("dust_sample_id", "")), "dust_sample_id must be a UUID"
    assert isinstance(data["design_airflow_acfm"], int) and data["design_airflow_acfm"] > 0
    assert isinstance(data["filter_area_ft2"], (int, float)) and data["filter_area_ft2"] > 0
    assert isinstance(data["air_to_cloth_ratio"], (int, float))
    assert isinstance(data["internal_volume_m3"], (int, float))
    assert data["internal_volume_m3"] > 0
    assert isinstance(data["pred_max_bar_g"], (int, float))
    assert isinstance(data["required_vent_area_m2"], (int, float))
    assert isinstance(data["installed_vent_area_m2"], (int, float))
    assert isinstance(data["vent_adequate"], bool)
    assert isinstance(data["dp_current_inwc"], (int, float))
    assert data["dp_trend"] in ("STABLE", "RISING", "ALARM_HIGH")
    assert isinstance(data["filter_change_due"], bool)
    assert data["status"] in ("DRAFT", "IN_SERVICE", "OUT_OF_SERVICE", "DECOMMISSIONED")


def assert_dha(data: dict):
    """Validate a DHA resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["author_id"], str) and data["author_id"]
    assert data["kst_class_highest"] in ("ST0", "ST1", "ST2", "ST3")
    assert isinstance(data["risk_score"], (int, float))
    assert 0 <= data["risk_score"] <= 100
    assert isinstance(data["overdue"], bool)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED", "REJECTED")


def assert_housekeeping_program(data: dict):
    """Validate a HousekeepingProgram resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["target_accumulation_g_per_m2"], (int, float))
    assert data["target_accumulation_g_per_m2"] > 0
    assert isinstance(data["frequency_hours"], int) and data["frequency_hours"] > 0
    assert data["current_posture"] in ("CURRENT", "DUE_SOON", "OVERDUE")


def assert_housekeeping_audit(data: dict):
    """Validate a HousekeepingAudit resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["auditor_id"], str) and data["auditor_id"]
    assert isinstance(data["measured_accumulation_g_per_m2"], (int, float))
    assert data["measured_accumulation_g_per_m2"] >= 0
    assert isinstance(data["pass_threshold_g_per_m2"], (int, float))
    assert data["status"] in ("SCHEDULED", "RECORDED", "OVERDUE", "SKIPPED")


def assert_hot_work_permit(data: dict):
    """Validate a HotWorkPermit resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["work_description"], str)
    assert isinstance(data["issuer_id"], str) and data["issuer_id"]
    assert isinstance(data["performer_id"], str) and data["performer_id"]
    assert isinstance(data["fire_watch_minutes_after"], int)
    assert data["status"] in ("ISSUED", "IN_PROGRESS", "CLOSED", "VOIDED", "EXPIRED")


def assert_inspection(data: dict):
    """Validate an Inspection resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert data["inspector_kind"] in ("AHJ", "INSURER", "INTERNAL")
    assert isinstance(data["inspector_ref"], str)
    assert data["status"] in ("OPEN", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_inspection_finding(data: dict):
    """Validate an InspectionFinding resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("inspection_id", "")), "inspection_id must be a UUID"
    assert data["severity"] in ("OBSERVATION", "MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["description"], str)
    assert data["status"] in (
        "OPEN", "IN_PROGRESS", "RESOLVED", "VERIFIED", "REOPENED", "DISPUTED",
        "WITHDRAWN",
    )


def assert_retrofit_project(data: dict):
    """Validate a RetrofitProject resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("trigger_finding_id", "")), \
        "trigger_finding_id must be a UUID"
    assert isinstance(data["scope_budget_cents"], int) and data["scope_budget_cents"] > 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["contingency_cents"], int)
    assert isinstance(data["total_projected_cents"], int)
    assert isinstance(data["contingency_rounding_cents"], int)
    assert data["status"] in (
        "SCOPING", "ESTIMATED", "APPROVED", "IN_EXECUTION", "CLOSED", "CANCELLED",
    )


def assert_retrofit_line_item(data: dict):
    """Validate a RetrofitLineItem resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["description"], str)
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] > 0
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")


def assert_incident(data: dict):
    """Validate an Incident resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert data["kind"] in ("FIRE", "DEFLAGRATION", "EMBER_RELEASE", "NEAR_MISS")
    assert data["severity"] in ("MINOR", "MAJOR", "CATASTROPHIC")
    assert data["root_cause_code"] in (
        "HOUSEKEEPING", "HOT_WORK", "EQUIPMENT_FAILURE", "STATIC_DISCHARGE", "UNKNOWN",
    )
    assert isinstance(data["investigation_lead_id"], str)
    assert isinstance(data["capa_count"], int)
    assert isinstance(data["capa_open_count"], int)
    assert data["status"] in (
        "OPEN", "INVESTIGATING", "CAPA_DEFINED", "CLOSED", "REOPENED",
    )


def assert_capa_action(data: dict):
    """Validate a CAPAAction resource representation."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("incident_id", "")), "incident_id must be a UUID"
    assert isinstance(data["description"], str)
    assert isinstance(data["owner_id"], str) and data["owner_id"]
    assert data["status"] in ("OPEN", "IN_PROGRESS", "CLOSED", "OVERDUE")


def assert_site_posture_invariants(data: dict):
    """Site posture invariants that must hold after any operation (PRD §2.4)."""
    assert data["posture"] in ("COMPLIANT", "CONDITIONAL", "DEFICIENT", "STOP_WORK")
    assert 0 <= data["posture_score"] <= 100
    if data["open_critical_findings"] >= 2:
        assert data["posture"] == "STOP_WORK", (
            "2 or more open critical findings must force STOP_WORK regardless of score"
        )
