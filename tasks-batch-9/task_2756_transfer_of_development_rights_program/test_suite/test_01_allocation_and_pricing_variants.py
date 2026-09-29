"""Allocation, equity-reporting, bonus-sizing and market-pricing formulas.

Each test drives the program's own endpoints from an empty registry and pins the
figures the PRD fixes for the two ordinance allocation formulas, the two program
evaluation equity variants, the nested receiving-side bonus sizing, the bank
channel per-unit rounding order, and the settlement money split.
"""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    REVIEWER_USER_ID,
    TEST_USERS,
    api_client,
    approve_application,
    assert_certificate,
    assert_market_transaction,
    assert_program_evaluation,
    assert_receiving_site_application,
    assert_sending_parcel,
    certify_application,
    compute_evaluation,
    create_active_receiving_area,
    create_active_sending_area,
    create_market_transaction_payload,
    create_receiving_site_application_payload,
    credit_party,
    enroll_parcel,
    fetch_certificate,
    fetch_easement,
    fetch_parcel,
    fetch_party,
    fetch_transaction,
    make_developer_headers,
    propose_transaction,
    publish_appraisal_schedule,
    register_bank,
    register_developer,
    register_landowner,
    set_clock,
    validate_success,
)

CLOCK = "2026-08-10T00:00:00Z"

# The parcel geometry both ordinance formulas are fed: 100.00 gross acres of
# which 22.00 are constrained, PRIME soil, two existing dwelling units.
SHARED_GEOMETRY = {
    "gross_acres": 100.00,
    "constrained_acres": 22.00,
    "soil_class": "PRIME",
    "existing_dwelling_units": 2,
}


def _enroll_identical_parcel_under_each_formula():
    """One landowner, two ACTIVE sending areas differing only in their adopted
    allocation formula, and one byte-identical parcel enrolled in each."""
    set_clock(CLOCK)
    owner = register_landowner(neighborhood_code="NB-EAST")
    ordinance = {
        "neighborhood_code": "NB-EAST",
        "base_rate_units_per_acre": 0.25,
        "gross_discount_factor": 0.80,
        "equity_tier": "UNDERSERVED",
        "sending_cap_units": 200,
    }
    area_v1 = create_active_sending_area(
        name="East Ridge V1", allocation_formula_version="V1_NET_ACRE", **ordinance
    )
    area_v2 = create_active_sending_area(
        name="East Ridge V2", allocation_formula_version="V2_GROSS_DISCOUNTED", **ordinance
    )
    parcel_v1 = enroll_parcel(owner["id"], area_v1["id"], **SHARED_GEOMETRY)
    parcel_v2 = enroll_parcel(owner["id"], area_v2["id"], **SHARED_GEOMETRY)
    return {
        "owner": owner,
        "area_v1": area_v1,
        "area_v2": area_v2,
        "parcel_v1": fetch_parcel(parcel_v1["id"]),
        "parcel_v2": fetch_parcel(parcel_v2["id"]),
    }


