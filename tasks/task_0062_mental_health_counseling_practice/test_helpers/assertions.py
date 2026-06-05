"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_therapist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["credential_status"] in [
        "ASSOCIATE", "SUPERVISED_PRACTICE", "INDEPENDENT", "SUSPENDED"
    ]
    assert isinstance(data["requires_supervision"], bool)
    assert isinstance(data["verified_direct_hours"], (int, float))
    assert isinstance(data["projected_direct_hours"], (int, float))
    assert isinstance(data["verified_supervision_hours"], (int, float))


def assert_state_license(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["therapist_id"])
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVOKED"]
    assert isinstance(data["telehealth_authorized"], bool)


def assert_supervision_log(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED"]
    assert isinstance(data["hours"], (int, float))


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ["ACTIVE", "ON_CLINICAL_HOLD", "DISCHARGED"]
    assert isinstance(data["fpl_percent"], (int, float))
    assert isinstance(data["sliding_fee_multiplier"], (int, float))


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert data["cost_share_model"] in ["COPAY", "COINSURANCE"]
    assert isinstance(data["deductible_met_cents"], int)
    assert data["deductible_met_cents"] >= 0


def assert_payer_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["in_network"], bool)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["cpt_code"] in ["90791", "90834"]
    assert data["modality"] in ["IN_PERSON", "TELEHEALTH"]
    assert data["payment_path"] in ["INSURANCE", "SELF_PAY"]
    assert data["status"] in [
        "SCHEDULED", "RENDERED", "COMPLETED", "CLAIMED", "WRITTEN_OFF", "CANCELLED"
    ]
    assert isinstance(data["patient_charge_cents"], int)


def assert_clinical_note(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SIGNED", "CO_SIGNED"]


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "ADJUDICATED", "DENIED", "RESUBMITTED", "VOID"]
    assert data["cpt_code"] in ["90791", "90834"]
    assert isinstance(data["billed_charge_cents"], int)


def assert_crisis_assessment(data: dict):
    _assert_common(data)
    assert data["risk_band"] in ["LOW", "MODERATE", "HIGH"]
    assert data["status"] in ["OPEN", "RESOLVED"]
    assert isinstance(data["risk_score"], (int, float))


def assert_safety_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["crisis_assessment_id"])
    assert isinstance(data["emergency_contacts"], list) and len(data["emergency_contacts"]) > 0
