"""Entity assertions and domain invariant checkers for the HMDA register."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ActionTaken,
    ApplicantRole,
    ApplicationChannel,
    ApplicationStage,
    CollectionMethod,
    DefectRateBasis,
    DemographicEntryStatus,
    EditExceptionStatus,
    EditRunScope,
    EditRunStatus,
    EditSeverity,
    ExclusionReason,
    FairLendingBasis,
    FairLendingStatus,
    FilingPosture,
    FindingResolution,
    FindingSeverity,
    GeocodeStatus,
    LarStatus,
    LienStatus,
    LoanPurpose,
    LoanType,
    OccupancyType,
    ObservationBasis,
    PurchaserType,
    SampleMethod,
    SampleStatus,
    SexCode,
    SignificanceFlag,
    StatementType,
    SubmissionStatus,
)

_MEMBERS = lambda enum_cls: [m.value for m in enum_cls]  # noqa: E731


def assert_common_fields(data: dict, entity_name: str) -> None:
    """Every stored resource carries a bare UUID id and a created_at timestamp."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID string with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: dict, entity_name: str) -> None:
    """Resources that carry updated_at and version alongside id and created_at."""
    assert_common_fields(data, entity_name)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity_name: str) -> None:
    """Resources that carry only id and created_at — no updated_at, no version."""
    assert_common_fields(data, entity_name)
    assert "updated_at" not in data or data["updated_at"] is None, (
        f"{entity_name} must not carry updated_at"
    )
    assert "version" not in data or data["version"] is None, (
        f"{entity_name} must not carry version"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_institution(data: dict) -> None:
    assert_versioned_fields(data, "Institution")
    assert isinstance(data["lei"], str) and len(data["lei"]) == 20
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["activity_year"], int)
    assert 2020 <= data["activity_year"] <= 2035
    assert isinstance(data["asset_size_usd_cents"], int)
    assert isinstance(data["partial_exemption_eligible"], bool)
    assert isinstance(data["quarterly_filer"], bool)
    assert data["required_field_count"] in (26, 48)
    assert data["filing_posture"] in _MEMBERS(FilingPosture)
    assert is_iso8601_timestamp(data["filing_deadline_at"])
    for counter in (
        "total_application_count",
        "pending_record_count",
        "reportable_record_count",
        "excluded_record_count",
        "cleared_record_count",
        "open_register_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Institution.{counter} must be a non-negative integer"
        )


def assert_application(data: dict) -> None:
    assert_versioned_fields(data, "Application")
    assert is_valid_uuid(data["institution_id"])
    assert isinstance(data["uli"], str) and len(data["uli"]) > 0
    assert is_iso8601_timestamp(data["application_date"])
    assert data["application_channel"] in _MEMBERS(ApplicationChannel)
    assert data["loan_type"] in _MEMBERS(LoanType)
    assert data["loan_purpose"] in _MEMBERS(LoanPurpose)
    assert data["occupancy_type"] in _MEMBERS(OccupancyType)
    assert data["lien_status"] in _MEMBERS(LienStatus)
    assert isinstance(data["loan_amount_cents"], int) and data["loan_amount_cents"] >= 1
    assert data["stage"] in _MEMBERS(ApplicationStage)
    assert data["lar_status"] in _MEMBERS(LarStatus)
    assert data["exclusion_reason"] in _MEMBERS(ExclusionReason)
    assert isinstance(data["is_superseded"], bool)
    assert isinstance(data["business_or_commercial_purpose"], bool)
    assert isinstance(data["open_end_line_of_credit"], bool)
    assert isinstance(data["denial_reason_codes"], list)
    assert isinstance(data["captured_field_count"], int)
    assert isinstance(data["applicable_field_count"], int)
    assert data["captured_field_count"] <= data["applicable_field_count"], (
        "captured_field_count may never exceed applicable_field_count"
    )
    if data.get("action_taken") is not None:
        assert data["action_taken"] in _MEMBERS(ActionTaken)
    if data.get("purchaser_type") is not None:
        assert data["purchaser_type"] in _MEMBERS(PurchaserType)


def assert_demographic_entry(data: dict) -> None:
    assert_versioned_fields(data, "DemographicEntry")
    assert is_valid_uuid(data["application_id"])
    assert data["applicant_role"] in _MEMBERS(ApplicantRole)
    assert data["collection_method"] in _MEMBERS(CollectionMethod)
    assert isinstance(data["ethnicity_codes"], list)
    assert isinstance(data["race_codes"], list)
    assert len(data["race_codes"]) <= 5, "race_codes may carry at most 5 entries"
    assert len(data["ethnicity_codes"]) <= 2, "ethnicity_codes may carry at most 2 entries"
    assert data["sex_code"] in _MEMBERS(SexCode)
    assert data["observation_basis"] in _MEMBERS(ObservationBasis)
    assert isinstance(data["is_natural_person"], bool)
    assert data["status"] in _MEMBERS(DemographicEntryStatus)


