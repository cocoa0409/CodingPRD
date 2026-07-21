"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_fund(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["total_capital_cents"], int)
    assert isinstance(data["committed_capital_cents"], int)
    assert isinstance(data["available_capital_cents"], int)
    # Fund reconciliation invariant (PRD Section 2.6).
    assert data["committed_capital_cents"] + data["available_capital_cents"] \
        == data["total_capital_cents"], "committed + available must equal total capital"


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "APPROVED", "OFFERED", "FUNDED", "DECLINED", "WITHDRAWN"
    ]
    assert data["property_type"] in ["SINGLE_FAMILY", "CONDO", "TOWNHOUSE", "MULTI_UNIT"]


def assert_valuation(data: dict):
    _assert_common(data)
    assert data["method"] in ["AVM", "APPRAISAL"]
    assert data["status"] in ["PENDING", "COMPLETED", "SUPERSEDED"]


def assert_offer(data: dict):
    _assert_common(data)
    assert data["status"] in ["PRESENTED", "ACCEPTED", "DECLINED", "COUNTERED", "WITHDRAWN"]
    assert isinstance(data["adjusted_start_value_cents"], int)


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "FUNDED", "ACTIVE", "EXIT_INITIATED", "SETTLEMENT_PROPOSED",
        "DISPUTED", "SETTLED", "DEFAULTED"
    ]
    assert data["covenant_status"] in ["COMPLIANT", "BREACH_NOTICED", "CURED"]


def assert_lien(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "RECORDED", "RELEASED"]
    assert data["title_status"] in ["PENDING", "CLEAR", "CLOUDED"]


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "CANCELLED"]


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["settlement_type"] in ["SALE", "BUYOUT"]
    assert data["status"] in ["PROPOSED", "DISPUTED", "FINALIZED", "VOID"]


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "RESOLVED", "REJECTED"]


def assert_settlement_conserved(data: dict, investment_amount_cents: int):
    """Waterfall conservation invariant (PRD Section 3.7): the mortgage payoff,
    the settlement fee, the investor's returned principal, the investor's
    appreciation share, and the homeowner payout together sum to the ending
    value."""
    total = (
        data["mortgage_payoff_cents"]
        + data["settlement_fee_cents"]
        + investment_amount_cents
        + data["appreciation_share_cents"]
        + data["homeowner_payout_cents"]
    )
    assert total == data["ending_value_cents"], \
        f"waterfall buckets sum {total} must equal ending_value {data['ending_value_cents']}"
    assert data["net_proceeds_cents"] == (
        data["ending_value_cents"] - data["mortgage_payoff_cents"] - data["settlement_fee_cents"]
    ), "net_proceeds must equal ending - payoff - fee"
