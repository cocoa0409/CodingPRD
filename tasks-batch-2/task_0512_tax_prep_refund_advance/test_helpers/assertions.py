"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract
(§2.4 common fields + per-entity fields). ComplianceClock carries only id +
created_at (PRD §2.4) and therefore omits updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_office(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["efin"], str)
    assert isinstance(data["state_code"], str)
    assert data["efin_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["bank_product_enabled"], bool)
    assert isinstance(data["open_return_count"], int)


def assert_credential(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("office_id", ""))
    assert isinstance(data["ptin"], str)
    assert isinstance(data["holder_name"], str)
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_preparer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("office_id", ""))
    assert is_valid_uuid(data.get("credential_id", ""))
    assert isinstance(data["full_name"], str)
    assert isinstance(data["assigned_open_returns"], int)
    assert isinstance(data["max_open_returns"], int)


def assert_client(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("office_id", ""))
    assert isinstance(data["full_name"], str)
    assert isinstance(data["ssn_last4"], str)
    assert data["risk_band"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["is_returning"], bool)


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("office_id", ""))
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("preparer_id", ""))
    assert isinstance(data["start_utc"], str)
    assert isinstance(data["end_utc"], str)
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_tax_return(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("office_id", ""))
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data["tax_year"], int)
    assert data["return_kind"] in ("ORIGINAL", "PRIOR_YEAR", "AMENDED_1040X")
    assert data["complexity_band"] in ("SIMPLE", "STANDARD", "COMPLEX")
    assert data["status"] in (
        "INTAKE", "DOCS_PENDING", "IN_PREP", "PREPARED",
        "EFILED_PENDING", "EFILED_ACCEPTED", "EFILED_REJECTED", "CANCELLED",
    )


def assert_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert data["doc_type"] in ("W2", "1099", "ID", "PRIOR_RETURN", "OTHER")
    assert isinstance(data["is_required"], bool)
    assert data["status"] in ("PENDING", "RECEIVED", "WAIVED")


def assert_fee_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert data["line_kind"] in ("BASE_1040", "SCHEDULE", "STATE_RETURN", "DISCOUNT")
    assert isinstance(data["amount_cents"], int)


def assert_audit_protection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("ACTIVE", "CANCELLED", "VOIDED")


def assert_efile_submission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert isinstance(data["efin_used"], str)
    assert isinstance(data["ptin_used"], str)
    assert data["ack_status"] in ("TRANSMITTED", "ACCEPTED", "REJECTED")


def assert_refund_transfer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert isinstance(data["bank_product_fee_cents"], int)
    assert data["status"] in ("PENDING_FUNDING", "DISBURSED", "CANCELLED")


def assert_refund_advance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert isinstance(data["requested_cents"], int)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "DISBURSED", "REPAID", "DENIED", "CANCELLED",
    )
