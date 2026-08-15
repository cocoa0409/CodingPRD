"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sponsor_name"], str) and len(data["sponsor_name"]) > 0
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["accrual_rate"], (int, float))
    assert isinstance(data["normal_retirement_age"], int)
    assert isinstance(data["prior_aftap_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert data["current_posture"] in ("UNRESTRICTED", "LUMP_SUM_RESTRICTED", "ACCRUAL_FROZEN")


def assert_actuary(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["credential_id"], str)
    assert data["enrollment_status"] in ("ENROLLED", "ASSOCIATE")


def assert_census_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["source_label"], str)
    assert data["status"] in ("UPLOADED", "NEEDS_CORRECTION", "VALIDATED", "LOCKED")
    assert isinstance(data["participant_count"], int)
    assert isinstance(data["error_count"], int)
    assert isinstance(data["screening_errors"], list)


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["census_batch_id"], str)
    assert isinstance(data["external_ref"], str)
    assert isinstance(data["date_of_birth"], str)
    assert data["status"] in ("ACTIVE", "TERMINATED_VESTED", "RETIREE")


def assert_assumption_set(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["label"], str)
    assert data["mortality_table"] == "TEST_TABLE_4AGE"
    assert isinstance(data["funding_discount_rate"], (int, float))
    assert isinstance(data["disclosure_discount_rate"], (int, float))
    assert isinstance(data["retirement_age"], int)
    assert isinstance(data["prepared_by_actuary_id"], str)
    assert data["status"] in ("DRAFT", "IN_REVIEW", "APPROVED", "LOCKED", "RETIRED")


def assert_asset_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["plan_year"], int)
    for f in ("market_value_begin", "contributions_received", "benefits_paid", "investment_return", "market_value_end"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_asset_valuation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["plan_year"], int)
    for f in ("market_value", "smoothed_value", "unrecognized_gain", "corridor_floor", "corridor_ceiling"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert data["corridor_applied"] in ("NONE", "FLOOR", "CEILING")


def assert_valuation_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["census_batch_id"], str)
    assert isinstance(data["assumption_set_id"], str)
    assert isinstance(data["asset_valuation_id"], str)
    assert data["status"] in ("INITIATED", "COMPUTED", "CERTIFIED", "SUPERSEDED", "VOID")
    assert isinstance(data["created_by_actuary_id"], str)


def assert_participant_accrual(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["valuation_run_id"], str)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["age_at_valuation"], int)
    assert isinstance(data["annuity_factor"], (int, float))
    assert isinstance(data["accrued_liability"], (int, float))
    assert isinstance(data["normal_cost_share"], (int, float))
    assert isinstance(data["frozen"], bool)


def assert_credit_balance_ledger(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    for f in ("carryover_balance", "prefunding_balance", "total_applied_to_date"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_credit_balance_election(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["contribution_demand_id"], str)
    assert isinstance(data["amount"], (int, float))
    assert data["status"] in ("EFFECTIVE", "REVOKED")
    assert isinstance(data["revoke_deadline"], str)


def assert_contribution_demand(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["valuation_run_id"], str)
    for f in ("tentative_minimum", "credit_applied", "minimum_due", "maximum_deductible",
              "paid_to_date", "outstanding_amount", "excise_accrued"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert isinstance(data["due_date"], str)
    assert data["status"] in ("OPEN", "PARTIALLY_SATISFIED", "SATISFIED", "DELINQUENT")


def assert_contribution_payment(data: dict):
    # Append-only payment event: id + created_at only, NO updated_at / version
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "payment is an immutable event: no version field"
    assert "updated_at" not in data, "payment is an immutable event: no updated_at field"
    assert isinstance(data["contribution_demand_id"], str)
    assert isinstance(data["amount"], (int, float))
    assert isinstance(data["paid_on"], str)


def assert_pbgc_filing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["valuation_run_id"], str)
    assert isinstance(data["plan_year"], int)
    assert data["premium_method"] in ("STANDARD", "ALTERNATIVE")
    assert isinstance(data["participant_count"], int)
    for f in ("premium_target", "market_assets", "uvb", "flat_rate_premium",
              "variable_rate_premium", "total_premium"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert isinstance(data["cap_applied"], bool)
    assert data["status"] in ("DRAFT", "FILED", "AMENDED", "VOID")


def assert_disclosure_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["valuation_run_id"], str)
    for f in ("pbo", "fair_value_assets", "funded_status"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert data["status"] in ("DRAFT", "ACKNOWLEDGED")


def assert_money(value, expected, label=""):
    """Assert a monetary value equals expected to 2 decimal places."""
    assert abs(float(value) - float(expected)) < 0.005, (
        f"{label}: expected {expected}, got {value}"
    )
