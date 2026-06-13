"""Entity assertions and domain invariant checkers (PRD §1, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    EncounterStatus,
    PrescriptionStatus,
    EligibilityStatus,
    LabOrderStatus,
    ClaimStatus,
    SubmissionStatus,
    RecallReminderStatus,
    PLAN_CARRIERS,
    ENCOUNTER_TYPES,
    RX_TYPES,
    PROVIDER_ROLES,
    FRAME_TIERS,
    POOL_TYPES,
    BILLING_ROUTES,
    RECALL_CHANNELS,
)


def _assert_common_versioned(data: dict):
    """id/created_at/updated_at/version present on a durable, mutable resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_patient(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["plan_carrier"] in PLAN_CARRIERS
    assert isinstance(data["medical_insurance_on_file"], bool)
    assert isinstance(data["recall_interval_months"], int)
    assert 1 <= data["recall_interval_months"] <= 36
    assert isinstance(data["outstanding_patient_balance_cents"], int)
    assert data["outstanding_patient_balance_cents"] >= 0


def assert_provider(data: dict):
    # Provider is common_fields:false — id + created_at only, no version (PRD §2.4, §3.1).
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role"] in PROVIDER_ROLES
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10 and data["npi"].isdigit()


def assert_encounter(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["encounter_type"] in ENCOUNTER_TYPES
    assert isinstance(data["exam_fee_cents"], int) and data["exam_fee_cents"] >= 0
    assert isinstance(data["refraction_fee_cents"], int) and data["refraction_fee_cents"] >= 0
    assert data["status"] in [s.value for s in EncounterStatus]
    assert isinstance(data["refraction_recorded"], bool)


def assert_prescription(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["encounter_id"])
    assert is_valid_uuid(data["patient_id"])
    assert data["rx_type"] in RX_TYPES
    assert isinstance(data["expiry_months"], int)
    assert data["status"] in [s.value for s in PrescriptionStatus]


def assert_eligibility(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["carrier"] in ["VSP", "EYEMED"]
    assert isinstance(data["exam_copay_cents"], int) and data["exam_copay_cents"] >= 0
    assert isinstance(data["materials_allowance_cents"], int) and data["materials_allowance_cents"] >= 0
    assert isinstance(data["exam_benefit_available"], bool)
    assert data["status"] in [s.value for s in EligibilityStatus]


def assert_benefit_pool(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["eligibility_id"])
    assert data["pool_type"] in POOL_TYPES
    assert_benefit_pool_invariants(data)


def assert_benefit_pool_invariants(data: dict):
    """remaining = allotted - consumed, never negative (PRD §2.8)."""
    allotted = data["allotted_cents"]
    consumed = data["consumed_cents"]
    remaining = data["remaining_cents"]
    assert isinstance(allotted, int) and isinstance(consumed, int) and isinstance(remaining, int)
    assert remaining >= 0, "remaining_cents is never allowed to fall below zero"
    assert remaining == allotted - consumed, (
        f"remaining_cents ({remaining}) must equal allotted - consumed "
        f"({allotted} - {consumed} = {allotted - consumed})"
    )


def assert_lab_order(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["prescription_id"])
    assert data["frame_brand_tier"] in FRAME_TIERS
    assert isinstance(data["frame_charge_cents"], int) and data["frame_charge_cents"] >= 0
    assert isinstance(data["lens_charge_cents"], int) and data["lens_charge_cents"] >= 0
    assert isinstance(data["materials_draw_cents"], int) and data["materials_draw_cents"] >= 0
    assert isinstance(data["patient_materials_cost_cents"], int) and data["patient_materials_cost_cents"] >= 0
    assert isinstance(data["remake_count"], int) and data["remake_count"] >= 0
    assert data["status"] in [s.value for s in LabOrderStatus]


def assert_claim(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["encounter_id"])
    assert data["billing_route"] in BILLING_ROUTES
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["plan_paid_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert isinstance(data["settled_cents"], int) and data["settled_cents"] >= 0
    assert data["claim_status"] in [s.value for s in ClaimStatus]
    assert data["submission_status"] in [s.value for s in SubmissionStatus]


def assert_recall_reminder(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["channel"] in RECALL_CHANNELS
    assert data["status"] in [s.value for s in RecallReminderStatus]


def find_pool(pools: list, pool_type: str) -> dict:
    """Locate the single MATERIALS or EXAM pool in a benefit-pools listing."""
    matches = [p for p in pools if p["pool_type"] == pool_type]
    assert len(matches) == 1, f"expected exactly one {pool_type} pool, found {len(matches)}"
    return matches[0]
