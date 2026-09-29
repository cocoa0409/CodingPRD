"""Formulas whose inputs interact: discount tiers, freight ordering, penalty stacks.

Each case stacks several independent selectors into one arithmetic result whose
value depends on the order the contract prescribes.
"""

from test_helpers import (
    ACCESSIBILITY_WCAG_2_2_AA,
    COMMENT_STATUS_ESCALATED,
    CYCLE_STATUS_CLOSED_FOR_SUBMISSION,
    ORDER_STATUS_QUOTED,
    PRICING_STATUS_PRICE_FILED,
    PROPOSAL_STATUS_FILED,
    ROSTERING_ONEROSTER_1_2,
    SEVERITY_CRITICAL,
    SEVERITY_MINOR,
    assert_decimal_equals,
    factories,
    fixtures,
    get_success_data,
    validate_paginated,
    validate_success,
)


def test_three_discount_tiers_stack_and_are_capped_at_a_fifth_of_list(api):
    """Volume, term and bundle tiers sum to 0.27 and are held down to 0.20.

    PRD 3.6: "The three are then added together and capped: `total_discount_pct`
    is the lesser of 0.20 and that sum, so no filing can ever discount more than
    a fifth of list regardless of how the tiers stack."

    Design: Difficulty/combinatorial_formula/net_state_price_per_year_rounding_pinned
    """
    world = fixtures.seed_filed_submission(
        api,
        "NV",
        state_overrides={"multi_year_max_years": 6},
        title_overrides={"isbn_base": "9780000000601", "list_price_cents": 12345},
    )
    bundle_id = fixtures.seed_bundle(
        api,
        world,
        component_count=4,
        accessibility_conformance=ACCESSIBILITY_WCAG_2_2_AA,
        rostering_standard=ROSTERING_ONEROSTER_1_2,
        privacy_addendum_signed=True,
    )

    version = api.read_submission_version(world.submission_id, fixtures.PRICING)
    proposal = validate_success(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id,
                version,
                bundle_id=bundle_id,
                base_price_cents=12345,
                term_years=5,
                annual_escalator_bps=250,
                projected_adoption_units=20000,
                digital_seat_price_cents=1500,
            ),
            fixtures.PRICING,
        ),
        201,
    )

    assert_decimal_equals(proposal["volume_discount_pct"], "0.12", "volume_discount_pct")
    assert_decimal_equals(proposal["term_discount_pct"], "0.06", "term_discount_pct")
    assert_decimal_equals(proposal["bundle_discount_pct"], "0.09", "bundle_discount_pct")
    assert_decimal_equals(proposal["total_discount_pct"], "0.20", "total_discount_pct")
    assert proposal["status"] == PROPOSAL_STATUS_FILED
    assert proposal["contract_locked"] is False


def test_each_contract_year_is_rounded_before_the_years_are_added(api):
    """Rounding five escalating years individually nets 51,911 cents, not 51,912.

    PRD 3.6: "**Each year's price is rounded half up to whole cents
    individually, and only then are the years added together** to give
    `net_state_price_cents`."

    Design: Difficulty/combinatorial_formula/net_state_price_per_year_rounding_pinned
    """
    world = fixtures.seed_filed_submission(
        api,
        "NV",
        state_overrides={"multi_year_max_years": 6},
        title_overrides={"isbn_base": "9780000000601", "list_price_cents": 12345},
    )
    bundle_id = fixtures.seed_bundle(
        api,
        world,
        component_count=4,
        accessibility_conformance=ACCESSIBILITY_WCAG_2_2_AA,
        rostering_standard=ROSTERING_ONEROSTER_1_2,
        privacy_addendum_signed=True,
    )

    version = api.read_submission_version(world.submission_id, fixtures.PRICING)
    proposal = validate_success(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id,
                version,
                bundle_id=bundle_id,
                base_price_cents=12345,
                term_years=5,
                annual_escalator_bps=250,
                projected_adoption_units=20000,
                digital_seat_price_cents=1500,
            ),
            fixtures.PRICING,
        ),
        201,
    )

    # Discounted year one is 9,876; escalating at 2.50% and rounding each year
    # gives 9,876 + 10,123 + 10,376 + 10,635 + 10,901 = 51,911. Summing the
    # exact decimals first would round to 51,912.
    assert proposal["net_state_price_cents"] == 51911
    assert proposal["avg_annual_price_cents"] == 10382

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["pricing_status"] == PRICING_STATUS_PRICE_FILED