def assert_geocode_assignment(data: dict) -> None:
    assert_versioned_fields(data, "GeocodeAssignment")
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in _MEMBERS(GeocodeStatus)
    assert isinstance(data["candidate_count"], int) and data["candidate_count"] >= 0
    assert isinstance(data["is_current"], bool)
    for field in ("street_address", "city", "state_code", "zip_code", "county_fips"):
        assert isinstance(data[field], str) and len(data[field]) > 0
    if data["status"] in ("MATCHED", "MANUAL_OVERRIDE"):
        assert is_valid_uuid(data.get("census_tract_id") or ""), (
            "a resolved assignment must name a census tract"
        )
    else:
        assert data.get("census_tract_id") is None, (
            "an unresolved assignment must leave census_tract_id null"
        )
        assert data.get("msa_md_code") is None, (
            "an unresolved assignment must leave msa_md_code null"
        )


def assert_census_tract(data: dict) -> None:
    assert_append_only_fields(data, "CensusTract")
    assert isinstance(data["tract_code"], str) and len(data["tract_code"]) == 11
    assert isinstance(data["county_fips"], str) and len(data["county_fips"]) == 5
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["msa_md_code"], str) and len(data["msa_md_code"]) == 5
    assert isinstance(data["owner_occupied_units"], int)
    assert isinstance(data["median_family_income_cents"], int)
    assert isinstance(data["minority_population_pct"], (int, float))
    assert isinstance(data["tract_to_msa_income_pct"], (int, float))


def assert_edit_run(data: dict) -> None:
    assert_versioned_fields(data, "EditRun")
    assert is_valid_uuid(data["institution_id"])
    assert data["scope"] in _MEMBERS(EditRunScope)
    assert data["status"] in _MEMBERS(EditRunStatus)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1
    for counter in (
        "snapshot_record_count",
        "syntactical_count",
        "validity_count",
        "quality_count",
        "macro_count",
        "total_exception_count",
        "open_exception_count",
        "verified_exception_count",
        "stale_exception_count",
        "cleared_record_count",
        "required_verified_quota",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"EditRun.{counter} must be a non-negative integer"
        )
    assert_edit_run_severity_totals(data)
    assert_edit_run_ledger_identity(data)


def assert_edit_run_severity_totals(data: dict) -> None:
    """total_exception_count is the sum of the four severity counters."""
    expected = (
        data["syntactical_count"]
        + data["validity_count"]
        + data["quality_count"]
        + data["macro_count"]
    )
    assert data["total_exception_count"] == expected, (
        f"total_exception_count {data['total_exception_count']} must equal the sum of "
        f"the severity counters {expected}"
    )


def assert_edit_run_ledger_identity(data: dict) -> None:
    """open + verified + stale exception counts reconcile to the run total."""
    total = (
        data["open_exception_count"]
        + data["verified_exception_count"]
        + data["stale_exception_count"]
    )
    assert total == data["total_exception_count"], (
        f"open+verified+stale ({total}) must equal total_exception_count "
        f"({data['total_exception_count']})"
    )


def assert_edit_exception(data: dict) -> None:
    assert_versioned_fields(data, "EditException")
    assert is_valid_uuid(data["edit_run_id"])
    assert data["severity"] in _MEMBERS(EditSeverity)
    assert data["status"] in _MEMBERS(EditExceptionStatus)
    assert isinstance(data["edit_code"], str) and len(data["edit_code"]) > 0
    assert isinstance(data["field_name"], str) and len(data["field_name"]) > 0
    assert isinstance(data["message"], str) and len(data["message"]) > 0
    if data["severity"] == "MACRO":
        assert data.get("application_id") is None, (
            "a macro exception describes the whole register and carries a null application_id"
        )
    else:
        assert is_valid_uuid(data.get("application_id") or "")


def assert_filing_submission(data: dict) -> None:
    assert_versioned_fields(data, "FilingSubmission")
    assert is_valid_uuid(data["institution_id"])
    assert data["status"] in _MEMBERS(SubmissionStatus)
    assert isinstance(data["submission_index"], int) and data["submission_index"] >= 1
    assert isinstance(data["activity_year"], int)
    assert isinstance(data["provisional_record_count"], int)
    assert isinstance(data["resubmission_count"], int) and data["resubmission_count"] >= 0
    assert isinstance(data["is_superseded"], bool)
    assert is_iso8601_timestamp(data["deadline_at"])
    if data["status"] in ("DRAFT", "EDITS_ATTACHED"):
        assert data.get("final_record_count") is None, (
            "final_record_count is null before certification"
        )
    if data.get("final_record_count") is not None:
        assert data["final_record_count"] <= data["provisional_record_count"], (
            "final_record_count may never exceed provisional_record_count"
        )


