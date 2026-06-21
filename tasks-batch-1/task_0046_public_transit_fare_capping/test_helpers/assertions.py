"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract.
Domain invariant checkers cover the reconciliation and conservation rules from §2.6,
§3.5, and §3.10.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every entity carries id, created_at, updated_at, and integer version (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_fare_product(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_code"], str) and len(data["zone_code"]) > 0
    assert isinstance(data["base_fare_cents"], int) and data["base_fare_cents"] >= 0
    assert isinstance(data["daily_cap_cents"], int)
    assert isinstance(data["weekly_cap_cents"], int)
    assert data["daily_cap_cents"] >= data["base_fare_cents"]
    assert data["weekly_cap_cents"] >= data["daily_cap_cents"]
    assert isinstance(data["transfer_window_minutes"], int) and data["transfer_window_minutes"] > 0
    assert 0.0 <= data["transfer_discount_pct"] <= 1.0
    assert 0.0 <= data["reduced_fare_pct"] < 1.0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_rider(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["home_zone_code"], str)
    assert data["income_tier"] in ("STANDARD", "LOW_INCOME")
    assert 0.0 <= data["low_income_discount_pct"] < 1.0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_funding_source(data: dict):
    _assert_common(data)
    assert isinstance(data["rider_id"], str)
    assert data["source_type"] in ("APPLE_PAY", "GOOGLE_PAY", "CONTACTLESS_CARD")
    assert isinstance(data["prepaid_balance_cents"], int)
    assert data["prepaid_balance_cents"] >= 0, "balance must never drop below 0 (§3.3)"
    assert isinstance(data["is_default"], bool)
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_reduced_fare_card(data: dict):
    _assert_common(data)
    assert isinstance(data["rider_id"], str)
    assert data["program_code"] in ("SENIOR", "DISABILITY", "STUDENT")
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ("PENDING_VERIFICATION", "VERIFIED", "EXPIRED", "REVOKED")


def assert_benefit_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["rider_id"], str)
    assert isinstance(data["employer_ref"], str)
    assert isinstance(data["period_month"], str)
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] > 0
    assert isinstance(data["consumed_cents"], int)
    assert 0 <= data["consumed_cents"] <= data["allocated_cents"], (
        "consumed_cents stays within [0, allocated_cents] (§3.5)"
    )
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "EXHAUSTED")


def assert_fare_week(data: dict):
    _assert_common(data)
    assert isinstance(data["rider_id"], str)
    assert isinstance(data["week_start_date"], str)
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["charged_total_cents"], int)
    assert data["charged_total_cents"] >= 0, "charged_total_cents bounded below by 0 (§2.6)"
    assert data["status"] in ("OPEN", "CLOSED")


def assert_tap(data: dict):
    _assert_common(data)
    assert isinstance(data["rider_id"], str)
    assert isinstance(data["fare_week_id"], str)
    assert isinstance(data["funding_source_id"], str)
    assert isinstance(data["tapped_at"], str)
    for f in ("list_fare_cents", "transfer_discount_cents", "cap_credit_cents",
              "charge_cents", "benefit_applied_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
        assert data[f] >= 0, f"{f} must be non-negative"
    assert data["status"] in ("PENDING", "CAPTURED", "REJECTED", "REVERSED")


# ─── Domain invariant checkers ────────────────────────────────────────────

def assert_out_of_pocket_conserved(initial_balance: int, current_balance: int,
                                   charged_total_cents: int):
    """§2.6 reconciliation invariant: (initial - current) balance == week charged_total."""
    assert (initial_balance - current_balance) == charged_total_cents, (
        f"rider out-of-pocket {initial_balance - current_balance} must equal "
        f"FareWeek.charged_total_cents {charged_total_cents}"
    )


def assert_charge_decomposition(tap: dict):
    """§3.7: charge_cents == billable - benefit_applied, with billable derivable from
    list_fare - transfer_discount - cap_credit. Verifies the response self-reconciles."""
    billable = tap["list_fare_cents"] - tap["transfer_discount_cents"] - tap["cap_credit_cents"]
    assert tap["charge_cents"] == billable - tap["benefit_applied_cents"], (
        "charge_cents must equal list_fare - transfer_discount - cap_credit - benefit_applied"
    )
    assert tap["charge_cents"] >= 0, "charge_cents is non-negative by construction"
