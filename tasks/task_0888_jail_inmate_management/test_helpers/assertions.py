"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_inmate(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["sex"] in ("MALE", "FEMALE")
    assert data["status"] in ("IN_CUSTODY", "RELEASED")
    assert isinstance(data["version"], int)


def assert_booking(data: dict):
    _common(data)
    assert data["booking_status"] in ("BOOKED", "CLASSIFIED", "HOUSED", "RELEASED")
    assert data["charge_severity"] in ("FELONY", "MISDEMEANOR", "INFRACTION")
    assert data["classification_level"] in (None, "MIN", "MED", "MAX")
    assert isinstance(data["sentence_days"], int) and data["sentence_days"] > 0
    assert isinstance(data["total_forfeited_days"], int)
    assert isinstance(data["version"], int)


def assert_classification_assessment(data: dict):
    _common(data)
    # ClassificationAssessment is immutable: no updated_at, no version.
    assert "version" not in data, "ClassificationAssessment must not carry version"
    assert "updated_at" not in data, "ClassificationAssessment must not carry updated_at"
    assert data["assessment_type"] in ("INITIAL", "REASSESSMENT")
    assert data["resulting_level"] in ("MIN", "MED", "MAX")
    assert isinstance(data["total_score"], int)


def assert_housing_unit(data: dict):
    _common(data)
    assert data["security_level"] in ("MIN", "MED", "MAX")
    assert data["gender"] in ("MALE", "FEMALE", "COED")
    assert isinstance(data["capacity"], int) and data["capacity"] > 0


def assert_bed(data: dict):
    _common(data)
    assert data["status"] in ("AVAILABLE", "OCCUPIED")


def assert_housing_assignment(data: dict):
    _common(data)
    assert data["assignment_status"] in ("ACTIVE", "ENDED")


def assert_court_event(data: dict):
    _common(data)
    assert data["court_event_status"] in ("SCHEDULED", "CONTINUED", "ATTENDED")
    assert isinstance(data["continuance_count"], int)


def assert_commissary_account(data: dict):
    _common(data)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["total_deposited_cents"], int)


def assert_commissary_order(data: dict):
    _common(data)
    assert data["order_status"] in ("PENDING", "FULFILLED", "REFUNDED")
    assert isinstance(data["order_total_cents"], int)


def assert_visitor(data: dict):
    _common(data)
    assert data["visitor_status"] in ("PENDING", "APPROVED")


def assert_visit(data: dict):
    _common(data)
    assert data["visit_status"] in ("REQUESTED", "APPROVED", "CANCELLED")


def assert_request(data: dict):
    _common(data)
    assert data["request_status"] in ("SUBMITTED", "UNDER_REVIEW", "DENIED", "RESOLVED")
    assert isinstance(data["appeal_count"], int)


def assert_infraction(data: dict):
    _common(data)
    assert data["infraction_status"] in ("REPORTED", "UPHELD")


def assert_property_item(data: dict):
    _common(data)
    assert data["property_status"] in ("STORED", "RETURNED")


def assert_ledger_conserved(account: dict, expected_fulfilled_total: int):
    """total_deposited_cents - balance_cents == sum(order_total for FULFILLED orders) (PRD §2.9)."""
    diff = account["total_deposited_cents"] - account["balance_cents"]
    assert diff == expected_fulfilled_total, (
        f"ledger not conserved: total_deposited - balance = {diff}, "
        f"expected {expected_fulfilled_total}"
    )
