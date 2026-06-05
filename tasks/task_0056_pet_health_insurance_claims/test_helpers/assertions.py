"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_POLICY_STATES = {"PENDING_PAYMENT", "ACTIVE", "LAPSED", "CANCELLED"}
_CLAIM_STATES = {"DRAFT", "SUBMITTED", "IN_REVIEW", "APPROVED", "DENIED", "PAID"}
_OCR_STATES = {"PENDING_OCR", "OCR_DONE", "REVIEW_NEEDED", "ACCEPTED", "REJECTED"}
_EXCLUSION_STATES = {"PRE_EXISTING", "COVERED"}
_YEAR_STATES = {"OPEN", "CLOSED"}


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be int >= 1"


def assert_account(data: dict):
    _common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["active_policy_count"], int) and data["active_policy_count"] >= 0
    assert isinstance(data["monthly_premium_cents"], int) and data["monthly_premium_cents"] >= 0
    assert isinstance(data["multi_pet_discount_applied"], bool)


def assert_policy(data: dict):
    _common(data)
    assert data["species"] in {"DOG", "CAT"}
    assert data["status"] in _POLICY_STATES
    assert data["base_premium_cents"] >= 0
    assert data["annual_deductible_cents"] >= 0
    assert 0 <= data["reimbursement_rate_bps"] <= 10000
    assert data["annual_cap_cents"] >= 0
    assert data["waiting_period_days"] >= 0
    assert isinstance(data["wellness_rider"], bool)


def assert_policy_year(data: dict):
    _common(data)
    assert data["status"] in _YEAR_STATES
    assert isinstance(data["year_index"], int) and data["year_index"] >= 0
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["deductible_met_cents"] >= 0
    assert data["reimbursed_cents"] >= 0
    assert data["wellness_used_cents"] >= 0


def assert_condition(data: dict):
    _common(data)
    assert data["exclusion_status"] in _EXCLUSION_STATES
    assert isinstance(data["name"], str)


def assert_claim(data: dict):
    _common(data)
    assert data["status"] in _CLAIM_STATES
    assert data["claim_type"] in {"ILLNESS", "ACCIDENT", "WELLNESS"}


def assert_claim_line(data: dict):
    _common(data)
    assert data["billed_amount_cents"] >= 0
    assert isinstance(data["excluded"], bool)


def assert_invoice(data: dict):
    _common(data)
    assert data["ocr_status"] in _OCR_STATES
