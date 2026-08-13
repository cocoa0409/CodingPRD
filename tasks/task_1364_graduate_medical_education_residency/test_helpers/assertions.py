"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import COMPETENCIES
from .types import (
    AcademicYearStatus, AccreditationStatus, AssignmentStatus, CaseLogStatus,
    CCCStatus, CitationArea, CitationSeverity, CitationStatus, ComplementStatus,
    DutyLogStatus, EvaluatorRole, LifecycleStatus, MoonlightingStatus,
    ProbationStatus, ProcedureCategory, RemediationStatus, RemediationTrigger,
    RotationStatus, ScheduleBlockStatus, Specialty, StandingStatus, SurveyStatus,
    ViolationRule, ViolationStatus,
)


def approx2(expected):
    """Two-decimal half-up quantities (hours, census, rates) compare with a
    tolerance of half a cent of an hour unit (PRD §2.6)."""
    return pytest.approx(expected, abs=0.005)


def assert_common_fields(data: dict):
    """PRD §2.5: id UUID; created_at/updated_at ISO 8601 UTC; version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["specialty"] in {s.value for s in Specialty}
    assert isinstance(data["acgme_program_code"], str) and data["acgme_program_code"]
    assert data["accreditation_status"] in {s.value for s in AccreditationStatus}


def assert_academic_year(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["year_label"], str) and data["year_label"]
    assert data["status"] in {s.value for s in AcademicYearStatus}


def assert_schedule_block(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["academic_year_id"])
    assert isinstance(data["block_index"], int) and 1 <= data["block_index"] <= 13
    assert data["status"] in {s.value for s in ScheduleBlockStatus}


def assert_complement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["academic_year_id"])
    assert isinstance(data["pgy_level"], int) and 1 <= data["pgy_level"] <= 7
    assert isinstance(data["approved_positions"], int) and data["approved_positions"] >= 0
    assert isinstance(data["annual_funding_budget_cents"], int)
    assert isinstance(data["blended_stipend_cents"], int)
    assert isinstance(data["resident_year_stipend_cents"], int)
    assert isinstance(data["effective_funded_positions"], int)
    assert isinstance(data["filled_headcount"], int)
    assert data["filled_funded_census"] == approx2(data["filled_funded_census"])
    assert data["status"] in {s.value for s in ComplementStatus}


def assert_resident(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["entry_academic_year_id"])
    assert isinstance(data["pgy_level"], int) and 1 <= data["pgy_level"] <= 7
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["lifecycle_status"] in {s.value for s in LifecycleStatus}
    assert data["standing_status"] in {s.value for s in StandingStatus}


def assert_rotation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["min_pgy_level"], int) and 1 <= data["min_pgy_level"] <= 7
    assert isinstance(data["max_residents_per_block"], int) and data["max_residents_per_block"] >= 1
    assert isinstance(data["is_night_float"], bool)
    assert data["status"] in {s.value for s in RotationStatus}


def assert_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["schedule_block_id"])
    assert is_valid_uuid(data["rotation_id"])
    assert data["status"] in {s.value for s in AssignmentStatus}


def assert_duty_log(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["resident_id"])
    assert data["duration_hours"] == approx2(data["duration_hours"])
    assert data["status"] in {s.value for s in DutyLogStatus}


def assert_violation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["duty_hour_log_id"])
    assert data["rule_code"] in {s.value for s in ViolationRule}
    assert data["status"] in {s.value for s in ViolationStatus}
    assert data["measured_value"] == approx2(data["measured_value"])


def assert_moonlighting(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["resident_id"])
    assert data["type"] in ("INTERNAL", "EXTERNAL")
    assert data["hours_per_week"] == approx2(data["hours_per_week"])
    assert data["status"] in {s.value for s in MoonlightingStatus}


def assert_evaluation(data: dict):
    """Append-only (PRD §2.5): id + created_at, and NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "immutable evaluation must not carry updated_at"
    assert "version" not in data, "immutable evaluation must not carry version"
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["academic_year_id"])
    assert data["reporting_period"] in ("H1", "H2")
    assert data["evaluator_role"] in {s.value for s in EvaluatorRole}
    comps = {r["competency"] for r in data["competency_ratings"]}
    assert comps == set(COMPETENCIES)


def assert_ccc_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["academic_year_id"])
    assert data["reporting_period"] in ("H1", "H2")
    assert data["status"] in {s.value for s in CCCStatus}


def assert_case_log(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["rotation_id"])
    assert data["procedure_category"] in {s.value for s in ProcedureCategory}
    assert data["role"] in ("SURGEON", "ASSIST")
    assert data["status"] in {s.value for s in CaseLogStatus}


def assert_case_requirement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["procedure_category"] in {s.value for s in ProcedureCategory}
    assert isinstance(data["required_count"], int) and data["required_count"] >= 1
    assert isinstance(data["required_primary_count"], int)
    assert 0 <= data["required_primary_count"] <= data["required_count"]


def assert_remediation_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["resident_id"])
    assert data["trigger_source"] in {s.value for s in RemediationTrigger}
    assert data["status"] in {s.value for s in RemediationStatus}


def assert_probation_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["resident_id"])
    assert data["status"] in {s.value for s in ProbationStatus}


def assert_citation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["area_code"] in {s.value for s in CitationArea}
    assert data["severity"] in {s.value for s in CitationSeverity}
    assert data["status"] in {s.value for s in CitationStatus}


def assert_survey(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["academic_year_id"])
    assert data["status"] in {s.value for s in SurveyStatus}


def assert_duty_summary(data: dict, resident_id: str):
    """PRD §3.3: the summary carries the six aggregate fields."""
    assert data["resident_id"] == resident_id
    for field in ("official_hours", "projected_hours", "rolling_4wk_avg_official",
                  "rolling_4wk_avg_projected", "attributed_moonlighting_hours"):
        assert field in data, f"duty-hour summary missing {field}"
        assert isinstance(data[field], (int, float))
