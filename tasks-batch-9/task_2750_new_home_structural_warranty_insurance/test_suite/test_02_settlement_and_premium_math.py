"""Premium rating at enrollment and the settlement waterfall on a claim.

Every test builds its own world from scratch through PRD-declared endpoints,
because each test runs against a freshly restarted server with an empty
database. All monetary values are integer numbers of cents.
"""

from test_helpers import (
    BUILDER_PERIOD_INSTANT,
    CANONICAL_PREMIUM_CENTS,
    INSURER_PERIOD_INSTANT,
    assert_claim,
    assert_policy,
    assert_structural_assessment,
    enroll_policy,
    file_structural_assessment,
    read_claim,
    setup_active_policy,
    setup_approved_builder_and_owner,
    setup_routed_claim,
    validate_paginated,
)

# An engineering report that satisfies all three conjuncts of the structural
# designation: a load-bearing element, a deflection above the threshold, and the
# engineer's own load-bearing finding.
LOAD_BEARING_REPORT = {
    "affected_elements": ["FOUNDATION_WALL"],
    "deflection_ratio": 0.0040,
    "load_bearing_affected": True,
}

TIER_BOUNDARY_REPORT = {
    "affected_elements": ["FOOTING", "FOUNDATION_WALL"],
    "deflection_ratio": 0.0051,
    "load_bearing_affected": True,
}


def _route_structural_claim(claim_instant, claimed_amount_cents, description,
                            defect_category="LOAD_BEARING_FAILURE",
                            report=None, scenario=None):
    """File, investigate at a substantiation ratio of 0.80, attach one
    designating engineering report, and route the claim.

    ``claim_instant`` alone decides the arm: 2026-09-01 sits inside the
    builder-obligation period of the canonical home, 2028-09-01 sits past it.
    """
    return setup_routed_claim(
        scenario=scenario,
        claim_instant=claim_instant,
        claimed_amount_cents=claimed_amount_cents,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category=defect_category,
        assessments=[dict(report or LOAD_BEARING_REPORT)],
        claim_overrides={"damage_description": description},
    )


# ---------------------------------------------------------------------------
# The two settlement variants: builder obligation versus insurer backing
# ---------------------------------------------------------------------------
def test_builder_arm_waives_the_deductible_and_establishes_no_reserve(api):
    """PRD 3.7: "When the `obligor` is `BUILDER`, routing advances the claim
    `UNDER_INVESTIGATION → BUILDER_OBLIGATION_NOTICE`. The settlement waterfall
    runs under the **builder-obligation variant**, writing `betterment_cents` and
    `net_payable_cents` and forcing `deductible_applied_cents` to 0 — the builder
    repairs in kind, so no policy deductible is charged to the homeowner. Both
    `reserve_cents` and `incurred_authorized_cents` remain 0, because the builder
    and not the carrier funds this arm, and **no builder loss-ratio recompute
    occurs**."
    PRD 3.7: "`deductible_applied_cents` is 0 under the builder-obligation
    variant. Under the insurer-backed variant it is the smaller of the scheduled
    deductible and `gross_adjusted_cents` — a small substantiated loss is fully
    absorbed by the deductible rather than producing a negative figure."
    PRD 3.6: "**The boundary date itself is builder-obligated** — a claim
    reported on exactly the last day of the obligation period belongs to the
    builder, and only the following day crosses over to the carrier."

    2,187,500 cents claimed at a substantiation ratio of 0.80 substantiates
    1,750,000 cents. With the deductible forced to 0 the provisional net is the
    whole substantiated figure, which selects the 8 percent betterment tier and
    settles at 1,610,000 cents.

    Design: Difficulty/dual_variant_calc/claim_net_payable_builder_arm_waives_deductible_insurer_arm_charges_it
    """
    scenario = _route_structural_claim(
        BUILDER_PERIOD_INSTANT, 2_187_500,
        "Stair-step cracking across the north foundation wall",
    )
    claim = scenario["claim"]

    assert_claim(claim)
    assert claim["obligor"] == "BUILDER", (
        f"a claim reported on 2026-09-01 falls inside the two-year builder "
        f"obligation period, got obligor {claim['obligor']}"
    )
    assert claim["status"] == "BUILDER_OBLIGATION_NOTICE", (
        f"the builder arm routes to BUILDER_OBLIGATION_NOTICE, "
        f"got {claim['status']}"
    )
    assert claim["designated_structural"] is True
    assert claim["gross_adjusted_cents"] == 1_750_000, (
        f"2,187,500 at 0.80 substantiates 1,750,000, "
        f"got {claim['gross_adjusted_cents']}"
    )
    assert claim["deductible_applied_cents"] == 0, (
        f"the builder-obligation variant forces the deductible to 0, "
        f"got {claim['deductible_applied_cents']}"
    )
    assert claim["betterment_cents"] == 140_000, (
        f"a provisional net of 1,750,000 selects 8 percent, "
        f"got {claim['betterment_cents']}"
    )
    assert claim["net_payable_cents"] == 1_610_000, (
        f"1,750,000 less 0 deductible less 140,000 betterment is 1,610,000, "
        f"got {claim['net_payable_cents']}"
    )
    assert claim["reserve_cents"] == 0, (
        f"the builder arm puts no carrier money aside, "
        f"got reserve {claim['reserve_cents']}"
    )
    assert claim["incurred_authorized_cents"] == 0, (
        f"the builder arm authorises no indemnity, "
        f"got {claim['incurred_authorized_cents']}"
    )


