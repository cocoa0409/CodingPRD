"""Entity assertions and domain invariant checkers.

Each per-entity assert_<entity>() verifies the PRD-declared shape of a
single response payload. Field names mirror PRD prose exactly.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status value sets - verbatim from PRD entity descriptions.
# ---------------------------------------------------------------------------
PATIENT_STATUSES = {"ACTIVE", "DECEASED", "MERGED_OUT", "ARCHIVED"}
SEX_AT_BIRTH_VALUES = {"FEMALE", "MALE", "UNKNOWN"}
VACCINE_PRODUCT_STATUSES = {"ACTIVE", "DISCONTINUED"}
ROUTE_VALUES = {"IM", "SC", "ORAL", "INTRANASAL"}
ANTIGEN_VALUES = {
    "DTAP_DIPHTHERIA", "DTAP_TETANUS", "DTAP_PERTUSSIS",
    "MMR_MEASLES", "MMR_MUMPS", "MMR_RUBELLA",
    "HEPB", "HPV", "POLIO", "VARICELLA",
}
ALLERGEN_CODES = {"EGG", "LATEX", "NEOMYCIN", "GELATIN", "YEAST", "OTHER"}
ALLERGY_SEVERITIES = {"MILD", "MODERATE", "SEVERE", "ANAPHYLAXIS"}
LOT_STATUSES = {"AVAILABLE", "RECALLED", "EXHAUSTED"}
RECALL_REASONS = {"MANUFACTURER_DEFECT", "CONTAMINATION", "EXPIRED"}
PROVIDER_ORG_STATUSES = {"ACTIVE", "SUSPENDED"}
REPORTING_JURISDICTIONS = {"IN_STATE", "OUT_OF_STATE"}
DOSE_STATES = {"SCHEDULED", "ADMINISTERED", "INVALIDATED", "CANCELLED"}
INVALIDATION_REASONS = {"LOT_RECALL", "DATA_ERROR"}
SERIOUSNESS_VALUES = {"NON_SERIOUS", "SERIOUS", "DEATH"}
CLINICAL_REVIEW_STATUSES = {
    "PENDING_REVIEW", "UNDER_REVIEW",
    "CAUSALLY_RELATED", "NOT_RELATED",
}
VAERS_SUBMISSION_STATUSES = {
    "NOT_SUBMITTED", "SUBMITTED", "ACK_RECEIVED", "REJECTED",
}
CERTIFICATE_STATUSES = {
    "DRAFT", "ISSUED", "DEFICIENT", "EXEMPTION_GRANTED", "REVOKED",
}
GRADE_LEVELS = {
    "K", "G1", "G2", "G3", "G4", "G5", "G6",
    "G7", "G8", "G9", "G10", "G11", "G12",
}


# ---------------------------------------------------------------------------
# Common helpers.
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any], entity_name: str) -> None:
    """Verify PRD §2.4 common-fields shape: id (UUID), created_at,
    updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be an integer"
    )
    assert data["version"] >= 1, (
        f"{entity_name}.version must be >= 1, got {data['version']!r}"
    )


def assert_version_incremented_by_one(before: Dict[str, Any],
                                      after: Dict[str, Any],
                                      entity_name: str = "entity") -> None:
    """PRD §2.4: 'version is an integer that starts at 1 on creation
    and increments by exactly 1 on every persisted mutation, again
    including cascades.'"""
    assert after["version"] == before["version"] + 1, (
        f"{entity_name}.version expected to increment by exactly 1 "
        f"(before={before['version']}, after={after['version']})"
    )


