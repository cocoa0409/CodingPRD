"""Entity assertions and domain invariant checkers.

Validate response shapes against the PRD contract (sections 2.4, 3.x). Uses the
framework's generic format checkers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    """Common primary-resource fields: id + the three timestamps/version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _common(data)
    assert isinstance(data["firm_name"], str) and len(data["firm_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["prepaid_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_county(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["e_file_enabled"], bool)
    assert isinstance(data["min_diligent_attempts"], int)
    assert isinstance(data["filing_fee_cents"], int)
    assert isinstance(data["max_concurrent_filings"], int)


def assert_server(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_no"], str)
    assert isinstance(data["max_active_assignments"], int)
    assert isinstance(data["active_assignment_count"], int)
    assert isinstance(data["completed_count"], int)
    assert isinstance(data["reliability_score"], (int, float))
    assert 0 <= data["reliability_score"] <= 100, "reliability_score in [0,100]"
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_service_request(data: dict):
    _common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["county_id"])
    assert isinstance(data["recipient_name"], str)
    assert isinstance(data["service_address"], str)
    assert isinstance(data["rush"], bool)
    assert isinstance(data["distinct_attempt_days"], int)
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["final_fee_cents"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ASSIGNED", "IN_PROGRESS", "SERVED",
        "NON_EST", "FILED", "COMPLETED", "CANCELLED",
    )


def assert_document(data: dict):
    _common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert data["doc_type"] in ("SUMMONS", "SUBPOENA", "COMPLAINT", "NOTICE", "WRIT")
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1


def assert_assignment(data: dict):
    _common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert is_valid_uuid(data["server_id"])
    assert isinstance(data["superseded"], bool)
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "ACTIVE", "COMPLETED",
        "DECLINED", "REASSIGNED", "CANCELLED",
    )


def assert_attempt(data: dict):
    _common(data)
    assert is_valid_uuid(data["assignment_id"])
    assert data["outcome"] in ("NO_ANSWER", "EVADED", "BAD_ADDRESS", "CONTACT_MADE")
    assert isinstance(data["superseded"], bool)


def assert_service(data: dict):
    _common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert is_valid_uuid(data["assignment_id"])
    assert data["service_type"] in ("PERSONAL", "SUBSTITUTE", "POSTING")


def assert_affidavit(data: dict):
    _common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert is_valid_uuid(data["declarant_server_id"])
    assert data["status"] in ("DRAFT", "SIGNED", "NOTARIZED", "FILED", "VOID")


def assert_skip_trace(data: dict):
    _common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert isinstance(data["candidate_addresses"], list)
    assert data["status"] in ("REQUESTED", "IN_PROGRESS", "LOCATED", "NOT_LOCATED")


def assert_stakeout(data: dict):
    _common(data)
    assert is_valid_uuid(data["assignment_id"])
    assert is_valid_uuid(data["server_id"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_filing(data: dict):
    _common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert is_valid_uuid(data["affidavit_id"])
    assert isinstance(data["reject_count"], int)
    assert data["status"] in ("PENDING", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_invoice_line(data: dict):
    _common(data)
    assert is_valid_uuid(data["service_request_id"])
    assert data["kind"] in (
        "BASE", "RUSH", "ATTEMPT", "SKIP_TRACE", "STAKEOUT", "FILING", "PRINTING",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["voided"], bool)


def assert_server_territory(data: dict):
    """Immutable join resource: id + created_at ONLY (PRD section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["server_id"])
    assert is_valid_uuid(data["county_id"])


# ─── Domain invariant checkers ────────────────────────────────────────────
def assert_fee_equals_nonvoided_lines(sr: dict, invoice_lines: list):
    """final_fee_cents must equal the sum of amount_cents over non-voided lines
    (PRD section 3.12: voided lines are excluded from totals)."""
    total = sum(ln["amount_cents"] for ln in invoice_lines if not ln["voided"])
    assert sr["final_fee_cents"] == total, (
        f"final_fee_cents {sr['final_fee_cents']} != sum of non-voided lines {total}"
    )


def find_lines(invoice_lines: list, kind: str, include_voided: bool = False) -> list:
    """Return invoice lines of a given kind (non-voided by default)."""
    return [
        ln for ln in invoice_lines
        if ln["kind"] == kind and (include_voided or not ln["voided"])
    ]
