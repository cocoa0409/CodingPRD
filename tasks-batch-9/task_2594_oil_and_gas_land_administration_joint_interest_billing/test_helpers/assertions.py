"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BOND_COVERAGE_FACTOR,
    DEPTH_RATE_CENTS_PER_FT,
    PLUG_BASE_CENTS,
    PLUG_CAP_CENTS,
)

LEASE_TENURE_STATUSES = [
    "PRIMARY_TERM",
    "HELD_BY_PRODUCTION",
    "SHUT_IN_HELD",
    "CONTINUOUS_DEV_HELD",
    "EXPIRED",
]
LEASE_OBLIGATION_STATUSES = ["COMPLIANT", "OBLIGATION_DUE", "CURED", "IN_BREACH"]
WELL_STATUSES = [
    "PROPOSED",
    "DRILLING",
    "PRODUCING",
    "SHUT_IN",
    "TEMPORARILY_ABANDONED",
    "PLUGGED",
]
POOLING_STATUSES = [
    "UNPOOLED",
    "POOLED_FORMING",
    "POOLED_EFFECTIVE",
    "POOLED_TERMINATED",
]
OWNER_TYPES = [
    "WORKING_INTEREST_PARTNER",
    "ROYALTY_OWNER",
    "OVERRIDING_ROYALTY_OWNER",
]
STATEMENT_STATUSES = ["DRAFT", "ISSUED", "DISPUTED", "SETTLED", "ADJUSTED", "VOID"]
DISPUTE_STATUSES = [
    "OPEN",
    "OPERATOR_RESPONDED",
    "ESCALATED",
    "RESOLVED_UPHELD",
    "RESOLVED_ADJUSTED",
    "EXPIRED",
]
BILLED_STATEMENT_STATUSES = ["ISSUED", "DISPUTED", "SETTLED"]
UNBILLED_STATEMENT_STATUSES = ["DRAFT", "ADJUSTED", "VOID"]


# --- Generic helpers ------------------------------------------------------


def assert_common_fields(data: dict, entity_label: str = "entity") -> None:
    """id, created_at, updated_at and version are present and well formed."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer, got {data.get('version')}"
    )


def assert_percentage_precision(value, field_name: str = "percentage") -> None:
    """A percentage is carried to exactly six decimal places."""
    assert value is not None, f"{field_name} must not be null"
    quantized = round(float(value), 6)
    assert abs(float(value) - quantized) < 1e-12, (
        f"{field_name} must be carried to six decimal places, got {value}"
    )


def assert_acreage_precision(value, field_name: str = "acreage") -> None:
    """An acreage figure is carried to exactly two decimal places."""
    assert value is not None, f"{field_name} must not be null"
    quantized = round(float(value), 2)
    assert abs(float(value) - quantized) < 1e-9, (
        f"{field_name} must be carried to two decimal places, got {value}"
    )


def assert_whole_cents(value, field_name: str = "amount_cents") -> None:
    """Money is a whole number of cents, never a fraction."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer number of cents, got {value!r}"
    )


def assert_date_equals(actual, expected: str, field_name: str) -> None:
    """Compare a date-bearing field against a YYYY-MM-DD calendar date."""
    assert actual is not None, f"{field_name} must not be null"
    assert str(actual)[:10] == expected, (
        f"Expected {field_name} on {expected}, got {actual}"
    )


# --- Entity assertions ----------------------------------------------------


def assert_lease(data: dict) -> None:
    assert_common_fields(data, "lease")
    assert isinstance(data["lease_number"], str) and data["lease_number"]
    assert isinstance(data["lessor_name"], str) and data["lessor_name"]
    assert_acreage_precision(data["gross_acres"], "lease.gross_acres")
    assert data["gross_acres"] > 0, "lease.gross_acres must be greater than zero"
    assert 0 < float(data["royalty_rate"]) < 1, (
        f"lease.royalty_rate must lie strictly between 0 and 1, got {data['royalty_rate']}"
    )
    assert data["tenure_status"] in LEASE_TENURE_STATUSES
    assert data["obligation_status"] in LEASE_OBLIGATION_STATUSES
    assert isinstance(data["extension_option_months"], int)
    assert_whole_cents(
        data["extension_bonus_per_acre_cents"], "lease.extension_bonus_per_acre_cents"
    )
    assert_whole_cents(
        data["extension_bonus_paid_cents"], "lease.extension_bonus_paid_cents"
    )
    assert_whole_cents(
        data["shut_in_royalty_per_acre_cents"], "lease.shut_in_royalty_per_acre_cents"
    )
    assert isinstance(data["extension_exercised"], bool)
    assert isinstance(data["shut_in_payments_made"], int)
    assert isinstance(data["continuous_dev_window_days"], int)
    assert_acreage_precision(data["committed_acres_total"], "lease.committed_acres_total")
    assert_acreage_precision(data["held_acres"], "lease.held_acres")


