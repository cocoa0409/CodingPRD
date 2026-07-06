"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure of an entity against the
PRD contract, using the framework's generic format checkers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_mutable(data: dict):
    """id + created_at + updated_at + version (entities the PRD declares mutable)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-free UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _common_immutable(data: dict):
    """id + created_at only (PRD-declared immutable entities: no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-free UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_fee_schedule(data: dict):
    _common_immutable(data)
    assert "updated_at" not in data, "FeeSchedule is immutable: must not carry updated_at"
    assert "version" not in data, "FeeSchedule is immutable: must not carry version"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    for fld in ("per_stamp_cents", "travel_base_cents", "travel_per_mile_cents",
                "ron_surcharge_cents", "state_cap_cents"):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"


def assert_account(data: dict):
    _common_mutable(data)
    assert isinstance(data["org_name"], str) and len(data["org_name"]) > 0
    assert isinstance(data["default_state_code"], str)
    assert isinstance(data["retention_years"], int)


def assert_notary(data: dict):
    _common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["ron_authorized"], bool)
    assert isinstance(data["nsa_certified"], bool)
    assert isinstance(data["active_session_count"], int)
    assert data["active_session_count"] >= 0


def assert_signer(data: dict):
    _common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["id_doc_type"] in ("DRIVERS_LICENSE", "PASSPORT", "STATE_ID")


def assert_signing_request(data: dict):
    _common_mutable(data)
    assert data["doc_category"] in ("GENERAL", "REAL_ESTATE", "LOAN_SIGNING", "APOSTILLE_BOUND")
    assert data["delivery_mode"] in ("RON", "MOBILE")
    assert data["status"] in ("DRAFT", "QUOTED", "ASSIGNED", "IN_SESSION", "COMPLETED", "CANCELLED")
    assert isinstance(data["estimate_fee_cents"], int)
    assert isinstance(data["final_fee_cents"], int)


def assert_request_document(data: dict):
    _common_mutable(data)
    assert data["doc_type"] in ("DEED", "MORTGAGE", "POA", "AFFIDAVIT", "BIRTH_CERT", "DIPLOMA", "OTHER")
    assert isinstance(data["signing_fee_cents"], int)


def assert_assignment(data: dict):
    _common_mutable(data)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_ron_session(data: dict):
    _common_mutable(data)
    assert data["session_status"] in ("SCHEDULED", "LIVE", "ENDED")
    assert data["recording_status"] in ("NOT_STARTED", "RECORDING", "ARCHIVED")


def assert_id_verification(data: dict):
    _common_mutable(data)
    assert data["trust_variant"] in ("STANDARD", "ENHANCED")
    assert data["outcome"] in ("PASS", "FAIL")
    assert isinstance(data["trust_score"], (int, float))


def assert_journal_entry(data: dict):
    _common_immutable(data)
    assert "version" not in data, "JournalEntry is append-only: must not carry version"
    assert data["entry_status"] in ("COMPLETED", "VOIDED")
    assert data["act_type"] in ("ACKNOWLEDGMENT", "JURAT", "OATH", "COPY_CERTIFICATION")


def assert_apostille_order(data: dict):
    _common_mutable(data)
    assert data["authentication_type"] in ("APOSTILLE", "CERTIFICATION")
    assert data["status"] in ("SUBMITTED", "ROUTED", "AUTHENTICATED", "RETURNED", "REJECTED")
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["resubmit_count"], int)


def assert_loan_package(data: dict):
    _common_mutable(data)
    assert data["status"] in ("DRAFT", "SCRUBBED", "FUNDED", "CANCELLED")
    assert isinstance(data["scrub_passed"], bool)
    assert isinstance(data["package_fee_cents"], int)


def assert_retention_record(data: dict):
    _common_immutable(data)
    assert "version" not in data, "RetentionRecord is append-only: must not carry version"
    assert data["hold_status"] in ("ACTIVE", "PURGEABLE")
