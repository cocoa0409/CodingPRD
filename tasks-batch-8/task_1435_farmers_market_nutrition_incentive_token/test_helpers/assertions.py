"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    VendorStatus, ShopperStatus, MarketDayStatus, TokenBatchStatus,
    IssuanceStatus, TokenStatus, SubmissionStatus, FraudCaseStatus,
    FraudCaseOrigin, TokenKind, BenefitType,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["match_pool_budget_cents"], int)
    assert isinstance(data["match_pool_remaining_cents"], int)
    assert isinstance(data["liability_forward_cents"], int)
    assert isinstance(data["liability_realized_cents"], int)
    assert isinstance(data["paid_out_cents"], int)


def assert_market(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must reference a program"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str) and data["city"]


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in VendorStatus}
    assert isinstance(data["payable_cents"], int)
    assert isinstance(data["legal_name"], str) and data["legal_name"]


def assert_shopper(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in ShopperStatus}
    assert data["benefit_type"] in {b.value for b in BenefitType}
    assert isinstance(data["season_match_used_cents"], int)
    assert isinstance(data["external_benefit_ref"], str) and data["external_benefit_ref"]


def assert_market_day(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in MarketDayStatus}
    for f in ("issued_value_cents", "voided_value_cents", "redeemed_value_cents", "variance_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["variance_cents"] == (
        data["issued_value_cents"] - data["voided_value_cents"] - data["redeemed_value_cents"]
    ), "variance_cents must equal issued - voided - redeemed"


def assert_token_batch(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in TokenBatchStatus}
    assert data["kind"] in {k.value for k in TokenKind}
    assert isinstance(data["serial_start"], int) and isinstance(data["serial_end"], int)
    assert data["serial_end"] >= data["serial_start"]
    assert isinstance(data["next_serial"], int)


def assert_issuance(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in IssuanceStatus}
    assert isinstance(data["benefit_charged_cents"], int)
    assert isinstance(data["base_value_cents"], int)
    assert isinstance(data["match_cents"], int)
    assert data["base_value_cents"] == data["benefit_charged_cents"], (
        "base value always equals the charged benefit"
    )


def assert_token(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in TokenStatus}
    assert data["kind"] in {k.value for k in TokenKind}
    assert isinstance(data["serial_number"], int)
    assert isinstance(data["denomination_cents"], int)


def assert_submission(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in SubmissionStatus}
    assert isinstance(data["token_ids"], list)
    assert isinstance(data["provisional_amount_cents"], int)


def assert_fraud_case(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in FraudCaseStatus}
    assert data["origin"] in {o.value for o in FraudCaseOrigin}
    subjects = [k for k in ("vendor_id", "shopper_id", "token_id") if data.get(k)]
    assert len(subjects) == 1, "a fraud case targets exactly one subject"


def assert_settlement_run(data: dict):
    _assert_common(data)
    assert isinstance(data["swept_submission_ids"], list)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["vendor_payment_count"], int)


def assert_program_pool_invariants(program: dict):
    """The match pool never exceeds budget and never goes negative."""
    assert 0 <= program["match_pool_remaining_cents"] <= program["match_pool_budget_cents"], (
        f"pool {program['match_pool_remaining_cents']} outside [0, {program['match_pool_budget_cents']}]"
    )