class TestParcelBaselineAllocationFormulaVariants:
    """The two statutory allocation formulas on identical parcel geometry."""

    def test_v1_net_acre_nets_out_constrained_acres(self):
        """A V1_NET_ACRE ordinance endows the parcel with 22 units.

        "Under `V1_NET_ACRE`, eligible acreage is `gross_acres` minus
        `constrained_acres`, and `gross_discount_factor` is ignored entirely."
        "Third, a raw figure is formed as the eligible acreage multiplied by the
        area's `base_rate_units_per_acre` multiplied by the soil multiplier.
        Fourth, that raw figure is floored to a whole number — truncated
        downward, never rounded — the parcel's `existing_dwelling_units` are
        subtracted from the floored value because each already-built dwelling
        consumes one allocated right, and the result is taken as zero if the
        subtraction would go negative."
        "`PRIME` yields a multiplier of 1.25, `STATEWIDE` yields 1.10, `LOCAL`
        yields 1.00, and `NONE` yields 0.75."

        Design: Difficulty/dual_variant_calc/parcel_allocation_v1_net_acre_vs_v2_gross_discounted
        """
        scenario = _enroll_identical_parcel_under_each_formula()
        parcel = scenario["parcel_v1"]
        assert_sending_parcel(parcel)
        assert parcel["baseline_allocation_units"] == 22, (
            "V1_NET_ACRE nets 22.00 constrained acres out of 100.00 gross, so "
            "(100.00 - 22.00) x 0.25 x 1.25 = 24.375 floors to 24 and two "
            f"dwellings leave 22: got {parcel['baseline_allocation_units']}"
        )

    def test_v2_gross_discounted_ignores_constrained_acres(self):
        """A V2_GROSS_DISCOUNTED ordinance endows the same parcel with 23 units.

        "Under `V2_GROSS_DISCOUNTED`, eligible acreage is `gross_acres`
        multiplied by the area's `gross_discount_factor`, and
        `constrained_acres` is ignored entirely."
        "Third, a raw figure is formed as the eligible acreage multiplied by the
        area's `base_rate_units_per_acre` multiplied by the soil multiplier.
        Fourth, that raw figure is floored to a whole number — truncated
        downward, never rounded — the parcel's `existing_dwelling_units` are
        subtracted from the floored value because each already-built dwelling
        consumes one allocated right, and the result is taken as zero if the
        subtraction would go negative."
        "`PRIME` yields a multiplier of 1.25, `STATEWIDE` yields 1.10, `LOCAL`
        yields 1.00, and `NONE` yields 0.75."

        Design: Difficulty/dual_variant_calc/parcel_allocation_v1_net_acre_vs_v2_gross_discounted
        """
        scenario = _enroll_identical_parcel_under_each_formula()
        parcel = scenario["parcel_v2"]
        assert_sending_parcel(parcel)
        assert parcel["baseline_allocation_units"] == 23, (
            "V2_GROSS_DISCOUNTED discounts gross acreage instead, so "
            "100.00 x 0.80 x 0.25 x 1.25 = 25.0 floors to 25 and two dwellings "
            f"leave 23: got {parcel['baseline_allocation_units']}"
        )

    def test_v2_awards_one_more_unit_than_v1_on_identical_inputs(self):
        """The two ordinances disagree by exactly one unit, and both parcels open
        their ledgers unsevered.

        "A consequence worth stating plainly: a parcel whose constrained fraction
        is larger than one minus the discount factor receives *more* rights under
        `V2_GROSS_DISCOUNTED` than under `V1_NET_ACRE`, on identical inputs."
        "On enrollment the derived ledger fields open at their starting values:
        `remaining_units` equals `baseline_allocation_units`, `severed_units` is
        0, `restricted_acres` is 0, `easement_status` is `NONE`, and
        `parcel_status` is `UNSEVERED`."

        Design: Difficulty/dual_variant_calc/parcel_allocation_v1_net_acre_vs_v2_gross_discounted
        """
        scenario = _enroll_identical_parcel_under_each_formula()
        v1, v2 = scenario["parcel_v1"], scenario["parcel_v2"]
        assert v2["baseline_allocation_units"] - v1["baseline_allocation_units"] == 1, (
            "the discounted-gross ordinance must award exactly one more unit on "
            f"identical geometry: {v2['baseline_allocation_units']} vs "
            f"{v1['baseline_allocation_units']}"
        )
        assert v1["remaining_units"] == 22, v1["remaining_units"]
        assert v2["remaining_units"] == 23, v2["remaining_units"]
        for label, parcel in (("V1_NET_ACRE", v1), ("V2_GROSS_DISCOUNTED", v2)):
            assert parcel["severed_units"] == 0, (
                f"{label} parcel opens with no severed units: {parcel['severed_units']}"
            )
            assert parcel["parcel_status"] == "UNSEVERED", (
                f"{label} parcel opens UNSEVERED: {parcel['parcel_status']}"
            )


def _two_preserved_easements_one_underserved():
    """One landowner, an UNDERSERVED area holding a 100-acre parcel and a
    HIGH_VALUE area holding a 20-acre parcel, both parcels fully severed and
    certified on 2026-08-10."""
    set_clock(CLOCK)
    owner = register_landowner(neighborhood_code="NB-EAST")
    east = create_active_sending_area(
        name="East Ridge", neighborhood_code="NB-EAST",
        allocation_formula_version="V1_NET_ACRE", base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80, equity_tier="UNDERSERVED", sending_cap_units=200,
    )
    west = create_active_sending_area(
        name="West Bench", neighborhood_code="NB-WEST",
        allocation_formula_version="V1_NET_ACRE", base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80, equity_tier="HIGH_VALUE", sending_cap_units=200,
    )
    parcel_e = enroll_parcel(owner["id"], east["id"], **SHARED_GEOMETRY)
    parcel_w = enroll_parcel(
        owner["id"], west["id"], gross_acres=20.00, constrained_acres=0.00,
        soil_class="LOCAL", existing_dwelling_units=0,
    )
    app_e = approve_application(parcel_e["id"], owner["id"], 22, REVIEWER_USER_ID)
    cert_e = certify_application(app_e["id"], ADMIN_USER_ID)
    app_w = approve_application(parcel_w["id"], owner["id"], 5, REVIEWER_USER_ID)
    cert_w = certify_application(app_w["id"], ADMIN_USER_ID)
    return {
        "owner": owner,
        "certificate_east": cert_e,
        "certificate_west": cert_w,
        "easement_east": fetch_easement(cert_e["conservation_easement_id"]),
        "easement_west": fetch_easement(cert_w["conservation_easement_id"]),
    }


