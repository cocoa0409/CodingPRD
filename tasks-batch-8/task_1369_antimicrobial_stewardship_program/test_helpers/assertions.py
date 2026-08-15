"""Entity assertions and domain invariant checkers for the stewardship API."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_hospital(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["nhsn_facility_id"], str) and data["nhsn_facility_id"]
    assert isinstance(data["dot_review_threshold"], int)
    assert isinstance(data["iv_to_po_min_iv_hours"], int)
    assert isinstance(data["antibiogram_min_isolates"], int)
    assert isinstance(data["restricted_auto_expire_hours"], int)
    assert isinstance(data["current_utc"], str)


def assert_practitioner(data: dict):
    _assert_common(data)
    assert isinstance(data["hospital_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["license_no"], str)
    assert data["discipline"] in ["PHYSICIAN", "PHARMACIST", "MICROBIOLOGIST", "INFECTION_PREVENTIONIST"]
    assert isinstance(data["is_stewardship_member"], bool)
    assert isinstance(data["is_active"], bool)
    assert data["stewardship_standing"] in ["GOOD", "WATCH", "SUSPENDED"]
    assert isinstance(data["unresolved_noncompliance_count"], int)


def assert_patient_case(data: dict):
    _assert_common(data)
    assert isinstance(data["hospital_id"], str)
    assert isinstance(data["mrn"], str)
    assert isinstance(data["admitted_at"], str)
    assert isinstance(data["ward"], str)
    assert isinstance(data["is_immunocompromised"], bool)
    assert isinstance(data["weight_kg"], (int, float))
    assert isinstance(data["renal_function_crcl"], int)
    assert isinstance(data["has_enteral_access"], bool)
    assert data["status"] in ["ADMITTED", "DISCHARGED"]


def assert_antimicrobial(data: dict):
    _assert_common(data)
    assert isinstance(data["hospital_id"], str)
    assert isinstance(data["drug_name"], str)
    assert isinstance(data["drug_class"], str)
    assert isinstance(data["is_restricted"], bool)
    assert isinstance(data["has_po_form"], bool)
    assert isinstance(data["is_penicillin_class"], bool)
    assert data["formulary_status"] in ["ACTIVE", "SUSPENDED"]


def assert_allergy_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_case_id"], str)
    assert isinstance(data["reported_reaction"], str)
    assert data["reaction_severity"] in ["MILD", "MODERATE", "SEVERE"]
    assert isinstance(data["years_since_reaction"], int)
    assert isinstance(data["risk_score"], (int, float))
    assert isinstance(data["delabel_eligible"], bool)
    assert data["status"] in ["SUSPECTED", "TESTING_SCHEDULED", "TESTED", "DELABELED", "CONFIRMED", "WITHDRAWN"]
    assert data["test_result"] in ["NULL", "NEGATIVE", "POSITIVE", "INDETERMINATE"]


def assert_culture_report(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_case_id"], str)
    assert isinstance(data["specimen_source"], str)
    assert isinstance(data["collected_at"], str)
    assert isinstance(data["organism"], str)
    assert isinstance(data["is_first_isolate"], bool)
    assert data["status"] in ["PRELIMINARY", "FINAL", "AMENDED"]


def assert_susceptibility_result(data: dict):
    _assert_common(data)
    assert isinstance(data["culture_report_id"], str)
    assert isinstance(data["antimicrobial_id"], str)
    assert data["interpretation"] in ["S", "I", "R"]
    assert isinstance(data["mic_value"], (int, float))
    assert data["mic_value"] > 0


def assert_antibiotic_order(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_case_id"], str)
    assert isinstance(data["antimicrobial_id"], str)
    assert isinstance(data["prescriber_id"], str)
    assert data["route"] in ["IV", "PO", "IM"]
    assert isinstance(data["dose_mg"], int)
    assert isinstance(data["frequency_per_day"], int)
    assert isinstance(data["administered_doses"], int)
    assert isinstance(data["cumulative_iv_hours"], int)
    assert isinstance(data["dot_calendar"], int)
    assert isinstance(data["dot_dose"], (int, float))
    assert data["indication"] in ["EMPIRIC", "CULTURE_DIRECTED", "PROPHYLAXIS"]
    assert data["approval_status"] in ["NOT_REQUIRED", "PENDING", "APPROVED", "DENIED", "EXPIRED"]
    assert data["therapy_status"] in [
        "AWAITING_APPROVAL", "ACTIVE", "REVIEW_REQUIRED",
        "DEESCALATED", "CONVERTED", "COMPLETED", "DISCONTINUED",
    ]


def assert_approval_request(data: dict):
    _assert_common(data)
    assert isinstance(data["antibiotic_order_id"], str)
    assert isinstance(data["requester_id"], str)
    assert isinstance(data["justification"], str)
    assert isinstance(data["submitted_at"], str)
    assert data["status"] in ["SUBMITTED", "ESCALATED", "APPROVED", "DENIED", "EXPIRED", "WITHDRAWN"]


def assert_audit_intervention(data: dict):
    _assert_common(data)
    assert isinstance(data["antibiotic_order_id"], str)
    assert isinstance(data["auditor_id"], str)
    assert data["intervention_type"] in ["DOSE_OPTIMIZATION", "DEESCALATION", "IV_TO_PO", "DURATION_REDUCTION", "STOP"]
    assert isinstance(data["recommendation_text"], str)
    assert data["recommendation_status"] in [
        "DOCUMENTED", "RECOMMENDED", "ACCEPTED", "REJECTED",
        "APPEALED", "REJECTED_FINAL", "SUPERSEDED",
    ]
    assert isinstance(data["due_at"], str)


def assert_conversion_opportunity(data: dict):
    _assert_common(data)
    assert isinstance(data["antibiotic_order_id"], str)
    assert data["opportunity_kind"] in ["IV_TO_PO", "DEESCALATION"]
    assert isinstance(data["eligibility_score"], (int, float))
    assert isinstance(data["detected_at"], str)
    assert data["status"] in ["DETECTED", "ACCEPTED", "DECLINED", "EXPIRED"]


def assert_antibiogram(data: dict):
    _assert_common(data)
    assert isinstance(data["hospital_id"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["generated_at"], str)
    assert isinstance(data["row_count"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]


def assert_antibiogram_row(data: dict):
    _assert_common(data)
    assert isinstance(data["antibiogram_id"], str)
    assert isinstance(data["organism"], str)
    assert isinstance(data["antimicrobial_id"], str)
    assert isinstance(data["isolate_count"], int)
    assert isinstance(data["susceptible_count"], int)
    assert isinstance(data["pct_susceptible"], (int, float))
    assert isinstance(data["is_reportable"], bool)


def assert_empiric_guideline(data: dict):
    _assert_common(data)
    assert isinstance(data["hospital_id"], str)
    assert isinstance(data["syndrome"], str)
    assert isinstance(data["first_line_antimicrobial_id"], str)
    assert isinstance(data["source_antibiogram_id"], str)
    assert data["status"] in ["DRAFT", "ADOPTED", "STALE", "RETIRED"]


def assert_dot_metric_snapshot(data: dict):
    _assert_common(data)
    assert isinstance(data["hospital_id"], str)
    assert isinstance(data["period_label"], str)
    assert isinstance(data["total_dot_calendar"], int)
    assert isinstance(data["total_dot_dose"], (int, float))
    assert isinstance(data["patient_days"], int)
    assert isinstance(data["dot_per_1000_pd_calendar"], (int, float))
    assert isinstance(data["dot_per_1000_pd_dose"], (int, float))
    assert data["benchmark_percentile"] in [10, 25, 50, 75, 90]
    assert data["status"] in ["OPEN", "FINALIZED"]


def assert_regulatory_report(data: dict):
    _assert_common(data)
    assert isinstance(data["hospital_id"], str)
    assert data["report_type"] in ["NHSN_AUR", "STATE_MANDATE"]
    assert isinstance(data["period_label"], str)
    assert isinstance(data["dot_snapshot_id"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_order_dot_invariants(data: dict):
    """DOT counters on an order obey the calendar/dose relationship."""
    assert data["dot_calendar"] >= 0
    assert data["administered_doses"] >= 0
    assert data["dot_calendar"] <= data["administered_doses"] or data["administered_doses"] == 0
    assert_cost_precision(data["dot_dose"])