def assert_disclosure_statement(data: dict) -> None:
    assert_append_only_fields(data, "DisclosureStatement")
    assert is_valid_uuid(data["submission_id"])
    assert data["statement_type"] in _MEMBERS(StatementType)
    assert isinstance(data["record_count"], int)
    assert isinstance(data["tract_suppression_count"], int)
    assert isinstance(data["suppressed_record_count"], int)
    assert isinstance(data["redacted_field_count"], int)
    assert is_iso8601_timestamp(data["published_at"])
    assert data["redacted_field_count"] == data["suppressed_record_count"] * 3, (
        "redacted_field_count is suppressed_record_count multiplied by three"
    )


def assert_audit_sample(data: dict) -> None:
    assert_versioned_fields(data, "AuditSample")
    assert is_valid_uuid(data["institution_id"])
    assert data["method"] in _MEMBERS(SampleMethod)
    assert data["status"] in _MEMBERS(SampleStatus)
    assert isinstance(data["sample_index"], int) and data["sample_index"] >= 1
    assert isinstance(data["fields_reviewed_per_record"], int)
    assert data["fields_reviewed_per_record"] >= 1
    assert isinstance(data["population_size"], int) and data["population_size"] >= 1
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 1
    assert data["sample_size"] <= data["population_size"], (
        "sample_size may never exceed population_size"
    )
    assert data["sample_size"] <= 50, "sample_size is capped at fifty records"
    assert isinstance(data["selected_application_ids"], list)
    assert len(data["selected_application_ids"]) == data["sample_size"]
    assert isinstance(data["defect_count"], int)
    assert isinstance(data["records_with_defect_count"], int)
    if data.get("defect_rate_basis") is not None:
        assert data["defect_rate_basis"] in _MEMBERS(DefectRateBasis)


def assert_audit_finding(data: dict) -> None:
    assert_versioned_fields(data, "AuditFinding")
    assert is_valid_uuid(data["audit_sample_id"])
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["field_name"], str) and len(data["field_name"]) > 0
    assert isinstance(data["recorded_value"], str)
    assert isinstance(data["source_document_value"], str)
    assert isinstance(data["is_defect"], bool)
    assert data["is_defect"] == (
        data["recorded_value"] != data["source_document_value"]
    ), "is_defect is an exact, case-sensitive comparison of the two values"
    assert data["severity"] in _MEMBERS(FindingSeverity)
    assert data["resolution"] in _MEMBERS(FindingResolution)
    assert is_iso8601_timestamp(data["remediation_start"])
    assert is_iso8601_timestamp(data["remediation_end"])


def assert_fair_lending_analysis(data: dict) -> None:
    assert_versioned_fields(data, "FairLendingAnalysis")
    assert is_valid_uuid(data["institution_id"])
    assert data["basis"] in _MEMBERS(FairLendingBasis)
    assert data["status"] in _MEMBERS(FairLendingStatus)
    assert data["significance_flag"] in _MEMBERS(SignificanceFlag)
    assert isinstance(data["analysis_index"], int) and data["analysis_index"] >= 1
    for counter in ("control_total", "control_denied", "protected_total", "protected_denied"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert data["control_total"] >= 1 and data["protected_total"] >= 1
    assert data["control_denied"] <= data["control_total"]
    assert data["protected_denied"] <= data["protected_total"]
    for rate in ("control_denial_rate_pct", "protected_denial_rate_pct", "disparity_index"):
        assert isinstance(data[rate], (int, float)), f"{rate} must be numeric"
        assert round(float(data[rate]), 2) == float(data[rate]), (
            f"{rate} must be rounded to two decimal places"
        )


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_register_accounting_identity(institution: dict) -> None:
    """pending + reportable + excluded record counts reconcile to the total."""
    total = (
        institution["pending_record_count"]
        + institution["reportable_record_count"]
        + institution["excluded_record_count"]
    )
    assert total == institution["total_application_count"], (
        "pending_record_count + reportable_record_count + excluded_record_count must "
        f"equal total_application_count, got {total} vs "
        f"{institution['total_application_count']}"
    )


def assert_significance_banding(data: dict) -> None:
    """significance_flag bands disparity_index at 200.0 and 125.0."""
    index = float(data["disparity_index"])
    if index >= 200.0:
        expected = "SEVERE"
    elif index >= 125.0:
        expected = "ELEVATED"
    else:
        expected = "NOT_SIGNIFICANT"
    assert data["significance_flag"] == expected, (
        f"disparity_index {index} must band as {expected}, got {data['significance_flag']}"
    )