def test_insurer_arm_charges_the_structural_deductible_and_reserves_the_net(api):
    """PRD 3.7: "When the `obligor` is `INSURER`, the same routing operation
    advances the claim `UNDER_INVESTIGATION → INSURER_ADJUDICATION`. The
    waterfall runs under the **insurer-backed variant**, writing
    `deductible_applied_cents`, `betterment_cents` and `net_payable_cents`. The
    claim's `incurred_authorized_cents` is set to the sum of its `paid_cents`,
    its `released_cents` and its `net_payable_cents`, and its `reserve_cents` is
    set to that `net_payable_cents` — the carrier has now put money aside."
    PRD 3.7: "The deductible schedule is selected by the claim's
    `designated_structural` flag: 250,000 cents when the flag is true, and
    100,000 cents when it is false. Note that the switch is the structural
    *designation* from the engineering reports, not the claimant's own
    `defect_category` and not the term's recorded `deductible_cents`."
    PRD 3.6: "Third, and most consequential, intake assigns the `obligor`. When
    the `reported_date` is on or before the policy's
    `builder_obligation_end_date`, the `obligor` is `BUILDER`; when it falls
    after that date, the `obligor` is `INSURER`."

    The same 2,187,500 cents claimed at the same 0.80 ratio on the same
    structural term, reported after the obligation boundary, is charged the
    250,000-cent structural deductible, leaving a provisional net of 1,500,000
    that still takes 8 percent and settles at 1,380,000 — which becomes the case
    reserve.

    Design: Difficulty/dual_variant_calc/claim_net_payable_builder_arm_waives_deductible_insurer_arm_charges_it
    """
    scenario = _route_structural_claim(
        INSURER_PERIOD_INSTANT, 2_187_500,
        "Identical stair-step cracking, second report",
    )
    claim = scenario["claim"]

    assert_claim(claim)
    assert claim["obligor"] == "INSURER", (
        f"a claim reported on 2028-09-01 falls past the 2028-08-14 obligation "
        f"boundary, got obligor {claim['obligor']}"
    )
    assert claim["status"] == "INSURER_ADJUDICATION", (
        f"the insurer arm routes to INSURER_ADJUDICATION, got {claim['status']}"
    )
    assert claim["designated_structural"] is True
    assert claim["gross_adjusted_cents"] == 1_750_000
    assert claim["deductible_applied_cents"] == 250_000, (
        f"a structurally designated claim is charged 250,000, "
        f"got {claim['deductible_applied_cents']}"
    )
    assert claim["betterment_cents"] == 120_000, (
        f"a provisional net of 1,500,000 selects 8 percent, "
        f"got {claim['betterment_cents']}"
    )
    assert claim["net_payable_cents"] == 1_380_000, (
        f"1,750,000 less 250,000 less 120,000 is 1,380,000, "
        f"got {claim['net_payable_cents']}"
    )
    assert claim["reserve_cents"] == 1_380_000, (
        f"the insurer arm reserves the net payable, "
        f"got {claim['reserve_cents']}"
    )
    assert claim["incurred_authorized_cents"] == 1_380_000, (
        f"paid 0 plus released 0 plus net payable 1,380,000, "
        f"got {claim['incurred_authorized_cents']}"
    )


