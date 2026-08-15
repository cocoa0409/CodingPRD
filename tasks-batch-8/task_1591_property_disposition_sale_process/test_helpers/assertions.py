"""Entity assertions and domain invariant checkers.

Field-level checks use the PRD Common Resource Properties conventions:
id is a bare UUID, created_at/updated_at are ISO 8601 UTC timestamps with
three fractional digits, version is an integer.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_asset(data: dict):
    _assert_common_fields(data)
    assert data["marketing_status"] in (
        "EVALUATION", "LISTED", "OFFERS_OPEN", "OFFERS_CLOSED", "WITHDRAWN")
    assert data["deal_status"] in (
        "IDLE", "PSA_DRAFT", "PSA_EXECUTED", "DD_ACTIVE", "BINDING", "CLOSING", "SOLD")
    assert data["asset_type"] in ("OFFICE", "INDUSTRIAL", "RETAIL", "MULTIFAMILY")
    assert isinstance(data["noi_cents"], int) and data["noi_cents"] > 0
    assert isinstance(data["guidance_price_cents"], int)
    assert isinstance(data["forfeited_deposits_cents"], int)


def assert_analysis(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")
    assert data["recommendation"] in ("SELL", "HOLD", "MARGINAL")
    assert data["selected_method"] in ("DIRECT_CAP", "DCF")
    assert isinstance(data["hold_value_direct_cap_cents"], int)
    assert isinstance(data["hold_value_dcf_cents"], int)
    assert isinstance(data["hold_value_cents"], int)
    assert isinstance(data["sell_net_cents"], int)
    assert isinstance(data["value_gap_cents"], int)


def assert_engagement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PROPOSED", "ACTIVE", "EXPIRED", "TERMINATED", "COMPLETED")
    assert isinstance(data["broker_firm_name"], str)


def assert_package(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "IN_REVIEW")
    assert isinstance(data["documents"], list)
    assert isinstance(data["verified_categories_count"], int)
    assert isinstance(data["completeness_pct"], int)


def assert_bidder(data: dict):
    _assert_common_fields(data)
    assert data["qualification_status"] in ("PENDING", "QUALIFIED", "DISQUALIFIED")
    assert isinstance(data["proof_of_funds_cents"], int)
    assert isinstance(data["access_windows"], list)


def assert_bid(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "SHORTLISTED", "SELECTED", "REJECTED", "WITHDRAWN")
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["improvement_count"], int)


def assert_psa(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "EXECUTED", "DD_ACTIVE", "BINDING", "CLOSING",
        "CLOSED", "TERMINATED", "SUPERSEDED")
    assert data["proration_convention"] in ("ACTUAL_365", "BANKERS_360")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["original_price_cents"], int)
    assert isinstance(data["accepted_retrade_total_cents"], int)


def assert_deposit(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ("INITIAL", "ADDITIONAL")
    assert data["status"] in (
        "DUE", "POSTED", "DELINQUENT", "REFUNDED", "FORFEITED", "APPLIED")
    assert isinstance(data["amount_cents"], int)


def assert_dd_item(data: dict):
    _assert_common_fields(data)
    assert data["category"] in ("PHYSICAL", "FINANCIAL", "LEGAL", "ENVIRONMENTAL", "TITLE")
    assert data["status"] in (
        "OPEN", "ACCEPTED", "REJECTED", "CONTESTED", "WITHDRAWN", "RESCINDED")
    assert isinstance(data["requested_reduction_cents"], int)


def assert_payoff(data: dict):
    _assert_common_fields(data)
    assert data["method"] in ("PAYOFF", "DEFEASANCE")
    assert data["status"] in ("QUOTED", "CONFIRMED", "STALE", "SETTLED")
    assert isinstance(data["accrued_interest_cents"], int)
    assert isinstance(data["prepayment_penalty_cents"], int)
    assert isinstance(data["defeasance_cost_cents"], int)
    assert isinstance(data["total_estimated_cost_cents"], int)


def assert_statement(data: dict):
    _assert_common_fields(data)
    assert data["convention"] in ("ACTUAL_365", "BANKERS_360")
    assert data["status"] in (
        "DRAFT", "PENDING_REVIEW", "APPROVED", "DISPUTED", "STALE", "FINALIZED")
    assert isinstance(data["proration_buyer_credit_cents"], int)
    assert isinstance(data["proration_buyer_debit_cents"], int)
    assert isinstance(data["buyer_due_cents"], int)
    assert isinstance(data["seller_net_cents"], int)


def assert_escrow(data: dict):
    _assert_common_fields(data)
    assert data["purpose"] == "INDEMNITY"
    assert data["status"] in ("HELD", "PARTIALLY_RELEASED", "RELEASED")
    assert isinstance(data["claims"], list)


def assert_escrow_partition_identity(data: dict):
    """The escrow conserved-quantity invariant (PRD Post-Closing Escrow):
    amount_cents always equals available + released_to_seller + paid_to_claims."""
    total = data["available_cents"] + data["released_to_seller_cents"] \
        + data["paid_to_claims_cents"]
    assert data["amount_cents"] == total, (
        f"escrow partition violated: amount {data['amount_cents']} != "
        f"available {data['available_cents']} + released "
        f"{data['released_to_seller_cents']} + paid {data['paid_to_claims_cents']}")


def assert_timestamp_prefix(actual: str, expected_prefix: str):
    """Compare a server timestamp against an expected instant without pinning
    the fractional-second rendering (PRD pins the instant, not the padding)."""
    assert isinstance(actual, str) and actual.startswith(expected_prefix), (
        f"expected timestamp starting {expected_prefix!r}, got {actual!r}")
