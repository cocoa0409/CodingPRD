"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


REQUEST_STATUSES = [
    "DRAFT_INTAKE", "IN_REVIEW", "READY", "IN_PROCESS",
    "CORRECTION_REQUIRED", "FULFILLED", "CANCELLED",
]
EFFECTIVENESS_STATUSES = [
    "DRAFT", "SUBMITTED", "ACTIVE", "REJECTED", "WITHDRAWN", "LAPSED", "TERMINATED",
]
REFLECTION_STATUSES = ["UNVERIFIED", "REFLECTED", "DISCREPANCY"]
SEARCH_STATUSES = ["ORDERED", "COMPLETED", "VERIFIED", "DISCREPANCY"]
FILING_EVENT_TYPES = [
    "CREATED", "SUBMITTED", "ACCEPTED", "REJECTED", "WITHDRAWN", "CONTINUED",
    "AMENDED", "TERMINATED", "LAPSED", "REVIVED", "REFLECTED", "DISCREPANCY_FLAGGED",
]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an int >= 1"
    )


def _assert_audit_fields(data: dict):
    """Immutable records carry only id + created_at; no updated_at, no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable record must not carry updated_at"
    assert "version" not in data, "immutable record must not carry version"


def assert_client_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["fees_charged_total_cents"], int)
    assert isinstance(data["fees_refunded_total_cents"], int)


def assert_jurisdiction_profile(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["per_additional_debtor_fee_cents"], int)
    assert isinstance(data["county_surcharge_cents"], int)
    assert isinstance(data["county_filing_collateral_classes"], list)
    assert isinstance(data["county_names"], list)
    assert data["individual_name_rule"] in ["DL_SAFE_HARBOR", "LEGAL_NAME_ONLY"]
    assert isinstance(data["expedited_daily_capacity"], int)


def assert_debtor(data: dict):
    _assert_common_fields(data)
    assert data["debtor_type"] in ["ORGANIZATION", "INDIVIDUAL"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]


def assert_secured_party(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_filing_request(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ["NEW_UCC1", "AMENDMENT", "CONTINUATION", "TERMINATION"]
    assert data["status"] in REQUEST_STATUSES
    assert data["collateral_class"] in ["GENERAL", "FIXTURE", "TIMBER_TO_BE_CUT", "AS_EXTRACTED"]
    assert isinstance(data["fee_authorization_cents"], int)
    if data.get("filing_office") is not None:
        assert data["filing_office"] in ["STATE", "COUNTY"]
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in ["CLIENT_REQUEST", "TARGET_LAPSED", "TARGET_TERMINATED"]


def assert_ucc_filing(data: dict):
    _assert_common_fields(data)
    assert data["filing_kind"] in ["INITIAL", "AMENDMENT", "CONTINUATION", "TERMINATION"]
    assert data["effectiveness_status"] in EFFECTIVENESS_STATUSES
    assert data["reflection_status"] in REFLECTION_STATUSES
    if data.get("filing_office") is not None:
        assert data["filing_office"] in ["STATE", "COUNTY"]


def assert_lien_search(data: dict):
    _assert_common_fields(data)
    assert data["purpose"] in ["PRE_FILING", "POST_FILING_VERIFICATION"]
    assert data["status"] in SEARCH_STATUSES


def assert_search_result_hit(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("lien_search_id", "")), "lien_search_id must be a UUID"
    assert isinstance(data["found_debtor_name"], str)
    assert isinstance(data["found_filing_number"], str)
    assert data["hit_kind"] in ["EXACT_MATCH", "SIMILAR"]
    assert isinstance(data["is_subject_filing"], bool)


def assert_perfection_report(data: dict):
    _assert_audit_fields(data)
    assert data["mode"] in ["AS_OF_NOW", "FORWARD_PROJECTION"]
    for field in (
        "active_count", "perfected_count", "unreflected_count",
        "expiring_within_horizon_count", "lapsed_count", "terminated_count",
        "projected_lapsed_count", "perfected_exposure_cents",
        "unperfected_exposure_cents", "projected_lapsed_exposure_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an int"


def assert_filing_event(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("ucc_filing_id", "")), "ucc_filing_id must be a UUID"
    assert data["event_type"] in FILING_EVENT_TYPES
    assert is_iso8601_timestamp(data.get("occurred_at", "")), "occurred_at must be ISO 8601"


def assert_client_fee_ledger_conserved(client: dict, live_charged_cents: int):
    """Net fee exposure: charged - refunded equals the fees locked on attempts still
    SUBMITTED or ACTIVE; the ledger moves only on submission and rejection (PRD §2.7)."""
    charged = client["fees_charged_total_cents"]
    refunded = client["fees_refunded_total_cents"]
    assert charged >= 0 and refunded >= 0
    assert charged - refunded == live_charged_cents, (
        f"net exposure {charged - refunded} != live charged fees {live_charged_cents}"
    )
