"""Entity assertions and domain invariant checkers (PRD §2.5–§2.7, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

FLEET_ACCOUNT_STATES = {"ACTIVE", "SUSPENDED", "CLOSED"}
VEHICLE_STATES = {"ACTIVE", "OUT_OF_SERVICE", "RETIRED"}
DRIVER_STATES = {"ACTIVE", "INACTIVE"}
CARD_STATES = {"ISSUED", "ACTIVE", "SUSPENDED", "CANCELLED"}
ASSIGNMENT_STATES = {"ACTIVE", "SUPERSEDED", "ENDED"}
POSTING_STATES = {"AUTHORIZED", "CAPTURED", "SETTLED", "VOIDED"}
REVIEW_STATES = {"CLEAN", "FLAGGED", "CLEARED"}
FUEL_PRODUCTS = {"UNLEADED", "PREMIUM", "DIESEL", "DEF"}
ALERT_STATES = {"OPEN", "INVESTIGATING", "CONFIRMED", "DISMISSED"}
RULE_CODES = {"OVER_TANK_FILL", "OUTSIDE_HOURS", "PRODUCT_MISMATCH"}
FAULT_STATES = {"OPEN", "MAINTENANCE_SCHEDULED", "MAINTENANCE_COMPLETE", "CLEARED"}
FAULT_SEVERITIES = {"INFO", "WARN", "CRITICAL"}
REPORT_STATES = {"DRAFT", "FILED"}


def _assert_common(data: dict):
    """PRD §2.5: every primary resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing 'Z' and optional fraction."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "timestamp"):
    """Compare two ISO 8601 instants by value, not by serialized spelling."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #

def assert_fleet_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["status"] in FLEET_ACCOUNT_STATES, f"unexpected account status {data['status']}"
    assert isinstance(data["base_jurisdiction"], str) and data["base_jurisdiction"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_holds_cents"], int)
    assert isinstance(data["settled_spend_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert isinstance(data["rebate_accrual_cents"], int)
    assert_credit_ledger_invariant(data)


def assert_credit_ledger_invariant(account: dict):
    """PRD §2.7: available_credit_cents + outstanding_holds_cents +
    settled_spend_cents always equals credit_limit_cents."""
    total = (
        account["available_credit_cents"]
        + account["outstanding_holds_cents"]
        + account["settled_spend_cents"]
    )
    assert total == account["credit_limit_cents"], (
        "credit ledger must conserve: available + holds + settled == credit_limit; "
        f"got {account['available_credit_cents']} + {account['outstanding_holds_cents']} + "
        f"{account['settled_spend_cents']} = {total} != {account['credit_limit_cents']}"
    )


def assert_vehicle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["fleet_account_id"])
    assert isinstance(data["plate"], str) and data["plate"]
    assert data["tank_capacity_gallons"] > 0
    assert data["starting_odometer"] >= 0
    assert data["current_odometer"] >= 0
    assert data["expected_mpg_min"] > 0
    assert data["expected_mpg_max"] >= data["expected_mpg_min"]
    assert data["status"] in VEHICLE_STATES, f"unexpected vehicle status {data['status']}"


def assert_driver(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["fleet_account_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["pin"], str) and len(data["pin"]) == 4 and data["pin"].isdigit()
    assert data["status"] in DRIVER_STATES


def assert_fuel_card(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["fleet_account_id"])
    assert isinstance(data["last4"], str)
    assert data["status"] in CARD_STATES, f"unexpected card status {data['status']}"
    assert isinstance(data["allowed_products"], list)
    assert set(data["allowed_products"]) <= FUEL_PRODUCTS
    assert isinstance(data["daily_dollar_limit_cents"], int) and data["daily_dollar_limit_cents"] >= 0
    assert data["per_txn_gallon_limit"] > 0
    assert 0 <= data["allowed_start_hour"] <= 23
    assert data["allowed_start_hour"] < data["allowed_end_hour"] <= 24


def assert_card_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["driver_id"])
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["effective_to"] is None or is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ASSIGNMENT_STATES, f"unexpected assignment status {data['status']}"


def assert_transaction(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_id"])
    assert data["product"] in FUEL_PRODUCTS
    assert data["gallons"] > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert data["odometer"] >= 0
    assert isinstance(data["jurisdiction"], str) and data["jurisdiction"]
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["hold_amount_cents"], int)
    assert is_iso8601_timestamp(data["purchased_at"])
    assert data["posting_status"] in POSTING_STATES, f"unexpected posting_status {data['posting_status']}"
    assert data["review_status"] in REVIEW_STATES, f"unexpected review_status {data['review_status']}"
    assert isinstance(data["mpg_exception"], bool)
    assert_hold_matches_posting_status(data)


def assert_hold_matches_posting_status(txn: dict):
    """PRD §3.4: hold_amount_cents equals gross_amount_cents while the
    transaction is AUTHORIZED or CAPTURED, and becomes 0 once it is SETTLED or
    VOIDED."""
    if txn["posting_status"] in {"AUTHORIZED", "CAPTURED"}:
        assert txn["hold_amount_cents"] == txn["gross_amount_cents"], (
            f"a {txn['posting_status']} transaction must hold its full gross "
            f"({txn['gross_amount_cents']}), got {txn['hold_amount_cents']}"
        )
    else:
        assert txn["hold_amount_cents"] == 0, (
            f"a {txn['posting_status']} transaction must hold 0, got {txn['hold_amount_cents']}"
        )


def assert_fraud_alert(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["transaction_id"])
    assert is_valid_uuid(data["card_id"])
    assert data["rule_code"] in RULE_CODES, f"unexpected rule_code {data['rule_code']}"
    assert data["status"] in ALERT_STATES, f"unexpected alert status {data['status']}"


def assert_telematics_fault(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["fault_code"], str) and data["fault_code"]
    assert data["severity"] in FAULT_SEVERITIES
    assert data["status"] in FAULT_STATES, f"unexpected fault status {data['status']}"


def assert_ifta_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["fleet_account_id"])
    assert isinstance(data["quarter"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["jurisdiction_lines"], list)
    assert isinstance(data["total_tax_cents"], int)
    assert data["status"] in REPORT_STATES, f"unexpected report status {data['status']}"


def jurisdiction_line(report: dict, jurisdiction: str) -> dict:
    """Pick the jurisdiction_lines entry for a jurisdiction (PRD §3.9)."""
    matches = [line for line in report["jurisdiction_lines"]
               if line["jurisdiction"] == jurisdiction]
    assert len(matches) == 1, (
        f"expected exactly one jurisdiction line for {jurisdiction}, "
        f"got {len(matches)} in {report['jurisdiction_lines']}"
    )
    return matches[0]


def assert_total_tax_is_sum_of_lines(report: dict):
    """PRD §3.9: total_tax_cents is the sum of net_tax_cents across all lines."""
    expected = sum(line["net_tax_cents"] for line in report["jurisdiction_lines"])
    assert report["total_tax_cents"] == expected, (
        f"total_tax_cents {report['total_tax_cents']} != sum of line net_tax_cents {expected}"
    )
