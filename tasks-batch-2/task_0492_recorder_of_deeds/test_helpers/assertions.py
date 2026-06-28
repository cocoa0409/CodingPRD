"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_office(data: dict):
    _assert_common(data)
    assert isinstance(data["county_name"], str) and len(data["county_name"]) > 0
    assert isinstance(data["book_capacity"], int) and data["book_capacity"] >= 1
    assert isinstance(data["next_instrument_number"], int)
    assert isinstance(data["current_book"], int)
    assert isinstance(data["current_page"], int)
    assert isinstance(data["documents_in_current_book"], int)
    assert isinstance(data["daily_collected_cents"], int)
    assert isinstance(data["total_indexed_entries"], int)


def assert_submitter(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["submitter_type"] in ["TITLE_COMPANY", "ATTORNEY", "SELF", "GOVERNMENT"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["escrow_deposited_total_cents"], int)
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["escrow_held_cents"], int)
    assert isinstance(data["escrow_available_cents"], int)


def assert_submitter_escrow_invariants(data: dict):
    """Escrow identity: available == balance - held (PRD Section 2.6 / 3.4)."""
    assert data["escrow_available_cents"] == data["escrow_balance_cents"] - data["escrow_held_cents"], (
        f"escrow_available_cents must equal balance - held; got "
        f"{data['escrow_available_cents']} != {data['escrow_balance_cents']} - {data['escrow_held_cents']}"
    )


def assert_package(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["submitter_id"])
    assert is_valid_uuid(data["office_id"])
    assert data["doc_type"] in ["DEED", "MORTGAGE", "LIEN", "UCC", "PLAT", "OTHER"]
    assert isinstance(data["declared_page_count"], int) and data["declared_page_count"] >= 1
    assert isinstance(data["declared_consideration_cents"], int)
    assert isinstance(data["notary_present"], bool)
    assert data["status"] in [
        "SUBMITTED", "IN_EXAMINATION", "ASSESSED", "PAID",
        "RECORDED", "REJECTED", "WITHDRAWN",
    ]
    assert isinstance(data["resubmission_count"], int)


def assert_party_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["package_id"])
    assert data["party_role"] in ["GRANTOR", "GRANTEE"]
    assert isinstance(data["party_name"], str)
    assert data["status"] in ["PENDING", "INDEXED", "VOIDED"]


def assert_fee_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["package_id"])
    assert isinstance(data["recording_fee_cents"], int)
    assert isinstance(data["transfer_tax_cents"], int)
    assert isinstance(data["records_mgmt_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert data["status"] in ["FINALIZED", "SUPERSEDED", "VOIDED"]


def assert_fee_assessment_total_invariant(data: dict):
    """total_due == recording_fee + transfer_tax + records_mgmt (PRD Section 3.3)."""
    assert data["total_due_cents"] == (
        data["recording_fee_cents"] + data["transfer_tax_cents"] + data["records_mgmt_cents"]
    ), "total_due_cents must equal the integer sum of the three rounded components"


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["package_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["method"] in ["ESCROW", "CARD"]
    assert data["status"] in ["CAPTURED", "FAILED"]


def assert_recorded_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["package_id"])
    assert isinstance(data["instrument_number"], int)
    assert isinstance(data["book"], int)
    assert isinstance(data["page"], int)
    assert is_iso8601_timestamp(data["recorded_on"])
    assert data["status"] in ["RECORDED", "CORRECTED_VOID"]


def assert_rejection_notice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["package_id"])
    assert data["reason_code"] in [
        "MARGIN", "NOTARY", "LEGAL_DESCRIPTION", "INDEX_INCOMPLETE", "FEE_DISCREPANCY",
    ]
    assert isinstance(data["cured"], bool)


def assert_plat(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["submitter_id"])
    assert is_valid_uuid(data["office_id"])
    assert isinstance(data["subdivision_name"], str)
    assert isinstance(data["block_number"], int)
    assert isinstance(data["start_lot"], int)
    assert isinstance(data["end_lot"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "RECORDED", "REJECTED"]


def assert_ucc_filing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["submitter_id"])
    assert is_valid_uuid(data["office_id"])
    assert data["lien_type"] in ["UCC1", "TAX_LIEN", "JUDGMENT_LIEN", "MECHANICS_LIEN"]
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["debtor_name"], str)
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["lapse_date"])
    assert isinstance(data["continuation_count"], int)
    assert data["status"] in ["ACTIVE", "LAPSED", "TERMINATED"]


def assert_copy_search_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["submitter_id"])
    assert data["request_type"] in ["CERTIFIED_COPY", "NAME_SEARCH"]
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ["REQUESTED", "FULFILLED", "DENIED"]
