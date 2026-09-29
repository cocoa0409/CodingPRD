"""Two variants of one computation, stored side by side and deliberately unequal.

Coverage is computed twice from the same correlation evidence, and total contract
value is computed twice from the same order shape. Each pair must disagree by an
amount the contract fixes exactly.
"""

from decimal import Decimal

from test_helpers import (
    ADOPTION_MODEL_ADOPTION_LIST,
    DEPTH_MASTERY,
    DEPTH_MENTION,
    DEPTH_PRACTICE,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_QUOTED,
    REVIEW_STATUS_ADOPTED,
    VERDICT_ACCEPTED,
    VERDICT_PENDING,
    VOTE_RECOMMEND,
    as_decimal,
    assert_decimal_equals,
    factories,
    fixtures,
    get_success_data,
    make_review_committee_member_headers,
    validate_paginated,
    validate_success,
)


def test_self_reported_and_verified_coverage_diverge_once_verdicts_land(api):
    """Accepting two of three entries splits the two coverage variants apart.

    PRD 3.4: "The **committee-verified** variant accepts only entries whose
    `reviewer_verdict` is `ACCEPTED`, discarding both `PENDING` and
    `INSUFFICIENT` evidence, and is stored in `verified_coverage_pct`; it is the
    gate at adoption time."

    Design: Difficulty/dual_variant_calc/coverage_self_reported_vs_committee_verified
    """
    world = fixtures.seed_state(api, "TX", min_verified_coverage_pct=50.00)
    fixtures.seed_standard(api, world, "TX.M.3.1", grade_low=3, grade_high=3, weight=3)
    fixtures.seed_standard(api, world, "TX.M.4.1", grade_low=4, grade_high=4, weight=2)
    fixtures.seed_standard(api, world, "TX.M.5.1", grade_low=5, grade_high=5, weight=5)
    fixtures.seed_cycle(api, world, cycle_year=2027)
    fixtures.seed_title(
        api,
        world,
        grade_low=3,
        grade_high=5,
        page_count=400,
        signature_page_capacity=480,
        list_price_cents=9000,
        isbn_base="9780000000301",
    )
    fixtures.set_clock(api, fixtures.CLOCK_INSIDE_SUBMISSION_WINDOW)
    fixtures.advance_phase(api, world)

    submission_id = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id), fixtures.EDITOR
        )
    )["id"]
    mastery_entry = get_success_data(
        api.create_correlation(
            submission_id,
            factories.correlation_payload("TX.M.3.1", depth_level=DEPTH_MASTERY),
            fixtures.EDITOR,
        )
    )["id"]
    practice_entry = get_success_data(
        api.create_correlation(
            submission_id,
            factories.correlation_payload("TX.M.4.1", depth_level=DEPTH_PRACTICE),
            fixtures.EDITOR,
        )
    )["id"]
    mention_entry = get_success_data(
        api.create_correlation(
            submission_id,
            factories.correlation_payload("TX.M.5.1", depth_level=DEPTH_MENTION),
            fixtures.EDITOR,
        )
    )["id"]

    reviewer = make_review_committee_member_headers("cm-1")
    validate_success(
        api.record_correlation_verdict(
            submission_id, mastery_entry, {"verdict": "ACCEPT"}, reviewer
        )
    )
    validate_success(
        api.record_correlation_verdict(
            submission_id, mention_entry, {"verdict": "ACCEPT"}, reviewer
        )
    )

    submission = validate_success(api.get_submission(submission_id, fixtures.EDITOR))
    # Denominator 3 + 2 + 5 = 10. Self-reported numerator 3(1.00) + 2(0.70) +
    # 5(0.40) = 6.40; verified numerator 3(1.00) + 5(0.40) = 5.00.
    assert_decimal_equals(
        submission["self_reported_coverage_pct"], "64.00", "self_reported_coverage_pct"
    )
    assert_decimal_equals(
        submission["verified_coverage_pct"], "50.00", "verified_coverage_pct"
    )
    difference = as_decimal(submission["self_reported_coverage_pct"]) - as_decimal(
        submission["verified_coverage_pct"]
    )
    assert difference == Decimal("14.00"), (
        f"The two variants must differ by 14.00, got {difference}"
    )

    entries, _ = validate_paginated(api.list_correlations(submission_id, fixtures.EDITOR))
    by_id = {entry["id"]: entry for entry in entries}
    assert_decimal_equals(
        by_id[mastery_entry]["effective_weight"], "3.00", "effective_weight"
    )
    assert by_id[mastery_entry]["reviewer_verdict"] == VERDICT_ACCEPTED
    assert by_id[mention_entry]["reviewer_verdict"] == VERDICT_ACCEPTED
    assert by_id[practice_entry]["reviewer_verdict"] == VERDICT_PENDING


