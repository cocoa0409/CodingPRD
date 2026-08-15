"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_payer_policy(data: dict):
    """Validate a PayerPolicy response against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["payer_name"], str) and data["payer_name"]
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["compliance_threshold_pct"], int)
    assert 1 <= data["compliance_threshold_pct"] <= 100
    assert isinstance(data["compliance_min_hours_per_night"], (int, float))
    assert isinstance(data["compliance_window_days"], int)
    assert isinstance(data["compliance_min_nights"], int)
    assert isinstance(data["rental_months_to_own"], int)
    for field in ("mask_cadence_days", "cushion_cadence_days",
                  "filter_cadence_days", "tubing_cadence_days",
                  "mask_exchange_window_days", "max_exchanges_per_window"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["requires_prior_auth"], bool)


def assert_patient(data: dict):
    """Validate a Patient response against the PRD contract."""
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert is_valid_uuid(data.get("payer_policy_id", "")), "payer_policy_id must be a UUID"
    assert isinstance(data["prescribing_clinician_npi"], str)
    assert data["patient_status"] in [
        "INTAKE", "ACTIVE_THERAPY", "NON_COMPLIANT_HOLD", "DISCONTINUING", "DISCONTINUED",
    ]
    assert data.get("therapy_started_on") is None or isinstance(data["therapy_started_on"], str)
    assert data.get("adherence_percentage") is None or isinstance(
        data["adherence_percentage"], (int, float))
    assert isinstance(data["is_compliance_current"], bool)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert data.get("current_device_enrollment_id") is None or isinstance(
        data["current_device_enrollment_id"], str)
    assert data.get("current_rental_contract_id") is None or isinstance(
        data["current_rental_contract_id"], str)


def assert_device_enrollment(data: dict):
    """Validate a DeviceEnrollment response against the PRD contract."""
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert isinstance(data["device_serial"], str) and data["device_serial"]
    assert isinstance(data["device_model"], str) and data["device_model"]
    assert data["acquisition_type"] in ["RENTAL", "PURCHASE"]
    assert data["enrollment_status"] in [
        "PENDING_SETUP", "SETUP_IN_PROGRESS", "ACTIVE", "RETRIEVAL_PENDING",
        "RETRIEVED", "RETURNED_TO_PAYER", "DECOMMISSIONED",
    ]
    assert data.get("setup_completed_on") is None or isinstance(data["setup_completed_on"], str)
    assert data.get("last_adherence_download_on") is None or isinstance(
        data["last_adherence_download_on"], str)


def assert_component_supply_plan(data: dict):
    """Validate a ComponentSupplyPlan response against the PRD contract."""
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert data["component_type"] in ["MASK", "CUSHION", "FILTER", "TUBING"]
    assert isinstance(data["quantity_per_cycle"], int) and data["quantity_per_cycle"] >= 1
    assert data.get("last_dispensed_on") is None or isinstance(data["last_dispensed_on"], str)
    assert data.get("next_eligible_on") is None or isinstance(data["next_eligible_on"], str)
    assert data.get("reminder_sent_on") is None or isinstance(data["reminder_sent_on"], str)
    assert data["plan_status"] in [
        "ACTIVE", "SUSPENDED_NON_COMPLIANCE", "SUSPENDED_DISCONTINUATION", "CLOSED",
    ]


def assert_resupply_order(data: dict):
    """Validate a ResupplyOrder response against the PRD contract."""
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert is_valid_uuid(data.get("component_supply_plan_id", "")), \
        "component_supply_plan_id must be a UUID"
    assert isinstance(data["requested_quantity"], int) and data["requested_quantity"] >= 1
    assert data["auth_status"] in [
        "PENDING_CLINICAL_CLEARANCE", "PENDING_PAYER_AUTH", "AUTHORIZED", "DENIED", "CANCELLED",
    ]
    assert data["fulfillment_status"] in [
        "NOT_READY", "READY_TO_SHIP", "SHIPPED", "DELIVERED", "INVOICED", "RETURNED",
    ]
    assert data.get("unit_allowable_cents") is None or isinstance(data["unit_allowable_cents"], int)
    assert data.get("patient_responsibility_cents") is None or isinstance(
        data["patient_responsibility_cents"], int)
    assert data.get("shipped_on") is None or isinstance(data["shipped_on"], str)


def assert_adherence_report(data: dict):
    """Validate an AdherenceReport response against the PRD contract."""
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert is_valid_uuid(data.get("device_enrollment_id", "")), \
        "device_enrollment_id must be a UUID"
    assert isinstance(data["window_end_on"], str)
    assert isinstance(data["window_start_on"], str)
    assert isinstance(data["nights_reported"], int) and data["nights_reported"] >= 0
    assert isinstance(data["compliant_nights"], int) and data["compliant_nights"] >= 0
    assert isinstance(data["adherence_pct_provisional"], (int, float))
    assert data.get("adherence_pct_final") is None or isinstance(
        data["adherence_pct_final"], (int, float))
    assert data["report_status"] in ["RECEIVED", "UNDER_REVIEW", "FINALIZED", "REJECTED"]


def assert_mask_exchange(data: dict):
    """Validate a MaskExchange response against the PRD contract."""
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert is_valid_uuid(data.get("device_enrollment_id", "")), \
        "device_enrollment_id must be a UUID"
    assert is_valid_uuid(data.get("original_mask_plan_id", "")), \
        "original_mask_plan_id must be a UUID"
    assert data["reason_code"] in [
        "FIT_LEAK", "SKIN_IRRITATION", "WRONG_SIZE", "PRESSURE_INTOLERANCE",
    ]
    assert data["exchange_status"] in [
        "REQUESTED", "APPROVED", "SHIPPED", "COMPLETED", "DENIED", "CANCELLED",
    ]
    assert isinstance(data["window_anchor_on"], str) and data["window_anchor_on"]
    assert data.get("completed_on") is None or isinstance(data["completed_on"], str)
    assert data.get("superseded_by_exchange_id") is None or isinstance(
        data["superseded_by_exchange_id"], str)


def assert_rental_contract(data: dict):
    """Validate a RentalContract response against the PRD contract."""
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert is_valid_uuid(data.get("device_enrollment_id", "")), \
        "device_enrollment_id must be a UUID"
    assert isinstance(data["rental_start_on"], str) and data["rental_start_on"]
    assert isinstance(data["rental_months_billed"], int) and data["rental_months_billed"] >= 0
    assert data["billing_status"] in [
        "SCHEDULED", "BILLING", "PAUSED_NON_COMPLIANCE",
        "CONVERTED_TO_OWNERSHIP", "TERMINATED",
    ]
    assert data["equipment_status"] in [
        "WITH_PATIENT", "RETRIEVAL_REQUESTED", "RETRIEVED", "OWNERSHIP_TRANSFERRED",
    ]


def assert_retrieval_case(data: dict):
    """Validate a RetrievalCase response against the PRD contract."""
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert is_valid_uuid(data.get("device_enrollment_id", "")), \
        "device_enrollment_id must be a UUID"
    assert data["reason_code"] in [
        "THERAPY_DISCONTINUED", "PROLONGED_NON_COMPLIANCE",
        "PAYER_STOPPED_COVERAGE", "PATIENT_REQUEST",
    ]
    assert data["retrieval_status"] in [
        "OPEN", "SCHEDULED", "IN_TRANSIT", "RECEIVED", "RECONCILED", "CLOSED_UNRECOVERABLE",
    ]
    assert isinstance(data["due_on"], str) and data["due_on"]
    assert data.get("received_on") is None or isinstance(data["received_on"], str)