def assert_well(data: dict) -> None:
    assert_common_fields(data, "well")
    assert isinstance(data["well_name"], str) and 1 <= len(data["well_name"]) <= 32
    assert isinstance(data["api_number"], str) and data["api_number"]
    assert data["product_type"] in ["OIL", "GAS"]
    assert isinstance(data["total_depth_ft"], int)
    assert 0 < data["total_depth_ft"] <= 30_000
    assert data["well_status"] in WELL_STATUSES
    assert data["pooling_status"] in POOLING_STATUSES
    assert_percentage_precision(
        data["allocation_factor_total"], "well.allocation_factor_total"
    )
    assert_percentage_precision(
        data["consent_working_interest_pct"], "well.consent_working_interest_pct"
    )
    assert_whole_cents(data["plugging_liability_cents"], "well.plugging_liability_cents")
    assert_whole_cents(data["billed_to_date_cents"], "well.billed_to_date_cents")


def assert_lease_allocation(data: dict) -> None:
    assert_common_fields(data, "allocation")
    assert is_valid_uuid(data["well_id"])
    assert is_valid_uuid(data["lease_id"])
    assert_acreage_precision(data["committed_acres"], "allocation.committed_acres")
    assert_percentage_precision(data["allocation_factor"], "allocation.allocation_factor")
    assert data["allocation_status"] in ["COMMITTED", "WITHDRAWN"]


def assert_interest_owner(data: dict) -> None:
    assert_common_fields(data, "interest owner")
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert data["owner_type"] in OWNER_TYPES
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert isinstance(data["tax_id_on_file"], bool)
    assert_whole_cents(data["bond_posted_cents"], "owner.bond_posted_cents")
    assert_whole_cents(data["required_bond_cents"], "owner.required_bond_cents")
    assert_whole_cents(data["suspense_balance_cents"], "owner.suspense_balance_cents")
    assert isinstance(data["audit_window_days"], int)
    assert 90 <= data["audit_window_days"] <= 1460


def assert_well_interest(data: dict) -> None:
    assert_common_fields(data, "well interest")
    assert is_valid_uuid(data["well_id"])
    assert is_valid_uuid(data["owner_id"])
    assert_percentage_precision(
        data["working_interest_pct"], "interest.working_interest_pct"
    )
    assert_percentage_precision(
        data["net_revenue_interest_pct"], "interest.net_revenue_interest_pct"
    )
    assert float(data["net_revenue_interest_pct"]) <= float(
        data["working_interest_pct"]
    ), "net_revenue_interest_pct may not exceed working_interest_pct"
    assert data["interest_status"] in ["ACTIVE", "SUPERSEDED", "TERMINATED"]
    assert isinstance(data["is_operator"], bool)
    assert isinstance(data["preferential_right"], bool)
    assert isinstance(data["non_consent_flag"], bool)
    assert_whole_cents(
        data["non_consent_recoverable_balance_cents"],
        "interest.non_consent_recoverable_balance_cents",
    )


def assert_afe(data: dict) -> None:
    assert_common_fields(data, "afe")
    assert is_valid_uuid(data["well_id"])
    assert isinstance(data["afe_number"], str) and data["afe_number"]
    assert data["operation_type"] in ["DRILL", "COMPLETION", "WORKOVER", "RECOMPLETION"]
    assert_whole_cents(data["estimated_cost_cents"], "afe.estimated_cost_cents")
    assert data["estimated_cost_cents"] > 0
    assert data["cost_class"] in ["CAPITAL", "OPERATING"]
    assert data["afe_status"] in [
        "ELECTIONS_OPEN",
        "FULLY_CONSENTED",
        "PARTIALLY_CONSENTED",
        "FAILED",
    ]
    assert 1.0 <= float(data["non_consent_penalty_multiple"]) <= 5.0
    assert 0 < float(data["minimum_consent_pct"]) <= 1
    assert_percentage_precision(data["minimum_consent_pct"], "afe.minimum_consent_pct")
    assert_percentage_precision(
        data["consent_working_interest_pct"], "afe.consent_working_interest_pct"
    )
    assert_percentage_precision(
        data["non_consent_working_interest_pct"], "afe.non_consent_working_interest_pct"
    )


def assert_afe_election(data: dict) -> None:
    assert_common_fields(data, "afe election")
    assert is_valid_uuid(data["afe_id"])
    assert is_valid_uuid(data["owner_id"])
    assert data["election_type"] in ["CONSENT", "NON_CONSENT"]
    assert data["election_status"] in ["SUBMITTED", "DEEMED_NON_CONSENT", "VOIDED"]
    assert_percentage_precision(data["wi_pct_snapshot"], "election.wi_pct_snapshot")
    assert_whole_cents(data["estimated_penalty_cents"], "election.estimated_penalty_cents")


