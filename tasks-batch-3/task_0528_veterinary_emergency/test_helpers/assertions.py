"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_TRIAGE_LEVELS = ["RED", "ORANGE", "YELLOW", "GREEN"]
_VISIT_STATES = [
    "REGISTERED", "TRIAGED", "IN_TREATMENT", "READY_FOR_DISCHARGE",
    "DISCHARGED", "DECEASED", "LWBS",
]
_DEPARTMENTS = ["ER", "CARDIOLOGY", "ONCOLOGY", "SURGERY", "NEUROLOGY"]


def assert_patient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["species"] in ["CANINE", "FELINE", "EXOTIC"]
    assert data["weight_kg"] > 0, "weight_kg must be > 0"
    assert isinstance(data["owner_user_id"], str)
    assert isinstance(data["version"], int)


def assert_visit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in _VISIT_STATES, f"unexpected visit status {data['status']}"
    assert data["department"] in _DEPARTMENTS, f"unexpected department {data['department']}"
    assert data["triage_level"] is None or data["triage_level"] in _TRIAGE_LEVELS
    assert isinstance(data["authorized_ceiling_cents"], int)
    assert isinstance(data["charges_committed_cents"], int)
    assert isinstance(data["version"], int)


def assert_referral(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PENDING", "ACCEPTED", "DECLINED"]
    assert data["to_department"] in ["CARDIOLOGY", "ONCOLOGY", "SURGERY", "NEUROLOGY"]


def assert_estimate(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["DRAFT", "ISSUED", "SUPERSEDED", "CONSUMED"]
    assert isinstance(data["low_cents"], int)
    assert isinstance(data["high_cents"], int)
    assert isinstance(data["deposit_cents"], int)


def assert_authorization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PENDING", "ACTIVE", "DECLINED", "VOIDED"]
    assert isinstance(data["approved_ceiling_cents"], int)


def assert_hospitalization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "RELEASED", "CANCELLED"]
    assert data["ward"] in ["ICU", "WARD"]


def assert_procedure(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["SCHEDULED", "PERFORMED", "CANCELLED"]
    assert data["modality"] in ["IMAGING_CT", "IMAGING_MRI", "SURGERY"]
    assert data["resource_room"] in ["CT_SUITE", "MRI_SUITE", "OR_1", "OR_2"]


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "FINALIZED", "SETTLED"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert data["balance_due_cents"] >= 0, "balance_due_cents floored at 0"


def assert_payment_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PROPOSED", "ACTIVE", "CANCELLED"]
    assert data["provider"] in ["CARECREDIT", "IN_HOUSE"]
    assert isinstance(data["promo_applied"], bool)


def assert_referring_vet_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # Append-only artifact — no version/updated_at fields.
    assert "version" not in data, "ReferringVetReport must not carry a version field"
    assert "updated_at" not in data, "ReferringVetReport must not carry an updated_at field"
