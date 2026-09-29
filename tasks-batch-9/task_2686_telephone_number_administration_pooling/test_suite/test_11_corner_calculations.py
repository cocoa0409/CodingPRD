"""Calculations: the two utilization bases, the exhaust projection, the ceilings and the tally."""
from test_helpers import (
    ADMIN_USER_ID,
    CLOCK_PLUS_30,
    CLOCK_PLUS_180,
    CLOCK_PLUS_181,
    DEFAULT_CLOCK,
    approve_request,
    assert_pct,
    assert_sweep_report,
    close_and_recommend,
    create_eligible_carrier,
    create_filing,
    create_submitted_filing,
    file_allocation_request,
    file_comment,
    grant_license,
    list_orders,
    load_block,
    load_held_blocks,
    load_pool_blocks,
    make_rate_center_pooled,
    open_audit_finding,
    read_block,
    read_carrier,
    read_filing,
    read_npa,
    read_rate_center,
    register_carrier,
    run_sweep,
    set_clock,
    setup_npa_with_rate_center,
    setup_plan_in_public_comment,
    submit_filing,
)

RESPONSE_DUE_AFTER_SWEEP = "2027-02-28T00:00:00Z"

# Four blocks reported, 3000 assigned, and a forecast of 1500 a quarter.
SEVENTY_FIVE_WITH_FORECAST = dict(
    numbers_assigned=3000,
    numbers_intermediate=0,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=4,
    forecast_quarters=[1500, 1500, 1500, 1500],
)


def _licensed_carrier_with_a_rate_center():
    """A carrier that may file and submit, and one rate center to file against."""
    set_clock()
    carrier = register_carrier("A")
    grant_license(carrier)
    npa, rate_center = setup_npa_with_rate_center()
    return carrier, npa, rate_center


class TestTheDenominatorDropsAdministrativeAndAgingNumbers:
    """Administrative and aging numbers leave the denominator and never join the numerator."""

    def test_two_blocks_with_five_hundred_unassignable_numbers_read_sixty_six_point_six_seven(self):
        """1000 assigned over 1500 assignable numbers is 66.67, not the 50.00 that a naive
        two-thousand-number denominator would publish.

        take `blocks_held_at_period_end`, multiply by the one thousand numbers in a block, then subtract `numbers_administrative` and subtract `numbers_aging`

        takes as its numerator the sum of `numbers_assigned`, `numbers_intermediate` and `numbers_reserved`

        Design: Corner/calculations/filing_utilization_denominator_excludes_administrative_and_aging
        """
        carrier, _npa, rate_center = _licensed_carrier_with_a_rate_center()
        filing = create_filing(
            carrier, rate_center,
            numbers_assigned=1000, numbers_intermediate=0, numbers_reserved=0,
            numbers_aging=300, numbers_administrative=200,
            blocks_held_at_period_end=2, forecast_quarters=[600, 600, 600, 600],
        )

        submitted = submit_filing(carrier, filing)

        assert submitted["status"] == "SUBMITTED"
        assert_pct(submitted["claimed_utilization_pct"], 66.67, "claimed_utilization_pct")
        assert submitted["numbers_assigned"] == 1000
        assert submitted["numbers_aging"] == 300
        assert submitted["numbers_administrative"] == 200
        assert submitted["blocks_held_at_period_end"] == 2


class TestAZeroDenominatorPublishesZero:
    """When nothing is assignable the guard answers 0.00 rather than dividing."""

    def test_a_block_entirely_consumed_by_administrative_and_aging_numbers_reads_zero(self):
        """One thousand numbers, six hundred of them administrative and four hundred aging,
        leave a denominator of exactly zero.

        If that denominator is zero or negative, the result is 0.00 and no division is attempted.

        takes `numbers_assigned` alone as its numerator, excluding intermediate and reserved numbers

        Design: Corner/calculations/filing_utilization_zero_denominator_returns_zero
        """
        carrier, _npa, rate_center = _licensed_carrier_with_a_rate_center()
        filing = create_filing(
            carrier, rate_center,
            numbers_assigned=0, numbers_intermediate=0, numbers_reserved=0,
            numbers_aging=400, numbers_administrative=600,
            blocks_held_at_period_end=1, forecast_quarters=[0, 0, 0, 0],
        )

        submitted = submit_filing(carrier, filing)

        assert submitted["status"] == "SUBMITTED"
        assert_pct(submitted["claimed_utilization_pct"], 0.00, "claimed_utilization_pct")
        assert_pct(submitted["strict_utilization_pct"], 0.00, "strict_utilization_pct")
        assert submitted["submitted_at"] == DEFAULT_CLOCK


