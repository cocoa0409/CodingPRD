"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}")


def assert_date_eq(actual, expected_date: str, label: str = "date"):
    """Day-precision comparison: the PRD pins calendar dates; the serialization
    may render a bare date or a midnight-UTC datetime, so compare the date part."""
    actual_str = str(actual)
    assert actual_str[:10] == expected_date, (
        f"{label} must be {expected_date}, got {actual_str!r}")


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("service_address"), str) and data["service_address"]
    assert data.get("service_class") in ("RESIDENTIAL", "COMMERCIAL")
    assert data.get("heating_fuel_type") in ("ELECTRIC", "GAS", "DUAL")
    assert isinstance(data.get("deposit_held_cents"), int) and data["deposit_held_cents"] >= 0
    for field in ("arrearage_balance_cents", "current_charges_balance_cents",
                  "credit_balance_cents", "reconnection_fee_due_cents"):
        assert isinstance(data.get(field), int), f"{field} must be integer cents"
    assert data.get("service_status") in ("CONNECTED", "DISCONNECT_PENDING", "DISCONNECTED")
    assert data.get("protection_status") in (
        "UNPROTECTED", "WEATHER_MORATORIUM", "MEDICAL_MORATORIUM")
    assert data.get("delinquency_tier") in ("CURRENT", "DELINQUENT", "SEVERELY_DELINQUENT")


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data.get("household_size"), int) and 1 <= data["household_size"] <= 12
    assert data.get("status") in (
        "SUBMITTED", "UNDER_REVIEW", "DOCS_PENDING", "VERIFIED", "DENIED", "WITHDRAWN")
    assert isinstance(data.get("submitted_by_user_id"), str)
    assert data.get("provisional_benefit_tier") in ("TIER_1", "TIER_2", "TIER_3", "INELIGIBLE")


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data.get("tier") in ("TIER_1", "TIER_2", "TIER_3")
    assert data.get("discount_pct") in (50, 30, 15)
    assert data.get("status") in ("PENDING", "ACTIVE", "LAPSED", "TERMINATED")


def assert_dpa(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data.get("status") in (
        "DRAFT", "ACTIVE", "DEFAULTED", "COMPLETED", "BROKEN", "CANCELLED")
    assert isinstance(data.get("installment_count"), int) and 2 <= data["installment_count"] <= 12
    for field in ("covered_arrearage_cents", "down_payment_required_cents",
                  "down_payment_received_cents", "installment_amount_cents",
                  "final_installment_amount_cents", "forgiveness_pool_cents",
                  "forgiven_posted_cents", "projected_forgiveness_cents",
                  "paid_to_arrearage_cents", "remaining_balance_cents"):
        assert isinstance(data.get(field), int), f"{field} must be integer cents"


def assert_dpa_ledger_invariants(dpa: dict):
    """The covered-arrearage ledger is conserved: covered == paid + forgiven + remaining."""
    assert dpa["covered_arrearage_cents"] == (
        dpa["paid_to_arrearage_cents"] + dpa["forgiven_posted_cents"]
        + dpa["remaining_balance_cents"]), (
        f"DPA ledger drift: covered {dpa['covered_arrearage_cents']} != "
        f"paid {dpa['paid_to_arrearage_cents']} + forgiven {dpa['forgiven_posted_cents']} "
        f"+ remaining {dpa['remaining_balance_cents']}")


def assert_payment(data: dict):
    """Payment is the immutable exception: only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Payment must not carry a version field"
    assert "updated_at" not in data, "Payment must not carry an updated_at field"
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert data.get("tender_type") in ("CASH", "CARD", "CHECK", "MONEY_ORDER")
    assert is_iso8601_timestamp(data.get("paid_at", "")), "paid_at must be ISO 8601"


def assert_breakdown_sums_to(breakdown: dict, amount_cents: int):
    """The seven waterfall buckets together sum to the tendered amount (PRD §3.5)."""
    keys = ("reconnection_fee_cents", "down_payment_cents", "installment_cents",
            "dpa_extra_cents", "arrearage_cents", "current_charges_cents",
            "overpayment_cents")
    total = 0
    for key in keys:
        assert isinstance(breakdown.get(key), int), f"breakdown.{key} must be integer cents"
        total += breakdown[key]
    assert total == amount_cents, (
        f"breakdown buckets sum to {total}, expected tendered {amount_cents}")


def assert_forgiveness_credit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dpa_id", "")), "dpa_id must be a UUID"
    assert isinstance(data.get("installment_number"), int) and data["installment_number"] >= 1
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] >= 0
    assert data.get("status") in ("POSTED", "REVERSED")


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data.get("condition_class") in ("LIFE_THREATENING", "SERIOUS")
    assert data.get("status") in ("ACTIVE", "EXPIRED", "REVOKED")
    assert isinstance(data.get("renewal_count"), int) and 0 <= data["renewal_count"] <= 2


def assert_shutoff_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data.get("status") in ("SCHEDULED", "BLOCKED", "EXECUTED", "CANCELLED")
    assert data.get("origin") in ("MANUAL", "AUTO")
    assert data.get("blocked_reason") in (None, "WEATHER", "MEDICAL")


def assert_funding_source(data: dict):
    _assert_common_fields(data)
    assert data.get("funder_type") in ("LIHEAP", "UTILITY_TRUST", "STATE_GRANT")
    assert data.get("status") in ("OPEN", "SUSPENDED", "CLOSED")
    assert isinstance(data.get("appropriated_cents"), int) and data["appropriated_cents"] > 0
    assert isinstance(data.get("eligible_tiers"), list) and len(data["eligible_tiers"]) >= 1


def assert_fund_conservation(report: dict):
    """Report invariant: pledged + disbursed + released == total ever allocated,
    and available == appropriated - pledged - disbursed (PRD §3.8)."""
    assert report["available_cents"] == (
        report["appropriated_cents"] - report["pledged_cents"] - report["disbursed_cents"]), (
        f"available {report['available_cents']} != appropriated {report['appropriated_cents']} "
        f"- pledged {report['pledged_cents']} - disbursed {report['disbursed_cents']}")


def assert_fund_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("funding_source_id", "")), "funding_source_id must be a UUID"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be a UUID"
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] >= 1
    assert data.get("status") in ("PLEDGED", "DISBURSED", "RELEASED")
    assert isinstance(data.get("batch_id"), str) and data["batch_id"]
    assert isinstance(data.get("allocation_sequence"), int) and data["allocation_sequence"] >= 1


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data.get("agency_code"), str) and data["agency_code"]
    assert data.get("status") in ("INITIATED", "COMPLETED", "EXPIRED")
