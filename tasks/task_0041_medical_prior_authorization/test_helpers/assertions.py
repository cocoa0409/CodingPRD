"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_provider(data: dict):
    assert is_valid_uuid(data.get("id", "")), "provider id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10 and data["npi"].isdigit()
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["specialty"] in [
        "CARDIOLOGY", "ONCOLOGY", "ORTHOPEDICS", "NEUROLOGY", "PRIMARY_CARE", "RADIOLOGY"
    ]
    assert isinstance(data["version"], int)


def assert_payer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "payer id must be valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["standard_sla_hours"], int) and data["standard_sla_hours"] >= 1
    assert isinstance(data["expedited_sla_hours"], int) and data["expedited_sla_hours"] >= 1
    assert data["expedited_sla_hours"] < data["standard_sla_hours"]


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "member id must be valid UUID"
    assert is_valid_uuid(data.get("payer_id", "")), "payer_id must be valid UUID"
    assert isinstance(data["member_number"], str) and len(data["member_number"]) > 0
    assert 0.0 <= data["coinsurance_rate"] <= 1.0
    assert isinstance(data["active_authorization_count"], int)
    assert data["active_authorization_count"] >= 0


def assert_authorization_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "request id must be valid UUID"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be valid UUID"
    assert is_valid_uuid(data.get("provider_id", "")), "provider_id must be valid UUID"
    assert is_valid_uuid(data.get("payer_id", "")), "payer_id must be valid UUID"
    assert data["request_type"] in ["SERVICE", "DRUG"]
    assert isinstance(data["procedure_code"], str) and len(data["procedure_code"]) > 0
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 1
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["is_expedited"], bool)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "PENDED",
        "APPROVED", "DENIED", "EXPIRED", "SUPERSEDED",
    ]
    assert isinstance(data["version"], int)


def assert_clinical_evidence(data: dict):
    """ClinicalEvidence is immutable: id + created_at, no version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "evidence id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["document_type"] in [
        "CHART_NOTE", "LAB_RESULT", "IMAGING", "MEDICATION_HISTORY", "LETTER_OF_MEDICAL_NECESSITY"
    ]
    assert isinstance(data["line_item_cost_cents"], int) and data["line_item_cost_cents"] >= 0
    assert isinstance(data["uri"], str) and len(data["uri"]) > 0


def assert_review_decision(data: dict):
    assert is_valid_uuid(data.get("id", "")), "decision id must be valid UUID"
    assert is_valid_uuid(data.get("request_id", "")), "request_id must be valid UUID"
    assert is_valid_uuid(data.get("reviewer_id", "")), "reviewer_id must be valid UUID"
    assert data["outcome"] in ["APPROVE", "PARTIAL", "DENY", "PEND"]


def assert_peer_to_peer_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "session id must be valid UUID"
    assert is_valid_uuid(data.get("request_id", "")), "request_id must be valid UUID"
    assert is_valid_uuid(data.get("reviewer_id", "")), "reviewer_id must be valid UUID"
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_appeal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "appeal id must be valid UUID"
    assert is_valid_uuid(data.get("request_id", "")), "request_id must be valid UUID"
    assert data["tier"] in [1, 2, 3]
    assert data["status"] in ["OPEN", "UPHELD", "OVERTURNED", "ESCALATED", "WITHDRAWN"]