def test_verified_coverage_starts_at_zero_while_every_entry_is_pending(api):
    """Before any verdict the publisher's claim stands alone at 64.00 against 0.00.

    PRD 3.4: "Because the verified variant admits a subset of the rows the
    self-reported variant admits, `verified_coverage_pct` is always less than or
    equal to `self_reported_coverage_pct` for the same data."

    Design: Difficulty/dual_variant_calc/coverage_self_reported_vs_committee_verified
    """
    world = fixtures.seed_state(api, "TX", min_verified_coverage_pct=50.00)
    fixtures.seed_standard(api, world, "TX.M.3.1", grade_low=3, grade_high=3, weight=3)
    fixtures.seed_standard(api, world, "TX.M.4.1", grade_low=4, grade_high=4, weight=2)
    fixtures.seed_standard(api, world, "TX.M.5.1", grade_low=5, grade_high=5, weight=5)
    fixtures.seed_cycle(api, world, cycle_year=2027)
    fixtures.seed_title(
        api,
        world,
        grade_low=3,
        grade_high=5,
        page_count=400,
        signature_page_capacity=480,
        list_price_cents=9000,
        isbn_base="9780000000301",
    )
    fixtures.set_clock(api, fixtures.CLOCK_INSIDE_SUBMISSION_WINDOW)
    fixtures.advance_phase(api, world)

    submission_id = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id), fixtures.EDITOR
        )
    )["id"]
    for code, depth in (
        ("TX.M.3.1", DEPTH_MASTERY),
        ("TX.M.4.1", DEPTH_PRACTICE),
        ("TX.M.5.1", DEPTH_MENTION),
    ):
        validate_success(
            api.create_correlation(
                submission_id,
                factories.correlation_payload(code, depth_level=depth),
                fixtures.EDITOR,
            ),
            201,
        )

    submission = validate_success(api.get_submission(submission_id, fixtures.EDITOR))
    assert_decimal_equals(
        submission["self_reported_coverage_pct"], "64.00", "self_reported_coverage_pct"
    )
    assert_decimal_equals(
        submission["verified_coverage_pct"], "0.00", "verified_coverage_pct"
    )
    assert as_decimal(submission["verified_coverage_pct"]) <= as_decimal(
        submission["self_reported_coverage_pct"]
    )


def test_quoted_total_prices_the_order_at_list_before_any_state_price_exists(api):
    """A quote values print units at the edition's list price and waives no freight.

    PRD 3.9: "In the quoted variant the unit price is the edition's own
    `list_price_cents`."

    Design: Difficulty/dual_variant_calc/order_quoted_vs_contracted_total_value
    """
    world = fixtures.seed_presented_slot(
        api,
        "CA",
        state_overrides={"adoption_model": ADOPTION_MODEL_ADOPTION_LIST},
        title_overrides={"isbn_base": "9780000000401", "list_price_cents": 9000},
        receipt_units=5000,
        panel_overrides={"quorum_required": 3},
        proposal_overrides={
            "base_price_cents": 9000,
            "term_years": 3,
            "annual_escalator_bps": 0,
            "projected_adoption_units": 100,
            "digital_seat_price_cents": 1500,
        },
    )
    fixtures.cast_ballots(api, world.slot_id, [VOTE_RECOMMEND] * 3)
    fixtures.tally_slot(api, world)

    proposal = validate_success(
        api.get_pricing_proposal(world.proposal_id, fixtures.PRICING)
    )
    assert proposal["net_state_price_cents"] == 26190
    assert proposal["avg_annual_price_cents"] == 8730

    order = validate_success(
        api.create_district_order(
            factories.district_order_payload(
                world.state_id,
                world.title_id,
                print_units=200,
                digital_seats=100,
                pricing_proposal_id=world.proposal_id,
            ),
            fixtures.QUOTING_REP,
        ),
        201,
    )
    # Print 200 x 9000 = 1,800,000 plus seats 100 x 1500 = 150,000 gives a
    # pre-freight total of 1,950,000, below the waiver, so freight is
    # 1,800,000 x 0.015 = 27,000 and no rebate applies to a quote.
    assert order["status"] == ORDER_STATUS_QUOTED
    assert order["quoted_tcv_cents"] == 1977000
    assert order["freight_surcharge_cents"] == 27000
    assert order["contracted_tcv_cents"] is None
    assert order["allocated_units"] == 0


def test_contracted_total_swaps_in_the_state_price_and_the_adopted_list_rebate(api):
    """Confirming the same order recomputes the total 89,730 cents lower.

    PRD 3.9: "Next, an adopted-list rebate applies **only** in the contracted
    variant and **only** when the state's `adoption_model` is `ADOPTION_LIST`: it
    is the print subtotal multiplied by 0.02, rounded half up to a whole cent; in
    every other case the rebate is 0."

    Design: Difficulty/dual_variant_calc/order_quoted_vs_contracted_total_value
    """
    world = fixtures.seed_presented_slot(
        api,
        "CA",
        state_overrides={"adoption_model": ADOPTION_MODEL_ADOPTION_LIST},
        title_overrides={"isbn_base": "9780000000401", "list_price_cents": 9000},
        receipt_units=5000,
        panel_overrides={"quorum_required": 3},
        proposal_overrides={
            "base_price_cents": 9000,
            "term_years": 3,
            "annual_escalator_bps": 0,
            "projected_adoption_units": 100,
            "digital_seat_price_cents": 1500,
        },
    )
    fixtures.cast_ballots(api, world.slot_id, [VOTE_RECOMMEND] * 3)
    fixtures.tally_slot(api, world)

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_ADOPTED

    order_id = get_success_data(
        api.create_district_order(
            factories.district_order_payload(
                world.state_id,
                world.title_id,
                print_units=200,
                digital_seats=100,
                pricing_proposal_id=world.proposal_id,
            ),
            fixtures.QUOTING_REP,
        )
    )["id"]
    quoted_total = validate_success(
        api.get_district_order(order_id, fixtures.QUOTING_REP)
    )["quoted_tcv_cents"]

    confirmed = validate_success(
        api.confirm_district_order(order_id, fixtures.CONFIRMING_REP)
    )
    # Print 200 x 8730 = 1,746,000 plus 150,000 of seats is 1,896,000
    # pre-freight; freight 26,190 and the adopted-list rebate 34,920.
    assert confirmed["status"] == ORDER_STATUS_CONFIRMED
    assert confirmed["contracted_tcv_cents"] == 1887270
    assert confirmed["freight_surcharge_cents"] == 26190
    assert quoted_total == 1977000
    assert quoted_total - confirmed["contracted_tcv_cents"] == 89730
