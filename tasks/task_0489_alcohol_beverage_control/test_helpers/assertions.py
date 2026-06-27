"""Entity assertions and domain invariant checkers (PRD sections 2.4, 2.6, 3).

Each assert_{entity}() validates the common envelope fields (UUID id, ISO 8601
timestamps, integer version) and the entity-specific fields / enums. Invariant
checkers encode the non-negativity and ledger rules the PRD states must always
hold.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_APPLICATION_STATES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "PROTEST_PERIOD", "PROTEST_HEARING",
    "APPROVED", "ISSUED", "DENIED", "WITHDRAWN",
}
_LICENSE_STATES = {"ACTIVE", "RENEWAL_DUE", "SUSPENDED", "REVOKED", "EXPIRED"}
_PERMIT_STATES = {"PENDING", "ACTIVE", "EXPIRED", "REVOKED"}
_VIOLATION_STATES = {"ALLEGED", "CONTESTED", "SUSTAINED", "DISMISSED"}
_PROTEST_STATES = {"FILED", "SCHEDULED", "SUSTAINED", "OVERRULED", "WITHDRAWN"}
_HEARING_OUTCOMES = {"PENDING", "PROTEST_SUSTAINED", "PROTEST_OVERRULED"}
_BACKGROUND_RESULTS = {"PENDING", "PASSED", "FAILED"}
_ZONING_RESULTS = {"PENDING", "CLEARED", "VARIANCE_GRANTED", "BLOCKED"}
_TRANSFER_STATES = {"PENDING", "APPROVED", "REJECTED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_license_class(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["premise_type"] in {"ON_PREMISE", "OFF_PREMISE", "MANUFACTURER"}
    assert isinstance(data["quota_managed"], bool)
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert data["renewal_cycle_months"] in {12, 24, 36}
    assert isinstance(data["requires_zoning"], bool)
    assert isinstance(data["max_servers_per_license"], int) and data["max_servers_per_license"] >= 0


def assert_quota_region(data: dict):
    _assert_common(data)
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert isinstance(data["population"], int) and data["population"] >= 0
    assert isinstance(data["persons_per_license"], int) and data["persons_per_license"] >= 1
    assert isinstance(data["moratorium"], bool)


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["disqualified"], bool)
    assert isinstance(data["felony_flag"], bool)


def assert_premise(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["region_code"], str)
    assert isinstance(data["street_address"], str) and len(data["street_address"]) > 0
    assert isinstance(data["distance_to_school_m"], int) and data["distance_to_school_m"] >= 0
    assert data["zoning_district"] in {"COMMERCIAL", "MIXED_USE", "RESIDENTIAL", "INDUSTRIAL"}


def assert_application(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["premise_id"], str)
    assert isinstance(data["license_class_code"], str)
    assert data["status"] in _APPLICATION_STATES, f"unexpected status {data['status']!r}"
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] >= 0
    assert isinstance(data["quota_slot_held"], bool)


def assert_background_check(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert data["result"] in _BACKGROUND_RESULTS


def assert_zoning_review(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert data["result"] in _ZONING_RESULTS
    assert isinstance(data["buffer_satisfied"], bool)


def assert_protest(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["protester_name"], str) and len(data["protester_name"]) > 0
    assert data["grounds"] in {"PUBLIC_NUISANCE", "OVER_CONCENTRATION", "ZONING", "MORAL_CHARACTER"}
    assert data["status"] in _PROTEST_STATES


def assert_hearing(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["room_code"], str) and len(data["room_code"]) > 0
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["outcome"] in _HEARING_OUTCOMES


def assert_license(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["license_class_code"], str)
    assert isinstance(data["region_code"], str)
    assert data["status"] in _LICENSE_STATES, f"unexpected status {data['status']!r}"
    assert_license_invariants(data)


def assert_license_invariants(data: dict):
    """Counters that never drop below zero (PRD section 2.6)."""
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    assert isinstance(data["demerit_points"], int) and data["demerit_points"] >= 0
    assert isinstance(data["active_server_count"], int) and data["active_server_count"] >= 0
    assert isinstance(data["outstanding_fine_cents"], int) and data["outstanding_fine_cents"] >= 0


def assert_server_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert data["status"] in _PERMIT_STATES
    assert isinstance(data["training_completed"], bool)


def assert_violation(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert data["severity"] in {"MINOR", "SERIOUS", "EGREGIOUS"}
    assert data["status"] in _VIOLATION_STATES


def assert_administrative_action(data: dict):
    _assert_common(data)
    assert isinstance(data["violation_id"], str)
    assert isinstance(data["license_id"], str)
    assert data["action_type"] in {"FINE", "SUSPENSION", "REVOCATION"}
    assert isinstance(data["fine_cents"], int) and data["fine_cents"] >= 0
    assert data["fine_cents"] <= 500000, "a single fine never exceeds the 500000-cent cap"
    assert isinstance(data["fine_paid_cents"], int) and data["fine_paid_cents"] >= 0
    assert isinstance(data["suspension_days"], int) and data["suspension_days"] >= 0


def assert_compliance_report(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert data["tier"] in {"SUPPLIER", "WHOLESALER", "RETAILER"}
    assert isinstance(data["period_code"], str)
    assert isinstance(data["gross_sales_cents"], int) and data["gross_sales_cents"] >= 0


def assert_transfer_request(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert data["transfer_type"] in {"OWNERSHIP", "LOCATION"}
    assert data["status"] in _TRANSFER_STATES
