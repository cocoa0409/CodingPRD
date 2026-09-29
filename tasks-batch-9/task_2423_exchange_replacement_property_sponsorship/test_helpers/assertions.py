"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccreditationMethod,
    AccreditationStatus,
    AllocationVariant,
    AssetType,
    CapitalNeedStatus,
    CapitalNeedType,
    ConsentDecision,
    DistributionKind,
    DistributionStatus,
    ExchangeFileStatus,
    ExemptionRule,
    ExitEventStatus,
    ExitMode,
    IdentificationRule,
    IdentificationStatus,
    InvestorEntityType,
    LedgerBucket,
    LedgerEntryType,
    LedgerSourceKind,
    LoanStatus,
    MasterLeaseStatus,
    OfferingStatus,
    PropertyStatus,
    RecourseType,
    SubscriptionStatus,
    SuitabilityStatus,
    TaxStatementStatus,
    TrustPosture,
    TrustStatus,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


# --------------------------------------------------------------------------
# Common-field shapes (PRD §2.5)
# --------------------------------------------------------------------------


def assert_common_fields(data: dict):
    """Every mutable record carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_fields(data: dict):
    """Journal rows carry only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')}"
    assert (
        "updated_at" not in data
    ), "append-only rows must omit updated_at from the representation"
    assert (
        "version" not in data
    ), "append-only rows must omit version from the representation"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_property(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) > 0
    assert data["asset_type"] in _values(AssetType)
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["annual_noi_cents"], int)
    assert isinstance(data["occupancy_rate"], (int, float))
    assert is_iso8601_timestamp(data["contract_close_deadline"])
    assert data["status"] in _values(PropertyStatus)


def assert_trust(data: dict):
    assert_common_fields(data)
    assert isinstance(data["property_id"], str) and len(data["property_id"]) > 0
    assert isinstance(data["trust_name"], str) and len(data["trust_name"]) > 0
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert isinstance(data["units_issued"], int) and data["units_issued"] >= 0
    assert isinstance(data["reserve_floor_cents"], int)
    assert isinstance(data["reserve_target_pct"], (int, float))
    assert isinstance(data["reserve_balance_cents"], int)
    assert isinstance(data["operating_balance_cents"], int)
    assert isinstance(data["equity_raised_cents"], int)
    assert isinstance(data["springing_llc_armed"], bool)
    assert data["status"] in _values(TrustStatus)
    assert data["posture"] in _values(TrustPosture)


def assert_offering(data: dict):
    assert_common_fields(data)
    assert isinstance(data["trust_id"], str) and len(data["trust_id"]) > 0
    assert data["exemption_rule"] in _values(ExemptionRule)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["min_units_per_investor"], int)
    assert isinstance(data["load_pct"], (int, float))
    assert isinstance(data["closing_costs_cents"], int)
    assert isinstance(data["reserve_funding_pct"], (int, float))
    assert isinstance(data["rescission_window_days"], int)
    assert isinstance(data["ppm_version"], int) and data["ppm_version"] >= 1
    assert isinstance(data["units_committed"], int)
    assert isinstance(data["equity_committed_cents"], int)
    assert data["status"] in _values(OfferingStatus)


def assert_investor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["entity_type"] in _values(InvestorEntityType)
    assert data["accreditation_method"] in _values(AccreditationMethod)
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["net_worth_cents"], int)
    assert isinstance(data["liquid_net_worth_cents"], int)
    assert data["accreditation_status"] in _values(AccreditationStatus)
    assert data["suitability_status"] in _values(SuitabilityStatus)


def assert_exchange_file(data: dict):
    assert_common_fields(data)
    assert isinstance(data["investor_id"], str) and len(data["investor_id"]) > 0
    assert isinstance(data["qi_reference"], str) and len(data["qi_reference"]) > 0
    assert is_iso8601_timestamp(data["relinquished_closed_on"])
    assert isinstance(data["relinquished_sale_price_cents"], int)
    assert data["relinquished_sale_price_cents"] >= 1
    assert isinstance(data["net_proceeds_cents"], int)
    assert data["net_proceeds_cents"] >= 0
    assert isinstance(data["debt_retired_cents"], int)
    assert data["debt_retired_cents"] >= 0
    assert data["identification_rule"] in _values(IdentificationRule)
    assert is_iso8601_timestamp(data["identification_deadline"])
    assert is_iso8601_timestamp(data["exchange_deadline"])
    assert data["status"] in _values(ExchangeFileStatus)