class TestPercentagesRoundHalfUp:
    """A true half-way ratio goes up, never to the nearest even digit."""

    def test_a_ratio_of_exactly_sixty_eight_point_eight_eight_five_publishes_as_sixty_eight_point_eight_nine(self):
        """13777 assigned numbers over a twenty-thousand-number denominator is exactly
        68.885, which is published as 68.89 rather than 68.88.

        Otherwise the numerator is divided by the denominator, multiplied by one hundred, and rounded half up to two decimal places.

        Design: Corner/calculations/filing_utilization_rounds_half_up_not_half_even
        """
        carrier, _npa, rate_center = _licensed_carrier_with_a_rate_center()
        filing = create_filing(
            carrier, rate_center,
            numbers_assigned=13777, numbers_intermediate=0, numbers_reserved=0,
            numbers_aging=0, numbers_administrative=0,
            blocks_held_at_period_end=20, forecast_quarters=[3000, 3000, 3000, 3000],
        )

        submitted = submit_filing(carrier, filing)

        assert_pct(submitted["claimed_utilization_pct"], 68.89, "claimed_utilization_pct")
        assert_pct(submitted["strict_utilization_pct"], 68.89, "strict_utilization_pct")


def _applicant_with_three_blocks_in_the_pool():
    """An eligible carrier and a rate center holding three pristine pool blocks."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    load_pool_blocks(npa, rate_center, 3, nxx_code="554")
    return carrier, npa, rate_center


class TestTheSnapshotReadsTheForecastNotTheHistory:
    """Two filings and a live forecast: the forward-looking variant is the one that counts."""

    def test_the_projection_follows_the_forecast_rather_than_the_assigned_growth(self):
        """The carrier's own history would report a comfortable nine months, while the
        forecast the filing carries reports six.

        At filing time the snapshot uses the forward-looking variant for `INITIAL`, `GROWTH` and `POOL_REPLENISH` requests

        adds the first two entries of the effective filing's `forecast_quarters` — the two nearest quarters — and spreads that total over a six-month demand horizon

        it is the effective filing's `audited_utilization_pct` when that field is non-null, otherwise that filing's `claimed_utilization_pct`

        Design: Corner/calculations/months_to_exhaust_prefers_the_forecast_over_the_history
        """
        carrier, _npa, rate_center = _applicant_with_three_blocks_in_the_pool()
        create_submitted_filing(
            carrier, rate_center, reporting_period="2025-H2",
            numbers_assigned=1000, numbers_intermediate=0, numbers_reserved=0,
            numbers_aging=0, numbers_administrative=0,
            blocks_held_at_period_end=2, forecast_quarters=[0, 0, 0, 0],
        )
        create_submitted_filing(carrier, rate_center, **SEVENTY_FIVE_WITH_FORECAST)

        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=2,
            justification="Two additional blocks to cover the next two forecast quarters",
        )

        assert_pct(
            request["months_to_exhaust_at_submission"], 6.00,
            "months_to_exhaust_at_submission",
        )
        assert_pct(
            request["utilization_pct_at_submission"], 75.00,
            "utilization_pct_at_submission",
        )
        assert read_rate_center(rate_center["id"])["available_block_count"] == 3


class TestAZeroForecastTakesTheSentinel:
    """No forecast at all is not a healthy projection; it is the sentinel."""

    def test_a_forecast_of_four_zeros_projects_the_sentinel_rather_than_dividing(self):
        """The monthly demand figure collapses to zero, so the projection reports 999.00 and
        the request still opens for review.

        If the monthly demand figure is zero or negative, the projection is the sentinel 999.00

        stores the rate center's projected months to exhaust, also to two decimal places

        Design: Corner/calculations/months_to_exhaust_returns_the_sentinel_when_demand_is_zero
        """
        carrier, _npa, rate_center = _applicant_with_three_blocks_in_the_pool()
        create_submitted_filing(
            carrier, rate_center,
            numbers_assigned=3000, numbers_intermediate=0, numbers_reserved=0,
            numbers_aging=0, numbers_administrative=0,
            blocks_held_at_period_end=4, forecast_quarters=[0, 0, 0, 0],
        )

        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="Growth request filed with a flat zero forecast",
        )

        assert_pct(
            request["months_to_exhaust_at_submission"], 999.00,
            "months_to_exhaust_at_submission",
        )
        assert_pct(
            request["utilization_pct_at_submission"], 75.00,
            "utilization_pct_at_submission",
        )
        assert request["status"] == "PENDING_REVIEW"


class TestOnlyPoolAvailableBlocksAreAvailable:
    """Five loaded blocks, two of them held, leave three in the pool."""

    def test_the_two_assigned_blocks_are_excluded_from_the_available_count(self):
        """The projection reads six months from three available blocks, not the ten months a
        count of all five would produce.

        Only blocks in `POOL_AVAILABLE` count toward `available_block_count`; blocks in `RESERVED`, `ASSIGNED`, `RECLAMATION_PENDING`, `AGING` or `RETIRED` are excluded

        Design: Corner/calculations/available_block_count_counts_only_pool_available_blocks
        """
        carrier, npa, rate_center = _applicant_with_three_blocks_in_the_pool()
        load_held_blocks(
            npa, rate_center, carrier, 2, nxx_code="554", first_thousands_digit=3,
        )
        create_submitted_filing(carrier, rate_center, **SEVENTY_FIVE_WITH_FORECAST)

        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="One more block for the Columbus build",
        )

        counted = read_rate_center(rate_center["id"])
        assert counted["available_block_count"] == 3
        assert counted["assigned_block_count"] == 2
        assert read_carrier(carrier["id"])["blocks_held_count"] == 2
        assert_pct(
            request["months_to_exhaust_at_submission"], 6.00,
            "months_to_exhaust_at_submission",
        )


class TestAnInitialRequestIsCappedAtASingleBlock:
    """The first block in a rate center cannot be justified by earned utilization."""

    def test_a_new_entrant_asking_for_three_blocks_is_granted_exactly_one(self):
        """Zero utilization would score a tier cap of nothing at all, yet the initial route
        hands over one block — the cleanest one — and no more.

        The entitlement itself is the smallest of four independent ceilings, none of which predicts the answer on its own.

        An `INITIAL` request forces the tier cap to 1 and the demand ceiling to 1

        Design: Corner/calculations/growth_grant_size_initial_request_is_capped_at_one_block
        """
        set_clock()
        entrant = create_eligible_carrier(
            "A", switch_clli="CLMBOH04DS0", ocn="3456",
            legal_name="Olentangy Wireless LLC", carrier_type="WIRELESS",
            months_in_operation=3,
        )
        npa, rate_center = setup_npa_with_rate_center()
        pool_blocks = load_pool_blocks(npa, rate_center, 5, nxx_code="554")
        create_submitted_filing(
            entrant, rate_center,
            numbers_assigned=0, numbers_intermediate=0, numbers_reserved=0,
            numbers_aging=0, numbers_administrative=0,
            blocks_held_at_period_end=1, forecast_quarters=[3000, 3000, 3000, 3000],
        )
        request = file_allocation_request(
            entrant, rate_center, request_type="INITIAL", requested_block_count=3,
            justification="Initial numbering resources for the Columbus launch",
        )

        approved = approve_request(request)

        assert approved["status"] == "APPROVED"
        assert approved["granted_block_count"] == 1
        assert approved["assigned_block_ids"] == [pool_blocks[0]["id"]]

        drawn = read_block(pool_blocks[0]["id"])
        assert drawn["allocation_status"] == "RESERVED"
        assert drawn["holder_carrier_id"] == entrant["id"]
        assert drawn["activation_due_at"] == CLOCK_PLUS_180
        assert drawn["activated_at"] is None

        after = read_rate_center(rate_center["id"])
        assert after["available_block_count"] == 4
        assert after["pending_request_count"] == 0
        assert read_npa(npa["id"])["status"] == "JEOPARDY"


class TestThePoolHandsOutTheCleanestBlockFirst:
    """Contamination decides the ranking; identifiers never do."""

    def test_the_pristine_block_is_drawn_and_the_contaminated_ones_stay_behind(self):
        """All three blocks are candidates in a pooled rate center, and the draw still takes
        the one with no contamination at all.

        Candidates are ordered by `contaminated_count` ascending, then `nxx_code` ascending, then `thousands_digit` ascending, then `created_at` ascending.

        The entity `id` is never a ranking input.

        unless the rate center's `pooling_status` is `POOLED` — its `contaminated_count` is exactly 0

        Design: Corner/calculations/block_pool_selection_hands_out_the_cleanest_block_first
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        clean = load_block(npa, rate_center, nxx_code="554", thousands_digit=0,
                           contaminated_count=0)
        middling = load_block(npa, rate_center, nxx_code="554", thousands_digit=1,
                             contaminated_count=40)
        dirty = load_block(npa, rate_center, nxx_code="554", thousands_digit=2,
                           contaminated_count=100)
        pooled = make_rate_center_pooled(rate_center)
        assert pooled["pooling_status"] == "POOLED"
        create_submitted_filing(carrier, rate_center, **SEVENTY_FIVE_WITH_FORECAST)
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="One growth block against a 75 percent utilization filing",
        )

        approved = approve_request(request)

        assert approved["granted_block_count"] == 1
        assert approved["assigned_block_ids"] == [clean["id"]]
        assert read_block(clean["id"])["allocation_status"] == "RESERVED"
        assert read_block(clean["id"])["holder_carrier_id"] == carrier["id"]

        for left_behind in (middling, dirty):
            untouched = read_block(left_behind["id"])
            assert untouched["allocation_status"] == "POOL_AVAILABLE"
            assert untouched["holder_carrier_id"] is None

        after = read_rate_center(rate_center["id"])
        assert after["pooling_status"] == "POOLED"
        assert after["available_block_count"] == 2
        assert after["assigned_block_count"] == 1


