"""Cost-share determinations: variant divergence and the pinned waterfall order.

The determination is a ten-step waterfall in which several steps read the output
of an earlier step rather than the raw inputs, so the order of evaluation is
observable in the money. These tests drive the two variants over one identical
set of income records, and separately pin the single legal order in which the
tier, the medical cap and the federal offset may be computed.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx


def _divergence_scenario(api):
    """A resident with three August income streams and a closed bed-hold interval.

    Of the three streams only two are verified, and the resident is away from the
    home for four days, so the provisional and the final determination see
    different income and different day counts.
    """
    scenario = fx.admitted_resident(
        api,
        admission_date="2026-08-05",
        application_date="2026-08-01",
        clock_before_decision="2026-08-05T00:00:00Z",
        care_level="NURSING",
        licensed_bed_count=2,
    )
    fx.declare_income(api, scenario.resident_id, "SSA", 180000, "2026-08", verify=True)
    fx.declare_income(
        api, scenario.resident_id, "VA_COMPENSATION", 120000, "2026-08", verify=False
    )
    fx.declare_income(
        api, scenario.resident_id, "MILITARY_RETIREMENT", 40000, "2026-08", verify=True
    )
    fx.hospitalize(api, scenario.resident_id, "2026-08-20", clock="2026-08-20T00:00:00Z")
    fx.readmit(api, scenario.resident_id, "2026-08-24", clock="2026-08-24T00:00:00Z")
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.census_run(api, "2026-08-31", scenario.home_id)
    return scenario


def test_provisional_determination_counts_unverified_income_and_prorates(api):
    """A provisional determination counts unverified income, deducts no medical expense and prorates.

    Per the PRD: "a provisional cost share counts records that are `UNVERIFIED`
    **or** `VERIFIED`, while a final cost share counts `VERIFIED` records only,
    and a `REJECTED` record is never counted by either." The unverified
    VA compensation stream therefore contributes eighty percent of its gross, and
    the day count is the pure calendar count from the admission date onwards.

    Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_divergence
    """
    scenario = _divergence_scenario(api)

    determination = validate_success(
        fx.determine_cost_share(api, scenario.resident_id, variant="PROVISIONAL"), 201
    )

    assert determination["gross_countable_income_cents"] == 316000
    assert determination["pna_deduction_cents"] == 9000
    assert determination["income_tier"] == "TIER_3"
    assert determination["allowed_medical_deduction_cents"] == 0
    assert determination["tiered_share_cents"] == 162400
    assert determination["resident_day_count"] == 27
    assert determination["federal_per_diem_offset_cents"] == 0
    assert determination["monthly_cost_share_cents"] == 141445
    assert determination["delta_from_prior_cents"] == 0


def test_final_determination_excludes_unverified_income_and_deducts_medical(api):
    """A final determination drops unverified income, caps the medical deduction and does not prorate.

    Per the PRD: "For `FINAL`, it is simply `tiered_share_cents` less
    `federal_per_diem_offset_cents`, floored at zero, with no proration at all."
    Dropping the unverified stream moves the resident down a tier, the medical
    cap for that tier bites at 15,000 cents, and the day count comes from the
    census rows rather than the calendar, so the four bed-hold days fall away.

    Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_divergence
    """
    scenario = _divergence_scenario(api)
    validate_success(
        fx.determine_cost_share(api, scenario.resident_id, variant="PROVISIONAL"), 201
    )

    final = validate_success(
        fx.determine_cost_share(
            api,
            scenario.resident_id,
            variant="FINAL",
            declared_medical_expense_cents=20000,
        ),
        201,
    )

    assert final["gross_countable_income_cents"] == 220000
    assert final["income_tier"] == "TIER_2"
    assert final["allowed_medical_deduction_cents"] == 15000
    assert final["tiered_share_cents"] == 92800
    assert final["resident_day_count"] == 23
    assert final["federal_per_diem_offset_cents"] == 13636
    assert final["monthly_cost_share_cents"] == 79164


def test_final_determination_records_its_delta_and_advances_the_billing_dimension(api):
    """The final determination records the change it introduces and moves the resident to FINAL_COST_SHARE.

    Per the PRD: "A resident whose `billing_status` is `PROVISIONAL_COST_SHARE`
    moves to `FINAL_COST_SHARE` the first time a `FINAL` determination is
    created, provided `expected_resident_version` matches, the resident is not
    `DISCHARGED`, and at least one of the resident's income records for that
    `effective_month` is `VERIFIED`". The billing dimension moves while the
    occupancy dimension stays exactly where it was.

    Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_divergence
    """
    scenario = _divergence_scenario(api)
    validate_success(
        fx.determine_cost_share(api, scenario.resident_id, variant="PROVISIONAL"), 201
    )

    final = validate_success(
        fx.determine_cost_share(
            api,
            scenario.resident_id,
            variant="FINAL",
            declared_medical_expense_cents=20000,
        ),
        201,
    )
    assert final["delta_from_prior_cents"] == -62281

    resident = fx.read_resident(api, scenario.resident_id)
    assert resident["monthly_cost_share_cents"] == 79164
    assert resident["billing_status"] == "FINAL_COST_SHARE"
    assert resident["occupancy_status"] == "ADMITTED"


def _tier_order_scenario(api):
    """A resident whose income sits five thousand cents above the first tier bound.

    A single verified stream of 114,000 cents leaves 105,000 cents after the
    personal needs allowance, so the tier selected before any medical deduction
    differs from the tier a re-tiering implementation would pick afterwards.
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    fx.declare_income(api, scenario.resident_id, "SSA", 114000, "2026-08", verify=True)
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.census_run(api, "2026-08-31", scenario.home_id)
    return scenario