def test_two_arms_settle_the_same_inputs_230000_cents_apart_on_one_policy(api):
    """PRD 3.7: "Because the builder variant zeroes the deductible at step 3,
    its provisional net is larger, which means step 5 can select a **higher**
    betterment tier for the builder arm than the insurer arm would select on the
    identical claim inputs. The two variants therefore disagree on the same claim
    row purely because of which period the `reported_date` fell in — and that is
    the intended behaviour, not an inconsistency."
    PRD 3.7: "`deductible_applied_cents` is 0 under the builder-obligation
    variant. Under the insurer-backed variant it is the smaller of the scheduled
    deductible and `gross_adjusted_cents` — a small substantiated loss is fully
    absorbed by the deductible rather than producing a negative figure."
    PRD 3.7: "The two arms have **deliberately disjoint side-effect sets**, and
    understanding that disjointness is the heart of this domain."

    Two claims with byte-identical money inputs on the same home and the same
    structural term diverge by exactly the 250,000-cent structural deductible
    less the 8 percent betterment charged on it: 1,610,000 against 1,380,000.

    Design: Difficulty/dual_variant_calc/claim_net_payable_builder_arm_waives_deductible_insurer_arm_charges_it
    """
    scenario = setup_active_policy()
    builder_arm = _route_structural_claim(
        BUILDER_PERIOD_INSTANT, 2_187_500,
        "Stair-step cracking across the north foundation wall",
        scenario=scenario,
    )
    insurer_arm = _route_structural_claim(
        INSURER_PERIOD_INSTANT, 2_187_500,
        "Identical stair-step cracking, second report",
        scenario=scenario,
    )

    claim_a = builder_arm["claim"]
    claim_b = insurer_arm["claim"]

    assert claim_a["policy_id"] == claim_b["policy_id"], (
        "both claims must sit on the same enrolled home"
    )
    assert claim_a["coverage_term_id"] == claim_b["coverage_term_id"], (
        "both claims must resolve to the same structural coverage term"
    )
    assert claim_a["claimed_amount_cents"] == claim_b["claimed_amount_cents"]
    assert claim_a["gross_adjusted_cents"] == claim_b["gross_adjusted_cents"] == 1_750_000, (
        "the substantiated figures are identical, so any divergence downstream "
        "comes from the variant and not from the inputs"
    )
    assert claim_a["obligor"] == "BUILDER" and claim_b["obligor"] == "INSURER"
    assert claim_a["deductible_applied_cents"] == 0
    assert claim_b["deductible_applied_cents"] == 250_000
    assert claim_a["net_payable_cents"] == 1_610_000
    assert claim_b["net_payable_cents"] == 1_380_000
    assert claim_a["net_payable_cents"] - claim_b["net_payable_cents"] == 230_000, (
        "the two variants must disagree by exactly 230,000 cents on identical "
        f"inputs, got {claim_a['net_payable_cents'] - claim_b['net_payable_cents']}"
    )