class TestOppositionRaisesTheCountAndNeitherWeight:
    """A comment against both options is counted but never weighed."""

    def test_the_government_objection_counts_without_tipping_the_recommendation(self):
        """Its weight of three would have outweighed the split's whole tally, and yet the
        overlay wins 3.50 against 3.00 over six comments.

        1.0 for a consumer, 1.5 for a business, 2.0 for a carrier and 3.0 for a government body

        `comment_count` counts every comment attached to the plan, including the `OPPOSE_BOTH` rows, which raise the count while contributing to neither weight

        `support_overlay_weight` is 3.50, `support_split_weight` is 3.00, `comment_count` is 6, and the recommendation is `ALL_SERVICES_OVERLAY`

        Design: Corner/calculations/comment_tally_counts_oppose_both_without_weighting_it
        """
        set_clock()
        _npa, plan = setup_plan_in_public_comment(comment_window_days=30)
        file_comment(plan, "CONSUMER", "SUPPORT_OVERLAY", "Keep my number as it is")
        file_comment(plan, "CONSUMER", "SUPPORT_OVERLAY",
                     "An overlay avoids reprinting everything")
        file_comment(plan, "BUSINESS", "SUPPORT_OVERLAY",
                     "Signage and fleet livery costs favour an overlay")
        file_comment(plan, "CARRIER", "SUPPORT_SPLIT",
                     "A split keeps ten-digit dialing off our legacy switches")
        file_comment(plan, "CONSUMER", "SUPPORT_SPLIT",
                     "Seven-digit dialing should be preserved")
        file_comment(plan, "GOVERNMENT", "OPPOSE_BOTH",
                     "Neither option addresses our PSAP routing concerns")

        set_clock(CLOCK_PLUS_30)
        closed = close_and_recommend(plan)

        assert closed["status"] == "OVERLAY_RECOMMENDED"
        assert closed["recommended_relief_type"] == "ALL_SERVICES_OVERLAY"
        assert_pct(closed["support_overlay_weight"], 3.50, "support_overlay_weight")
        assert_pct(closed["support_split_weight"], 3.00, "support_split_weight")
        assert closed["comment_count"] == 6
        assert closed["recommender_user_id"] == ADMIN_USER_ID


