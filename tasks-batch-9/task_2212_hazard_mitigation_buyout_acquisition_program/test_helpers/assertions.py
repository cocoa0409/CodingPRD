"""Domain assertion helpers.

Shape checks assert the field set and common-field conventions the PRD states for
each resource; invariant checks assert relationships the PRD states between
fields (rounding precision, derived totals, half-open and buffered intervals).
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import DOB_FACTORS, PROHIBITED_USE_CODES, REQUIRED_UTILITY_TYPES, THRESHOLDS


# ─── Common-field conventions ─────────────────────────────────────────────────

def assert_common_fields(entity, versioned=True):
    """Every resource carries a UUID id and an ISO-8601 UTC created_at."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO-8601 UTC: {entity['created_at']!r}"
    )
    assert_timestamp_format(entity["created_at"])
    if versioned:
        assert is_iso8601_timestamp(entity["updated_at"]), (
            f"updated_at is not ISO-8601 UTC: {entity['updated_at']!r}"
        )
        assert isinstance(entity["version"], int)
        assert entity["version"] >= 1, f"version must start at 1, got {entity['version']}"


def parse_instant(value):
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    assert isinstance(value, str), f"expected an ISO-8601 UTC instant string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO-8601 UTC instant: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual, expected, label="instant"):
    """Compare two ISO-8601 UTC instants by the moment they denote.

    The PRD fixes a three-fractional-digit rendering for created_at, updated_at and
    api_request_timestamp only; for the other server-stamped instants it states the
    instant, not its fractional-digit rendering, so the moment is what is compared.
    """
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_append_only_fields(record):
    """Append-only records carry no updated_at and no version."""
    assert_common_fields(record, versioned=False)
    assert "updated_at" not in record, "append-only record must not expose updated_at"
    assert "version" not in record, "append-only record must not expose version"


def assert_decimal_places(value, places):
    """A numeric field is quantised to exactly ``places`` decimal places."""
    quantised = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == quantised, (
        f"{value!r} is not quantised to {places} decimal places"
    )


