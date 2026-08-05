"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["segment"] in ("RESIDENTIAL", "SMALL_COMMERCIAL", "LARGE_COMMERCIAL")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_broker_user(data: dict):
    _common(data)
    assert data["staff_role"] in ("AGENT", "MANAGER")
    assert isinstance(data["approval_limit_cents"], int)
    assert isinstance(data["pipeline_commission_cents"], int)


def assert_supplier(data: dict):
    _common(data)
    assert data["commodity"] in ("ELECTRICITY", "GAS")
    assert isinstance(data["service_states"], list)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_account(data: dict):
    _common(data)
    assert data["status"] in ("PENDING_LOA", "VERIFIED", "ENROLLED", "SUSPENDED")
    assert isinstance(data["reserved_dr_kw"], int) and data["reserved_dr_kw"] >= 0
    assert isinstance(data["estimated_annual_usage_kwh"], int)


def assert_authorization(data: dict):
    _common(data)
    assert data["scope"] in ("USAGE_ONLY", "USAGE_AND_ENROLL")
    assert data["status"] in ("DRAFT", "SIGNED", "REVOKED", "EXPIRED")


def assert_usage_record(data: dict):
    # UsageRecord is append-only: only id + created_at as common fields.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "UsageRecord must not carry updated_at"
    assert "version" not in data, "UsageRecord must not carry version"
    assert isinstance(data["usage_kwh"], int)
    assert isinstance(data["is_actual"], bool)


def assert_rfp(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "OPEN", "BEST_AND_FINAL", "AWARDED", "CANCELLED")


def assert_quote(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "SHORTLISTED", "AWARDED", "WITHDRAWN", "VOID")
    assert isinstance(data["rate_mills_per_kwh"], int)
    assert isinstance(data["broker_adder_mills"], int)


def assert_contract(data: dict):
    _common(data)
    assert data["status"] in (
        "PENDING_CUSTOMER", "PENDING_APPROVAL", "APPROVED", "ENROLLMENT_SUBMITTED",
        "ACTIVE", "REJECTED", "DROPPED", "EXPIRED", "RENEWED",
    )
    assert data["rate_alert"] in ("NONE", "RATE_DROP")
    assert isinstance(data["renewal_window_open"], bool)


def assert_commission_statement(data: dict):
    _common(data)
    assert data["basis"] in ("ESTIMATED", "ACTUAL")
    assert data["status"] in ("PROVISIONAL", "APPROVED", "TRUED_UP", "VOIDED")
    assert isinstance(data["gross_commission_cents"], int)
    assert isinstance(data["net_commission_cents"], int)


def assert_dr_enrollment(data: dict):
    _common(data)
    assert data["status"] in ("ENROLLED", "ACTIVE", "PERFORMED", "SETTLED", "WITHDRAWN")
    assert isinstance(data["committed_kw"], int)
    assert isinstance(data["provisional_incentive_cents"], int)
