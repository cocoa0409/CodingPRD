"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ORDER_STATUSES = (
    "RECEIVED", "SEARCH_IN_PROGRESS", "SEARCH_COMPLETE", "REPORT_DRAFTING",
    "REPORT_UNDER_REVIEW", "READY_FOR_DELIVERY", "DELIVERED", "CANCELLED",
)
ASSIGNMENT_STATUSES = (
    "IN_PROGRESS", "SUBMITTED", "RETURNED_FOR_CORRECTION", "ACCEPTED", "CANCELLED",
)
DOCUMENT_STATUSES = ("REPORTED", "VERIFIED", "FLAGGED_FOR_CURATIVE", "VOID")
CHECK_STATUSES = ("PENDING", "VERIFIED", "MISMATCH", "RESOLVED")
REPORT_STATUSES = (
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUIRED",
    "APPROVED", "DELIVERED", "CANCELLED",
)
CURATIVE_STATUSES = ("OPEN", "SATISFIED", "WAIVED")
RETRIEVAL_STATUSES = ("REQUESTED", "FEE_POSTED", "FEE_REVERSED", "INVOICED")
INSTRUMENT_TYPES = (
    "DEED", "MORTGAGE", "LIEN", "JUDGMENT", "TAX_LIEN", "EASEMENT", "RESTRICTION",
)


def assert_common_fields(data: dict):
    """PRD §2.4 system-managed property set carried by every primary resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_nullable_timestamp(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601 UTC, got {value!r}"
    )


def assert_abstract_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_ref"], str) and data["client_ref"]
    assert isinstance(data["property_address"], str) and data["property_address"]
    assert isinstance(data["county"], str) and data["county"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["legal_description_text"], str)
    assert isinstance(data["search_period_years"], int)
    assert 1 <= data["search_period_years"] <= 60
    assert isinstance(data["effective_date"], str)
    assert data["sla_tier"] in ("STANDARD", "RUSH")
    assert data["liability_tier"] in ("STANDARD", "EXTENDED")
    assert isinstance(data["scope_start_date"], str)
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    _assert_nullable_timestamp(data, "delivered_at")
    assert isinstance(data["is_overdue"], bool)
    assert data["status"] in ORDER_STATUSES
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["accrued_fees_cents"], int)
    assert data.get("final_fee_cents") is None or isinstance(data["final_fee_cents"], int)
    assert isinstance(data["late_credit_cents"], int)
    assert data.get("billed_fee_cents") is None or isinstance(data["billed_fee_cents"], int)
    assert isinstance(data["liability_cap_cents"], int)
    assert isinstance(data["open_curative_count"], int)
    assert isinstance(data["legal_hold"], bool)


def assert_search_assignment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["abstracter_ref"], str) and data["abstracter_ref"]
    assert data["search_type"] in ("CHAIN_OF_TITLE", "LIEN_JUDGMENT_TAX")
    assert is_iso8601_timestamp(data.get("window_start", "")), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), "window_end must be ISO 8601"
    assert isinstance(data["document_count"], int) and data["document_count"] >= 0
    assert isinstance(data["verified_count"], int) and data["verified_count"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data.get("return_reason") is None or isinstance(data["return_reason"], str)
    assert data["status"] in ASSIGNMENT_STATUSES


def assert_record_document(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["assignment_id"], str)
    assert data["instrument_type"] in INSTRUMENT_TYPES
    assert isinstance(data["grantor_name"], str)
    assert isinstance(data["grantee_name"], str)
    assert isinstance(data["instrument_number"], str) and data["instrument_number"]
    assert isinstance(data["recording_date"], str)
    assert data.get("prior_document_id") is None or isinstance(data["prior_document_id"], str)
    assert isinstance(data["in_scope"], bool)
    assert isinstance(data["chain_break_flag"], bool)
    assert isinstance(data["exception_applies"], bool)
    assert data["status"] in DOCUMENT_STATUSES


def assert_legal_description_check(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["survey_reference"], str)
    assert isinstance(data["checked_legal_description"], str)
    assert isinstance(data["survey_exception_applied"], bool)
    assert data.get("resolved_description") is None or isinstance(data["resolved_description"], str)
    assert data["status"] in CHECK_STATUSES


def assert_abstract_report(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0
    assert data.get("revision_reason") is None or isinstance(data["revision_reason"], str)
    assert data.get("reviewer_examiner_ref") is None or isinstance(data["reviewer_examiner_ref"], str)
    _assert_nullable_timestamp(data, "review_slot_start")
    _assert_nullable_timestamp(data, "review_slot_end")
    assert data["status"] in REPORT_STATUSES


def assert_curative_requirement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert data.get("record_document_id") is None or isinstance(data["record_document_id"], str)
    assert data.get("raised_by_examiner_ref") is None or isinstance(data["raised_by_examiner_ref"], str)
    assert isinstance(data["description"], str) and data["description"]
    assert data["severity"] in ("LOW", "STANDARD", "CRITICAL")
    assert data.get("resolution_note") is None or isinstance(data["resolution_note"], str)
    assert data["status"] in CURATIVE_STATUSES


def assert_county_retrieval(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["record_document_id"], str)
    assert isinstance(data["county"], str) and data["county"]
    assert data["fee_mode"] in ("PER_DOCUMENT", "PER_PAGE")
    assert data.get("page_count") is None or isinstance(data["page_count"], int)
    assert data.get("fee_cents") is None or isinstance(data["fee_cents"], int)
    assert data["status"] in RETRIEVAL_STATUSES


def assert_order_fee_invariants(data: dict):
    """PRD §2.6/§2.7 ledger invariants that hold on any order read."""
    assert data["accrued_fees_cents"] >= 0, "accrued fees never go negative"
    assert data["liability_cap_cents"] >= 0, "liability cap never goes negative"
    assert data["liability_cap_cents"] <= 200000, "absolute ceiling on the liability cap"
    assert data["late_credit_cents"] >= 0
    if data.get("final_fee_cents") is not None and data.get("billed_fee_cents") is not None:
        assert data["billed_fee_cents"] == data["final_fee_cents"] - data["late_credit_cents"], (
            "billed fee must equal final fee minus late credit"
        )
