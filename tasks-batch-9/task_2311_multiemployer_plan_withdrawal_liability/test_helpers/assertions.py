"""Domain assertions: entity shapes, declared precisions and the conserved quantities."""

from typing import Any, Dict, Iterable, List, Sequence

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    DECLINE_RATIO_DECIMAL_PLACES,
    FRACTION_DECIMAL_PLACES,
    POOL_RATIO_DECIMAL_PLACES,
)

# Statuses that keep an instalment's principal inside the employer's balance.
OPEN_INSTALLMENT_STATUSES = ("SCHEDULED", "DUE", "DELINQUENT")
# Schedule generations whose instalments still count toward the balance.
LIVE_SCHEDULE_STATUSES = ("ACTIVE", "DEFAULT_ELIGIBLE", "NOTICED")


# ─── Common fields ────────────────────────────────────────────────────────────

def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Every resource carries an id, both timestamps and a version."""
    assert is_valid_uuid(entity["id"]), f"id is not a uuid: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1


def assert_fields_present(entity: Dict[str, Any], field_names: Iterable[str]) -> None:
    missing = [name for name in field_names if name not in entity]
    assert not missing, f"missing fields: {missing}"


# ─── Precision ────────────────────────────────────────────────────────────────

def assert_decimal_places(value: float, places: int) -> None:
    """The value must be representable at exactly the declared scale."""
    assert isinstance(value, (int, float)), f"not numeric: {value!r}"
    scaled = round(float(value) * (10 ** places))
    assert abs(float(value) * (10 ** places) - scaled) < 1e-6, (
        f"{value} carries more than {places} decimal places"
    )


def assert_four_decimal_places(value: float) -> None:
    assert_decimal_places(value, FRACTION_DECIMAL_PLACES)


def assert_six_decimal_places(value: float) -> None:
    assert_decimal_places(value, DECLINE_RATIO_DECIMAL_PLACES)


def assert_ten_decimal_places(value: float) -> None:
    assert_decimal_places(value, POOL_RATIO_DECIMAL_PLACES)


def assert_close(actual: float, expected: float, places: int = 4) -> None:
    assert actual == pytest.approx(expected, abs=0.5 * 10 ** (-places))


def assert_cents(actual: Any, expected: int) -> None:
    """Monetary fields are whole integer cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"monetary field is not an integer number of cents: {actual!r}"
    )
    assert actual == expected, f"expected {expected} cents, got {actual}"


# ─── Entity shapes ────────────────────────────────────────────────────────────

def assert_plan_shape(plan: Dict[str, Any]) -> None:
    assert_common_fields(plan)
    assert_fields_present(
        plan,
        [
            "name",
            "industry",
            "allocation_method",
            "de_minimis_variant",
            "interest_rate_bps",
            "unattributable_uvb_cents",
            "mass_withdrawal_declared",
            "employer_count",
            "issued_assessment_count",
        ],
    )


def assert_controlled_group_shape(group: Dict[str, Any]) -> None:
    assert_common_fields(group)
    assert_fields_present(
        group,
        [
            "name",
            "common_control_basis",
            "bond_posture",
            "joint_exposure_cents",
            "contingent_exposure_cents",
            "exposure_score",
        ],
    )
    assert_four_decimal_places(group["exposure_score"])


def assert_employer_shape(employer: Dict[str, Any]) -> None:
    assert_common_fields(employer)
    assert_fields_present(
        employer,
        [
            "plan_id",
            "controlled_group_id",
            "legal_name",
            "ein",
            "obligation_start_year",
            "covered_work_status",
            "cba_count",
            "status",
            "outstanding_liability_cents",
            "obligation_end_year",
            "credit_watch",
            "delinquency_strikes",
        ],
    )


def assert_valuation_shape(valuation: Dict[str, Any]) -> None:
    assert_common_fields(valuation)
    assert_fields_present(
        valuation,
        [
            "plan_id",
            "plan_year",
            "measurement_window_start",
            "measurement_window_end",
            "uvb_total_cents",
            "uvb_pool_cents",
            "all_employer_contributions_cents",
            "all_employer_cbu",
            "interest_rate_bps",
            "status",
            "allocated_uvb_cents",
            "unallocated_uvb_cents",
        ],
    )