class TestProgramEvaluationEquityIndexVariants:
    """The same two recorded easements under the two equity-weighting variants."""

    def test_acreage_weighted_equity_index_uses_the_underserved_acre_share(self):
        """Weighting by preserved acreage puts the index at 83.33.

        "`equity_index` measures how much of the period's preservation came from
        underserved neighborhoods, and it is computed in one of two variants over
        the same easement set, where an easement counts as underserved when its
        parcel's sending area has an `equity_tier` of `UNDERSERVED`. Under
        `ACREAGE_WEIGHTED` the index is the underserved share of
        `preserved_acres`; under `PARCEL_COUNT_WEIGHTED` it is the underserved
        share of `easement_count`. Both are percentages rounded half up to two
        decimal places, and both report 0.00 when their denominator is zero."

        Design: Difficulty/dual_variant_calc/equity_index_acreage_weighted_vs_parcel_count_weighted
        """
        scenario = _two_preserved_easements_one_underserved()
        assert scenario["easement_east"]["restricted_acres"] == pytest.approx(100.00, abs=0.01), (
            "the fully severed 100-acre UNDERSERVED parcel encumbers all of its "
            f"acreage: {scenario['easement_east']['restricted_acres']}"
        )
        assert scenario["easement_west"]["restricted_acres"] == pytest.approx(20.00, abs=0.01), (
            "the fully severed 20-acre HIGH_VALUE parcel encumbers all of its "
            f"acreage: {scenario['easement_west']['restricted_acres']}"
        )
        evaluation = compute_evaluation("2026-08-01", "2026-08-31", "ACREAGE_WEIGHTED")
        assert_program_evaluation(evaluation)
        assert evaluation["equity_index"] == pytest.approx(83.33, abs=0.01), (
            "100.00 underserved acres of 120.00 preserved acres is 83.33 percent: "
            f"got {evaluation['equity_index']}"
        )

    def test_parcel_count_weighted_equity_index_uses_the_underserved_easement_share(self):
        """Weighting by easement count puts the same data at 50.00.

        "`equity_index` measures how much of the period's preservation came from
        underserved neighborhoods, and it is computed in one of two variants over
        the same easement set, where an easement counts as underserved when its
        parcel's sending area has an `equity_tier` of `UNDERSERVED`. Under
        `ACREAGE_WEIGHTED` the index is the underserved share of
        `preserved_acres`; under `PARCEL_COUNT_WEIGHTED` it is the underserved
        share of `easement_count`. Both are percentages rounded half up to two
        decimal places, and both report 0.00 when their denominator is zero."
        "The two variants deliberately disagree on identical data: one large
        underserved easement dominates an acreage-weighted index, while a small
        underserved easement carries exactly the same weight as a large one under
        count weighting."

        Design: Difficulty/dual_variant_calc/equity_index_acreage_weighted_vs_parcel_count_weighted
        """
        _two_preserved_easements_one_underserved()
        evaluation = compute_evaluation("2026-08-01", "2026-08-31", "PARCEL_COUNT_WEIGHTED")
        assert_program_evaluation(evaluation)
        assert evaluation["equity_index"] == pytest.approx(50.00, abs=0.01), (
            "one underserved easement of two counted easements is 50.00 percent: "
            f"got {evaluation['equity_index']}"
        )

    def test_both_variants_report_the_same_preservation_and_unit_metrics(self):
        """Only `equity_index` differs; the shared metrics and the exact-period
        supersession are identical across the two variants.

        "`preserved_acres` sums `restricted_acres` over easements whose
        `recording_status` is `RECORDED` or `AMENDED` and whose `recorded_at`
        date falls in the window; easements still `PENDING_RECORDING` are
        excluded entirely. `easement_count` counts those same easements.
        `issued_units` sums `units_face` over certificates whose `issued_at`
        date falls in the window, and `retired_units` sums `units_retired` over
        that same certificate set — note that both are scoped by issuance date,
        so a retirement is attributed to the period in which the certificate was
        issued, not the period in which it was retired. `redeemed_units` sums
        `units` over redemptions that are `CONFIRMED` and whose `confirmed_at`
        date falls in the window. `outstanding_units` is `issued_units` less
        `redeemed_units` less `retired_units`. `absorption_pct` is the sum of
        `absorbed_units` divided by the sum of `absorption_cap_units` across
        every receiving area whose `status` is `ACTIVE` or `SUSPENDED`, as a
        percentage rounded half up to two decimal places, and reports 0.00 rather
        than erroring when the denominator is zero; `DRAFT` areas never enter
        that denominator, and the figure is a program-wide snapshot rather than a
        window-scoped one."
        "Overlap with existing evaluations is constrained in a specific way: no
        other `COMPUTED` evaluation may partially overlap the requested window,
        and a partial overlap is rejected with `ERR_EVALUATION_PERIOD_OVERLAP` —
        but an exact-match period is allowed, and computing it moves the earlier
        evaluation to `SUPERSEDED`, which is how the program restates a period
        after corrections."

        Design: Difficulty/dual_variant_calc/equity_index_acreage_weighted_vs_parcel_count_weighted
        """
        _two_preserved_easements_one_underserved()
        acreage = compute_evaluation("2026-08-01", "2026-08-31", "ACREAGE_WEIGHTED")
        count = compute_evaluation("2026-08-01", "2026-08-31", "PARCEL_COUNT_WEIGHTED")

        for label, evaluation in (("ACREAGE_WEIGHTED", acreage), ("PARCEL_COUNT_WEIGHTED", count)):
            assert evaluation["preserved_acres"] == pytest.approx(120.00, abs=0.01), (
                f"{label}: 100.00 + 20.00 preserved acres, got "
                f"{evaluation['preserved_acres']}"
            )
            assert evaluation["easement_count"] == 2, (
                f"{label}: two recorded easements, got {evaluation['easement_count']}"
            )
        assert count["issued_units"] == 27, (
            f"22 + 5 units of face value were issued in the window: {count['issued_units']}"
        )
        assert count["redeemed_units"] == 0, count["redeemed_units"]
        assert count["retired_units"] == 0, count["retired_units"]
        assert count["outstanding_units"] == 27, (
            "27 issued less nothing redeemed less nothing retired: "
            f"{count['outstanding_units']}"
        )
        assert count["absorption_pct"] == pytest.approx(0.00, abs=0.01), (
            "no receiving area exists, so the absorption denominator is zero and "
            f"the figure is reported as 0.00: got {count['absorption_pct']}"
        )
        restated = validate_success(
            api_client.get_evaluation(acreage["id"], TEST_USERS["admin_headers"])
        )
        assert restated["status"] == "SUPERSEDED", (
            "recomputing the identical period supersedes the earlier evaluation: "
            f"got {restated['status']}"
        )
        assert count["status"] == "COMPUTED", (
            f"the restating evaluation stays COMPUTED: got {count['status']}"
        )