def test_freight_is_decided_on_the_pre_freight_total_and_so_is_charged(api):
    """A 2,480,000 subtotal misses the waiver even though the final total clears it.

    PRD 3.9: "Freight is then decided **on the pre-freight total, never on the
    final total**: `freight_surcharge_cents` is 0 when the pre-freight total is at
    or above the freight waiver threshold of 2,500,000 cents — that is, twenty-five
    thousand dollars — and otherwise is the print subtotal multiplied by a freight
    rate of 0.015, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/order_freight_waiver_evaluated_on_pre_freight_total
    """
    world = fixtures.seed_state(api, "AZ")
    fixtures.seed_title(
        api, world, isbn_base="9780000000701", list_price_cents=12400
    )

    order = validate_success(
        api.create_district_order(
            factories.district_order_payload(
                world.state_id, world.title_id, print_units=200, digital_seats=0
            ),
            fixtures.QUOTING_REP,
        ),
        201,
    )

    # 200 x 12,400 = 2,480,000 pre-freight, so freight is 37,200 and the stored
    # total of 2,517,200 sits above the threshold the waiver test never saw.
    assert order["status"] == ORDER_STATUS_QUOTED
    assert order["freight_surcharge_cents"] == 37200
    assert order["quoted_tcv_cents"] == 2517200
    assert order["allocated_units"] == 0


def test_a_pre_freight_total_on_the_threshold_waives_freight_entirely(api):
    """Two more copies lift the subtotal over 2,500,000 and freight drops to zero.

    PRD 3.9: "Testing the waiver against the post-freight total instead would flip
    the outcome for orders whose pre-freight total sits just below the threshold,
    so the evaluation order is fixed."

    Design: Difficulty/combinatorial_formula/order_freight_waiver_evaluated_on_pre_freight_total
    """
    world = fixtures.seed_state(api, "AZ")
    fixtures.seed_title(
        api, world, isbn_base="9780000000702", list_price_cents=12400
    )

    order = validate_success(
        api.create_district_order(
            factories.district_order_payload(
                world.state_id, world.title_id, print_units=202, digital_seats=0
            ),
            fixtures.QUOTING_REP,
        ),
        201,
    )

    # 202 x 12,400 = 2,504,800 pre-freight, at or above the waiver threshold.
    assert order["freight_surcharge_cents"] == 0
    assert order["quoted_tcv_cents"] == 2504800


def test_critical_and_overdue_penalties_stack_into_a_single_score(api):
    """Three unresolved criticals plus five overdue answers dock the score to 30.

    PRD 3.7: "The score itself starts at 100 and is docked for each defect: 25
    points for every prohibited-tag hit, 10 points for every missing required
    topic, 15 points for every unresolved critical comment, and 5 points for every
    overdue response."

    Design: Difficulty/combinatorial_formula/compliance_score_weighted_penalty_stack_with_floor
    """
    world = fixtures.seed_filed_submission(
        api, "UT", state_overrides={"comment_response_days": 10}
    )
    fixtures.stack_public_comments(
        api,
        world,
        [SEVERITY_CRITICAL, SEVERITY_CRITICAL, SEVERITY_CRITICAL, SEVERITY_MINOR, SEVERITY_MINOR],
    )

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    cycle = validate_success(
        api.advance_cycle_phase(world.cycle_id, world.officer)
    )
    assert cycle["status"] == CYCLE_STATUS_CLOSED_FOR_SUBMISSION

    comments, _ = validate_paginated(
        api.list_public_comments(world.submission_id, fixtures.EDITOR)
    )
    assert [comment["status"] for comment in comments] == [COMMENT_STATUS_ESCALATED] * 5

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    # 100 - 15(3) - 5(5) = 30.
    assert submission["unresolved_critical_count"] == 3
    assert submission["overdue_response_count"] == 5
    assert submission["prohibited_hit_count"] == 0
    assert submission["missing_required_topic_count"] == 0
    assert submission["compliance_score"] == 30
    assert submission["adoption_blocked"] is True


def test_the_penalty_stack_is_floored_and_never_runs_negative(api):
    """Five escalated criticals dock exactly 100 points and the score stops at 0.

    PRD 3.7: "`compliance_score` is that result, floored at 0 — it never goes
    negative no matter how many defects accumulate."

    Design: Difficulty/combinatorial_formula/compliance_score_weighted_penalty_stack_with_floor
    """
    world = fixtures.seed_filed_submission(
        api, "UT", state_overrides={"comment_response_days": 10}
    )
    fixtures.stack_public_comments(api, world, [SEVERITY_CRITICAL] * 5)

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    get_success_data(api.advance_cycle_phase(world.cycle_id, world.officer))

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    # 100 - 15(5) - 5(5) lands exactly on the floor the score stops at.
    assert submission["unresolved_critical_count"] == 5
    assert submission["overdue_response_count"] == 5
    assert submission["compliance_score"] == 0
    assert submission["adoption_blocked"] is True