def assert_contribution_record_shape(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert_fields_present(
        record,
        [
            "employer_id",
            "plan_year_start",
            "plan_year_end",
            "contribution_base_units",
            "contribution_amount_cents",
            "contribution_rate_cents_per_cbu",
            "status",
            "employer_version_at_apply",
        ],
    )


def assert_withdrawal_event_shape(event: Dict[str, Any]) -> None:
    assert_common_fields(event)
    assert_fields_present(
        event,
        [
            "employer_id",
            "cessation_date",
            "withdrawal_plan_year",
            "reported_cause",
            "status",
            "determined_type",
            "rules_variant",
            "partial_withdrawal_fraction",
            "decline_ratio",
            "high_base_year_average_cbu",
            "testing_period_average_cbu",
        ],
    )
    assert_four_decimal_places(event["partial_withdrawal_fraction"])
    assert_six_decimal_places(event["decline_ratio"])
    assert_four_decimal_places(event["high_base_year_average_cbu"])
    assert_four_decimal_places(event["testing_period_average_cbu"])


def assert_assessment_shape(assessment: Dict[str, Any]) -> None:
    assert_common_fields(assessment)
    assert_fields_present(
        assessment,
        [
            "withdrawal_event_id",
            "valuation_id",
            "allocation_method_applied",
            "de_minimis_variant_applied",
            "interest_rate_bps_applied",
            "gross_allocated_cents",
            "de_minimis_reduction_cents",
            "award_adjustment_cents",
            "net_assessed_cents",
            "annual_payment_cents",
            "high_3yr_average_cbu",
            "pool_term_breakdown",
            "lifecycle_status",
            "review_status",
            "collection_status",
            "active_schedule_generation",
        ],
    )
    assert_four_decimal_places(assessment["high_3yr_average_cbu"])
    assert isinstance(assessment["pool_term_breakdown"], list)


def assert_schedule_shape(schedule: Dict[str, Any]) -> None:
    assert_common_fields(schedule)
    assert_fields_present(
        schedule,
        [
            "liability_assessment_id",
            "generation_seq",
            "source",
            "annual_payment_cents",
            "applied_credit_cents",
            "amortization_basis_cents",
            "amortization_years",
            "forgiven_by_cap_cents",
            "capped_basis_cents",
            "installment_count",
            "quarterly_installment_cents",
            "final_installment_cents",
            "first_due_date",
            "status",
            "consecutive_delinquent_count",
        ],
    )


def assert_installment_shape(installment: Dict[str, Any]) -> None:
    assert_common_fields(installment)
    assert_fields_present(
        installment,
        [
            "payment_schedule_id",
            "sequence_number",
            "principal_cents",
            "amount_due_cents",
            "amount_paid_cents",
            "due_date",
            "delinquent_on",
            "status",
        ],
    )


def assert_review_request_shape(request: Dict[str, Any]) -> None:
    assert_common_fields(request)
    assert_fields_present(
        request,
        [
            "liability_assessment_id",
            "grounds_summary",
            "challenged_assumption",
            "status",
            "filed_at",
            "filed_by_user_id",
            "plan_response_deadline_at",
            "decision",
            "assumption_ruling",
        ],
    )


def assert_arbitration_shape(arbitration: Dict[str, Any]) -> None:
    assert_common_fields(arbitration)
    assert_fields_present(
        arbitration,
        [
            "liability_assessment_id",
            "review_request_id",
            "initiated_at",
            "round_number",
            "status",
            "award_outcome",
            "assumption_ruling",
        ],
    )


def assert_asset_sale_shape(transaction: Dict[str, Any]) -> None:
    assert_common_fields(transaction)
    assert_fields_present(
        transaction,
        [
            "seller_employer_id",
            "buyer_controlled_group_id",
            "closing_date",
            "closing_plan_year",
            "purchase_price_cents",
            "bond_amount_cents",
            "buyer_assumes_contribution_obligation",
            "workforce_continuity_pct",
            "asset_continuity_pct",
            "customer_continuity_pct",
            "required_bond_cents",
            "status",
            "exemption_status",
            "successor_determination",
            "substantial_continuity_score",
        ],
    )
    assert_four_decimal_places(transaction["substantial_continuity_score"])


# ─── Conserved quantities ─────────────────────────────────────────────────────

def assert_uvb_allocation_conserved(valuation: Dict[str, Any]) -> None:
    """Allocated plus unallocated unfunded vested benefits equal the total."""
    assert (
        valuation["allocated_uvb_cents"] + valuation["unallocated_uvb_cents"]
        == valuation["uvb_total_cents"]
    ), (
        "allocated_uvb_cents + unallocated_uvb_cents must equal uvb_total_cents: "
        f"{valuation['allocated_uvb_cents']} + {valuation['unallocated_uvb_cents']} "
        f"!= {valuation['uvb_total_cents']}"
    )


def open_principal_total(installments: Sequence[Dict[str, Any]]) -> int:
    """Sum of principal over instalments that are still owed."""
    return sum(
        item["principal_cents"]
        for item in installments
        if item["status"] in OPEN_INSTALLMENT_STATUSES
    )


def assert_outstanding_liability_matches(
    employer: Dict[str, Any], installments: Sequence[Dict[str, Any]]
) -> None:
    """The employer's balance equals the principal still owed on the live generation."""
    expected = open_principal_total(installments)
    assert employer["outstanding_liability_cents"] == expected, (
        "outstanding_liability_cents must equal the summed principal of instalments "
        f"still owed: {employer['outstanding_liability_cents']} != {expected}"
    )


def assert_assessment_decomposition(
    schedule: Dict[str, Any], installments: Sequence[Dict[str, Any]], net_assessed_cents: int
) -> None:
    """Principal plus cap forgiveness plus applied credit reconstructs the assessment."""
    principal_total = sum(item["principal_cents"] for item in installments)
    total = (
        principal_total + schedule["forgiven_by_cap_cents"] + schedule["applied_credit_cents"]
    )
    assert total == net_assessed_cents, (
        "summed principal + forgiven_by_cap_cents + applied_credit_cents must equal "
        f"net_assessed_cents: {principal_total} + {schedule['forgiven_by_cap_cents']} + "
        f"{schedule['applied_credit_cents']} != {net_assessed_cents}"
    )


def assert_principal_split(schedule: Dict[str, Any], installments: Sequence[Dict[str, Any]]) -> None:
    """Every instalment but the last carries the floor share; the last absorbs the remainder."""
    ordered: List[Dict[str, Any]] = sorted(installments, key=lambda item: item["sequence_number"])
    assert len(ordered) == schedule["installment_count"]
    for item in ordered[:-1]:
        assert item["principal_cents"] == schedule["quarterly_installment_cents"]
    assert ordered[-1]["principal_cents"] == schedule["final_installment_cents"]
    assert sum(item["principal_cents"] for item in ordered) == schedule["capped_basis_cents"]