def round_half_up(value, places):
    """Round-half-up to ``places`` decimals, the PRD's stated rounding mode."""
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def round_half_up_cents(value):
    """Round-half-up to a whole number of cents."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ─── Mitigation project ───────────────────────────────────────────────────────

def assert_mitigation_project_shape(project):
    assert_common_fields(project)
    for field in (
        "project_code",
        "grant_program",
        "subrecipient_name",
        "cost_share_federal_pct",
        "total_federal_share_cap_cents",
        "period_of_performance_end_date",
        "status",
        "federal_obligated_cents",
        "program_income_balance_cents",
        "protected_open_space_acres",
        "participating_parcel_count",
        "holdout_parcel_count",
        "contiguous_open_space_parcel_count",
        "largest_component_parcel_ids",
        "neighborhood_viability_ratio",
        "viability_status",
    ):
        assert field in project, f"project is missing {field}"
    assert isinstance(project["largest_component_parcel_ids"], list)
    assert_decimal_places(project["protected_open_space_acres"], 2)
    assert_decimal_places(project["neighborhood_viability_ratio"], 4)


def assert_viability_status_matches_ratio(project):
    """viability_status reads off the rounded ratio at the two inclusive bounds."""
    ratio = float(project["neighborhood_viability_ratio"])
    if ratio >= THRESHOLDS["VIABILITY_VIABLE_MIN"]:
        expected = "VIABLE"
    elif ratio >= THRESHOLDS["VIABILITY_AT_RISK_MIN"]:
        expected = "AT_RISK"
    else:
        expected = "NONVIABLE"
    assert project["viability_status"] == expected, (
        f"ratio {ratio} should give {expected}, got {project['viability_status']}"
    )


# ─── Benefit-cost analysis ────────────────────────────────────────────────────

def assert_benefit_cost_analysis_shape(bca):
    assert_common_fields(bca)
    for field in (
        "project_id",
        "analysis_method",
        "hazard_type",
        "sfha_zone",
        "repetitive_loss_flag",
        "annualized_loss_avoided_cents",
        "project_useful_life_years",
        "discount_rate_pct",
        "mitigation_cost_cents",
        "pv_annuity_factor",
        "npv_benefits_cents",
        "bcr",
        "status",
    ):
        assert field in bca, f"benefit-cost analysis is missing {field}"
    assert_decimal_places(bca["pv_annuity_factor"], 6)
    assert_decimal_places(bca["bcr"], 3)


def expected_pv_annuity_factor(discount_rate_pct, useful_life_years):
    """The FEMA_BCA_TOOLKIT factor: (1 - (1 + rate) ** -years) / rate to six decimals."""
    rate = Decimal(str(discount_rate_pct))
    factor = (Decimal(1) - (Decimal(1) + rate) ** -int(useful_life_years)) / rate
    return round_half_up(factor, 6)


def expected_npv_benefits_toolkit_cents(annualized_loss_avoided_cents, pv_annuity_factor):
    """Annualized loss avoided times the already-rounded factor, rounded to cents."""
    return round_half_up_cents(
        Decimal(str(annualized_loss_avoided_cents)) * Decimal(str(pv_annuity_factor))
    )


def expected_npv_benefits_pre_calculated_cents(annualized_loss_avoided_cents,
                                               project_useful_life_years):
    """Under PRE_CALCULATED_BENEFIT the benefit is an exact integer product."""
    return int(annualized_loss_avoided_cents) * int(project_useful_life_years)


def expected_bcr(npv_benefits_cents, mitigation_cost_cents):
    """NPV benefits over mitigation cost, rounded half-up to three decimals."""
    return round_half_up(
        Decimal(str(npv_benefits_cents)) / Decimal(str(mitigation_cost_cents)), 3
    )


# ─── Parcel ───────────────────────────────────────────────────────────────────

def assert_parcel_shape(parcel):
    assert_common_fields(parcel)
    for field in (
        "project_id",
        "apn",
        "site_address",
        "acreage",
        "occupancy_type",
        "structure_type",
        "substantial_damage_pct",
        "participation_status",
        "acquisition_status",
        "dob_deduction_total_cents",
    ):
        assert field in parcel, f"parcel is missing {field}"


# ─── Appraisal ────────────────────────────────────────────────────────────────

def assert_appraisal_shape(appraisal):
    assert_common_fields(appraisal)
    for field in (
        "parcel_id",
        "appraisal_type",
        "valuation_basis",
        "appraiser_user_id",
        "appraiser_license_no",
        "effective_date",
        "indicated_value_cents",
        "status",
        "revision_count",
    ):
        assert field in appraisal, f"appraisal is missing {field}"


def assert_validity_window(appraisal, expected_end_date):
    """validity_end_date is effective_date plus twelve calendar months."""
    assert appraisal["validity_end_date"] == expected_end_date, (
        f"validity_end_date should be {expected_end_date}, "
        f"got {appraisal['validity_end_date']}"
    )


# ─── Duplication of benefits ──────────────────────────────────────────────────

def assert_dob_record_shape(record):
    assert_common_fields(record)
    for field in (
        "parcel_id",
        "benefit_source",
        "amount_cents",
        "repair_documented_cents",
        "received_on",
        "deductible_cents",
        "status",
    ):
        assert field in record, f"duplication-of-benefits record is missing {field}"


def expected_dob_deduction_cents(benefit_source, amount_cents, repair_documented_cents=0):
    """Per-record deduction: (amount less documented repairs, floored at zero) times factor."""
    net = Decimal(str(amount_cents)) - Decimal(str(repair_documented_cents))
    if net < 0:
        net = Decimal(0)
    return round_half_up_cents(net * Decimal(str(DOB_FACTORS[benefit_source])))


# ─── Purchase offer ───────────────────────────────────────────────────────────

def assert_purchase_offer_shape(offer):
    assert_common_fields(offer)
    for field in (
        "parcel_id",
        "source_appraisal_id",
        "offer_basis",
        "base_value_cents",
        "dob_deduction_cents",
        "pre_incentive_net_cents",
        "incentive_cents",
        "net_offer_cents",
        "status",
    ):
        assert field in offer, f"purchase offer is missing {field}"


def assert_offer_arithmetic(offer):
    """The offer's three derived money fields agree with each other."""
    assert offer["pre_incentive_net_cents"] == (
        offer["base_value_cents"] - offer["dob_deduction_cents"]
    ), "pre_incentive_net_cents must be base value less the duplication deduction"
    assert offer["net_offer_cents"] == (
        offer["pre_incentive_net_cents"] + offer["incentive_cents"]
    ), "net_offer_cents must be the pre-incentive net plus the incentive"


def expected_incentive_cents(pre_incentive_net_cents, occupancy_type="OWNER_OCCUPIED"):
    """The banded owner-occupant incentive: flat rate, rounded first, then capped.

    The bands are half-open on the post-deduction figure, and the rate is 0 for
    any occupancy other than OWNER_OCCUPIED.
    """
    if occupancy_type != "OWNER_OCCUPIED":
        return 0
    net = Decimal(str(pre_incentive_net_cents))
    if net < THRESHOLDS["INCENTIVE_BAND_LOW_MAX_CENTS"]:
        rate = Decimal(str(THRESHOLDS["INCENTIVE_RATE_LOW"]))
    elif net < THRESHOLDS["INCENTIVE_BAND_MID_MAX_CENTS"]:
        rate = Decimal(str(THRESHOLDS["INCENTIVE_RATE_MID"]))
    else:
        rate = Decimal(str(THRESHOLDS["INCENTIVE_RATE_HIGH"]))
    return min(round_half_up_cents(net * rate), THRESHOLDS["INCENTIVE_CAP_CENTS"])