# ---------------------------------------------------------------------------
# Premium rating: the rounding order is pinned per component
# ---------------------------------------------------------------------------
def test_premium_components_round_independently_before_they_are_summed(api):
    """PRD 2.5: "Premium arithmetic rounds **per component, not once at the
    end**: each of the three coverage components is rounded to whole cents
    independently and the three rounded integers are then added together."
    PRD 3.3: "`premium_component_workmanship_cents` is the purchase price
    multiplied by the workmanship share of 0.18, multiplied by the band's base
    rate in basis points, divided by 10,000, and rounded half up to a whole
    number of cents."
    PRD 3.3: "`premium_component_structural_cents` is computed from the
    structural share of 0.55 and then multiplied by the band's structural
    loading, with the rounding to whole cents performed exactly once, **after**
    the loading has been applied — rounding before the loading is wrong, and so
    is skipping the loading."
    PRD 3.3: "Finally, `premium_cents` is the sum of the three independently
    rounded component integers plus the surcharge, added as exact integers.
    Summing the three unrounded values and rounding once at the end is a
    different answer for some prices and is not what this program charges."

    A class-C home at 36,500,000 cents is the price where the two readings part
    company: rounding each component first gives 46,647 + 69,971 + 178,166 and a
    total of 299,284 with the flat 4,500-cent Texas surcharge, while summing the
    three exact values and rounding once at the end gives 299,283.

    Design: Difficulty/combinatorial_formula/policy_premium_per_component_rounding_order_is_pinned
    """
    scenario = setup_approved_builder_and_owner(
        homeowner_overrides={"full_name": "Bruno Calder",
                             "email": "bruno.calder@example.com"},
    )
    policy = enroll_policy(
        scenario["builder"]["id"], scenario["homeowner"]["id"],
        street_address="44 Willow Bend Dr", state_code="TX",
        purchase_price_cents=36_500_000, closing_date="2026-08-15",
    )

    assert_policy(policy)
    assert policy["risk_class_at_enrollment"] == "C", (
        f"the enrolling builder is class C, "
        f"got {policy['risk_class_at_enrollment']}"
    )
    assert policy["premium_component_workmanship_cents"] == 46_647, (
        f"36,500,000 x 0.18 x 71 / 10,000 rounds to 46,647, "
        f"got {policy['premium_component_workmanship_cents']}"
    )
    assert policy["premium_component_systems_cents"] == 69_971, (
        f"36,500,000 x 0.27 x 71 / 10,000 is 69,970.5 and rounds half up to "
        f"69,971, got {policy['premium_component_systems_cents']}"
    )
    assert policy["premium_component_structural_cents"] == 178_166, (
        f"36,500,000 x 0.55 x 71 / 10,000 x 1.25 rounds once, after the "
        f"loading, to 178,166, got "
        f"{policy['premium_component_structural_cents']}"
    )
    assert policy["state_surcharge_cents"] == 4_500, (
        f"Texas charges a flat 4,500 cents, got {policy['state_surcharge_cents']}"
    )
    assert policy["premium_cents"] == 299_284, (
        f"46,647 + 69,971 + 178,166 + 4,500 is 299,284, "
        f"got {policy['premium_cents']}"
    )
    assert policy["premium_cents"] != 299_283, (
        "299,283 is what summing the three unrounded components and rounding "
        "once at the end produces, and is not what this program charges"
    )


def test_premium_of_the_canonical_home_sums_three_rounded_components(api):
    """PRD 2.5: "Premium arithmetic rounds **per component, not once at the
    end**: each of the three coverage components is rounded to whole cents
    independently and the three rounded integers are then added together. The
    flat per-state surcharge is added last, as an exact integer, and is never
    rounded."
    PRD 3.3: "Finally, `premium_cents` is the sum of the three independently
    rounded component integers plus the surcharge, added as exact integers.
    Summing the three unrounded values and rounding once at the end is a
    different answer for some prices and is not what this program charges."

    A second price point where the two readings differ by a cent: the canonical
    class-C home at 44,500,000 cents in Texas charges 363,894 cents, and the
    stored total must equal the sum of the three stored component integers plus
    the stored surcharge exactly.

    Design: Difficulty/combinatorial_formula/policy_premium_per_component_rounding_order_is_pinned
    """
    scenario = setup_approved_builder_and_owner()
    policy = enroll_policy(
        scenario["builder"]["id"], scenario["homeowner"]["id"],
    )

    assert_policy(policy)
    assert policy["risk_class_at_enrollment"] == "C"
    assert policy["state_surcharge_cents"] == 4_500
    component_sum = (
        policy["premium_component_workmanship_cents"]
        + policy["premium_component_systems_cents"]
        + policy["premium_component_structural_cents"]
        + policy["state_surcharge_cents"]
    )
    assert component_sum == policy["premium_cents"], (
        f"the charged premium must be the exact integer sum of the three "
        f"rounded components plus the surcharge: {component_sum} != "
        f"{policy['premium_cents']}"
    )
    assert policy["premium_cents"] == CANONICAL_PREMIUM_CENTS, (
        f"a class-C home at 44,500,000 cents in TX charges "
        f"{CANONICAL_PREMIUM_CENTS}, got {policy['premium_cents']}"
    )