def assert_cost_entry(data: dict) -> None:
    assert_common_fields(data, "cost entry")
    assert is_valid_uuid(data["well_id"])
    assert data["cost_category"] in [
        "DRILLING",
        "COMPLETION",
        "LEASE_OPERATING",
        "WORKOVER",
        "PLUGGING",
    ]
    assert data["cost_class"] in ["CAPITAL", "OPERATING"]
    assert_whole_cents(data["amount_cents"], "cost_entry.amount_cents")
    assert data["amount_cents"] > 0
    assert data["cost_status"] in ["ACCRUED", "PAID"]
    if data["cost_status"] == "ACCRUED":
        assert data["paid_date"] is None, "an accrued cost entry keeps paid_date null"


def assert_jib_statement(data: dict) -> None:
    assert_common_fields(data, "jib statement")
    assert is_valid_uuid(data["well_id"])
    assert isinstance(data["statement_number"], str)
    assert 1 <= len(data["statement_number"]) <= 32
    assert data["cost_basis"] in ["ACCRUAL", "CASH"]
    assert data["activity_class"] in ["DRILLING", "PRODUCING"]
    assert data["overhead_rate_class"] in ["FIXED_RATE", "PERCENTAGE_BASIS"]
    assert data["statement_status"] in STATEMENT_STATUSES
    for field in (
        "capital_direct_cents",
        "operating_direct_cents",
        "direct_cost_cents",
        "overhead_cents",
        "total_billed_cents",
    ):
        assert_whole_cents(data[field], f"statement.{field}")
    assert isinstance(data["billable_months"], int)
    assert data["direct_cost_cents"] == (
        data["capital_direct_cents"] + data["operating_direct_cents"]
    ), "direct_cost_cents is the sum of the capital and operating pools"
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


def assert_jib_line_item(data: dict) -> None:
    """A line item carries only id and created_at as common fields: it has no
    updated_at field and no version field at all."""
    assert is_valid_uuid(data.get("id", "")), "line item id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "a line item has no updated_at field"
    assert "version" not in data, "a line item has no version field at all"
    assert is_valid_uuid(data["statement_id"])
    assert is_valid_uuid(data["owner_id"])
    assert_percentage_precision(data["wi_pct_snapshot"], "line_item.wi_pct_snapshot")
    assert_percentage_precision(
        data["consent_normalized_wi_pct"], "line_item.consent_normalized_wi_pct"
    )
    for field in (
        "direct_capital_cents",
        "direct_operating_cents",
        "overhead_cents",
        "non_consent_reallocated_cents",
        "non_consent_withheld_cents",
        "penalty_accrued_cents",
        "rounding_residual_cents",
        "total_billed_cents",
    ):
        assert_whole_cents(data[field], f"line_item.{field}")


def assert_billing_dispute(data: dict) -> None:
    assert_common_fields(data, "dispute")
    assert is_valid_uuid(data["statement_id"])
    assert is_valid_uuid(data["owner_id"])
    assert data["dispute_kind"] in ["BILLING_DISPUTE", "AUDIT_EXCEPTION"]
    assert_whole_cents(data["disputed_amount_cents"], "dispute.disputed_amount_cents")
    assert data["disputed_amount_cents"] > 0
    assert isinstance(data["basis_note"], str)
    assert 1 <= len(data["basis_note"]) <= 500
    assert data["dispute_status"] in DISPUTE_STATUSES
    assert isinstance(data["round_count"], int) and 0 <= data["round_count"] <= 2
    assert isinstance(data["deemed_in_favor_of_partner"], bool)


def assert_production_revenue(data: dict) -> None:
    assert_common_fields(data, "production revenue")
    assert is_valid_uuid(data["well_id"])
    assert isinstance(data["production_month"], str)
    assert len(data["production_month"]) == 7 and data["production_month"][4] == "-"
    assert 1 <= int(data["production_month"][5:]) <= 12
    assert_whole_cents(data["gross_revenue_cents"], "revenue.gross_revenue_cents")
    assert data["gross_revenue_cents"] > 0
    assert float(data["volume_units"]) > 0
    for field in (
        "severance_tax_cents",
        "net_proceeds_cents",
        "total_royalty_cents",
        "total_disbursed_cents",
    ):
        assert_whole_cents(data[field], f"revenue.{field}")
    assert data["distribution_status"] in ["ACCRUED", "RELEASED", "SUSPENDED"]