class TestADeltaOfExactlyFivePointsIsProbation:
    """The probation comparison includes its own boundary."""

    def test_eighty_claimed_against_seventy_five_audited_earns_probation(self):
        """The gap is exactly five points, which is a penalty rather than the nothing an
        exclusive comparison would return, and it is not yet a referral.

        Its `adjusted_utilization_pct` is the strict assigned-only basis recomputed over the adjusted inputs

        a difference of 5.00 points or more yields `PROBATION`, and anything smaller yields `NONE`

        Both comparisons are inclusive, so a difference of exactly 5.00 is `PROBATION` and one of exactly 20.00 is `RECLAMATION_REFERRAL`

        Design: Corner/calculations/audit_delta_of_exactly_five_points_is_probation
        """
        # The carrier is fully qualified on both axes, so the only thing that can
        # move its eligibility_status off ELIGIBLE is the audit penalty itself.
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        filing = create_submitted_filing(
            carrier, rate_center,
            numbers_assigned=1400, numbers_intermediate=200, numbers_reserved=0,
            numbers_aging=0, numbers_administrative=0,
            blocks_held_at_period_end=2, forecast_quarters=[500, 500, 500, 500],
        )
        assert_pct(filing["claimed_utilization_pct"], 80.00, "claimed_utilization_pct")

        finding = open_audit_finding(
            filing, "OVERSTATED_UTILIZATION",
            adjusted_numbers_assigned=1500, adjusted_numbers_administrative=0,
        )

        assert_pct(finding["adjusted_utilization_pct"], 75.00, "adjusted_utilization_pct")
        assert finding["penalty_action"] == "PROBATION"
        assert finding["status"] == "OPEN"
        assert finding["auditor_user_id"] == ADMIN_USER_ID
        assert finding["disposed_by_user_id"] is None

        audited = read_filing(filing["id"])
        assert audited["status"] == "UNDER_AUDIT"
        assert_pct(audited["claimed_utilization_pct"], 80.00, "claimed_utilization_pct")
        assert_pct(audited["strict_utilization_pct"], 70.00, "strict_utilization_pct")

        # The penalty only lands when the approver disposes of the finding.
        assert read_carrier(carrier["id"])["eligibility_status"] == "ELIGIBLE"
        assert read_carrier(carrier["id"])["probation_until"] is None


