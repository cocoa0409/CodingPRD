"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

LIGHT_ROW_TYPES = ("MemberEnrollmentSegment", "OverReadReview", "SupplementalRecord")


def assert_common_fields(data: dict):
    """Fields every full resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_light_row(data: dict):
    """MemberEnrollmentSegment / OverReadReview / SupplementalRecord carry only
    id and created_at; updated_at and version are absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "light rows must not expose updated_at (PRD §2.4)"
    assert "version" not in data, "light rows must not expose version (PRD §2.4)"


def assert_season(data: dict):
    assert_common_fields(data)
    assert isinstance(data["measurement_year"], int)
    assert is_iso8601_timestamp(data["submission_deadline"])
    assert is_iso8601_timestamp(data["admin_data_cutoff"])
    assert isinstance(data["approved_supplemental_sources"], list)
    assert data["status"] in ("DRAFT", "OPEN", "SUBMISSION_CLOSED")
    assert isinstance(data["certified_run_count"], int)


def assert_spec(data: dict):
    assert_common_fields(data)
    assert isinstance(data["season_id"], str)
    assert isinstance(data["hedis_measure_code"], str) and data["hedis_measure_code"]
    assert isinstance(data["version_label"], str)
    assert data["collection_method"] in ("ADMINISTRATIVE", "HYBRID")
    assert data["hybrid_policy"] in ("SAMPLE_ONLY", "ADMIN_SUPPLEMENTED")
    assert data["matching_policy"] in ("EXACT", "TOLERANT")
    assert isinstance(data["sample_size_floor"], int)
    assert isinstance(data["age_min"], int) and isinstance(data["age_max"], int)
    assert data["gender_requirement"] in ("ANY", "F", "M")
    assert isinstance(data["continuous_enrollment_months"], int)
    assert isinstance(data["allowable_gap_days"], int)
    assert data["status"] in ("LOADED", "ACTIVE", "RETIRED")


def assert_member(data: dict):
    assert_common_fields(data)
    assert isinstance(data["member_ref"], str) and data["member_ref"]
    assert data["gender"] in ("F", "M")


def assert_enrollment_segment(data: dict):
    assert_light_row(data)
    assert isinstance(data["member_id"], str)
    assert is_iso8601_timestamp(data["span_start"])
    assert is_iso8601_timestamp(data["span_end"])


def assert_provider(data: dict):
    assert_common_fields(data)
    assert isinstance(data["provider_ref"], str) and data["provider_ref"]
    assert isinstance(data["name"], str)
    assert isinstance(data["open_gap_count"], int)


def assert_run(data: dict):
    assert_common_fields(data)
    assert isinstance(data["season_id"], str)
    assert isinstance(data["spec_id"], str)
    assert isinstance(data["spec_version_label"], str)
    assert data["collection_method"] in ("ADMINISTRATIVE", "HYBRID")
    assert data["reporting_status"] in (
        "POPULATION_PENDING", "POPULATED", "RATE_COMPUTED",
        "SUBMITTED", "CERTIFIED", "CERTIFICATION_FAILED",
    )
    assert data["audit_status"] in (
        "UNAUDITED", "IN_REVIEW", "AUDIT_PASSED", "AUDIT_FAILED",
    )
    assert isinstance(data["denominator_count"], int)
    assert isinstance(data["exclusion_count"], int)
    assert isinstance(data["admin_numerator_count"], int)
    assert isinstance(data["sample_exclusion_count"], int)
    assert isinstance(data["sample_numerator_count"], int)


def assert_population_entry(data: dict):
    assert_common_fields(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["member_ref"], str)
    assert isinstance(data["is_excluded"], bool)
    assert isinstance(data["is_sampled"], bool)
    assert isinstance(data["admin_compliant"], bool)
    assert isinstance(data["sample_compliant"], bool)


def assert_sample(data: dict):
    assert_common_fields(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["drawn_size"], int)
    assert isinstance(data["draw_step"], (int, float))
    assert data["status"] in ("DRAWN", "FINALIZED", "LOCKED")
    assert data["irr_state"] in ("PENDING", "PASSED", "FAILED")
    assert data["irr_ratio"] is None or isinstance(data["irr_ratio"], (int, float))
    assert isinstance(data["remediation_count"], int)
    assert isinstance(data["required_overread_fraction"], (int, float))


def assert_chase(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sample_id"], str)
    assert isinstance(data["member_ref"], str)
    assert data["status"] in (
        "REQUESTED", "RECEIVED", "REJECTED_UNREADABLE",
        "WITHDRAWN", "ABSTRACTED", "EXCLUDED_VALID",
    )
    assert isinstance(data["chase_round"], int)


def assert_abstraction(data: dict):
    assert_common_fields(data)
    assert isinstance(data["chase_id"], str)
    assert data["result"] in ("HIT", "MISS", "NOT_ABSTRACTABLE")
    assert isinstance(data["abstractor_user_id"], str)
    assert isinstance(data["requires_overread"], bool)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CONFIRMED", "OVERREAD_PASSED", "REMEDIATION",
    )
    assert isinstance(data["resubmission_count"], int)


def assert_overread_review(data: dict):
    assert_light_row(data)
    assert isinstance(data["abstraction_id"], str)
    assert isinstance(data["reviewer_user_id"], str)
    assert data["outcome"] in ("AGREE", "DISAGREE")


def assert_supplemental_batch(data: dict):
    assert_common_fields(data)
    assert isinstance(data["run_id"], str)
    assert data["source_type"] in (
        "LAB_FEED", "IMMUNIZATION_REGISTRY", "PHARMACY", "EHR",
    )
    assert data["status"] in ("RECEIVED", "SCREENED", "ACCEPTED", "REJECTED")
    assert isinstance(data["record_count"], int)
    assert isinstance(data["accepted_record_count"], int)


def assert_supplemental_record(data: dict):
    assert_light_row(data)
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["member_ref"], str)
    assert data["disposition"] in (
        "PENDING", "ACCEPTED", "REJECTED_UNKNOWN_MEMBER",
        "REJECTED_OUT_OF_WINDOW", "REJECTED_DUPLICATE",
    )


def assert_gap_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["member_ref"], str)
    assert data["gap_reason"] == "NO_EVIDENCE_OF_SERVICE"
    assert data["status"] in (
        "OPEN", "OUTREACH_DONE", "CLOSED_COMPLIANT", "CLOSED_NONCOMPLIANT",
    )
    assert data.get("closure_source") in (None, "MANUAL", "AUTO_EVIDENCE")


def assert_engagement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["season_id"], str)
    assert isinstance(data["measure_run_id"], str)
    assert isinstance(data["auditor_user_id"], str)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("SCHEDULED", "IN_REVIEW", "COMPLETED")
    assert data.get("outcome") in (None, "PASS", "FAIL")


def assert_finding(data: dict):
    assert_common_fields(data)
    assert isinstance(data["engagement_id"], str)
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert isinstance(data["summary"], str)
    assert data["status"] in ("OPEN", "RESOLVED")