def assert_owner_disbursement(data: dict) -> None:
    assert_common_fields(data, "disbursement")
    assert is_valid_uuid(data["revenue_id"])
    assert is_valid_uuid(data["owner_id"])
    assert is_valid_uuid(data["lease_id"])
    for field in (
        "gross_share_cents",
        "withheld_recovery_cents",
        "net_amount_cents",
        "late_interest_cents",
    ):
        assert_whole_cents(data[field], f"disbursement.{field}")
    assert data["disbursement_status"] in ["ACCRUED", "PAID", "SUSPENDED"]
    if data["suspense_reason"] is not None:
        assert data["suspense_reason"] in [
            "MISSING_TAX_ID",
            "NON_CONSENT_RECOVERY",
            "POOLING_TERMINATED",
        ]
    if data["interest_basis"] is not None:
        assert data["interest_basis"] in ["FROM_DUE_DATE", "FROM_PROCEEDS_RECEIPT"]


def assert_assignment_transfer(data: dict) -> None:
    assert_common_fields(data, "transfer")
    assert is_valid_uuid(data["well_id"])
    assert is_valid_uuid(data["assignor_owner_id"])
    assert is_valid_uuid(data["assignee_owner_id"])
    assert_percentage_precision(data["transfer_wi_pct"], "transfer.transfer_wi_pct")
    assert_percentage_precision(data["transfer_nri_pct"], "transfer.transfer_nri_pct")
    assert_whole_cents(data["sale_price_cents"], "transfer.sale_price_cents")
    assert_whole_cents(
        data["bond_check_required_cents"], "transfer.bond_check_required_cents"
    )
    assert isinstance(data["ppr_eligible_count"], int)
    assert isinstance(data["ppr_waiver_count"], int)
    assert data["transfer_status"] in [
        "NOTICED",
        "PPR_EXERCISED",
        "PPR_WAIVED",
        "CLOSED",
    ]


# --- Domain invariant checkers -------------------------------------------


def expected_plugging_liability_cents(total_depth_ft: int) -> int:
    """3,500,000 plus 1,200 for every foot of measured depth, capped at
    25,000,000."""
    raw = PLUG_BASE_CENTS + DEPTH_RATE_CENTS_PER_FT * int(total_depth_ft)
    return min(raw, PLUG_CAP_CENTS)


def round_half_up(value: float) -> int:
    """Round to whole cents so that exactly one half cent rounds away from zero
    to the larger magnitude."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(Decimal(repr(float(value))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_required_bond_cents(per_well_products) -> int:
    """Each per-well product rounded half up first, then summed, then scaled by
    the coverage factor and rounded half up once more."""
    total = sum(round_half_up(p) for p in per_well_products)
    return round_half_up(total * BOND_COVERAGE_FACTOR)


def assert_allocation_factors_sum_to_one(allocations: list) -> None:
    """After the residual adjustment the committed factors total exactly
    1.000000."""
    committed = [a for a in allocations if a["allocation_status"] == "COMMITTED"]
    total = round(sum(float(a["allocation_factor"]) for a in committed), 6)
    assert total == 1.000000, (
        f"Committed allocation factors must total exactly 1.000000, got {total}"
    )


def assert_line_items_sum_to_statement_total(statement: dict, line_items: list) -> None:
    """The line items of a statement account for its whole total."""
    total = sum(item["total_billed_cents"] for item in line_items)
    assert total == statement["total_billed_cents"], (
        f"Line items total {total} but the statement carries "
        f"{statement['total_billed_cents']}"
    )


def assert_revenue_conservation(revenue: dict, disbursements: list) -> None:
    """Gross proceeds equal severance tax plus royalty plus what was
    disbursed."""
    parts = (
        revenue["severance_tax_cents"]
        + revenue["total_royalty_cents"]
        + revenue["total_disbursed_cents"]
    )
    assert parts == revenue["gross_revenue_cents"], (
        f"Severance {revenue['severance_tax_cents']} + royalty "
        f"{revenue['total_royalty_cents']} + disbursed "
        f"{revenue['total_disbursed_cents']} must equal gross "
        f"{revenue['gross_revenue_cents']}"
    )
    if disbursements:
        gross_shares = sum(d["gross_share_cents"] for d in disbursements)
        assert gross_shares == revenue["total_disbursed_cents"], (
            f"total_disbursed_cents {revenue['total_disbursed_cents']} must equal "
            f"the sum of gross shares {gross_shares}"
        )


def assert_active_working_interest_sum(interests: list, expected: float) -> None:
    active = [i for i in interests if i["interest_status"] == "ACTIVE"]
    total = round(sum(float(i["working_interest_pct"]) for i in active), 6)
    assert total == round(expected, 6), (
        f"Active working interest must total {expected}, got {total}"
    )