# ---------------------------------------------------------------------------
# The betterment tier is read from the pre-betterment provisional net
# ---------------------------------------------------------------------------
def test_betterment_tier_at_the_1500000_floor_takes_eight_percent(api):
    """PRD 3.7: "The betterment percentage is selected from that **provisional
    net, before betterment is subtracted**: nothing at all when the provisional
    net is below 500,000 cents, 5 percent when it is from 500,000 cents up to but
    not including 1,500,000 cents, and 8 percent when it is 1,500,000 cents or
    more. This is the step that looks circular and is not: the tier is chosen
    from the pre-betterment figure, and re-selecting it from the post-betterment
    figure is wrong."
    PRD 3.7: "`betterment_cents` is the provisional net multiplied by that
    percentage, rounded half up to whole cents."
    PRD 3.7: "The provisional net is `gross_adjusted_cents` less
    `deductible_applied_cents`, computed as exact integers."

    The provisional net lands exactly on the 1,500,000-cent floor, which the top
    tier owns, so 8 percent is charged and the claim settles at 1,380,000. Had
    the tier been re-selected from the post-betterment figure of 1,380,000 it
    would have dropped to 5 percent and produced 1,425,000.

    Design: Difficulty/combinatorial_formula/claim_betterment_tier_selected_before_betterment_is_subtracted
    """
    scenario = _route_structural_claim(
        INSURER_PERIOD_INSTANT, 2_187_500,
        "Foundation displacement, at the tier boundary",
        defect_category="STRUCTURAL_CRACKING", report=TIER_BOUNDARY_REPORT,
    )
    claim = scenario["claim"]

    assert_claim(claim)
    assert claim["gross_adjusted_cents"] == 1_750_000
    assert claim["deductible_applied_cents"] == 250_000
    assert claim["betterment_cents"] == 120_000, (
        f"a provisional net of exactly 1,500,000 takes 8 percent, which is "
        f"120,000, got {claim['betterment_cents']}"
    )
    assert claim["net_payable_cents"] == 1_380_000, (
        f"1,500,000 less 120,000 is 1,380,000, got {claim['net_payable_cents']}"
    )
    assert claim["net_payable_cents"] != 1_425_000, (
        "1,425,000 is the figure produced by re-selecting the tier from the "
        "post-betterment net, and is not what the pinned order yields"
    )


def test_betterment_tier_three_cents_below_the_floor_takes_five_percent(api):
    """PRD 3.7: "The betterment percentage is selected from that **provisional
    net, before betterment is subtracted**: nothing at all when the provisional
    net is below 500,000 cents, 5 percent when it is from 500,000 cents up to but
    not including 1,500,000 cents, and 8 percent when it is 1,500,000 cents or
    more. This is the step that looks circular and is not: the tier is chosen
    from the pre-betterment figure, and re-selecting it from the post-betterment
    figure is wrong."
    PRD 3.7: "`gross_adjusted_cents` is the `claimed_amount_cents` multiplied by
    the `substantiation_ratio`, rounded half up to whole cents."
    PRD 3.7: "`betterment_cents` is the provisional net multiplied by that
    percentage, rounded half up to whole cents."

    Three cents less on the claim substantiates 1,749,998, so the provisional net
    of 1,499,998 falls just short of the top tier's inclusive floor and is
    charged 5 percent instead.

    Design: Difficulty/combinatorial_formula/claim_betterment_tier_selected_before_betterment_is_subtracted
    """
    scenario = _route_structural_claim(
        INSURER_PERIOD_INSTANT, 2_187_497,
        "Foundation displacement, three cents below the tier boundary",
        defect_category="STRUCTURAL_CRACKING", report=TIER_BOUNDARY_REPORT,
    )
    claim = scenario["claim"]

    assert_claim(claim)
    assert claim["gross_adjusted_cents"] == 1_749_998, (
        f"2,187,497 at 0.80 is 1,749,997.6 and rounds half up to 1,749,998, "
        f"got {claim['gross_adjusted_cents']}"
    )
    assert claim["deductible_applied_cents"] == 250_000
    assert claim["betterment_cents"] == 75_000, (
        f"a provisional net of 1,499,998 takes 5 percent, which rounds half up "
        f"to 75,000, got {claim['betterment_cents']}"
    )
    assert claim["net_payable_cents"] == 1_424_998, (
        f"1,499,998 less 75,000 is 1,424,998, got {claim['net_payable_cents']}"
    )


