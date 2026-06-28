"""Entity assertions and domain invariant checkers for the Massage Therapy Practice API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for full (common_fields:true) entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_modality(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["requires_certification"], bool)
    assert isinstance(data["archived"], bool)


def assert_therapist(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_number"], str)
    assert data["license_status"] in ("ACTIVE", "LICENSE_EXPIRED")
    assert data["commission_scheme"] in ("FLAT", "TIERED")
    assert isinstance(data["accrued_commission_cents"], int)
    assert isinstance(data["mtd_service_revenue_cents"], int)


def assert_table(data: dict):
    assert_common_fields(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert isinstance(data["supports_prenatal"], bool)
    assert isinstance(data["archived"], bool)


def assert_client(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["hsa_balance_cents"], int) and data["hsa_balance_cents"] >= 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_intake(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert data["intake_status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_consent(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert data["draping_policy"] in ("FULL_DRAPE", "PARTIAL_DRAPE", "DECLINE_TREATMENT")
    assert data["consent_status"] in ("ACTIVE", "REVOKED")


def assert_plan(data: dict):
    assert_common_fields(data)
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["included_sessions"], int) and data["included_sessions"] >= 1
    assert isinstance(data["rollover_cap_sessions"], int) and data["rollover_cap_sessions"] >= 0


def assert_package(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["credit_balance_sessions"], int) and data["credit_balance_sessions"] >= 0
    assert data["package_status"] in ("ACTIVE", "SUSPENDED", "CANCELLED")


def assert_ledger_entry(data: dict):
    """CreditLedgerEntry is append-only: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "ledger id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entry must not carry updated_at"
    assert "version" not in data, "append-only ledger entry must not carry version"
    assert data["reason"] in ("GRANT", "ROLLOVER_FORFEIT", "REDEEM", "REFUND", "EXPIRE")
    assert isinstance(data["delta_sessions"], int)
    assert isinstance(data["balance_after"], int)


def assert_commission_tier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["tier_index"], int) and data["tier_index"] >= 0
    assert isinstance(data["floor_revenue_cents"], int) and data["floor_revenue_cents"] >= 0
    assert isinstance(data["archived"], bool)


def assert_appointment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["therapist_id"])
    assert is_valid_uuid(data["table_id"])
    assert is_valid_uuid(data["modality_id"])
    assert data["scheduling_status"] in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data["settlement_status"] in ("UNSETTLED", "PRICED", "PAID", "VOID")
    assert data["payer"] in ("CASH", "HSA", "MEMBERSHIP")
    assert data["duration_minutes"] in (30, 60, 90, 120)


def assert_soap_note(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert data["note_status"] in ("DRAFT", "FINALIZED", "AMENDED")


def assert_superbill(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["diagnosis_codes"], list) and len(data["diagnosis_codes"]) >= 1
    assert data["superbill_status"] in ("ISSUED", "VOID")