# ─── Relocation ───────────────────────────────────────────────────────────────

def assert_relocation_case_shape(case):
    assert_common_fields(case)
    for field in (
        "parcel_id",
        "displacee_type",
        "household_reference",
        "rhp_method",
        "rental_assistance_start_date",
        "rental_assistance_months",
        "replacement_housing_payment_cents",
        "rental_assistance_cents",
        "total_relocation_benefit_cents",
        "status",
        "appeal_count",
    ):
        assert field in case, f"relocation case is missing {field}"


def assert_relocation_total(case):
    """The total benefit is the housing payment plus rental assistance plus moving."""
    assert case["total_relocation_benefit_cents"] == (
        case["replacement_housing_payment_cents"]
        + case["rental_assistance_cents"]
        + case["moving_expense_cents"]
    ), "total_relocation_benefit_cents must sum its three components"


# ─── Closing and deed restriction ─────────────────────────────────────────────

def assert_closing_record_shape(closing):
    assert_common_fields(closing)
    for field in (
        "parcel_id",
        "accepted_offer_id",
        "scheduled_closing_date",
        "purchase_price_cents",
        "settlement_cost_cents",
        "status",
    ):
        assert field in closing, f"closing record is missing {field}"


def assert_deed_restriction_shape(restriction):
    assert_common_fields(restriction)
    for field in (
        "parcel_id",
        "closing_record_id",
        "restriction_type",
        "prohibited_uses",
        "recorded_on",
        "monitoring_interval_months",
        "next_monitoring_due_date",
        "maintenance_responsible_party",
        "status",
    ):
        assert field in restriction, f"deed restriction is missing {field}"
    assert sorted(restriction["prohibited_uses"]) == sorted(PROHIBITED_USE_CODES), (
        f"prohibited_uses must be the four published codes, got {restriction['prohibited_uses']}"
    )


# ─── Demolition ───────────────────────────────────────────────────────────────

def assert_work_order_shape(work_order):
    assert_common_fields(work_order)
    for field in (
        "parcel_id",
        "contractor_id",
        "asbestos_survey_status",
        "scheduled_start",
        "scheduled_end",
        "buffered_start",
        "buffered_end",
        "status",
        "failed_inspection_count",
        "required_utility_types",
        "confirmed_utility_types",
        "diversion_pct",
    ):
        assert field in work_order, f"work order is missing {field}"
    assert sorted(work_order["required_utility_types"]) == sorted(REQUIRED_UTILITY_TYPES), (
        "required_utility_types must be the four published utility types, "
        f"got {work_order['required_utility_types']}"
    )


def assert_buffered_window(work_order, expected_buffered_start, expected_buffered_end):
    """buffered_start is 24 hours before the scheduled start; buffered_end 24 hours after."""
    assert_instant_equals(work_order["buffered_start"], expected_buffered_start, "buffered_start")
    assert_instant_equals(work_order["buffered_end"], expected_buffered_end, "buffered_end")


def expected_diversion_pct(recycled_tons, total_debris_tons):
    """Recycled over total, as a percentage rounded half-up to two decimals."""
    return round_half_up(
        Decimal(str(recycled_tons)) / Decimal(str(total_debris_tons)) * Decimal(100), 2
    )


# ─── Program income ledger ────────────────────────────────────────────────────

def assert_program_income_entry_shape(entry):
    assert_append_only_fields(entry)
    for field in (
        "project_id",
        "entry_type",
        "amount_cents",
        "federal_share_cents",
        "posted_on",
        "status",
    ):
        assert field in entry, f"program income entry is missing {field}"


def expected_federal_item_cents(gross_cents, cost_share_federal_pct):
    """One obligation-ledger item: gross times the cost share, rounded to cents."""
    return round_half_up_cents(
        Decimal(str(gross_cents)) * Decimal(str(cost_share_federal_pct))
    )


def expected_federal_share_cents(amount_cents, cost_share_federal_pct, is_expenditure):
    """The federal share is rounded first, then signed by the entry type."""
    magnitude = round_half_up_cents(
        Decimal(str(amount_cents)) * Decimal(str(cost_share_federal_pct))
    )
    return -magnitude if is_expenditure else magnitude