def _developer_and_core_receiving_area():
    """One developer and one ACTIVE receiving area at 4.00 units/acre of
    as-of-right density with a 0.35 bonus ceiling."""
    set_clock(CLOCK)
    developer = register_developer(neighborhood_code="NB-CORE")
    receiving_area = create_active_receiving_area(
        name="Core Receiving Area", neighborhood_code="NB-CORE",
        base_density_units_per_acre=4.00, max_bonus_pct=0.35,
        absorption_cap_units=500, design_review_required=False,
        eligible_sending_area_codes=[],
    )
    return developer, receiving_area


def _file_site(developer, receiving_area, site_acres, requested_bonus_units):
    """File one receiving-site application and return the created record."""
    return validate_success(
        api_client.create_receiving_site_application(
            create_receiving_site_application_payload(
                developer["id"], receiving_area["id"], site_acres, requested_bonus_units
            ),
            make_developer_headers(developer["id"]),
        ),
        201,
    )


class TestReceivingBonusSizingCombinesTierFactorAndDensity:
    """Bonus sizing over site_acres, base density, the bonus ceiling, the size-band
    tier factor and the requested units, with two separate floors."""

    def test_large_site_takes_the_full_tier_factor(self):
        """A 12.00-acre site takes the 1.00 tier factor and sizes to 16 units.

        "First a site tier factor is chosen from `site_acres`: a site of at least
        10.00 acres takes 1.00, a site of at least 3.00 but under 10.00 acres
        takes 0.90, and anything smaller takes 0.75. The boundaries are inclusive
        on their lower edge, so exactly 10.00 acres takes the full factor and
        exactly 3.00 acres takes 0.90. Second, `base_units` is `site_acres`
        multiplied by the area's `base_density_units_per_acre`, floored to a whole
        number. Third, `max_bonus_units` is the already-floored `base_units`
        multiplied by the area's `max_bonus_pct` and then by the tier factor,
        floored again. The two floors are applied at exactly those two points;
        collapsing them into a single floor over the whole product yields a
        different and incorrect number. `required_backing_units` is then the
        lesser of `requested_bonus_units` and `max_bonus_units` — a developer who
        asks for more density than the area can grant is not rejected at intake,
        but is only ever required to back, and can only ever receive, the area's
        maximum."
        "The provisional variant, used at intake and again on every design
        resubmission, writes `provisional_bonus_units` as the lesser of
        `requested_bonus_units` and half of `max_bonus_units` floored — a release
        fraction of one half."

        Design: Difficulty/combinatorial_formula/receiving_bonus_nested_min_over_site_tier_and_density_mode_a
        """
        developer, receiving_area = _developer_and_core_receiving_area()
        rsa = _file_site(developer, receiving_area, 12.00, 20)
        assert_receiving_site_application(rsa)
        assert rsa["base_units"] == 48, (
            f"12.00 acres x 4.00 units/acre floors to 48: got {rsa['base_units']}"
        )
        assert rsa["max_bonus_units"] == 16, (
            "48 x 0.35 x the 1.00 large-site factor is 16.8, which floors to 16: "
            f"got {rsa['max_bonus_units']}"
        )
        assert rsa["required_backing_units"] == 16, (
            "the lesser of the 20 units requested and the area's maximum of 16: "
            f"got {rsa['required_backing_units']}"
        )
        assert rsa["provisional_bonus_units"] == 8, (
            "the lesser of 20 requested and half of 16 floored, which is 8: "
            f"got {rsa['provisional_bonus_units']}"
        )

    def test_small_site_takes_the_reduced_tier_factor(self):
        """A 2.50-acre site in the same area takes the 0.75 factor and sizes to 2.

        "First a site tier factor is chosen from `site_acres`: a site of at least
        10.00 acres takes 1.00, a site of at least 3.00 but under 10.00 acres
        takes 0.90, and anything smaller takes 0.75. The boundaries are inclusive
        on their lower edge, so exactly 10.00 acres takes the full factor and
        exactly 3.00 acres takes 0.90. Second, `base_units` is `site_acres`
        multiplied by the area's `base_density_units_per_acre`, floored to a whole
        number. Third, `max_bonus_units` is the already-floored `base_units`
        multiplied by the area's `max_bonus_pct` and then by the tier factor,
        floored again. The two floors are applied at exactly those two points;
        collapsing them into a single floor over the whole product yields a
        different and incorrect number. `required_backing_units` is then the
        lesser of `requested_bonus_units` and `max_bonus_units` — a developer who
        asks for more density than the area can grant is not rejected at intake,
        but is only ever required to back, and can only ever receive, the area's
        maximum."
        "The provisional variant, used at intake and again on every design
        resubmission, writes `provisional_bonus_units` as the lesser of
        `requested_bonus_units` and half of `max_bonus_units` floored — a release
        fraction of one half."

        Design: Difficulty/combinatorial_formula/receiving_bonus_nested_min_over_site_tier_and_density_mode_a
        """
        developer, receiving_area = _developer_and_core_receiving_area()
        rsa = _file_site(developer, receiving_area, 2.50, 20)
        assert_receiving_site_application(rsa)
        assert rsa["base_units"] == 10, (
            f"2.50 acres x 4.00 units/acre floors to 10: got {rsa['base_units']}"
        )
        assert rsa["max_bonus_units"] == 2, (
            "10 x 0.35 x the 0.75 small-site factor is 2.625, which floors to 2: "
            f"got {rsa['max_bonus_units']}"
        )
        assert rsa["required_backing_units"] == 2, (
            f"the lesser of 20 requested and the maximum of 2: got {rsa['required_backing_units']}"
        )
        assert rsa["provisional_bonus_units"] == 1, (
            "the lesser of 20 requested and half of 2 floored, which is 1: "
            f"got {rsa['provisional_bonus_units']}"
        )

    def test_two_sites_in_one_area_size_differently_and_both_skip_the_board(self):
        """The same area's two sites land on different maxima, and neither has an
        allocated bonus at intake.

        "Third, `max_bonus_units` is the already-floored `base_units` multiplied
        by the area's `max_bonus_pct` and then by the tier factor, floored again."
        "When the flag is false, it starts `SUBMITTED → DESIGN_APPROVED` and skips
        the board entirely, with `design_review_round` left at 0 and
        `design_reviewed_by_user_id` left unset. Either way the provisional sizing
        has already run, and `backed_units`, `pending_backed_units`, and
        `allocated_bonus_units` all start at 0."

        Design: Difficulty/combinatorial_formula/receiving_bonus_nested_min_over_site_tier_and_density_mode_a
        """
        developer, receiving_area = _developer_and_core_receiving_area()
        big = _file_site(developer, receiving_area, 12.00, 20)
        small = _file_site(developer, receiving_area, 2.50, 20)
        assert big["max_bonus_units"] == 16 and small["max_bonus_units"] == 2, (
            "two sites in the same receiving area fall in different size bands: "
            f"{big['max_bonus_units']} and {small['max_bonus_units']}"
        )
        for label, rsa in (("large site", big), ("small site", small)):
            assert rsa["status"] == "DESIGN_APPROVED", (
                f"{label}: an area that does not require design review admits the "
                f"filing straight to DESIGN_APPROVED, got {rsa['status']}"
            )
            assert rsa["allocated_bonus_units"] == 0, (
                f"{label}: allocated_bonus_units starts at 0, got "
                f"{rsa['allocated_bonus_units']}"
            )