class TestTheDeadlineInstantBelongsToTheCarrier:
    """The reclamation pass compares strictly, so the deadline itself is safe."""

    def test_a_sweep_on_the_deadline_issues_nothing_and_the_next_day_issues_one(self):
        """Standing exactly on the activation deadline the block is untouched; one day later
        the same sweep reclaims it.

        A block whose `allocation_status` is `RESERVED`, whose `activated_at` is still null, and whose `activation_due_at` is

        A block whose `activation_due_at` is exactly the sweep instant is not reclaimed, because the carrier still owns that instant

        `issued_at` at the sweep instant, `response_due_at` 30 days after the sweep instant

        Design: Corner/calculations/sweep_reclaims_strictly_after_the_activation_deadline
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        block = load_held_blocks(
            npa, rate_center, carrier, 1, nxx_code="554", mark_activated=False
        )[0]
        assert block["allocation_status"] == "RESERVED"
        assert block["activation_due_at"] == CLOCK_PLUS_180

        set_clock(CLOCK_PLUS_180)
        on_the_deadline = run_sweep(rate_center_id=rate_center["id"])
        assert_sweep_report(on_the_deadline, 0, 0, 0, CLOCK_PLUS_180)
        assert read_block(block["id"])["allocation_status"] == "RESERVED"
        assert list_orders(number_block_id=block["id"]) == []

        set_clock(CLOCK_PLUS_181)
        the_next_day = run_sweep(rate_center_id=rate_center["id"])

        assert_sweep_report(the_next_day, 1, 0, 0, CLOCK_PLUS_181)
        reclaimed = read_block(block["id"])
        assert reclaimed["allocation_status"] == "RECLAMATION_PENDING"
        assert reclaimed["routing_status"] == "UNROUTED"

        orders = list_orders(number_block_id=block["id"])
        assert len(orders) == 1
        assert orders[0]["reason"] == "ACTIVATION_DEADLINE_MISSED"
        assert orders[0]["issued_at"] == CLOCK_PLUS_181
        assert orders[0]["response_due_at"] == RESPONSE_DUE_AFTER_SWEEP
