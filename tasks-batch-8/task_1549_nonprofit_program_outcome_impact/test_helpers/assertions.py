"""Entity assertions and domain invariant checkers (PRD sections 2.4 and 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Common-field assertion. Per PRD section 2.4 every entity carries the same
# four system-managed properties.
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict, entity_name: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_program(data: dict):
    assert_common_fields(data, "Program")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("status") in {"DRAFT", "ACTIVE", "SUSPENDED", "ARCHIVED"}
    assert "current_logic_model_id" in data
    assert isinstance(data.get("current_consent_form_version"), int)
    assert data["current_consent_form_version"] >= 1


def assert_funder(data: dict):
    assert_common_fields(data, "Funder")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("status") in {"ACTIVE", "INACTIVE"}


def assert_logic_model(data: dict):
    assert_common_fields(data, "LogicModel")
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("version_no"), int) and data["version_no"] >= 1
    assert data.get("status") in {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"}


def assert_indicator(data: dict):
    assert_common_fields(data, "Indicator")
    assert isinstance(data.get("logic_model_id"), str)
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("level") in {"OUTPUT", "OUTCOME", "IMPACT"}
    assert data.get("unit") in {"COUNT", "PERCENT", "SCORE"}
    assert data.get("direction") in {"HIGHER_IS_BETTER", "LOWER_IS_BETTER"}
    assert isinstance(data.get("baseline_value"), (int, float))
    assert isinstance(data.get("target_value"), (int, float))
    assert isinstance(data.get("weight"), (int, float)) and data["weight"] > 0
    assert data.get("measurement_frequency") in {"PER_EVENT", "MONTHLY", "END_OF_CYCLE"}
    assert data.get("status") in {"DRAFT", "ACTIVE", "RETIRED"}


def assert_cycle(data: dict):
    assert_common_fields(data, "ProgramCycle")
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("label"), str)
    for f in ("enrollment_start", "enrollment_end", "cycle_start", "cycle_end", "reporting_due_date"):
        assert is_iso8601_timestamp(data.get(f, "")), f"ProgramCycle.{f} must be ISO 8601"
    assert data.get("status") in {
        "SETUP", "ENROLLING", "ACTIVE", "DATA_CLOSED", "UNDER_REVIEW", "REPORTED", "ARCHIVED",
    }
    assert "pinned_logic_model_id" in data
    assert "consent_form_version_snapshot" in data
    assert isinstance(data.get("active_participant_count"), int)
    assert isinstance(data.get("total_observation_count"), int)
    assert isinstance(data.get("validated_observation_count"), int)
    assert "data_completeness_pct" in data
    assert "latest_dq_score" in data


def assert_participant(data: dict):
    assert_common_fields(data, "Participant")
    assert isinstance(data.get("program_cycle_id"), str)
    assert isinstance(data.get("external_ref"), str) and data["external_ref"]
    assert is_iso8601_timestamp(data.get("enrolled_at", "")), (
        "Participant.enrolled_at must be ISO 8601"
    )
    assert data.get("status") in {"ENROLLED", "ACTIVE", "EXITED", "COMPLETED", "WITHDRAWN"}
    assert data.get("consent_status") in {"NONE", "CURRENT", "EXPIRED"}


def assert_consent(data: dict):
    assert_common_fields(data, "ConsentRecord")
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("form_version"), int)
    assert data.get("scope") in {"FULL", "AGGREGATE_ONLY"}
    assert is_iso8601_timestamp(data.get("granted_at", "")), "ConsentRecord.granted_at"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "ConsentRecord.expires_at"
    assert data.get("status") in {"GRANTED", "SUPERSEDED", "REVOKED", "EXPIRED"}


def assert_instrument(data: dict):
    assert_common_fields(data, "Instrument")
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("instrument_version"), int) and data["instrument_version"] >= 1
    assert data.get("status") in {"DRAFT", "PUBLISHED", "RETIRED"}


def assert_certification(data: dict):
    assert_common_fields(data, "TrainingCertification")
    assert isinstance(data.get("staff_user_id"), str) and data["staff_user_id"]
    assert isinstance(data.get("instrument_id"), str)
    assert isinstance(data.get("certified_instrument_version"), int)
    assert data["certified_instrument_version"] >= 1
    assert is_iso8601_timestamp(data.get("certified_at", "")), "certification.certified_at"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "certification.expires_at"
    assert data.get("status") in {"CERTIFIED", "SUSPENDED", "STALE", "EXPIRED"}


def assert_observation(data: dict):
    assert_common_fields(data, "Observation")
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("indicator_id"), str)
    assert isinstance(data.get("instrument_id"), str)
    assert isinstance(data.get("instrument_version"), int)
    assert isinstance(data.get("value"), (int, float))
    assert is_iso8601_timestamp(data.get("collected_at", "")), "observation.collected_at"
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "observation.recorded_at"
    assert isinstance(data.get("collected_by_id"), str) and data["collected_by_id"]
    assert data.get("review_status") in {"PENDING", "VALIDATED", "FLAGGED", "EXCLUDED"}
    assert isinstance(data.get("is_late"), bool)


def assert_milestone(data: dict):
    assert_common_fields(data, "Milestone")
    assert isinstance(data.get("program_cycle_id"), str)
    assert isinstance(data.get("indicator_id"), str)
    assert is_iso8601_timestamp(data.get("due_date", "")), "milestone.due_date"
    assert isinstance(data.get("milestone_target"), (int, float))
    assert data.get("status") in {"PENDING", "MET", "MISSED"}


def assert_audit(data: dict):
    assert_common_fields(data, "DataQualityAudit")
    assert isinstance(data.get("program_cycle_id"), str)
    assert data.get("status") in {"OPEN", "CLOSED"}
    assert isinstance(data.get("opened_by_id"), str) and data["opened_by_id"]
    assert isinstance(data.get("open_finding_count"), int) and data["open_finding_count"] >= 0


def assert_finding(data: dict):
    assert_common_fields(data, "AuditFinding")
    assert isinstance(data.get("audit_id"), str)
    assert data.get("finding_type") in {
        "MISSING_DATA", "OUTLIER", "UNCERTIFIED_COLLECTOR", "CONSENT_LAPSE", "LATE_DATA",
    }
    assert isinstance(data.get("participant_id"), str)
    assert data.get("status") in {"OPEN", "WAIVED", "REMEDIATED"}


def assert_report(data: dict):
    assert_common_fields(data, "Report")
    assert isinstance(data.get("program_cycle_id"), str)
    assert isinstance(data.get("funder_id"), str)
    assert data.get("report_type") in {"FUNDER_STANDARD", "FUNDER_CUSTOM", "INTERNAL_DASHBOARD"}
    assert data.get("status") in {
        "DRAFT", "GENERATED", "DELIVERED", "ACCEPTED", "RETURNED", "SUPERSEDED",
    }


def assert_engagement(data: dict):
    assert_common_fields(data, "VendorEngagement")
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("vendor_name"), str) and data["vendor_name"]
    assert isinstance(data.get("scope_program_cycle_ids"), list)
    for f in ("access_start", "access_end", "deliverable_due"):
        assert is_iso8601_timestamp(data.get(f, "")), f"VendorEngagement.{f}"
    assert data.get("status") in {"PROPOSED", "ACTIVE", "COMPLETED", "TERMINATED"}


def assert_improvement_action(data: dict):
    assert_common_fields(data, "ImprovementAction")
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("title"), str) and data["title"]
    assert data.get("status") in {
        "PROPOSED", "APPROVED", "IN_PROGRESS", "IMPLEMENTED",
        "VERIFIED_EFFECTIVE", "VERIFIED_INEFFECTIVE",
    }


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_cycle_aggregate_invariants(cycle: dict):
    """PRD section 3.4: cycle aggregates are counts/percentages that never
    go negative and the completeness, when present, stays within [0, 100]."""
    assert cycle["active_participant_count"] >= 0
    assert cycle["total_observation_count"] >= 0
    assert cycle["validated_observation_count"] >= 0
    assert cycle["validated_observation_count"] <= cycle["total_observation_count"]
    if cycle.get("data_completeness_pct") is not None:
        assert 0.0 <= cycle["data_completeness_pct"] <= 100.0
    if cycle.get("latest_dq_score") is not None:
        assert 0.0 <= cycle["latest_dq_score"] <= 100.0