def test_smaller_claim_settles_higher_across_the_betterment_tier_floor(api):
    """PRD 3.7: "The betterment percentage is selected from that **provisional
    net, before betterment is subtracted**: nothing at all when the provisional
    net is below 500,000 cents, 5 percent when it is from 500,000 cents up to but
    not including 1,500,000 cents, and 8 percent when it is 1,500,000 cents or
    more. This is the step that looks circular and is not: the tier is chosen
    from the pre-betterment figure, and re-selecting it from the post-betterment
    figure is wrong."
    PRD 3.7: "The settlement waterfall itself runs in seven pinned steps, and
    the order matters more than any single number in it."

    The two claims straddle the top tier's floor by three cents of claimed
    amount, and the inversion that follows — the larger claim settling for less —
    only holds when the tier is read from the pre-betterment figure.

    Design: Difficulty/combinatorial_formula/claim_betterment_tier_selected_before_betterment_is_subtracted
    """
    scenario = setup_active_policy()
    at_floor = _route_structural_claim(
        INSURER_PERIOD_INSTANT, 2_187_500,
        "Foundation displacement, at the tier boundary",
        defect_category="STRUCTURAL_CRACKING", report=TIER_BOUNDARY_REPORT,
        scenario=scenario,
    )
    below_floor = _route_structural_claim(
        INSURER_PERIOD_INSTANT, 2_187_497,
        "Foundation displacement, three cents below the tier boundary",
        defect_category="STRUCTURAL_CRACKING", report=TIER_BOUNDARY_REPORT,
        scenario=scenario,
    )

    high = at_floor["claim"]
    low = below_floor["claim"]

    assert high["claimed_amount_cents"] > low["claimed_amount_cents"]
    assert high["betterment_cents"] == 120_000
    assert low["betterment_cents"] == 75_000
    assert high["net_payable_cents"] == 1_380_000
    assert low["net_payable_cents"] == 1_424_998
    assert low["net_payable_cents"] > high["net_payable_cents"], (
        "the smaller claim must settle higher, which only holds when the "
        f"betterment tier is read pre-betterment: {low['net_payable_cents']} "
        f"is not above {high['net_payable_cents']}"
    )


# ---------------------------------------------------------------------------
# The structural designation needs a load-bearing element, whatever the
# deflection says
# ---------------------------------------------------------------------------
def _investigated_workmanship_claim():
    """One ACTIVE home with a small cracking claim carried as far as
    investigation, with no engineering report on it yet."""
    scenario = setup_routed_claim(
        claim_instant=None,
        route=False,
        assessments=None,
        coverage_type="WORKMANSHIP",
        defect_category="STRUCTURAL_CRACKING",
        claimed_amount_cents=400_000,
        substantiation_ratio=0.80,
        claim_overrides={
            "damage_description": "Hairline cracking at the garage return wall"
        },
    )
    return scenario["claim"]


def test_empty_affected_elements_defeats_the_designation_at_severe_deflection(api):
    """PRD 3.6: "The report's own `designated_structural` verdict requires
    **all three** of the following to hold at once: `load_bearing_affected` is
    true; at least one entry in `affected_elements` is a load-bearing element,
    meaning one of `FOOTING`, `FOUNDATION_WALL`, `BEAM`, `LOAD_BEARING_WALL`,
    `ROOF_TRUSS` or `SLAB`; and the `deflection_ratio` is 0.0033 or greater, the
    threshold value itself qualifying."
    PRD 3.6: "An empty `affected_elements` array likewise fails the second
    conjunct, and therefore yields a verdict of false even when the engineer
    marked `load_bearing_affected` true and measured a severe deflection."
    PRD 3.6: "Filing a report advances the claim's `version` by 1, and an empty
    `affected_elements` array is a legitimate filing, not an error."
    PRD 3.6: "The claim carries its own `designated_structural` flag, which is
    the logical OR across every assessment ever filed on it: it is true as soon
    as any single report reaches a true verdict, and once raised it is **never
    lowered** by a subsequent report that fails the test."

    A deflection of 0.0500 is fifteen times the threshold and the engineer
    marked the structure load-bearing, so two of the three conjuncts hold with
    room to spare. The empty element list still defeats the verdict, and the
    claim's own flag stays down.

    Design: Difficulty/boundary_precision_check/empty_affected_elements_defeats_structural_designation_at_the_deflection_threshold
    """
    claim = _investigated_workmanship_claim()
    assert claim["designated_structural"] is False, (
        "a fresh claim carries designated_structural false"
    )

    report = file_structural_assessment(
        claim["id"], affected_elements=[], deflection_ratio=0.0500,
        load_bearing_affected=True,
    )

    assert_structural_assessment(report)
    assert report["affected_elements"] == [], (
        "an empty element list is a legitimate filing and must be stored as one"
    )
    assert report["load_bearing_affected"] is True
    assert abs(float(report["deflection_ratio"]) - 0.0500) < 1e-9, (
        f"the measured deflection must be stored as filed, "
        f"got {report['deflection_ratio']}"
    )
    assert report["designated_structural"] is False, (
        "no entry in an empty element list can be load-bearing, so the second "
        "conjunct fails and the verdict is false however severe the deflection"
    )

    refreshed = read_claim(claim["id"])
    assert_claim(refreshed)
    assert refreshed["designated_structural"] is False, (
        "the claim flag is the OR over the reports filed, and the only report "
        "on this claim reached a false verdict"
    )


