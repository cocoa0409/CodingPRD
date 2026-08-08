"""Entity assertions and domain invariant checkers."""

import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

DASHED_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
RENDERED_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# Shared field-shape assertions
# --------------------------------------------------------------------------


def assert_dashed_uuid(value, label="id"):
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert DASHED_UUID_RE.match(value), (
        f"{label} must be a dashed 8-4-4-4-12 UUID with no type prefix, got {value!r}"
    )
    assert is_valid_uuid(value), f"{label} must be a valid UUID, got {value!r}"


def assert_rendered_timestamp(value, label="timestamp"):
    """Datetimes are ISO 8601 UTC with exactly three fractional digits and a Z."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert RENDERED_TIMESTAMP_RE.match(value), (
        f"{label} must be ISO 8601 UTC with exactly three fractional-second digits "
        f"and a trailing Z, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"


def assert_date_only(value, label="date"):
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert DATE_ONLY_RE.match(value), (
        f"{label} must be a plain YYYY-MM-DD string, got {value!r}"
    )


def assert_versioned_common_fields(data, label="resource"):
    """Resources that carry id, created_at, updated_at and version."""
    assert_dashed_uuid(data.get("id"), f"{label}.id")
    assert_rendered_timestamp(data.get("created_at"), f"{label}.created_at")
    assert_rendered_timestamp(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_append_only_common_fields(data, label="record"):
    """Append-only observations carry only id and created_at."""
    assert_dashed_uuid(data.get("id"), f"{label}.id")
    assert_rendered_timestamp(data.get("created_at"), f"{label}.created_at")
    assert "updated_at" not in data, (
        f"{label} is append-only and must not carry an updated_at field"
    )
    assert "version" not in data, (
        f"{label} is append-only and must not carry a version field"
    )


def assert_envelope_meta(body):
    meta = body.get("meta", {})
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id required"
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_rendered_timestamp(
        meta.get("api_request_timestamp"), "meta.api_request_timestamp"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_operator(data):
    assert_versioned_common_fields(data, "Operator")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 200
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert isinstance(data["fee_balance_cents"], int), (
        "fee_balance_cents must be integer cents"
    )


def assert_facility(data):
    assert_versioned_common_fields(data, "Facility")
    assert_dashed_uuid(data["operator_id"], "Facility.operator_id")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["facility_class"] in [
        "CLASS_A_COMPETITION", "CLASS_B_PUBLIC", "CLASS_C_SEMI_PUBLIC", "SPA",
    ]
    assert data["water_type"] in ["POOL", "SPA"]
    assert data["surface_area_sqft"] > 0
    assert data["water_volume_gallons"] >= 0
    assert data["max_depth_feet"] > 0
    assert data["drain_count"] >= 1
    assert isinstance(data["features"], list)
    assert isinstance(data["is_seasonal"], bool)
    assert isinstance(data["requires_plan_review"], bool)
    assert isinstance(data["max_bather_load"], int)
    assert isinstance(data["lifeguard_required"], bool)
    assert isinstance(data["required_signage_types"], list)
    assert data["vgb_compliance_status"] in ["COMPLIANT", "EXPIRED", "NONCOMPLIANT"]
    assert isinstance(data["open_demerit_points"], int)
    assert data["operating_posture"] in ["OPEN", "RESTRICTED", "CLOSED"]
    assert data["posture_reason"] in [
        "CLOSURE_ORDER_OPEN", "PERMIT_MISSING", "PERMIT_NOT_ACTIVE", "OUT_OF_SEASON",
        "VGB_NONCOMPLIANT", "CRITICAL_VIOLATION_OPEN", "SIGNAGE_INCOMPLETE",
        "LIFEGUARD_COVERAGE_MISSING", "NONE",
    ]


def assert_plan_review(data):
    assert_versioned_common_fields(data, "PlanReview")
    assert_dashed_uuid(data["facility_id"], "PlanReview.facility_id")
    assert data["project_type"] in [
        "NEW_CONSTRUCTION", "ALTERATION", "EQUIPMENT_REPLACEMENT",
    ]
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "CORRECTIONS_REQUIRED", "APPROVED",
        "DISAPPROVED", "SUPERSEDED",
    ]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert_date_only(data["submitted_on"], "PlanReview.submitted_on")


def assert_permit(data):
    assert_versioned_common_fields(data, "Permit")
    assert_dashed_uuid(data["facility_id"], "Permit.facility_id")
    assert data["permit_type"] in ["ANNUAL", "SEASONAL"]
    assert_date_only(data["term_start_date"], "Permit.term_start_date")
    assert_date_only(data["term_end_date"], "Permit.term_end_date")
    assert_date_only(data["applied_on"], "Permit.applied_on")
    assert isinstance(data["term_days"], int) and data["term_days"] > 0
    assert isinstance(data["is_late_application"], bool)
    assert isinstance(data["assessed_fee_cents"], int)
    assert data["fee_variant"] in [None, "FULL_TERM", "SEASONAL_PRORATED"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ISSUED", "DENIED", "SUSPENDED",
        "REVOKED", "EXPIRED",
    ]
    assert isinstance(data["refunded"], bool)


def assert_inspection(data):
    assert_versioned_common_fields(data, "Inspection")
    assert_dashed_uuid(data["facility_id"], "Inspection.facility_id")
    assert data["inspection_type"] in [
        "ROUTINE", "REINSPECTION", "COMPLAINT", "PREOPERATIONAL",
    ]
    assert isinstance(data["inspector_user_id"], str)
    assert_rendered_timestamp(
        data["scheduled_start_at"], "Inspection.scheduled_start_at"
    )
    assert_rendered_timestamp(data["scheduled_end_at"], "Inspection.scheduled_end_at")
    assert data["workflow_status"] in [
        "SCHEDULED", "IN_PROGRESS", "SUBMITTED", "FINALIZED", "VOIDED",
    ]
    assert data["enforcement_status"] in [
        "NONE", "NOTICE_ISSUED", "ESCALATED", "CLEARED",
    ]
    assert data["result"] in [None, "PASS", "CONDITIONAL", "FAIL"]


def assert_violation(data):
    assert_versioned_common_fields(data, "Violation")
    assert_dashed_uuid(data["inspection_id"], "Violation.inspection_id")
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 32
    assert data["severity"] in ["IMMINENT_HEALTH_HAZARD", "CRITICAL", "NONCRITICAL"]
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert isinstance(data["corrected_on_site"], bool)
    assert isinstance(data["points_assessed"], int)
    assert data["status"] in ["OPEN", "CORRECTED", "VERIFIED", "VOIDED"]
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0


def assert_water_reading(data):
    assert_append_only_common_fields(data, "WaterChemistryReading")
    assert_dashed_uuid(data["facility_id"], "WaterChemistryReading.facility_id")
    assert_rendered_timestamp(data["sampled_at"], "WaterChemistryReading.sampled_at")
    assert data["source"] in ["OPERATOR_LOG", "INSPECTOR_FIELD", "REOPEN_VERIFICATION"]
    assert data["free_chlorine_ppm"] >= 0
    assert data["combined_chloramine_ppm"] >= 0
    assert 0 <= data["ph"] <= 14
    assert data["cyanuric_acid_ppm"] >= 0
    assert data["water_temp_f"] >= 0
    assert data["compliance_status"] in ["IN_RANGE", "OUT_OF_RANGE", "IMMINENT_HAZARD"]
    assert isinstance(data["out_of_range_parameters"], list)


def assert_closure_order(data):
    assert_versioned_common_fields(data, "ClosureOrder")
    assert_dashed_uuid(data["facility_id"], "ClosureOrder.facility_id")
    assert data["closure_reason"] in [
        "FECAL_FORMED", "FECAL_DIARRHEAL", "VOMIT", "BLOOD", "CHEMICAL",
        "WATER_CHEMISTRY", "EQUIPMENT", "RWI_OUTBREAK", "PERMIT_ACTION",
    ]
    assert isinstance(data["ordered_by_user_id"], str)
    assert data["ordered_by_role"] in [
        "Inspector", "HealthAuthorityAdmin", "Operator", "system",
    ]
    assert_rendered_timestamp(data["ordered_at"], "ClosureOrder.ordered_at")
    assert data["status"] in ["OPEN", "REOPEN_REQUESTED", "CLEARED", "VOIDED"]
    assert data["remediation_variant"] in ["FIXED_TABLE", "CT_COMPUTED"]
    assert isinstance(data["required_remediation_minutes"], int)
    assert_rendered_timestamp(
        data["earliest_reopen_at"], "ClosureOrder.earliest_reopen_at"
    )
    assert isinstance(data["denial_count"], int) and data["denial_count"] >= 0


def assert_staff_assignment(data):
    assert_versioned_common_fields(data, "StaffAssignment")
    assert_dashed_uuid(data["facility_id"], "StaffAssignment.facility_id")
    assert isinstance(data["staff_ref"], str) and 1 <= len(data["staff_ref"]) <= 64
    assert isinstance(data["staff_name"], str) and len(data["staff_name"]) > 0
    assert data["role_type"] in ["LIFEGUARD", "ATTENDANT"]
    assert_date_only(
        data["certification_expires_on"], "StaffAssignment.certification_expires_on"
    )
    assert_rendered_timestamp(data["shift_start_at"], "StaffAssignment.shift_start_at")
    assert_rendered_timestamp(data["shift_end_at"], "StaffAssignment.shift_end_at")
    assert data["status"] in ["SCHEDULED", "CANCELLED"]
    assert data["cancel_reason"] in [None, "OPERATOR_REQUEST", "FACILITY_CLOSED"]


def assert_compliance_artifact(data):
    assert_versioned_common_fields(data, "ComplianceArtifact")
    assert_dashed_uuid(data["facility_id"], "ComplianceArtifact.facility_id")
    assert data["artifact_type"] in ["SIGNAGE", "DRAIN_CERTIFICATION"]
    assert_date_only(data["effective_on"], "ComplianceArtifact.effective_on")
    assert_date_only(data["expires_on"], "ComplianceArtifact.expires_on")
    assert data["status"] in ["ACTIVE", "EXPIRED", "SUPERSEDED"]


def assert_complaint(data):
    assert_versioned_common_fields(data, "Complaint")
    assert_dashed_uuid(data["facility_id"], "Complaint.facility_id")
    assert data["complaint_type"] in [
        "RWI_ILLNESS", "INJURY", "WATER_QUALITY", "SANITATION", "SAFETY_EQUIPMENT",
    ]
    assert isinstance(data["narrative"], str) and len(data["narrative"]) > 0
    assert_rendered_timestamp(data["reported_at"], "Complaint.reported_at")
    assert data["risk_variant"] in [None, "SINGLE_REPORT", "CLUSTER_AGGREGATE"]
    assert isinstance(data["cluster_case_count"], int)
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert isinstance(data["escalated"], bool)
    assert data["status"] in [
        "RECEIVED", "TRIAGED", "INVESTIGATING", "SUBSTANTIATED", "UNSUBSTANTIATED",
        "CLOSED",
    ]


def assert_fee_ledger_entry(data):
    assert_append_only_common_fields(data, "FeeLedgerEntry")
    assert_dashed_uuid(data["operator_id"], "FeeLedgerEntry.operator_id")
    assert data["entry_type"] in [
        "PERMIT_FEE", "LATE_PENALTY", "PLAN_REVIEW_FEE", "REINSPECTION_FEE",
        "PAYMENT", "REFUND",
    ]
    assert isinstance(data["amount_cents"], int), "amount_cents must be integer cents"
    assert_rendered_timestamp(data["posted_at"], "FeeLedgerEntry.posted_at")
    if data["entry_type"] in ("PERMIT_FEE", "LATE_PENALTY", "PLAN_REVIEW_FEE",
                              "REINSPECTION_FEE"):
        assert data["amount_cents"] > 0, (
            f"{data['entry_type']} is a charge and posts a positive amount"
        )
    else:
        assert data["amount_cents"] < 0, (
            f"{data['entry_type']} is a credit and posts a negative amount"
        )
    if data["entry_type"] in ("PLAN_REVIEW_FEE", "REINSPECTION_FEE", "PAYMENT"):
        assert data["permit_id"] is None, (
            f"{data['entry_type']} postings carry a null permit_id"
        )


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------


def assert_fee_balance_equals_ledger_sum(operator, ledger_rows):
    """Money is a conserved quantity: the balance is the sum of every posting."""
    total = sum(row["amount_cents"] for row in ledger_rows)
    assert operator["fee_balance_cents"] == total, (
        f"fee_balance_cents {operator['fee_balance_cents']} must equal the sum of "
        f"ledger postings {total}"
    )


def assert_posture(facility, expected_posture, expected_reason):
    assert facility["operating_posture"] == expected_posture, (
        f"Expected operating_posture {expected_posture}, got "
        f"{facility['operating_posture']} (reason {facility['posture_reason']})"
    )
    assert facility["posture_reason"] == expected_reason, (
        f"Expected posture_reason {expected_reason}, got {facility['posture_reason']}"
    )
