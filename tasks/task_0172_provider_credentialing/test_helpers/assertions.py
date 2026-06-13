"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_org(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"
    assert isinstance(data["recred_cycle_days"], int)
    assert isinstance(data["expiring_soon_window_days"], int)


def assert_payer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["payer_type"] in ("COMMERCIAL", "MEDICARE", "MEDICAID")
    assert isinstance(data["retroactive_allowed"], bool)
    assert isinstance(data["panel_capacity"], int) and data["panel_capacity"] >= 1


def assert_sanctions_source(data: dict):
    _assert_common_fields(data)
    assert data["source_code"] in ("OIG_LEIE", "SAM_EXCLUSIONS")
    assert isinstance(data["severity_weight"], int) and data["severity_weight"] > 0


def assert_provider(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["npi"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["application_status"] in (
        "DRAFT", "SUBMITTED", "IN_VERIFICATION", "READY_FOR_REVIEW",
    )
    assert data["credentialing_status"] in (
        "PENDING", "CLEARED", "CONDITIONAL", "EXCLUDED",
    )
    assert data["recred_state"] in (
        "NOT_CLEARED", "CURRENT", "RECRED_DUE", "IN_RECREDENTIALING",
    )
    assert isinstance(data["readiness_score"], (int, float))
    assert isinstance(data["sanction_score"], int)


def assert_credential_item(data: dict):
    _assert_common_fields(data)
    assert data["item_type"] in (
        "STATE_LICENSE", "DEA_REGISTRATION", "BOARD_CERTIFICATION",
    )
    assert isinstance(data["identifier"], str) and len(data["identifier"]) > 0
    assert is_iso8601_timestamp(data["issued_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert data["verification_state"] in (
        "UNVERIFIED", "PENDING_PSV", "VERIFIED", "REJECTED",
    )
    assert data["expirable_band"] in ("VALID", "EXPIRING_SOON", "LAPSED")


def assert_verification_request(data: dict):
    _assert_common_fields(data)
    assert data["method"] in ("PRIMARY_SOURCE", "DESIGNATED_AGENT")
    assert data["status"] in ("OPEN", "COMPLETED_PASS", "COMPLETED_FAIL")


def assert_sanctions_screening(data: dict):
    _assert_common_fields(data)
    assert data["result"] in ("CLEAR", "HIT")
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_credentialing_file(data: dict):
    _assert_common_fields(data)
    assert data["review_status"] in (
        "ASSEMBLING", "UNDER_REVIEW", "APPROVED", "DENIED", "CONDITIONAL",
    )
    assert isinstance(data["tally_yes"], int)
    assert isinstance(data["tally_no"], int)


def assert_peer_reviewer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["user_id"], str) and len(data["user_id"]) > 0
    assert isinstance(data["vote_weight"], int) and data["vote_weight"] > 0


def assert_peer_review_vote(data: dict):
    _assert_common_fields(data)
    assert data["ballot"] in ("YES", "NO", "ABSTAIN")


def assert_payer_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "SUBMITTED", "ACTIVE", "REJECTED", "TERMINATED",
    )
