"""Combinatorial money formulas: nested rounding, band selection and nested min/max."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.test_users import TEST_USERS


# ─── The duplication-of-benefits sweep ────────────────────────────────────────

def test_each_dob_record_is_rounded_before_the_parcel_total_accumulates_it(api):
    """Two half-cent SBA records each round up individually, not once at the total.

    "The product is rounded half up to whole cents **at this point, for this
    record**, and stored as that record's `deductible_cents`."

    "The parcel's `dob_deduction_total_cents` is then the sum of those
    already-rounded per-record `deductible_cents` values, accumulated in the
    sweep order."

    Design: Difficulty/combinatorial_formula/dob_deduction_rounds_per_record_before_summation
    """
    state = fixtures.create_approved_project(api, parcel_overrides={"acreage": 0.50})
    project, parcel = state["project"], state["parcel"]

    nfip = fixtures.record_dob(
        api,
        project,
        parcel["id"],
        benefit_source="NFIP_CLAIM",
        amount_cents=1_200_000,
        repair_documented_cents=300_000,
        received_on="2026-03-01",
    )
    sba_a = fixtures.record_dob(
        api,
        project,
        parcel["id"],
        benefit_source="SBA_LOAN",
        amount_cents=500_001,
        repair_documented_cents=0,
        received_on="2026-04-01",
    )
    sba_b = fixtures.record_dob(
        api,
        project,
        parcel["id"],
        benefit_source="SBA_LOAN",
        amount_cents=700_001,
        repair_documented_cents=0,
        received_on="2026-05-01",
    )

    assert nfip["deductible_cents"] == 900_000
    assert nfip["status"] == "ACTIVE"
    assert sba_a["deductible_cents"] == 250_001
    assert sba_b["deductible_cents"] == 350_001

    refreshed = validate_success(
        api.get_parcel(parcel["id"], TEST_USERS["program_administrator_headers"])
    )
    assert refreshed["dob_deduction_total_cents"] == 1_500_002


def test_the_sum_then_round_answer_is_one_cent_short_and_is_not_produced(api):
    """The same three records summed raw and rounded once would give 1500001, which is wrong.

    "Summing the unrounded products and rounding the total is a different number
    and is wrong: two `SBA_LOAN` records each landing on a half-cent both round
    up individually, whereas their raw sum contains no fraction at all."

    "That net award is multiplied by the factor for its `benefit_source`, which
    is 1.00 for `NFIP_CLAIM`, 1.00 for `ICC`, 1.00 for `PRIVATE_INSURANCE`, 0.50
    for `SBA_LOAN` and 0.85 for `CDBG_DR`."

    Design: Difficulty/combinatorial_formula/dob_deduction_rounds_per_record_before_summation
    """
    state = fixtures.create_approved_project(api, parcel_overrides={"acreage": 0.50})
    project, parcel = state["project"], state["parcel"]

    fixtures.record_dob(
        api,
        project,
        parcel["id"],
        benefit_source="NFIP_CLAIM",
        amount_cents=1_200_000,
        repair_documented_cents=300_000,
        received_on="2026-03-01",
    )
    for amount, received_on in ((500_001, "2026-04-01"), (700_001, "2026-05-01")):
        fixtures.record_dob(
            api,
            project,
            parcel["id"],
            benefit_source="SBA_LOAN",
            amount_cents=amount,
            repair_documented_cents=0,
            received_on=received_on,
        )

    refreshed = validate_success(
        api.get_parcel(parcel["id"], TEST_USERS["program_administrator_headers"])
    )
    assert refreshed["dob_deduction_total_cents"] == 1_500_002
    assert refreshed["dob_deduction_total_cents"] != 1_500_001


# ─── The offer incentive band ─────────────────────────────────────────────────

def _two_parcel_offers(api):
    """Two otherwise identical parcels whose appraisals straddle the 0.10/0.07 band."""
    state = fixtures.create_approved_project_with_parcels(
        api,
        [
            {"apn": "APN-X", "site_address": "1 Levee Ln", "acreage": 0.25},
            {"apn": "APN-Y", "site_address": "3 Levee Ln", "acreage": 0.25},
        ],
    )
    project = state["project"]
    parcel_x, parcel_y = state["parcels"]

    x = fixtures.progress_parcel_to_value_established(
        api, project, parcel_x, pre_event_fmv_cents=10_000_000,
        indicated_value_cents=10_000_000,
    )
    y = fixtures.progress_parcel_to_value_established(
        api, project, parcel_y, pre_event_fmv_cents=10_100_000,
        indicated_value_cents=10_100_000,
    )
    for parcel in (x["parcel"], y["parcel"]):
        fixtures.record_dob(
            api,
            project,
            parcel["id"],
            benefit_source="NFIP_CLAIM",
            amount_cents=100_000,
            repair_documented_cents=0,
            received_on="2026-05-01",
        )

    offer_x = fixtures.build_offer(
        api, project, x["parcel"]["id"], x["review_appraisal"]
    )
    offer_y = fixtures.build_offer(
        api, project, y["parcel"]["id"], y["review_appraisal"]
    )
    return offer_x, offer_y


def test_incentive_band_is_selected_on_the_post_deduction_net_not_the_appraisal(api):
    """A 10,000,000 appraisal nets 9,900,000 and stays in the 0.10 band.

    "`pre_incentive_net_cents` is `base_value_cents` minus `dob_deduction_cents`,
    taken as zero if that difference is negative."

    "For an `OWNER_OCCUPIED` parcel, the rate is read from the single half-open
    band containing `pre_incentive_net_cents`: 0.10 when `pre_incentive_net_cents`
    is below 10,000,000 cents; 0.07 when it is at least 10,000,000 and below
    25,000,000; and 0.05 when it is 25,000,000 or more."

    Design: Difficulty/combinatorial_formula/net_offer_incentive_tier_keyed_on_post_deduction_figure
    """
    offer_x, offer_y = _two_parcel_offers(api)

    assert offer_x["base_value_cents"] == 10_000_000
    assert offer_x["dob_deduction_cents"] == 100_000
    assert offer_x["pre_incentive_net_cents"] == 9_900_000
    assert offer_x["incentive_cents"] == 990_000
    assert offer_x["net_offer_cents"] == 10_890_000
    assert offer_x["status"] == "DRAFT"

    assert offer_y["pre_incentive_net_cents"] == 10_000_000
    assert offer_y["incentive_cents"] == 700_000


def test_a_larger_appraisal_can_produce_a_strictly_smaller_net_offer(api):
    """Crossing into the 0.07 band makes the result non-monotone in the appraisal.

    "The critical property is that the tier is keyed on the **post-deduction**
    figure, not on `base_value_cents`, so the result is not monotone in the
    appraised value."

    "A larger appraisal produces a smaller offer."

    Design: Difficulty/combinatorial_formula/net_offer_incentive_tier_keyed_on_post_deduction_figure
    """
    offer_x, offer_y = _two_parcel_offers(api)

    assert offer_y["base_value_cents"] == 10_100_000
    assert offer_y["dob_deduction_cents"] == 100_000
    assert offer_y["net_offer_cents"] == 10_700_000
    assert offer_x["net_offer_cents"] - offer_y["net_offer_cents"] == 190_000
    assert offer_y["status"] == "DRAFT"


# ─── The rental assistance chain ──────────────────────────────────────────────

def _tenant_case(api):
    state = fixtures.parcel_with_accepted_offer(
        api,
        parcel_overrides={
            "apn": "APN-TEN",
            "site_address": "9 Levee Ln",
            "acreage": 0.20,
            "occupancy_type": "TENANT_OCCUPIED",
            "structure_type": "MULTI_FAMILY",
        },
    )
    case = fixtures.open_relocation_case(
        api,
        state["parcel"]["id"],
        displacee_type="TENANT_90_DAY",
        household_reference="HH-TEN-1",
        rhp_method="COMPARABLE_DWELLING",
        rental_assistance_start_date="2026-09-01",
        current_rent_cents=90_000,
        current_utility_cents=15_000,
        comparable_rent_cents=130_000,
        comparable_utility_cents=20_000,
        monthly_gross_income_cents=320_000,
        moving_expense_cents=175_000,
        comparable_dwelling_price_cents=None,
    )
    case = validate_success(
        api.determine_relocation_eligibility(
            case["id"], TEST_USERS["relocation_specialist_headers"]
        )
    )
    return state, case


def test_ability_to_pay_leg_wins_the_interior_minimum_of_the_rental_chain(api):
    """Thirty percent of income is below the actual housing cost, so it sets the base.

    "Fourth, the ability to pay is `monthly_gross_income_cents` multiplied by
    0.30, **rounded half up to whole cents before it is used** - that is, the
    rounding happens ahead of the comparison in the next step, not after it.
    Fifth, the base monthly amount is the **lesser** of the current housing cost
    and the ability to pay; the larger of the two is discarded and never
    resurfaces."

    "First, `rental_assistance_months` is 42 when `displacee_type` is
    `TENANT_90_DAY`, and exactly 0 when `displacee_type` is `OWNER_OCCUPANT`,
    `TENANT_UNDER_90_DAY` or `BUSINESS`."

    "Second, `rental_assistance_end_date` is `rental_assistance_start_date` plus
    `rental_assistance_months` calendar months, clamped to month end where the
    anchor day-of-month does not exist in the target month, and it is the
    **exclusive** upper bound of the occupation interval."

    Design: Difficulty/combinatorial_formula/rental_assistance_ability_to_pay_leg_wins_nested_min_max
    """
    _state, case = _tenant_case(api)

    assert case["rental_assistance_months"] == 42
    assert case["rental_assistance_end_date"] == "2030-03-01"
    assert case["rental_assistance_cents"] == 2_268_000
    assert case["status"] == "ELIGIBILITY_DETERMINED"


def test_tenant_case_draws_no_housing_payment_and_no_owner_occupant_incentive(api):
    """The tenant leg zeroes the housing payment while the offer carries no incentive.

    "The owner-occupant incentive rate is 0 whenever the parcel's
    `occupancy_type` is anything other than `OWNER_OCCUPIED`."

    "Ninth, `rental_assistance_cents` is the lesser of that uncapped total and
    3,150,000 cents."

    "Tenth, `total_relocation_benefit_cents` is
    `replacement_housing_payment_cents` plus `rental_assistance_cents` plus
    `moving_expense_cents`."

    Design: Difficulty/combinatorial_formula/rental_assistance_ability_to_pay_leg_wins_nested_min_max
    """
    state, case = _tenant_case(api)

    assert state["offer"]["incentive_cents"] == 0
    assert state["offer"]["net_offer_cents"] == 20_000_000
    assert case["acquisition_price_cents"] == 20_000_000
    assert case["replacement_housing_payment_cents"] == 0
    assert case["total_relocation_benefit_cents"] == 2_443_000

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["federal_obligated_cents"] == 15_000_000