def _certified_certificate_priced_by_schedule(neighborhood_code, equity_tier, area_name):
    """A landowner holding a certified 22-unit certificate whose origin
    neighborhood carries an ACTIVE appraisal schedule of 1234567 cents per unit
    with a +250 basis point equity adjustment."""
    set_clock(CLOCK)
    owner = register_landowner(neighborhood_code=neighborhood_code)
    area = create_active_sending_area(
        name=area_name, neighborhood_code=neighborhood_code,
        allocation_formula_version="V1_NET_ACRE", base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80, equity_tier=equity_tier, sending_cap_units=200,
    )
    schedule = publish_appraisal_schedule(
        neighborhood_code=neighborhood_code, per_unit_value_cents=1_234_567,
        equity_adjustment_bps=250, effective_from="2026-01-01", effective_to="2027-01-01",
    )
    parcel = enroll_parcel(owner["id"], area["id"], **SHARED_GEOMETRY)
    application = approve_application(parcel["id"], owner["id"], 22, REVIEWER_USER_ID)
    certificate = certify_application(application["id"], ADMIN_USER_ID)
    return {
        "owner": owner,
        "area": area,
        "schedule": schedule,
        "parcel": parcel,
        "certificate": certificate,
    }


class TestBankPurchasePricingRoundsPerUnitBeforeMultiplying:
    """The administered bank purchase price on a 22-unit certificate."""

    def test_bank_purchase_rounds_the_per_unit_price_then_multiplies(self):
        """Per-unit rounding first yields 27004296 cents, not 27004298.

        "`applied_per_unit_value_cents` is the selected schedule's
        `per_unit_value_cents` multiplied by one plus its `equity_adjustment_bps`
        divided by ten thousand, rounded half up to a whole number of cents — the
        rounding happens on the per-unit figure, before any multiplication by
        units. `appraised_reference_cents` is then `applied_per_unit_value_cents`
        multiplied by `units`."
        "For `BANK_PURCHASE`, a per-unit price is formed by discounting the
        equity-adjusted per-unit value by 300 basis points — multiplying it by one
        minus three hundred divided by ten thousand — and rounding half up to
        whole cents; `gross_price_cents` is again that per-unit price multiplied by
        `units`. The order matters and is not negotiable: round to whole cents
        **per unit first**, then multiply by the unit count. Multiplying first and
        rounding the total once produces a different figure and is wrong."

        Design: Difficulty/combinatorial_formula/bank_purchase_price_rounds_per_unit_before_multiplying_mode_b
        """
        scenario = _certified_certificate_priced_by_schedule("NB-EAST", "UNDERSERVED", "East Ridge")
        bank = register_bank(neighborhood_code="NB-CORE")
        transaction = validate_success(
            api_client.create_market_transaction(
                create_market_transaction_payload(
                    scenario["certificate"]["id"], scenario["owner"]["id"], bank["id"],
                    units=22, channel="BANK_PURCHASE", conveyance_mode="WHOLE",
                ),
                TEST_USERS["admin_headers"],
            ),
            201,
        )
        assert_market_transaction(transaction)
        assert transaction["applied_per_unit_value_cents"] == 1_265_431, (
            "1234567 cents at +250 bps is 1265431.175, rounded half up to 1265431: "
            f"got {transaction['applied_per_unit_value_cents']}"
        )
        assert transaction["appraised_reference_cents"] == 27_839_482, (
            "1265431 cents per unit across 22 units: got "
            f"{transaction['appraised_reference_cents']}"
        )
        assert transaction["gross_price_cents"] == 27_004_296, (
            "1265431 discounted 300 bps is 1227468.07 -> 1227468 per unit, times "
            f"22 units: got {transaction['gross_price_cents']}"
        )
        assert transaction["gross_price_cents"] != 27_004_298, (
            "27004298 is the figure produced by multiplying by units first and "
            "rounding the total once, which the per-unit-first order forbids"
        )

    def test_bank_purchase_proposal_records_deviation_and_encumbers_the_certificate(self):
        """The proposal reports a signed deviation, names the rights' own
        neighborhood, and leaves the money split at zero until settlement.

        "`price_deviation_bps` is the difference between `gross_price_cents` and
        `appraised_reference_cents`, divided by `appraised_reference_cents`,
        multiplied by ten thousand, and rounded half up to a whole number of basis
        points; it is signed, so a below-appraisal deal reports a negative figure."
        "`applied_neighborhood_code` records the certificate's
        `origin_neighborhood_code`."
        "An accepted proposal opens in `status` `PROPOSED`, moves the certificate
        `HELD → UNDER_CONTRACT`, grows the certificate's `units_encumbered` by the
        traded `units`, and increments the certificate's `version`.
        `program_fee_cents`, `equity_surcharge_cents`, and `net_to_seller_cents`
        all stay at 0 until settlement, and `conveyed_certificate_id`,
        `settled_at`, `reversed_at`, and `reversal_reason` all stay unset."

        Design: Difficulty/combinatorial_formula/bank_purchase_price_rounds_per_unit_before_multiplying_mode_b
        """
        scenario = _certified_certificate_priced_by_schedule("NB-EAST", "UNDERSERVED", "East Ridge")
        bank = register_bank(neighborhood_code="NB-CORE")
        transaction = validate_success(
            api_client.create_market_transaction(
                create_market_transaction_payload(
                    scenario["certificate"]["id"], scenario["owner"]["id"], bank["id"],
                    units=22, channel="BANK_PURCHASE", conveyance_mode="WHOLE",
                ),
                TEST_USERS["admin_headers"],
            ),
            201,
        )
        assert transaction["price_deviation_bps"] == -300, (
            "a 300 basis point administered discount sits 300 bps below the "
            f"appraised reference: got {transaction['price_deviation_bps']}"
        )
        assert transaction["applied_neighborhood_code"] == "NB-EAST", (
            "the deal is priced off the neighborhood the rights came from: got "
            f"{transaction['applied_neighborhood_code']}"
        )
        assert transaction["status"] == "PROPOSED", transaction["status"]
        assert transaction["program_fee_cents"] == 0, (
            f"the fee stays at 0 until settlement: got {transaction['program_fee_cents']}"
        )
        assert transaction["net_to_seller_cents"] == 0, (
            "seller proceeds stay at 0 until settlement: got "
            f"{transaction['net_to_seller_cents']}"
        )
        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert_certificate(certificate)
        assert certificate["market_status"] == "UNDER_CONTRACT", certificate["market_status"]
        assert certificate["units_encumbered"] == 22, (
            "the traded units are encumbered by the proposal: got "
            f"{certificate['units_encumbered']}"
        )