def assert_identification(data: dict):
    assert_common_fields(data)
    assert isinstance(data["exchange_file_id"], str)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["fair_market_value_cents"], int)
    assert data["fair_market_value_cents"] >= 1
    assert is_iso8601_timestamp(data["identified_at"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["status"] in _values(IdentificationStatus)


def assert_subscription(data: dict):
    assert_common_fields(data)
    assert isinstance(data["offering_id"], str)
    assert isinstance(data["investor_id"], str)
    assert isinstance(data["exchange_file_id"], str)
    assert isinstance(data["units_requested"], int) and data["units_requested"] >= 1
    assert isinstance(data["investment_amount_cents"], int)
    assert isinstance(data["boot_cents"], int) and data["boot_cents"] >= 0
    assert data["status"] in _values(SubscriptionStatus)


def assert_loan_facility(data: dict):
    assert_common_fields(data)
    assert isinstance(data["trust_id"], str)
    assert isinstance(data["lender_name"], str) and len(data["lender_name"]) > 0
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["rate_bps"], int)
    assert data["recourse_type"] in _values(RecourseType)
    assert isinstance(data["ltv_pct"], (int, float))
    assert isinstance(data["dscr"], (int, float))
    assert isinstance(data["repriced_count"], int) and data["repriced_count"] >= 0
    assert data["status"] in _values(LoanStatus)


def assert_master_lease(data: dict):
    assert_common_fields(data)
    assert isinstance(data["trust_id"], str)
    assert isinstance(data["master_tenant_user_id"], str)
    assert isinstance(data["base_rent_annual_cents"], int)
    assert isinstance(data["supplemental_rent_annual_cents"], int)
    assert data["status"] in _values(MasterLeaseStatus)


def assert_ledger_entry(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["trust_id"], str)
    assert data["entry_type"] in _values(LedgerEntryType)
    assert data["bucket"] in _values(LedgerBucket)
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["source_kind"] in _values(LedgerSourceKind)


def assert_capital_need(data: dict):
    assert_common_fields(data)
    assert isinstance(data["trust_id"], str)
    assert data["need_type"] in _values(CapitalNeedType)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in _values(CapitalNeedStatus)


def assert_distribution(data: dict):
    assert_common_fields(data)
    assert isinstance(data["trust_id"], str)
    assert data["kind"] in _values(DistributionKind)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["provisional_amount_cents"], int)
    assert data["status"] in _values(DistributionStatus)


def assert_distribution_allocation(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["distribution_id"], str)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["units"], int)
    assert isinstance(data["raw_share_cents"], (int, float))
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["residual_adjustment_cents"], int)


def assert_tax_statement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["trust_id"], str)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["tax_year"], int) and data["tax_year"] >= 2026
    assert data["allocation_variant"] in _values(AllocationVariant)
    assert isinstance(data["rental_income_cents"], int)
    assert isinstance(data["interest_expense_cents"], int)
    assert isinstance(data["depreciation_cents"], int)
    assert isinstance(data["net_taxable_income_cents"], int)
    assert data["status"] in _values(TaxStatementStatus)


def assert_exit_event(data: dict):
    assert_common_fields(data)
    assert isinstance(data["trust_id"], str)
    assert data["exit_mode"] in _values(ExitMode)
    assert isinstance(data["gross_price_cents"], int) and data["gross_price_cents"] >= 1
    assert isinstance(data["selling_costs_cents"], int)
    assert data["selling_costs_cents"] >= 0
    assert isinstance(data["consent_threshold_pct"], (int, float))
    assert isinstance(data["consented_units"], int)
    assert data["status"] in _values(ExitEventStatus)


def assert_exit_consent(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["exit_event_id"], str)
    assert isinstance(data["subscription_id"], str)
    assert data["decision"] in _values(ConsentDecision)
    assert isinstance(data["units_at_consent"], int)
    assert is_iso8601_timestamp(data["recorded_at"])


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------


def assert_four_decimal_places(value, label: str = "value"):
    """Ratios reported as numbers carry exactly four decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    rounded = round(float(value), 4)
    assert (
        abs(float(value) - rounded) < 1e-9
    ), f"{label} must carry at most four decimal places, got {value!r}"


def assert_posture(trust: dict, expected: str):
    assert (
        trust["posture"] == expected
    ), f"Expected posture {expected}, got {trust['posture']} on trust {trust['id']}"


def assert_trust_balances_replay_ledger(trust: dict, entries: list):
    """Bucket balances are the signed sums of that bucket's journal rows."""
    operating = sum(
        e["amount_cents"] for e in entries if e["bucket"] == LedgerBucket.OPERATING.value
    )
    reserve = sum(
        e["amount_cents"] for e in entries if e["bucket"] == LedgerBucket.RESERVE.value
    )
    assert trust["operating_balance_cents"] == operating, (
        f"operating_balance_cents {trust['operating_balance_cents']} must equal the "
        f"signed sum of OPERATING entries {operating}"
    )
    assert trust["reserve_balance_cents"] == reserve, (
        f"reserve_balance_cents {trust['reserve_balance_cents']} must equal the "
        f"signed sum of RESERVE entries {reserve}"
    )


def assert_reversal_negates(reversal: dict, original: dict):
    """A reversal carries exactly the negation of the entry it names."""
    assert reversal["reversal_of_entry_id"] == original["id"], (
        "reversal_of_entry_id must point at the entry being reversed"
    )
    assert reversal["amount_cents"] == -original["amount_cents"], (
        f"reversal amount {reversal['amount_cents']} must negate "
        f"{original['amount_cents']}"
    )


def assert_allocation_sum_equals(allocations: list, amount_cents: int):
    """The sum of allocated_cents across every row equals the amount exactly."""
    total = sum(row["allocated_cents"] for row in allocations)
    assert total == amount_cents, (
        f"Sum of allocated_cents {total} must equal the distributed amount "
        f"{amount_cents} exactly"
    )


def assert_dense_closing_sequence(subscriptions: list):
    """Closing ordinals run 1 through n with no gaps."""
    seqs = sorted(
        s["closing_sequence_no"]
        for s in subscriptions
        if s.get("closing_sequence_no") not in (None, "")
    )
    assert seqs == list(
        range(1, len(seqs) + 1)
    ), f"closing_sequence_no must be dense 1..n, got {seqs}"


def assert_pagination_meta(meta: dict, limit: int, offset: int):
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert isinstance(meta["total_count"], int)
    assert isinstance(meta["has_more"], bool)


def assert_sorted_by_created_at_ascending(rows: list):
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(
        stamps
    ), f"List must be sorted by created_at ascending, got {stamps}"
