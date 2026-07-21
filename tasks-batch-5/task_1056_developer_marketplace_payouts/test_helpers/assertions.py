"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_MUTABLE_COMMON = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data: dict):
    """Every mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer starting at 1, got {data.get('version')!r}"


def assert_append_only_fields(data: dict):
    """Immutable reference/append-only rows carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "version" not in data, "append-only rows must not expose version"
    assert "updated_at" not in data, "append-only rows must not expose updated_at"


def assert_bare_uuid(value: str):
    assert is_valid_uuid(value), f"expected a UUID with no type prefix, got {value!r}"


def assert_developer(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "TERMINATED"
    ], f"unexpected developer status {data['status']!r}"
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["tax_id_provided"], bool)
    assert isinstance(data["payout_hold"], bool)
    assert isinstance(data["risk_watch"], bool)
    assert data["policy_strike_count"] >= 0
    assert data["negative_balance_cents"] >= 0, "negative_balance_cents is a non-negative amount"
    assert data["unpaid_accrual_cents"] >= 0 or data["negative_balance_cents"] == 0
    assert 0 <= data["risk_score"] <= 100, "risk_score is capped at 100"
    assert data["risk_variant"] in ["STANDARD", "ACCELERATED"]


def assert_app(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "LIVE", "SUSPENDED", "DELISTED"
    ], f"unexpected app status {data['status']!r}"
    assert data["category"] in [
        "PRODUCTIVITY", "GAMES", "FINANCE", "HEALTH", "DEVELOPER_TOOLS"
    ]
    assert isinstance(data["listed_countries"], list)
    assert data["review_round"] >= 0
    assert data["policy_strike_count"] >= 0


def assert_review_submission(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "IN_TRIAGE", "PASSED", "REJECTED"]
    assert data["round_number"] >= 1
    assert_bare_uuid(data["app_id"])


def assert_pricing_plan(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ["ONE_TIME", "SUBSCRIPTION", "IAP"]
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert data["price_cents"] > 0, "price_cents must be strictly greater than zero"
    assert data["effective_from"] <= data["effective_to"], \
        "effective_from may not be later than effective_to"


def assert_tax_jurisdiction(data: dict):
    assert_append_only_fields(data)
    assert 0 <= data["vat_rate_bps"] <= 3000
    assert isinstance(data["marketplace_facilitator"], bool)
    assert len(data["country_code"]) == 2


def assert_revenue_share_tier(data: dict):
    assert_append_only_fields(data)
    assert 0 < data["developer_share_bps"] <= 10000
    assert data["min_cumulative_base_cents"] >= 0


def assert_purchase(data: dict):
    assert_common_fields(data)
    assert data["payment_status"] in [
        "AUTHORIZED", "CAPTURED", "VOIDED", "PARTIALLY_REFUNDED", "REFUNDED", "CHARGED_BACK"
    ]
    assert data["settlement_status"] in ["UNSETTLED", "ACCRUED", "PAID", "CLAWED_BACK"]
    assert data["tax_remitter"] in ["MARKETPLACE", "DEVELOPER"]
    assert data["gross_cents"] > 0
    assert data["revenue_base_cents"] == data["gross_cents"] - data["tax_cents"], \
        "revenue_base_cents is gross_cents less tax_cents"
    assert data["refunded_gross_cents"] >= 0


def assert_purchase_split_identity(data: dict):
    """Platform fee plus developer net plus tax equals the gross the buyer paid."""
    total = (
        data["platform_fee_cents"]
        + data["provisional_developer_net_cents"]
        + data["tax_cents"]
    )
    assert total == data["gross_cents"], (
        f"platform_fee_cents + provisional_developer_net_cents + tax_cents = {total}, "
        f"expected gross_cents {data['gross_cents']}"
    )


def assert_refund(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["REQUESTED", "APPROVED", "DENIED", "EXECUTED"]
    assert data["reason"] in ["BUYER_REQUEST", "FRAUD", "POLICY", "DUPLICATE"]
    assert data["amount_cents"] > 0


def assert_chargeback(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["RECEIVED", "REPRESENTED", "WON", "LOST", "REVERSED"]
    assert data["amount_cents"] > 0
    assert data["clawback_cents"] >= 0


def assert_policy_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "OPEN", "INVESTIGATING", "UPHELD", "DISMISSED", "APPEALED", "REINSTATED"
    ]
    assert data["category"] in [
        "FRAUD", "IP_INFRINGEMENT", "MALWARE", "CONTENT", "PAYMENT_ABUSE"
    ]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]


def assert_payout_batch(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "OPEN", "CALCULATED", "PENDING_APPROVAL", "APPROVED", "PAID", "FAILED"
    ]
    assert data["line_count"] >= 0
    assert data["period_start"] < data["period_end"], \
        "period_start must fall strictly before period_end"


def assert_payout_line(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "PAYABLE", "HELD_BELOW_MINIMUM", "HELD_DEVELOPER", "PAID", "FAILED"
    ]
    assert data["reserve_cents"] >= 0
    assert data["recovery_cents"] >= 0
    assert data["withholding_cents"] >= 0
    assert data["carryover_added_cents"] >= 0


def assert_payout_waterfall_consistency(data: dict):
    """The pinned waterfall order: withholding is taken on the balance after
    recovery, and payable is that balance less withholding."""
    after_reserve = data["gross_earnings_cents"] - data["reserve_cents"]
    after_recovery = after_reserve - data["recovery_cents"]
    payable = after_recovery - data["withholding_cents"]
    if data["status"] == "PAYABLE":
        assert data["payout_amount_cents"] == payable, (
            f"payout_amount_cents {data['payout_amount_cents']} should equal "
            f"after_recovery - withholding_cents = {payable}"
        )
    elif data["status"] == "HELD_BELOW_MINIMUM":
        assert data["payout_amount_cents"] == 0
        assert data["carryover_added_cents"] == max(0, payable)


def assert_ledger_entry(data: dict):
    assert_append_only_fields(data)
    assert data["entry_type"] in [
        "ACCRUAL", "TAX_PASSTHROUGH", "TIER_TRUEUP", "REFUND_REVERSAL", "CLAWBACK",
        "CLAWBACK_REVERSAL", "RESERVE", "RECOVERY", "WITHHOLDING", "PAYOUT", "CARRYOVER",
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["settled"], bool)


def assert_tax_form(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ISSUABLE", "NOT_REQUIRED"]
    assert data["reportable_cents"] >= 0
    assert data["withheld_cents"] >= 0


def assert_developer_accrual_identity(developer: dict, unsettled_entries: list):
    """Accrual less negative balance equals the sum of unsettled ledger amounts."""
    ledger_sum = sum(e["amount_cents"] for e in unsettled_entries)
    lhs = developer["unpaid_accrual_cents"] - developer["negative_balance_cents"]
    assert lhs == ledger_sum, (
        f"unpaid_accrual_cents - negative_balance_cents = {lhs}, but the unsettled "
        f"ledger sums to {ledger_sum}"
    )