def test_load_bearing_element_at_exactly_the_deflection_threshold_designates(
    api, underwriting_officer_headers
):
    """PRD 3.6: "The report's own `designated_structural` verdict requires
    **all three** of the following to hold at once: `load_bearing_affected` is
    true; at least one entry in `affected_elements` is a load-bearing element,
    meaning one of `FOOTING`, `FOUNDATION_WALL`, `BEAM`, `LOAD_BEARING_WALL`,
    `ROOF_TRUSS` or `SLAB`; and the `deflection_ratio` is 0.0033 or greater, the
    threshold value itself qualifying."
    PRD 3.6: "An empty `affected_elements` array likewise fails the second
    conjunct, and therefore yields a verdict of false even when the engineer
    marked `load_bearing_affected` true and measured a severe deflection."
    PRD 3.6: "The claim carries its own `designated_structural` flag, which is
    the logical OR across every assessment ever filed on it: it is true as soon
    as any single report reaches a true verdict, and once raised it is **never
    lowered** by a subsequent report that fails the test."
    PRD 2.6: "Engineering assessments of a claim are filterable by
    `designated_structural`."

    The second report measures a deflection of exactly 0.0033 — a fourteenth of
    the deflection the first report measured — yet names one load-bearing
    element, so the threshold value itself qualifies and the verdict comes out
    true. The claim's flag rises by the logical OR, and the two reports separate
    cleanly under the designation filter.

    Design: Difficulty/boundary_precision_check/empty_affected_elements_defeats_structural_designation_at_the_deflection_threshold
    """
    claim = _investigated_workmanship_claim()

    empty_report = file_structural_assessment(
        claim["id"], affected_elements=[], deflection_ratio=0.0500,
        load_bearing_affected=True,
    )
    threshold_report = file_structural_assessment(
        claim["id"], affected_elements=["FOOTING"], deflection_ratio=0.0033,
        load_bearing_affected=True,
    )

    assert_structural_assessment(threshold_report)
    assert empty_report["designated_structural"] is False
    assert abs(float(threshold_report["deflection_ratio"]) - 0.0033) < 1e-9, (
        f"the threshold deflection must be stored as filed, "
        f"got {threshold_report['deflection_ratio']}"
    )
    assert threshold_report["designated_structural"] is True, (
        "0.0033 is the threshold value and qualifies, and FOOTING is a "
        "load-bearing element, so all three conjuncts hold"
    )

    refreshed = read_claim(claim["id"])
    assert_claim(refreshed)
    assert refreshed["designated_structural"] is True, (
        "one true report is enough to raise the claim's flag by logical OR"
    )

    designating, meta = validate_paginated(
        api.list_structural_assessments(
            claim["id"], underwriting_officer_headers,
            params={"designated_structural": "true"},
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one of the two reports designates, got {meta['total_count']}"
    )
    assert [row["id"] for row in designating] == [threshold_report["id"]], (
        "the designating report is the one measured at the threshold"
    )

    non_designating, non_meta = validate_paginated(
        api.list_structural_assessments(
            claim["id"], underwriting_officer_headers,
            params={"designated_structural": "false"},
        )
    )
    assert non_meta["total_count"] == 1, (
        f"the severe-deflection report with no element named is the only "
        f"non-designating one, got {non_meta['total_count']}"
    )
    assert [row["id"] for row in non_designating] == [empty_report["id"]]
