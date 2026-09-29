"""Dual-variant calculations: one stored input set, two genuinely different formulas."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


TOOLKIT_INPUTS = {
    "analysis_method": "FEMA_BCA_TOOLKIT",
    "annualized_loss_avoided_cents": 4_000_000,
    "project_useful_life_years": 30,
    "discount_rate_pct": 0.07,
    "mitigation_cost_cents": 45_000_000,
}

PRE_CALCULATED_INPUTS = dict(TOOLKIT_INPUTS, analysis_method="PRE_CALCULATED_BENEFIT")


def _attach_analysis(api, project, inputs):
    return validate_success(
        api.create_benefit_cost_analysis(
            project["id"],
            factories.create_benefit_cost_analysis_payload(project["id"], **inputs),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        201,
    )


def test_toolkit_variant_discounts_the_benefit_stream_over_the_useful_life(api):
    """The discounted variant computes its factor and multiplies by the rounded factor.

    "Under `FEMA_BCA_TOOLKIT`, the present-value annuity factor is one minus the
    quantity (one plus `discount_rate_pct`) raised to the power of the negative
    of `project_useful_life_years`, all divided by `discount_rate_pct`; that
    quotient is rounded half up to six decimal places and stored as
    `pv_annuity_factor`."

    "The critical sequencing is that `npv_benefits_cents` is then
    `annualized_loss_avoided_cents` multiplied by the **already-rounded
    six-decimal factor** - not by the unrounded quotient - and that product is
    rounded half up to whole cents."

    "Both methods then converge: `bcr` is `npv_benefits_cents` divided by
    `mitigation_cost_cents`, rounded half up to three decimal places."

    Design: Difficulty/dual_variant_calc/bcr_discounted_npv_vs_undiscounted_life_cycle_divergence
    """
    project = fixtures.create_draft_project(api)

    bca = _attach_analysis(api, project, TOOLKIT_INPUTS)

    assert float(bca["pv_annuity_factor"]) == 12.409041
    assert bca["npv_benefits_cents"] == 49_636_164
    assert float(bca["bcr"]) == 1.103
    assert bca["status"] == "SUBMITTED"


def test_pre_calculated_variant_performs_no_discounting_at_all(api):
    """The undiscounted variant zeroes the factor and takes an exact integer product.

    "Under `PRE_CALCULATED_BENEFIT`, no discounting occurs at all.
    `pv_annuity_factor` is stored as exactly 0.000000, `discount_rate_pct` is
    retained on the record but never read by the arithmetic, and
    `npv_benefits_cents` is `annualized_loss_avoided_cents` multiplied by
    `project_useful_life_years` as an exact integer product with no rounding
    step whatsoever."

    Design: Difficulty/dual_variant_calc/bcr_discounted_npv_vs_undiscounted_life_cycle_divergence
    """
    project = fixtures.create_draft_project(api)

    bca = _attach_analysis(api, project, PRE_CALCULATED_INPUTS)

    assert float(bca["pv_annuity_factor"]) == 0.0
    assert bca["npv_benefits_cents"] == 120_000_000
    assert float(bca["bcr"]) == 2.667
    assert float(bca["discount_rate_pct"]) == 0.07
    assert bca["status"] == "SUBMITTED"


def test_the_two_analysis_methods_diverge_by_the_whole_discounting_effect(api):
    """Identical stored inputs give two different benefit streams, not a rounding cent.

    "The analysis computes `pv_annuity_factor`, `npv_benefits_cents` and `bcr` at
    creation, and **the arithmetic differs materially between the two methods -
    this is not one formula with a switch, it is two formulas.**"

    Design: Difficulty/dual_variant_calc/bcr_discounted_npv_vs_undiscounted_life_cycle_divergence
    """
    discounted_project = fixtures.create_draft_project(api)
    undiscounted_project = fixtures.create_draft_project(api)

    discounted = _attach_analysis(api, discounted_project, TOOLKIT_INPUTS)
    undiscounted = _attach_analysis(api, undiscounted_project, PRE_CALCULATED_INPUTS)

    assert (
        undiscounted["npv_benefits_cents"] - discounted["npv_benefits_cents"]
        == 70_363_836
    )
    assert float(discounted["bcr"]) == 1.103
    assert float(undiscounted["bcr"]) == 2.667


# ─── Replacement housing payment: two replacement-cost legs ───────────────────

RHP_INPUTS = {
    "comparable_dwelling_price_cents": 22_000_000,
    "actual_purchase_price_cents": 24_000_000,
    "moving_expense_cents": 175_000,
    "rental_assistance_start_date": "2026-09-01",
    "displacee_type": "OWNER_OCCUPANT",
}


def _determined_case(api, parcel_id, household_reference, rhp_method):
    case = fixtures.open_relocation_case(
        api,
        parcel_id,
        household_reference=household_reference,
        rhp_method=rhp_method,
        **RHP_INPUTS,
    )
    return validate_success(
        api.determine_relocation_eligibility(
            case["id"], TEST_USERS["relocation_specialist_headers"]
        )
    )


def test_comparable_dwelling_variant_reads_only_the_comparable_dwelling_price(api):
    """The comparable-dwelling leg gaps the comparable price against the acquisition price.

    "Under `COMPARABLE_DWELLING`, the gross gap is
    `comparable_dwelling_price_cents` minus `acquisition_price_cents`."

    "Determination snapshots `acquisition_price_cents` from that accepted offer's
    `net_offer_cents`, computes `rental_assistance_months`,
    `rental_assistance_end_date`, `replacement_housing_payment_cents`,
    `rental_assistance_cents` and `total_relocation_benefit_cents`, moves
    `status` to `ELIGIBILITY_DETERMINED`, and advances the case's `version` by
    1."

    "Tenth, `total_relocation_benefit_cents` is
    `replacement_housing_payment_cents` plus `rental_assistance_cents` plus
    `moving_expense_cents`."

    Design: Difficulty/dual_variant_calc/replacement_housing_comparable_dwelling_vs_actual_replacement_divergence
    """
    state = fixtures.parcel_with_accepted_offer(api)
    assert state["offer"]["net_offer_cents"] == 21_400_000

    case = _determined_case(api, state["parcel"]["id"], "HH-A", "COMPARABLE_DWELLING")

    assert case["acquisition_price_cents"] == 21_400_000
    assert case["replacement_housing_payment_cents"] == 600_000
    assert case["rental_assistance_months"] == 0
    assert case["rental_assistance_cents"] == 0
    assert case["total_relocation_benefit_cents"] == 775_000
    assert case["status"] == "ELIGIBILITY_DETERMINED"


def test_actual_replacement_variant_reads_only_the_actual_purchase_price(api):
    """The actual-replacement leg ignores the comparable price entirely.

    "Under `ACTUAL_REPLACEMENT`, the gross gap is `actual_purchase_price_cents`
    minus `acquisition_price_cents`; `comparable_dwelling_price_cents` remains
    stored on the record but is never read by this variant."

    "`replacement_housing_payment_cents` is then, for a `displacee_type` of
    `OWNER_OCCUPANT`, the lesser of the eligible gap and 3,150,000 cents; and
    for a `displacee_type` of `TENANT_90_DAY`, `TENANT_UNDER_90_DAY` or
    `BUSINESS`, exactly 0."

    Design: Difficulty/dual_variant_calc/replacement_housing_comparable_dwelling_vs_actual_replacement_divergence
    """
    state = fixtures.parcel_with_accepted_offer(api)

    case = _determined_case(api, state["parcel"]["id"], "HH-B", "ACTUAL_REPLACEMENT")

    assert case["acquisition_price_cents"] == 21_400_000
    assert case["comparable_dwelling_price_cents"] == 22_000_000
    assert case["replacement_housing_payment_cents"] == 2_600_000
    assert case["total_relocation_benefit_cents"] == 2_775_000
    assert case["status"] == "ELIGIBILITY_DETERMINED"


def test_the_two_rhp_methods_diverge_on_identical_stored_data(api):
    """Two cases on one parcel differing only in rhp_method land two million apart.

    "The variants can diverge substantially on identical stored data: an
    `acquisition_price_cents` of 19,794,998 against a
    `comparable_dwelling_price_cents` of 22,000,000 and an
    `actual_purchase_price_cents` of 20,500,000, for an `OWNER_OCCUPANT`, yields
    2,205,002 under `COMPARABLE_DWELLING` and only 705,002 under
    `ACTUAL_REPLACEMENT`."

    Design: Difficulty/dual_variant_calc/replacement_housing_comparable_dwelling_vs_actual_replacement_divergence
    """
    state = fixtures.parcel_with_accepted_offer(api)
    parcel_id = state["parcel"]["id"]

    comparable = _determined_case(api, parcel_id, "HH-A", "COMPARABLE_DWELLING")
    actual = _determined_case(api, parcel_id, "HH-B", "ACTUAL_REPLACEMENT")

    assert comparable["acquisition_price_cents"] == actual["acquisition_price_cents"]
    assert (
        actual["replacement_housing_payment_cents"]
        - comparable["replacement_housing_payment_cents"]
        == 2_000_000
    )
