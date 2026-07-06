"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_common_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_defender_office(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["annual_voucher_budget_cents"], int)
    assert data["recoupment_basis"] in ("SCHEDULE", "ACTUAL")
    assert isinstance(data["voucher_spent_cents"], int)
    assert data["budget_status"] in ("OPEN", "RESTRICTED")


def assert_attorney(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["office_id"], str)
    assert isinstance(data["name"], str)
    assert data["attorney_type"] in ("STAFF", "PANEL")
    assert data["status"] in ("ACTIVE", "AT_CAPACITY", "SUSPENDED")
    assert isinstance(data["hourly_rate_cents"], int)


def assert_courtroom(data: dict):
    # common_fields:false — id + created_at only, no version / updated_at.
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["courthouse"], str)
    assert "version" not in data, "Courtroom is immutable and must not carry version"
    assert "updated_at" not in data, "Courtroom is immutable and must not carry updated_at"


def assert_case(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["office_id"], str)
    assert isinstance(data["defendant_name"], str)
    assert data["charge_class"] in ("FELONY_A", "FELONY_B", "MISDEMEANOR", "JUVENILE", "APPEAL")
    assert data["status"] in ("REFERRED", "SCREENED", "ASSIGNED", "DISPOSED", "DENIED")
    assert data["eligibility_status"] in ("PENDING", "ELIGIBLE", "PARTIAL", "INELIGIBLE")
    assert data["weight_basis"] in ("PROVISIONAL", "ACTUAL")


def assert_financial_screening(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["case_id"], str)
    assert data["status"] in ("SUBMITTED", "DECIDED")
    assert data["result"] in ("PENDING", "ELIGIBLE", "PARTIAL", "INELIGIBLE")
    assert isinstance(data["contribution_amount_cents"], int)


def assert_conflict_check(data: dict):
    # common_fields:false — id + created_at only.
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["attorney_id"], str)
    assert data["result"] in ("CLEAR", "CONFLICT")
    assert "version" not in data, "ConflictCheck is immutable and must not carry version"


def assert_assignment(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["attorney_id"], str)
    assert data["status"] in ("ACTIVE", "REASSIGNED", "CLOSED")


def assert_court_event(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["case_id"], str)
    assert data["event_type"] in ("ARRAIGNMENT", "MOTION_HEARING", "PRETRIAL", "TRIAL", "SENTENCING")
    assert data["status"] in ("SCHEDULED", "VACATED")


def assert_service_request(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["case_id"], str)
    assert data["service_type"] in ("INVESTIGATOR", "EXPERT_PSYCH", "EXPERT_FORENSIC")
    assert data["status"] in ("REQUESTED", "APPROVED", "COMPLETED")


def assert_voucher(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["attorney_id"], str)
    assert data["voucher_type"] in ("PANEL_FEE", "SERVICE")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "VOIDED")


def assert_recoupment_order(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["case_id"], str)
    assert data["basis"] in ("SCHEDULE", "ACTUAL")
    assert data["status"] in ("ASSESSED", "PARTIALLY_COLLECTED", "SATISFIED", "WAIVED")
