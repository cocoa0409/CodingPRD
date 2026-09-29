"""The two minimum-price variants, and the two good-faith score variants.

One parcel, one appraisal and one cured lien feed both readings. The affordable
housing entity is quoted the written-down floor while the open market is quoted
the market floor, and the same five-round bargaining record scores below the
pass mark on the interim reading and above it on the final one.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data


def _write_down_case(api):
    """A cured parcel appraised at 100,000,000 with a housing authority in negotiation.

    The lien is cured at 250,000 so the cure deduction is fixed, the parcel is
    carried at 70,000,000, and the appraisal is accepted at 100,000,000 with an
    effective date of 2026-08-01T00:00:00Z. The housing authority answers the
    statutory notice by expressing interest, which opens the offer.
    """
    return fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )


def test_01_affordable_housing_variant_writes_down_below_the_carrying_value(api):
    """The housing authority's quoted floor drops the book-value floor entirely.

    "Under `AFFORDABLE_HOUSING_PREFERENCE` the answer is the larger of the raw
    minimum and zero: the 0.35 statutory affordable-housing write-down applies
    and the book-value floor is deliberately dropped, so from identical parcel,
    appraisal and curative data this variant yields a strictly lower minimum
    price than `MARKET_FLOOR` and may lawfully fall below book value."

    Design: Difficulty/dual_variant_calc/minimum_price_market_floor_versus_affordable_housing_write_down
    """
    ctx = _write_down_case(api)
    ctx = fx.build_preference_offer(api, ctx, preference_category="AFFORDABLE_HOUSING")

    offer = ctx["offer"]
    assert offer["preference_category"] == "AFFORDABLE_HOUSING", (
        "the offer must carry the category the housing authority claimed, got "
        f"{offer['preference_category']!r}"
    )
    assert offer["ah_minimum_price_cents"] == 64750000, (
        "100,000,000 less the 0.35 write-down is 65,000,000, less the 250,000 "
        "cure deduction is 64,750,000, got "
        f"{offer['ah_minimum_price_cents']}"
    )
    assert offer["ah_minimum_price_cents"] < ctx["parcel"]["book_value_cents"], (
        "the written-down floor is allowed to sit below the carrying value: "
        f"{offer['ah_minimum_price_cents']} is not below "
        f"{ctx['parcel']['book_value_cents']}"
    )


def test_02_market_floor_variant_prices_the_open_market_above_the_carrying_value(api):
    """The competitive offering is priced with no write-down at all.

    "The write-down fraction is 0.35 for the `AFFORDABLE_HOUSING_PREFERENCE`
    variant and zero for the `MARKET_FLOOR` variant." "Under `MARKET_FLOOR` the
    answer is the larger of the raw minimum and the parcel's `book_value_cents`,
    so the agency can never offer public land below its carrying value on the
    open market."

    Design: Difficulty/dual_variant_calc/minimum_price_market_floor_versus_affordable_housing_write_down
    """
    ctx = _write_down_case(api)
    ctx = fx.build_offering_after_impasse(api, ctx)

    offering = ctx["offering"]
    assert offering["minimum_price_variant"] == "MARKET_FLOOR", (
        "a competitive sale is priced on the market-floor variant, got "
        f"{offering['minimum_price_variant']!r}"
    )
    assert offering["minimum_price_cents"] == 99750000, (
        "100,000,000 with no write-down less the 250,000 cure deduction is "
        f"99,750,000, got {offering['minimum_price_cents']}"
    )
    assert offering["minimum_price_cents"] > ctx["parcel"]["book_value_cents"], (
        "the raw minimum already clears the carrying value, so the floor does "
        f"not bind: {offering['minimum_price_cents']} is not above "
        f"{ctx['parcel']['book_value_cents']}"
    )


def test_03_the_two_variants_diverge_by_the_statutory_write_down(api):
    """The same data quotes two prices 35,000,000 cents apart, and one deposit.

    "The required deposit is the offering's own frozen `minimum_price_cents`
    multiplied by 0.05, rounded half up to a whole cent, and then raised to the
    floor of 5,000,000 cents if the product falls below it — so every offering
    priced below 100,000,000 cents demands the same flat 5,000,000-cent
    deposit."

    Design: Difficulty/dual_variant_calc/minimum_price_market_floor_versus_affordable_housing_write_down
    """
    ctx = _write_down_case(api)
    ctx = fx.build_offering_after_impasse(api, ctx)

    quoted_to_entity = ctx["offer"]["ah_minimum_price_cents"]
    quoted_to_market = ctx["offering"]["minimum_price_cents"]
    assert quoted_to_market - quoted_to_entity == 35000000, (
        "the write-down of 0.35 on a 100,000,000 base is the whole divergence: "
        f"{quoted_to_market} less {quoted_to_entity} is "
        f"{quoted_to_market - quoted_to_entity}"
    )
    assert ctx["offering"]["required_deposit_cents"] == 5000000, (
        "a twentieth of 99,750,000 is 4,987,500, which falls below the floor, "
        "so the deposit is the flat 5,000,000 cents, got "
        f"{ctx['offering']['required_deposit_cents']}"
    )


def test_04_interim_reading_omits_concession_and_sits_below_the_pass_mark(api):
    """Three agency rounds and two timely ones score 65 while bargaining runs.

    "The interim variant is recomputed on every appended round and exposed as
    `interim_good_faith_score`; it omits concession points entirely, treating
    them as zero, omits the premature-impasse penalty, and then caps the result
    at 75 — price convergence cannot fairly be judged while the parties are
    still exchanging offers."

    Design: Difficulty/dual_variant_calc/good_faith_interim_score_below_pass_while_final_clears
    """
    ctx = _write_down_case(api)
    ctx = fx.build_graded_impasse_offer(api, ctx)

    after_rounds = ctx["offer_after_rounds"]
    assert after_rounds["officer_round_count"] == 3, (
        "the custodian agency tendered three of the five rounds, got "
        f"{after_rounds['officer_round_count']}"
    )
    assert after_rounds["timely_response_count"] == 2, (
        "both preference-entity rounds answered inside a fortnight, got "
        f"{after_rounds['timely_response_count']}"
    )
    assert after_rounds["interim_good_faith_score"] == 65, (
        "45 engagement points plus 20 timeliness points and no concession "
        f"points is 65, got {after_rounds['interim_good_faith_score']}"
    )
    assert after_rounds["interim_good_faith_score"] < 70, (
        "the interim reading must fall short of the passing mark, got "
        f"{after_rounds['interim_good_faith_score']}"
    )


def test_05_final_reading_adds_concession_points_and_clears_the_pass_mark(api):
    """The same record scores 90 at determination and the conduct is satisfied.

    "The final variant runs once, at determination, and is stored in
    `final_good_faith_score`; it adds concession points, subtracts the
    premature-impasse penalty, applies no cap of 75, and is the only variant
    ever compared against the passing mark of 70."

    Design: Difficulty/dual_variant_calc/good_faith_interim_score_below_pass_while_final_clears
    """
    ctx = _write_down_case(api)
    ctx = fx.build_graded_impasse_offer(api, ctx)

    offer = get_success_data(
        api.get_preference_offer(ctx["offer"]["id"], fx.OFFICER_HEADERS)
    )
    assert offer["final_good_faith_score"] == 90, (
        "45 engagement points, 20 timeliness points and 25 concession points "
        "with no premature-impasse penalty is 90, got "
        f"{offer['final_good_faith_score']}"
    )
    assert offer["final_good_faith_score"] >= 70, (
        "the final reading must clear the passing mark, got "
        f"{offer['final_good_faith_score']}"
    )
    assert (
        offer["final_good_faith_score"] - offer["interim_good_faith_score"] == 25
    ), (
        "the whole difference between the readings is the concession component: "
        f"{offer['final_good_faith_score']} less "
        f"{offer['interim_good_faith_score']}"
    )
    assert offer["good_faith_status"] == "SATISFIED", (
        "a final score of at least 70 satisfies the good-faith duty, got "
        f"{offer['good_faith_status']!r}"
    )
    assert offer["negotiation_status"] == "IMPASSE", (
        "grading conduct leaves the negotiation dimension where it stood, got "
        f"{offer['negotiation_status']!r}"
    )