def _proposed_private_sale_just_above_the_mid_fee_tier():
    """A PROPOSED PRIVATE sale of a whole 22-unit certificate from a HIGH_VALUE
    sending area at an agreed gross of 25100000 cents, one hundred thousand cents
    above the 25000000-cent fee tier boundary."""
    scenario = _certified_certificate_priced_by_schedule("NB-WEST", "HIGH_VALUE", "West Bench")
    developer = register_developer(neighborhood_code="NB-CORE")
    bank = register_bank(neighborhood_code="NB-CORE")
    credit_party(developer["id"], 30_000_000)
    transaction = propose_transaction(
        scenario["certificate"]["id"], scenario["owner"]["id"], developer["id"],
        units=22, channel="PRIVATE", agreed_price_cents=25_100_000,
    )
    scenario.update({"developer": developer, "bank": bank, "transaction": transaction})
    return scenario


class TestSettlementFeeTierKeyedOnGrossPrice:
    """The four-step money split at settlement of a 25100000-cent private sale."""

    def test_program_fee_rate_tier_is_selected_from_the_gross_price(self):
        """The gross of 25100000 cents sits in the 200 basis point tier.

        "First, a fee rate is selected by tier from `gross_price_cents` itself,
        never from any post-surcharge figure: a gross of at most 5,000,000 cents —
        fifty thousand dollars — attracts 350 basis points; a gross above that but
        at most 25,000,000 cents — two hundred fifty thousand dollars — attracts
        275 basis points; anything above that attracts 200 basis points. Tier
        boundaries are inclusive on their upper bound, so a gross of exactly
        5,000,000 cents sits in the first tier at 350 basis points while 5,000,001
        cents sits in the second at 275. Second, `program_fee_cents` is
        `gross_price_cents` multiplied by that rate divided by ten thousand,
        rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/settlement_fee_tier_keyed_on_gross_not_on_net_mode_c
        """
        scenario = _proposed_private_sale_just_above_the_mid_fee_tier()
        settled = validate_success(
            api_client.settle_market_transaction(
                scenario["transaction"]["id"], TEST_USERS["admin_headers"], {}
            )
        )
        assert_market_transaction(settled)
        assert settled["gross_price_cents"] == 25_100_000, (
            "a PRIVATE gross is the agreed price taken exactly as supplied: got "
            f"{settled['gross_price_cents']}"
        )
        assert settled["program_fee_cents"] == 502_000, (
            "25100000 cents is above the 25000000-cent boundary, so the rate is "
            f"200 bps and the fee is 502000 cents: got {settled['program_fee_cents']}"
        )
        assert settled["program_fee_cents"] != 666_091, (
            "666091 cents is the fee a 275 bps rate keyed off the resulting net of "
            "24221500 would produce, and the tier is keyed off the gross instead"
        )

    def test_equity_surcharge_and_seller_proceeds_move_cash_in_three_legs(self):
        """The HIGH_VALUE surcharge, the residual net, and the three cash legs.

        "Third, `equity_surcharge_cents` is `gross_price_cents` multiplied by a
        surcharge rate divided by ten thousand, rounded half up to whole cents,
        where the surcharge rate comes from the `equity_tier` of the sending area
        named by the certificate's `origin_sending_area_id`: 150 basis points for
        `HIGH_VALUE`, 75 basis points for `MODERATE`, and 0 basis points for
        `UNDERSERVED`, so preserving land in an underserved neighborhood carries no
        surcharge at all. Fourth, `net_to_seller_cents` is `gross_price_cents` less
        `program_fee_cents` less `equity_surcharge_cents`. Each cents figure is
        rounded independently."
        "Cash then moves in three legs that sum to zero, as §2.11 requires: the
        buyer's `cash_balance_cents` is reduced by `gross_price_cents`, the
        seller's `cash_balance_cents` is increased by `net_to_seller_cents`, and
        the `MUNICIPAL_BANK` party's `fee_revenue_cents` is increased by
        `program_fee_cents` plus `equity_surcharge_cents`."

        Design: Difficulty/combinatorial_formula/settlement_fee_tier_keyed_on_gross_not_on_net_mode_c
        """
        scenario = _proposed_private_sale_just_above_the_mid_fee_tier()
        settled = validate_success(
            api_client.settle_market_transaction(
                scenario["transaction"]["id"], TEST_USERS["admin_headers"], {}
            )
        )
        assert settled["equity_surcharge_cents"] == 376_500, (
            "a HIGH_VALUE origin area carries 150 bps of 25100000 cents: got "
            f"{settled['equity_surcharge_cents']}"
        )
        assert settled["net_to_seller_cents"] == 24_221_500, (
            "25100000 less the 502000 fee less the 376500 surcharge: got "
            f"{settled['net_to_seller_cents']}"
        )
        seller = fetch_party(scenario["owner"]["id"])
        buyer = fetch_party(scenario["developer"]["id"])
        bank = fetch_party(scenario["bank"]["id"])
        assert seller["cash_balance_cents"] == 24_221_500, (
            f"the seller receives the net: got {seller['cash_balance_cents']}"
        )
        assert buyer["cash_balance_cents"] == 4_900_000, (
            "the buyer's 30000000-cent balance is reduced by the 25100000-cent "
            f"gross: got {buyer['cash_balance_cents']}"
        )
        assert bank["fee_revenue_cents"] == 878_500, (
            "the municipal bank accrues the 502000 fee plus the 376500 surcharge: "
            f"got {bank['fee_revenue_cents']}"
        )

    def test_whole_conveyance_moves_the_traded_certificate_to_the_buyer(self):
        """Trading the whole remaining balance conveys the certificate itself.

        "When the traded `units` equal the certificate's `units_remaining`,
        `conveyance_mode` is pinned to `WHOLE`: the certificate itself changes
        hands, its `holder_party_id` becomes `buyer_party_id`, and
        `conveyed_certificate_id` is set to the traded `certificate_id`."
        "Both parties' `units_held` and `certificates_held_count` are recomputed,
        `settled_at` is set to the current logical clock, the transaction moves
        `PROPOSED → SETTLED`, and its `version` is incremented."

        Design: Difficulty/combinatorial_formula/settlement_fee_tier_keyed_on_gross_not_on_net_mode_c
        """
        scenario = _proposed_private_sale_just_above_the_mid_fee_tier()
        settled = validate_success(
            api_client.settle_market_transaction(
                scenario["transaction"]["id"], TEST_USERS["admin_headers"], {}
            )
        )
        assert settled["status"] == "SETTLED", settled["status"]
        assert settled["conveyed_certificate_id"] == scenario["certificate"]["id"], (
            "a WHOLE conveyance names the traded certificate itself: got "
            f"{settled['conveyed_certificate_id']}"
        )
        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert certificate["holder_party_id"] == scenario["developer"]["id"], (
            "the traded certificate changes hands to the buyer: got "
            f"{certificate['holder_party_id']}"
        )
        reread = fetch_transaction(scenario["transaction"]["id"])
        assert reread["conveyance_mode"] == "WHOLE", (
            f"the system pins the conveyance at settlement: got {reread['conveyance_mode']}"
        )
