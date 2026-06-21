"""Entity assertions and domain invariant checkers for the hospice & palliative care API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version starts at 1 and only increments"


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["per_beneficiary_cap_cents"], int)
    assert data["per_beneficiary_cap_cents"] >= 0
    assert isinstance(data["cap_liability_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["counted_beneficiaries"], int)
    assert isinstance(data["cap_settled"], bool)
    assert_provider_invariants(data)


def assert_provider_invariants(data: dict):
    """Ledger invariants that must hold after any operation."""
    assert data["cap_liability_cents"] >= 0, "cap_liability_cents is never below zero"
    assert data["total_paid_cents"] >= 0
    assert data["counted_beneficiaries"] >= 0


def assert_election(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_name"], str) and len(data["patient_name"]) > 0
    assert data["status"] in ("ELECTED", "REVOKED", "DISCHARGED", "EXPIRED")
    assert isinstance(data["current_period_number"], int)
    assert data["current_period_number"] >= 1
    assert isinstance(data["days_used_in_period"], int)
    assert data["days_used_in_period"] >= 0
    assert isinstance(data["bereavement_required"], bool)


def assert_benefit_period(data: dict):
    _assert_common(data)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["length_days"] in (90, 60)
    assert isinstance(data["start_offset_days"], int) and data["start_offset_days"] >= 0
    assert isinstance(data["requires_face_to_face"], bool)
    assert data["cert_status"] in ("PENDING_CERT", "CERTIFIED")


def assert_certification(data: dict):
    _assert_common(data)
    assert isinstance(data["period_sequence"], int) and data["period_sequence"] >= 1
    assert isinstance(data["narrative_present"], bool)
    assert data["status"] in ("DRAFT", "CERTIFIED", "REJECTED")


def assert_care_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["idg_members"], list)
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data["review_due_offset_days"], int)
    assert data["review_due_offset_days"] >= 1


def assert_care_day(data: dict):
    _assert_common(data)
    assert data["level_of_care"] in ("ROUTINE", "RESPITE", "GIP")
    assert isinstance(data["high_intensity"], bool)
    assert isinstance(data["payment_cents"], int) and data["payment_cents"] >= 0
    assert isinstance(data["respite_run_length"], int) and data["respite_run_length"] >= 0


def assert_coverage_item(data: dict):
    _assert_common(data)
    assert data["item_type"] in ("MEDICATION", "DME")
    assert isinstance(data["related_to_terminal_dx"], bool)
    assert data["coverage_status"] in ("COVERED", "EXCLUDED")


def assert_physician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["is_medical_director"], bool)


def assert_bereavement_case(data: dict):
    _assert_common(data)
    assert isinstance(data["service_window_days"], int) and data["service_window_days"] >= 365
    assert data["status"] in ("OPEN", "CLOSED")