def test_income_tier_is_selected_before_the_medical_deduction(api):
    """The tier comes from net income before the medical deduction, not after it.

    Per the PRD: "`income_tier` is chosen from the net figure of step 3 — that
    is, from net income **before** any medical deduction." Net before deduction
    is 105,000 cents, which is above the first tier's upper bound, so the second
    tier is selected and its 15,000-cent cap governs the deduction.

    Design: Difficulty/combinatorial_formula/cost_share_medical_cap_tier_evaluation_order_pinned
    """
    scenario = _tier_order_scenario(api)

    determination = validate_success(
        fx.determine_cost_share(
            api,
            scenario.resident_id,
            variant="FINAL",
            declared_medical_expense_cents=20000,
        ),
        201,
    )

    assert determination["gross_countable_income_cents"] == 114000
    assert determination["pna_deduction_cents"] == 9000
    assert determination["income_tier"] == "TIER_2"
    assert determination["allowed_medical_deduction_cents"] == 15000


def test_federal_offset_is_capped_against_the_post_deduction_tiered_share(api):
    """The offset cap is a share of the tiered amount the medical deduction already reduced.

    Per the PRD: "For `FINAL` it is the lesser of two separately rounded
    quantities: the federal daily per diem rate for the resident's
    `current_care_level`, multiplied by `resident_day_count`, multiplied by 500
    basis points (five percent), divided by ten thousand and rounded half up; and
    `tiered_share_cents` multiplied by 3,000 basis points (thirty percent),
    divided by ten thousand and rounded half up." The cap wins here, and the
    figure it is taken from is the reduced tiered share, so the cost share lands
    on 25,200 cents rather than on the 28,000 that a re-tiered waterfall gives.

    Design: Difficulty/combinatorial_formula/cost_share_medical_cap_tier_evaluation_order_pinned
    """
    scenario = _tier_order_scenario(api)

    determination = validate_success(
        fx.determine_cost_share(
            api,
            scenario.resident_id,
            variant="FINAL",
            declared_medical_expense_cents=20000,
        ),
        201,
    )

    assert determination["tiered_share_cents"] == 36000
    assert determination["resident_day_count"] == 31
    assert determination["federal_per_diem_offset_cents"] == 10800
    assert determination["monthly_cost_share_cents"] == 25200
    assert determination["monthly_cost_share_cents"] != 28000
