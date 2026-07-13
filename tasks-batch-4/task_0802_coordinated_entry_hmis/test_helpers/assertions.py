"""Entity assertions and domain invariant checkers.

These verify the structural contract of each entity response (id/timestamp shapes,
enum membership, field types). They intentionally avoid asserting values that the PRD
leaves open so they can be reused across many tests.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CLIENT_STATUSES = ["INTAKE", "ACTIVE", "HOUSED", "INACTIVE", "MERGED"]
ACUITY_TIERS = ["LOW", "MODERATE", "HIGH"]
ASSESSMENT_STATUSES = ["DRAFT", "COMPLETED", "EXPIRED"]
CONSENT_STATUSES = ["PENDING", "ACTIVE", "REVOKED", "EXPIRED"]
SCREENING_STATUSES = ["OPEN", "RESOLVED"]
SCREENING_OUTCOMES = ["DIVERTED", "PROCEED_TO_SHELTER", "PROCEED_TO_PRIORITIZATION"]
BED_STATUSES = ["ACTIVE", "OFFLINE"]
RESERVATION_STATUSES = ["RESERVED", "CHECKED_IN", "CHECKED_OUT", "NO_SHOW", "CANCELLED", "EXPIRED"]
WAITLIST_STATUSES = ["WAITING", "PROMOTED", "CANCELLED", "EXPIRED"]
PRIORITIZATION_STATUSES = ["ACTIVE", "MATCHED", "HOUSED", "DEFERRED", "REMOVED"]
REFERRAL_STATUSES = ["PENDING", "ACCEPTED", "DECLINED", "ENROLLED", "EXPIRED"]
EXIT_OUTCOMES = ["POSITIVE", "NEUTRAL", "NEGATIVE"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_mutable_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_client(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["dob"], str) and len(data["dob"]) > 0
    assert data["status"] in CLIENT_STATUSES, f"unexpected client status {data['status']!r}"
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["months_homeless"], int) and data["months_homeless"] >= 0
    assert isinstance(data["chronic_homeless"], bool)
    if data.get("vulnerability_score") is not None:
        assert isinstance(data["vulnerability_score"], int)
    if data.get("acuity_tier") is not None:
        assert data["acuity_tier"] in ACUITY_TIERS


def assert_assessment(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ASSESSMENT_STATUSES
    assert isinstance(data["self_report_points"], int)


def assert_consent(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in CONSENT_STATUSES
    assert data["scope"] in ["SHARE_ALL", "SHARE_LIMITED"]


def assert_screening(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in SCREENING_STATUSES
    if data.get("outcome") is not None:
        assert data["outcome"] in SCREENING_OUTCOMES


def assert_shelter(data: dict):
    _assert_mutable_common(data)
    assert data["project_type"] in ["ES", "TH"]
    assert isinstance(data["total_beds"], int) and data["total_beds"] >= 0
    assert isinstance(data["available_beds"], int) and data["available_beds"] >= 0
    assert data["available_beds"] <= data["total_beds"], "available_beds cannot exceed total_beds"


def assert_bed(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in BED_STATUSES


def assert_bed_reservation(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in RESERVATION_STATUSES
    assert is_valid_uuid(data.get("bed_id", "")), "bed_id must be a server-assigned UUID"


def assert_waitlist_entry(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in WAITLIST_STATUSES
    assert isinstance(data["priority_score"], int)


def assert_prioritization_entry(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in PRIORITIZATION_STATUSES
    assert isinstance(data["rank_score"], int)


def assert_housing_navigator(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["max_caseload"], int) and data["max_caseload"] >= 1
    assert isinstance(data["current_caseload"], int) and data["current_caseload"] >= 0


def assert_referral(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in REFERRAL_STATUSES


def assert_exit_record(data: dict):
    # append-only: only id + created_at are guaranteed; NO updated_at / version.
    _assert_common(data)
    assert data["outcome"] in EXIT_OUTCOMES
    assert isinstance(data["bed_nights"], int) and data["bed_nights"] >= 0