# ---------------------------------------------------------------------------
# Patient - PRD §3.1 / §2.4.
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    """PRD §3.1 / §2.4. Patient carries common fields plus first_name,
    last_name, date_of_birth, sex_at_birth, state_resident,
    guardian_contact_email, medical_exemption_on_file, status."""
    _assert_common_fields(data, "Patient")
    assert isinstance(data.get("first_name"), str) and data["first_name"], (
        "Patient.first_name must be non-empty string"
    )
    assert isinstance(data.get("last_name"), str) and data["last_name"], (
        "Patient.last_name must be non-empty string"
    )
    assert isinstance(data.get("date_of_birth"), str), (
        "Patient.date_of_birth must be string (ISO 8601 date)"
    )
    assert data.get("sex_at_birth") in SEX_AT_BIRTH_VALUES, (
        f"Patient.sex_at_birth must be one of {SEX_AT_BIRTH_VALUES}, "
        f"got {data.get('sex_at_birth')!r}"
    )
    assert isinstance(data.get("state_resident"), bool), (
        "Patient.state_resident must be bool"
    )
    assert isinstance(data.get("medical_exemption_on_file"), bool), (
        "Patient.medical_exemption_on_file must be bool"
    )
    assert data.get("status") in PATIENT_STATUSES, (
        f"Patient.status must be one of {PATIENT_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# VaccineProduct - PRD §3.2 / §2.4.
# ---------------------------------------------------------------------------
def assert_vaccine_product(data: Dict[str, Any]) -> None:
    """PRD §3.2 / §2.4."""
    _assert_common_fields(data, "VaccineProduct")
    assert isinstance(data.get("cvx_code"), str) and 1 <= len(
        data["cvx_code"]) <= 6, (
        "VaccineProduct.cvx_code must be 1..6 chars"
    )
    assert isinstance(data.get("trade_name"), str), (
        "VaccineProduct.trade_name must be string"
    )
    antigens = data.get("antigens")
    assert isinstance(antigens, list) and len(antigens) >= 1, (
        "VaccineProduct.antigens must be array with min length 1"
    )
    for a in antigens:
        assert a in ANTIGEN_VALUES, (
            f"VaccineProduct.antigens entry must be one of "
            f"{ANTIGEN_VALUES}, got {a!r}"
        )
    assert isinstance(data.get("min_age_days"), int), (
        "VaccineProduct.min_age_days must be int"
    )
    assert data["min_age_days"] >= 0, (
        "VaccineProduct.min_age_days must be >= 0"
    )
    max_age = data.get("max_age_days")
    assert max_age is None or isinstance(max_age, int), (
        "VaccineProduct.max_age_days must be int or null"
    )
    assert data.get("route") in ROUTE_VALUES, (
        f"VaccineProduct.route must be one of {ROUTE_VALUES}"
    )
    assert data.get("status") in VACCINE_PRODUCT_STATUSES, (
        f"VaccineProduct.status must be one of {VACCINE_PRODUCT_STATUSES}"
    )
    cflags = data.get("contraindication_flags")
    if cflags is not None:
        assert isinstance(cflags, list), (
            "VaccineProduct.contraindication_flags must be list when present"
        )


# ---------------------------------------------------------------------------
# VaccineLot - PRD §3.2 / §2.4.
# ---------------------------------------------------------------------------
def assert_vaccine_lot(data: Dict[str, Any]) -> None:
    """PRD §3.2 / §2.4."""
    _assert_common_fields(data, "VaccineLot")
    assert is_valid_uuid(data.get("vaccine_product_id", "")), (
        "VaccineLot.vaccine_product_id must be UUID"
    )
    assert is_valid_uuid(data.get("provider_organization_id", "")), (
        "VaccineLot.provider_organization_id must be UUID"
    )
    assert isinstance(data.get("lot_number"), str), (
        "VaccineLot.lot_number must be string"
    )
    assert isinstance(data.get("expiration_date"), str), (
        "VaccineLot.expiration_date must be string (ISO 8601 date)"
    )
    assert isinstance(data.get("doses_on_hand"), int), (
        "VaccineLot.doses_on_hand must be int"
    )
    assert data["doses_on_hand"] >= 0, (
        "VaccineLot.doses_on_hand must be >= 0"
    )
    assert data.get("status") in LOT_STATUSES, (
        f"VaccineLot.status must be one of {LOT_STATUSES}"
    )
    rr = data.get("recall_reason")
    if rr is not None:
        assert rr in RECALL_REASONS, (
            f"VaccineLot.recall_reason must be one of {RECALL_REASONS} "
            f"or null, got {rr!r}"
        )


# ---------------------------------------------------------------------------
# ProviderOrganization - PRD §3.2 / §3.6 / §2.4.
# ---------------------------------------------------------------------------
def assert_provider_organization(data: Dict[str, Any]) -> None:
    """PRD §3.2 / §3.6 / §2.4."""
    _assert_common_fields(data, "ProviderOrganization")
    assert isinstance(data.get("name"), str) and data["name"], (
        "ProviderOrganization.name must be non-empty string"
    )
    assert isinstance(data.get("npi"), str), (
        "ProviderOrganization.npi must be string"
    )
    assert len(data["npi"]) == 10 and data["npi"].isdigit(), (
        f"ProviderOrganization.npi must be exactly 10 digits, "
        f"got {data['npi']!r}"
    )
    assert data.get("reporting_jurisdiction") in REPORTING_JURISDICTIONS, (
        f"ProviderOrganization.reporting_jurisdiction must be one of "
        f"{REPORTING_JURISDICTIONS}"
    )
    score = data.get("reporting_compliance_score")
    assert isinstance(score, (int, float)), (
        "ProviderOrganization.reporting_compliance_score must be number"
    )
    assert 0.0 <= float(score) <= 100.0, (
        "ProviderOrganization.reporting_compliance_score must be in [0, 100]"
    )
    assert data.get("status") in PROVIDER_ORG_STATUSES, (
        f"ProviderOrganization.status must be one of "
        f"{PROVIDER_ORG_STATUSES}"
    )


# ---------------------------------------------------------------------------
# AdministeredDose - PRD §3.3 / §2.4.
# ---------------------------------------------------------------------------
def assert_administered_dose(data: Dict[str, Any]) -> None:
    """PRD §3.3 / §2.4."""
    _assert_common_fields(data, "AdministeredDose")
    assert is_valid_uuid(data.get("patient_id", "")), (
        "AdministeredDose.patient_id must be UUID"
    )
    assert is_valid_uuid(data.get("vaccine_product_id", "")), (
        "AdministeredDose.vaccine_product_id must be UUID"
    )
    assert is_valid_uuid(data.get("lot_id", "")), (
        "AdministeredDose.lot_id must be UUID"
    )
    assert is_valid_uuid(data.get("provider_organization_id", "")), (
        "AdministeredDose.provider_organization_id must be UUID"
    )
    assert isinstance(data.get("administering_clinician_id"), str), (
        "AdministeredDose.administering_clinician_id must be string"
    )
    assert data.get("dose_state") in DOSE_STATES, (
        f"AdministeredDose.dose_state must be one of {DOSE_STATES}, "
        f"got {data.get('dose_state')!r}"
    )
    inv = data.get("invalidation_reason")
    if inv is not None:
        assert inv in INVALIDATION_REASONS, (
            f"AdministeredDose.invalidation_reason must be one of "
            f"{INVALIDATION_REASONS} or null, got {inv!r}"
        )
    assert is_iso8601_timestamp(data.get("reported_at", "")), (
        "AdministeredDose.reported_at must be ISO 8601 timestamp"
    )
    assert isinstance(data.get("catchup_flag"), bool), (
        "AdministeredDose.catchup_flag must be bool"
    )


# ---------------------------------------------------------------------------
# AllergyRecord - PRD §3.4 / §2.4 (no updated_at, no version).
# ---------------------------------------------------------------------------
def assert_allergy_record(data: Dict[str, Any]) -> None:
    """PRD §3.4 / §2.4: 'The AllergyRecord entity is the single
    exception: its record is immutable once written and therefore
    carries only id and created_at - both updated_at and version are
    absent from its representation.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"AllergyRecord.id must be UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "AllergyRecord.created_at must be ISO 8601"
    )
    # Verify absence of updated_at and version.
    assert "updated_at" not in data, (
        "AllergyRecord must NOT carry updated_at "
        "(PRD §2.4: 'both updated_at and version are absent')"
    )
    assert "version" not in data, (
        "AllergyRecord must NOT carry version "
        "(PRD §2.4: 'both updated_at and version are absent')"
    )
    assert is_valid_uuid(data.get("patient_id", "")), (
        "AllergyRecord.patient_id must be UUID"
    )
    assert data.get("allergen_code") in ALLERGEN_CODES, (
        f"AllergyRecord.allergen_code must be one of {ALLERGEN_CODES}"
    )
    assert data.get("severity") in ALLERGY_SEVERITIES, (
        f"AllergyRecord.severity must be one of {ALLERGY_SEVERITIES}"
    )
    assert is_iso8601_timestamp(data.get("recorded_at", "")), (
        "AllergyRecord.recorded_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# AdverseEvent - PRD §3.9 / §2.4.
# ---------------------------------------------------------------------------
def assert_adverse_event(data: Dict[str, Any]) -> None:
    """PRD §3.9 / §2.4."""
    _assert_common_fields(data, "AdverseEvent")
    assert is_valid_uuid(data.get("patient_id", "")), (
        "AdverseEvent.patient_id must be UUID"
    )
    assert is_valid_uuid(data.get("dose_id", "")), (
        "AdverseEvent.dose_id must be UUID"
    )
    assert is_iso8601_timestamp(data.get("onset_at", "")), (
        "AdverseEvent.onset_at must be ISO 8601"
    )
    sc = data.get("symptom_codes")
    assert isinstance(sc, list) and len(sc) >= 1, (
        "AdverseEvent.symptom_codes must be array with min length 1"
    )
    assert data.get("seriousness") in SERIOUSNESS_VALUES, (
        f"AdverseEvent.seriousness must be one of {SERIOUSNESS_VALUES}"
    )
    assert data.get("clinical_review_status") in CLINICAL_REVIEW_STATUSES, (
        f"AdverseEvent.clinical_review_status must be one of "
        f"{CLINICAL_REVIEW_STATUSES}"
    )
    assert data.get("vaers_submission_status") in VAERS_SUBMISSION_STATUSES, (
        f"AdverseEvent.vaers_submission_status must be one of "
        f"{VAERS_SUBMISSION_STATUSES}"
    )
    assert isinstance(data.get("vaers_required"), bool), (
        "AdverseEvent.vaers_required must be bool"
    )
    sub_id = data.get("vaers_submission_id")
    if sub_id is not None:
        assert is_valid_uuid(sub_id), (
            "AdverseEvent.vaers_submission_id must be UUID when non-null"
        )


# ---------------------------------------------------------------------------
# AntigenScheduleRule - PRD §3.7 / §2.4.
# ---------------------------------------------------------------------------
def assert_antigen_schedule_rule(data: Dict[str, Any]) -> None:
    """PRD §3.7 / §2.4."""
    _assert_common_fields(data, "AntigenScheduleRule")
    assert data.get("antigen") in ANTIGEN_VALUES, (
        f"AntigenScheduleRule.antigen must be one of {ANTIGEN_VALUES}"
    )
    assert isinstance(data.get("dose_sequence_number"), int), (
        "AntigenScheduleRule.dose_sequence_number must be int"
    )
    assert data["dose_sequence_number"] >= 1, (
        "AntigenScheduleRule.dose_sequence_number must be >= 1"
    )
    for f in ("routine_min_age_days", "routine_recommended_age_days",
              "routine_max_age_days", "catchup_min_interval_days"):
        assert isinstance(data.get(f), int), (
            f"AntigenScheduleRule.{f} must be int"
        )
    pre = data.get("prerequisite_rule_id")
    if pre is not None:
        assert is_valid_uuid(pre), (
            "AntigenScheduleRule.prerequisite_rule_id must be UUID or null"
        )
    assert isinstance(data.get("school_enrollment_required"), bool), (
        "AntigenScheduleRule.school_enrollment_required must be bool"
    )


# ---------------------------------------------------------------------------
# SchoolEnrollmentCertificate - PRD §3.8 / §2.4.
# ---------------------------------------------------------------------------
def assert_school_certificate(data: Dict[str, Any]) -> None:
    """PRD §3.8 / §2.4."""
    _assert_common_fields(data, "SchoolEnrollmentCertificate")
    assert is_valid_uuid(data.get("patient_id", "")), (
        "SchoolEnrollmentCertificate.patient_id must be UUID"
    )
    assert isinstance(data.get("school_year"), str), (
        "SchoolEnrollmentCertificate.school_year must be string"
    )
    sy = data["school_year"]
    parts = sy.split("-")
    assert len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 4, (
        f"SchoolEnrollmentCertificate.school_year must be format YYYY-YYYY, "
        f"got {sy!r}"
    )
    assert int(parts[1]) == int(parts[0]) + 1, (
        "PRD §3.8: school_year second year must be first year + 1"
    )
    assert data.get("grade_level") in GRADE_LEVELS, (
        f"SchoolEnrollmentCertificate.grade_level must be one of "
        f"{GRADE_LEVELS}"
    )
    assert data.get("certificate_status") in CERTIFICATE_STATUSES, (
        f"SchoolEnrollmentCertificate.certificate_status must be one of "
        f"{CERTIFICATE_STATUSES}"
    )
    ma = data.get("missing_antigens")
    assert isinstance(ma, list), (
        "SchoolEnrollmentCertificate.missing_antigens must be list"
    )
    # PRD §3.8: "sorted alphabetically ascending by antigen name so
    # that the result is order-stable across invocations."
    assert list(ma) == sorted(ma), (
        f"SchoolEnrollmentCertificate.missing_antigens must be sorted "
        f"alphabetically ascending, got {ma!r}"
    )
    ia = data.get("issued_at")
    if ia is not None:
        assert is_iso8601_timestamp(ia), (
            "SchoolEnrollmentCertificate.issued_at must be ISO 8601 or null"
        )


# ---------------------------------------------------------------------------
# Score precision - PRD §3.6 / §2.8.
# ---------------------------------------------------------------------------
def assert_score_precision(score: float) -> None:
    """PRD §2.8 / §3.6: 'rounded to two decimal places.'"""
    # Compare to its 2-dp rounded form.
    rounded = round(float(score) + 1e-9, 2)
    assert abs(float(score) - rounded) < 1e-6, (
        f"reporting_compliance_score must have <= 2 decimal places, "
        f"got {score!r}"
    )


__all__ = [
    "PATIENT_STATUSES",
    "SEX_AT_BIRTH_VALUES",
    "VACCINE_PRODUCT_STATUSES",
    "ROUTE_VALUES",
    "ANTIGEN_VALUES",
    "ALLERGEN_CODES",
    "ALLERGY_SEVERITIES",
    "LOT_STATUSES",
    "RECALL_REASONS",
    "PROVIDER_ORG_STATUSES",
    "REPORTING_JURISDICTIONS",
    "DOSE_STATES",
    "INVALIDATION_REASONS",
    "SERIOUSNESS_VALUES",
    "CLINICAL_REVIEW_STATUSES",
    "VAERS_SUBMISSION_STATUSES",
    "CERTIFICATE_STATUSES",
    "GRADE_LEVELS",
    "assert_version_incremented_by_one",
    "assert_patient",
    "assert_vaccine_product",
    "assert_vaccine_lot",
    "assert_provider_organization",
    "assert_administered_dose",
    "assert_allergy_record",
    "assert_adverse_event",
    "assert_antigen_schedule_rule",
    "assert_school_certificate",
    "assert_score_precision",
]
