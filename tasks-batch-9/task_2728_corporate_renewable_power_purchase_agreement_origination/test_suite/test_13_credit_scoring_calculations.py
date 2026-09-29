"""The credit and sustainability arithmetic, one formula limb at a time.

Two independent chains run on the same submission — an additive sustainability
score and a weighted credit score — and neither may overwrite the other.  Below
them sit three formulas with sharp edges: the inclusive near-term year boundary,
the `min()` of two unsecured-limit ceilings, the ceiling of the *residual* after
netting, and the two haircut tables keyed on two different entities.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import get_success_data  # noqa: E402

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.test_users import CREDIT_OFFICER, ORIGINATOR  # noqa: E402

#: 40 + 30 + 20 + 10 — the only input combination that saturates the scale.
SATURATED_SUSTAINABILITY = 100.00

#: 0.55 * 84 + 0.30 * 75 + 0.15 * 100.
ANCHOR_CREDIT_SCORE = 83.70


def test_01_the_additive_and_the_weighted_chain_both_run_on_one_submission(api):
    """All four commitments sum to exactly 100.00 while the weighted credit score
    lands independently on 83.70, and neither figure exists before submission.

    "On creation `qualification_status` is `DRAFT`, `conditions` is the empty
    array, `claimed_attributes_mwh` is 0, `watchlist_since` is null,
    `decision_by_user_id` is null, and `credit_score`, `credit_score_variant`,
    `credit_tier`, `sustainability_score` and `unsecured_credit_limit_usd` are all
    null — no scoring runs at creation."

    "The sustainability score is purely additive and also runs on submission."

    "A validated science-based target — `has_science_based_target` being true —
    adds 40 points."

    "The three effective component values are then combined by weight — the rating
    component at 0.55, the leverage component at 0.30 and the disclosure component
    at 0.15 — and the weighted sum is rounded half up to two decimal places to give
    `credit_score`."

    Design: Corner/calculations/sustainability_score_sums_all_four_additive_components_to_100_00
    """
    buyer = fx.create_offtaker(api, has_science_based_target=True,
                               re100_member=True, scope2_target_year=2030)
    asserts.assert_all_null(buyer, ["sustainability_score", "credit_score",
                                    "credit_tier", "credit_score_variant",
                                    "unsecured_credit_limit_usd"])

    reviewed = fx.submit_offtaker(api, buyer["id"])
    asserts.assert_score(reviewed["sustainability_score"],
                         SATURATED_SUSTAINABILITY, "sustainability_score")
    asserts.assert_score(reviewed["credit_score"], ANCHOR_CREDIT_SCORE,
                         "credit_score")
    assert reviewed["credit_tier"] == "PRIME", reviewed
    assert reviewed["qualification_status"] == "UNDER_REVIEW", reviewed
    asserts.assert_version_advanced_by(buyer["version"], reviewed["version"], 1,
                                       "offtaker version")

    # 100.00 clears the QUALIFY gate of 70.00 with room to spare.
    qualified = fx.decide_offtaker(api, buyer["id"], "QUALIFY")
    assert qualified["qualification_status"] == "QUALIFIED", qualified


# ---------------------------------------------------------------------------
# NEAR_TERM_YEAR is 2030 and the comparison is inclusive.
# ---------------------------------------------------------------------------

#: Identical in every field that scores, so the only moving part is the
#: near-term target year.
BOUNDARY_INPUTS = {
    "credit_rating": "A",
    "rating_agency": "SP",
    "reported_ebitda_usd": 60000000.00,
    "net_debt_to_ebitda": 2.5,
    "disclosure_framework": "NONE",
    "has_science_based_target": True,
    "re100_member": False,
}

#: 40 (science-based target) + 20 (a 2030 target).
ON_THE_BOUNDARY = 60.00

#: 40 alone: a 2031 target contributes nothing, and neither does `NONE`.
OFF_THE_BOUNDARY = 40.00

#: 0.55 * 84 + 0.30 * 75 + 0.15 * 30 — `NONE` still scores 30 credit points.
BOUNDARY_CREDIT_SCORE = 73.20

QUALIFY_SUSTAINABILITY_GATE = 70.00


def test_02_a_one_year_change_in_the_target_moves_the_score_by_twenty(api):
    """2030 earns the twenty points, 2031 earns nothing, and an omitted target
    contributes nothing rather than raising an error.

    "A `scope2_target_year` that is not null **and** falls no later than 2030 adds
    20 points; a target of exactly 2030 does contribute, and a null target
    contributes nothing and is not an error."

    "Reporting under any framework other than `NONE` adds 10 points."

    "The **disclosure component** is a lookup on `disclosure_framework`:
    `CDP_AND_TCFD` is worth 100 points, `TCFD_ONLY` 80, `CDP_ONLY` 70 and `NONE`
    30."

    Design: Corner/calculations/sustainability_near_term_year_boundary_2030_counts_2031_and_null_do_not
    """
    on_boundary = fx.create_offtaker(api, legal_name="Boundary Co 2030",
                                     scope2_target_year=2030,
                                     **BOUNDARY_INPUTS)
    over_boundary = fx.create_offtaker(api, legal_name="Boundary Co 2031",
                                       scope2_target_year=2031,
                                       **BOUNDARY_INPUTS)
    no_target = fx.create_offtaker(api, legal_name="Boundary Co No Target",
                                   **BOUNDARY_INPUTS)
    assert no_target["scope2_target_year"] is None, no_target

    scored_on = fx.submit_offtaker(api, on_boundary["id"])
    asserts.assert_score(scored_on["sustainability_score"], ON_THE_BOUNDARY,
                         "sustainability_score")

    scored_over = fx.submit_offtaker(api, over_boundary["id"])
    asserts.assert_score(scored_over["sustainability_score"], OFF_THE_BOUNDARY,
                         "sustainability_score")

    scored_null = fx.submit_offtaker(api, no_target["id"])
    asserts.assert_score(scored_null["sustainability_score"], OFF_THE_BOUNDARY,
                         "sustainability_score")
    assert scored_null["scope2_target_year"] is None, scored_null

    # `NONE` scores 30 credit points while contributing 0 sustainability points.
    for scored in (scored_on, scored_over, scored_null):
        asserts.assert_score(scored["credit_score"], BOUNDARY_CREDIT_SCORE,
                             "credit_score")
        assert scored["credit_tier"] == "STANDARD", scored
        assert float(scored["sustainability_score"]) \
            < QUALIFY_SUSTAINABILITY_GATE, (
            "none of these buyers could be QUALIFIED on these commitments")


# ---------------------------------------------------------------------------
# The unsecured limit is a min() of two ceilings, and each limb must be able to
# win on its own.
# ---------------------------------------------------------------------------

SMALL_EBITDA_LIMIT_USD = 3000000.00
LARGE_EBITDA_SCORE = 92.60
PRIME_TIER_CAP_USD = 25000000.00
DECLINED_SCORE = 21.50


def test_03_each_limb_of_the_unsecured_limit_wins_in_turn(api):
    """The EBITDA share binds a PRIME buyer on modest earnings, the hard tier cap
    binds a PRIME buyer on very large earnings, and a `DECLINED` buyer lands on
    0.00 by both limbs at once rather than on an error.

    "The first is a hard cap by tier: 25,000,000.00 USD for `PRIME`,
    10,000,000.00 for `STANDARD`, 2,000,000.00 for `SUBPRIME` and 0.00 for
    `DECLINED`."

    "The second is a share of reported earnings: `reported_ebitda_usd` multiplied
    by 5 percent for `PRIME`, 2 percent for `STANDARD`, one-half of one percent for
    `SUBPRIME` and zero for `DECLINED`, rounded half up to two decimal places."

    "`unsecured_credit_limit_usd` is whichever of the two is smaller, and a
    `DECLINED` buyer therefore lands on 0.00 by both limbs."

    Design: Corner/calculations/unsecured_limit_takes_the_lesser_of_tier_cap_and_ebitda_share
    """
    small = fx.create_submitted_offtaker(api, anchor=False,
                                         has_science_based_target=True,
                                         re100_member=True,
                                         scope2_target_year=2030)
    asserts.assert_score(small["credit_score"], ANCHOR_CREDIT_SCORE,
                         "credit_score")
    assert small["credit_tier"] == "PRIME", small
    asserts.assert_money(small["unsecured_credit_limit_usd"],
                         SMALL_EBITDA_LIMIT_USD, "unsecured_credit_limit_usd")

    large = fx.create_submitted_offtaker(
        api, anchor=False, legal_name="Aurora Holdings PLC", credit_rating="AA",
        reported_ebitda_usd=900000000.00, net_debt_to_ebitda=1.0,
        has_science_based_target=True, re100_member=True,
        scope2_target_year=2030)
    asserts.assert_score(large["credit_score"], LARGE_EBITDA_SCORE,
                         "credit_score")
    assert large["credit_tier"] == "PRIME", large
    asserts.assert_money(large["unsecured_credit_limit_usd"],
                         PRIME_TIER_CAP_USD, "unsecured_credit_limit_usd")

    declined = fx.create_submitted_offtaker(
        api, anchor=False, legal_name="Deadbeat Industries Ltd",
        credit_rating="CCC", net_debt_to_ebitda=8.0,
        disclosure_framework="NONE")
    asserts.assert_score(declined["credit_score"], DECLINED_SCORE,
                         "credit_score")
    assert declined["credit_tier"] == "DECLINED", declined
    asserts.assert_money(declined["unsecured_credit_limit_usd"], 0.00,
                         "unsecured_credit_limit_usd")

    # The limit is an Offtaker-level figure until a deal copies it.
    _, meta = fx.list_all(api.list_deals(ORIGINATOR))
    assert meta["total_count"] == 0, meta


# ---------------------------------------------------------------------------
# The ceiling is applied to the residual after netting, not to gross exposure.
# ---------------------------------------------------------------------------

OVER_CONTRACTED_MW = 50.000
OVER_EXPECTED_MWH = 122640.00
OVER_CONTRACT_PRICE = 26.75
OVER_EXPOSURE_USD = 3280620.00
OVER_REQUIREMENT_USD = 500000.00

UNDER_CONTRACTED_MW = 25.000
UNDER_EXPECTED_MWH = 61320.00
UNDER_CONTRACT_PRICE = 22.75
UNDER_EXPOSURE_USD = 1395030.00

COLLATERAL_THRESHOLD_USD = 3000000.00
PROJECT_CAPACITY_MW = 100.000


def test_04_the_requirement_ceils_the_residual_and_not_the_gross_exposure(api):
    """A deal 280,620.00 over the line needs a whole two increments, while a deal
    under the line needs nothing at all; the same buyer's limit is snapshotted onto
    both.

    "`expected_annual_mwh` is `contracted_mw` multiplied by the technology capacity
    factor of the parent project — 0.28 for `SOLAR`, 0.42 for `WIND`, 0.35 for
    `STORAGE_HYBRID` — multiplied by the 8,760 hours in a year, rounded half up to
    two decimal places."

    "Second, the buyer's unsecured appetite is netted off — `collateral_threshold_usd`
    on the deal equals the `unsecured_credit_limit_usd` snapshotted from the anchor
    buyer, and it is the threshold below which no collateral is called at all."

    "Third, otherwise, the residual is `exposure_usd` less
    `collateral_threshold_usd`, that residual is divided by the collateral
    increment of 250,000.00 USD and the quotient is rounded **up** to the next whole
    number of increments — a ceiling, never a half-up round — and
    `credit_support_required_usd` is that whole count of increments multiplied by
    250,000.00."

    Design: Corner/calculations/credit_support_requirement_rounds_up_to_a_whole_increment
    """
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"])
    asserts.assert_money(buyer["unsecured_credit_limit_usd"],
                         COLLATERAL_THRESHOLD_USD, "unsecured_credit_limit_usd")

    over = fx.create_deal(api, project["id"], buyer["id"], node["id"],
                          product_type="VIRTUAL_CFD",
                          contracted_mw=OVER_CONTRACTED_MW, term_years=12,
                          base_fixed_price_usd_per_mwh=26.00)
    asserts.assert_mwh(over["expected_annual_mwh"], OVER_EXPECTED_MWH,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(over["contract_price_usd_per_mwh"],
                         OVER_CONTRACT_PRICE, "contract_price_usd_per_mwh")
    assert over["price_tier"] == "LOW", over
    asserts.assert_money(over["exposure_usd"], OVER_EXPOSURE_USD,
                         "exposure_usd")
    asserts.assert_money(over["collateral_threshold_usd"],
                         COLLATERAL_THRESHOLD_USD, "collateral_threshold_usd")

    # 280,620.00 / 250,000.00 = 1.12248, ceiled to two whole increments: not
    # 250,000.00, not the raw residual, and not a ceiling of gross exposure.
    asserts.assert_money(over["credit_support_required_usd"],
                         OVER_REQUIREMENT_USD, "credit_support_required_usd")

    under = fx.create_deal(api, project["id"], buyer["id"], node["id"],
                           product_type="VIRTUAL_CFD",
                           contracted_mw=UNDER_CONTRACTED_MW, term_years=12,
                           base_fixed_price_usd_per_mwh=22.00)
    asserts.assert_mwh(under["expected_annual_mwh"], UNDER_EXPECTED_MWH,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(under["contract_price_usd_per_mwh"],
                         UNDER_CONTRACT_PRICE, "contract_price_usd_per_mwh")
    asserts.assert_money(under["exposure_usd"], UNDER_EXPOSURE_USD,
                         "exposure_usd")
    asserts.assert_money(under["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    assert under["credit_status"] == "NOT_SUBMITTED", under

    # Both deals share the same threshold snapshot, and the project's ledger
    # counts only deals whose status is EXECUTED or EFFECTIVE — these are DRAFT.
    asserts.assert_money(under["collateral_threshold_usd"],
                         COLLATERAL_THRESHOLD_USD, "collateral_threshold_usd")
    ledger = fx.read_project(api, project["id"])
    asserts.assert_mw(ledger["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(ledger["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")


# ---------------------------------------------------------------------------
# Face amount is not credit: two haircut tables keyed on two entities.
# ---------------------------------------------------------------------------

#: BBB / FITCH / 4.0 / NONE scores 62.10, which is STANDARD — and the tier
#: exists as soon as scoring has run, well before any decision.
GUARANTOR_INPUTS = {
    "legal_name": "Bare Minimum Industrials LLC",
    "credit_rating": "BBB",
    "rating_agency": "FITCH",
    "reported_ebitda_usd": 20000000.00,
    "net_debt_to_ebitda": 4.0,
    "disclosure_framework": "NONE",
}
GUARANTOR_SCORE = 62.10

LC_FACE_USD = 500000.00
LC_HAIRCUT_PCT = 10.00
LC_ELIGIBLE_USD = 450000.00

PG_FACE_USD = 1000000.00
PG_HAIRCUT_PCT = 25.00
PG_ELIGIBLE_USD = 750000.00

COMBINED_ELIGIBLE_USD = 1200000.00

#: Long enough to clear the 365-day tenor rule from the logical clock.
LONG_TENOR_EXPIRY = "2031-12-31T00:00:00Z"


def test_05_two_haircut_tables_discount_two_instruments_differently(api):
    """A BBB bank's letter is discounted 10.00 and a merely `STANDARD` parent's
    guarantee 25.00, so 1,500,000.00 of face is worth 1,200,000.00 of coverage —
    and registration computes neither figure.

    "A letter of credit is discounted by the issuing bank's rating: 0.00 for
    `AAA`, `AA` and `A`, 10.00 for `BBB` and 35.00 for `BB`."

    "A parent guarantee is discounted by the guarantor's own commercial tier: 0.00
    for `PRIME`, 25.00 for `STANDARD` and 60.00 for `SUBPRIME`, which is why a weak
    parent contributes little even behind a large face amount."

    "A registered instrument arrives with `status` `PROPOSED` and with
    `haircut_pct`, `eligible_credit_usd`, `posted_at` and `closed_at` all null;
    registration deliberately does **not** move `posted_credit_support_usd` and does
    **not** increment the deal's `version`."

    "A successful post moves the instrument `PROPOSED → POSTED`, stamps `posted_at`
    with the logical clock, and recomputes the deal's `posted_credit_support_usd`
    as the sum of `eligible_credit_usd` over that deal's `POSTED` instruments."

    Design: Corner/calculations/eligible_credit_support_haircut_by_issuer_rating_and_guarantor_tier
    """
    guarantor = fx.create_submitted_offtaker(api, anchor=False,
                                             **GUARANTOR_INPUTS)
    asserts.assert_score(guarantor["credit_score"], GUARANTOR_SCORE,
                         "credit_score")
    assert guarantor["credit_tier"] == "STANDARD", guarantor
    assert guarantor["qualification_status"] == "UNDER_REVIEW", guarantor

    # The anchor names this guarantor, but the guarantor has not itself
    # qualified, so the anchor's own variant stays STANDALONE.
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(
        api, parent_guarantor_offtaker_id=guarantor["id"])
    assert buyer["credit_score_variant"] == "STANDALONE", buyer
    asserts.assert_score(buyer["credit_score"], ANCHOR_CREDIT_SCORE,
                         "credit_score")
    project = fx.create_project(api, node["id"])
    deal = fx.create_deal(api, project["id"], buyer["id"], node["id"],
                          product_type="VIRTUAL_CFD", term_years=12)
    deal_id = deal["id"]

    # "the deal's `credit_status` must be `SUBMITTED`, `APPROVED`,
    # `SUPPORT_SHORTFALL` or `DECLINED`" before an instrument may be posted, so
    # the package is submitted first; the requirement still sizes to 0.00.
    submitted = fx.submit_credit(api, deal_id)
    assert submitted["credit_status"] == "SUBMITTED", submitted

    letter = fx.register_letter_of_credit(api, deal_id, LC_FACE_USD,
                                          issuer_name="Second Federal Bank",
                                          issuer_rating="BBB",
                                          expiry_date=LONG_TENOR_EXPIRY)
    guarantee = get_success_data(api.register_credit_support(
        deal_id,
        f.parent_guarantee_payload(PG_FACE_USD, guarantor["id"],
                                   expiry_date=LONG_TENOR_EXPIRY),
        CREDIT_OFFICER), 201)
    for registered in (letter, guarantee):
        assert registered["status"] == "PROPOSED", registered
        asserts.assert_all_null(registered, ["haircut_pct",
                                             "eligible_credit_usd",
                                             "posted_at", "closed_at"])
    at_rest = fx.read_deal(api, deal_id)
    assert at_rest["version"] == submitted["version"], at_rest
    asserts.assert_money(at_rest["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")

    posted_letter = fx.post_instrument(api, deal_id, letter["id"])
    assert posted_letter["status"] == "POSTED", posted_letter
    asserts.assert_money(posted_letter["haircut_pct"], LC_HAIRCUT_PCT,
                         "haircut_pct")
    asserts.assert_money(posted_letter["eligible_credit_usd"], LC_ELIGIBLE_USD,
                         "eligible_credit_usd")

    posted_guarantee = fx.post_instrument(api, deal_id, guarantee["id"])
    asserts.assert_money(posted_guarantee["haircut_pct"], PG_HAIRCUT_PCT,
                         "haircut_pct")
    asserts.assert_money(posted_guarantee["eligible_credit_usd"],
                         PG_ELIGIBLE_USD, "eligible_credit_usd")
    asserts.assert_instant_equals(posted_guarantee["posted_at"],
                                  fx.INITIAL_CLOCK, "posted_at")

    covered = fx.read_deal(api, deal_id)
    asserts.assert_money(covered["posted_credit_support_usd"],
                         COMBINED_ELIGIBLE_USD, "posted_credit_support_usd")

    # Over-collateralising a deal that needs nothing changes no status.
    asserts.assert_money(covered["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    assert covered["credit_status"] == "SUBMITTED", covered
