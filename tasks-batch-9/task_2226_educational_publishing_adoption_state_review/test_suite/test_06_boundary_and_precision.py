"""Values sitting exactly on a threshold, and the rounding that puts them there.

Each case pins one boundary the contract states inclusively or exclusively, and
the value one step to the wrong side of it.
"""

from test_helpers import (
    COMMENT_STATUS_RESPONDED,
    PRICING_STATUS_PRICE_FILED,
    PRICING_STATUS_UNPRICED,
    PROPOSAL_STATUS_FILED,
    PROPOSAL_STATUS_SUPERSEDED,
    REVIEW_STATUS_DRAFT,
    REVIEW_STATUS_FILED,
    REVIEW_STATUS_NOT_ADOPTED,
    SEVERITY_MINOR,
    SLOT_STATUS_TALLIED,
    TALLY_OUTCOME_RECOMMEND,
    VOTE_ABSTAIN,
    VOTE_RECOMMEND,
    VOTE_REJECT,
    ApiErrorId,
    assert_decimal_equals,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_projection_one_unit_short_of_the_tier_earns_no_volume_discount(api):
    """4,999 projected units sit below the tier and the state pays full list.

    PRD 3.6: "The **volume discount** rewards scale: `volume_discount_pct` is 0.12
    when `projected_adoption_units` is at least 20,000, otherwise 0.07 when it is
    at least 5,000, otherwise 0.00."

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_at_exactly_five_thousand_units
    """
    world = fixtures.seed_filed_submission(api, "UT")

    version = api.read_submission_version(world.submission_id, fixtures.PRICING)
    proposal = validate_success(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id,
                version,
                base_price_cents=10000,
                term_years=1,
                annual_escalator_bps=0,
                projected_adoption_units=4999,
            ),
            fixtures.PRICING,
        ),
        201,
    )

    assert_decimal_equals(proposal["volume_discount_pct"], "0.00", "volume_discount_pct")
    assert_decimal_equals(proposal["total_discount_pct"], "0.00", "total_discount_pct")
    assert proposal["net_state_price_cents"] == 10000
    assert proposal["status"] == PROPOSAL_STATUS_FILED


def test_a_projection_exactly_on_the_tier_earns_the_seven_percent_discount(api):
    """5,000 projected units cross the tier and supersede the earlier filing.

    PRD 3.6: "Every prior proposal of that submission whose `status` is `FILED` or
    `APPROVED` and whose `contract_locked` is false moves to `SUPERSEDED`."

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_at_exactly_five_thousand_units
    """
    world = fixtures.seed_filed_submission(api, "UT")

    first_version = api.read_submission_version(world.submission_id, fixtures.PRICING)
    first_id = get_success_data(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id,
                first_version,
                base_price_cents=10000,
                term_years=1,
                annual_escalator_bps=0,
                projected_adoption_units=4999,
            ),
            fixtures.PRICING,
        )
    )["id"]

    second_version = api.read_submission_version(world.submission_id, fixtures.PRICING)
    second = validate_success(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id,
                second_version,
                base_price_cents=10000,
                term_years=1,
                annual_escalator_bps=0,
                projected_adoption_units=5000,
            ),
            fixtures.PRICING,
        ),
        201,
    )

    assert_decimal_equals(second["volume_discount_pct"], "0.07", "volume_discount_pct")
    assert_decimal_equals(second["term_discount_pct"], "0.00", "term_discount_pct")
    assert_decimal_equals(second["bundle_discount_pct"], "0.00", "bundle_discount_pct")
    assert_decimal_equals(second["total_discount_pct"], "0.07", "total_discount_pct")
    assert second["net_state_price_cents"] == 9300
    assert second["avg_annual_price_cents"] == 9300
    assert second["status"] == PROPOSAL_STATUS_FILED

    superseded = validate_success(api.get_pricing_proposal(first_id, fixtures.PRICING))
    assert superseded["status"] == PROPOSAL_STATUS_SUPERSEDED

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["pricing_status"] == PRICING_STATUS_PRICE_FILED


def test_coverage_rounding_up_to_the_exact_minimum_lets_the_filing_through(api):
    """Three weight over seven rounds to 42.86 and clears a 42.86 floor.

    PRD 3.4: "The coverage percentage is then 100 multiplied by the numerator,
    divided by the denominator, rounded half up to 2 decimal places, and finally
    capped at 100.00."

    Design: Difficulty/boundary_precision_check/coverage_rounds_to_exact_minimum_while_lower_claim_is_rejected
    """
    world = fixtures.seed_state(api, "OR", min_verified_coverage_pct=42.86)
    fixtures.seed_standard(api, world, "OR.E.5.1", subject="ELA", weight=3)
    fixtures.seed_standard(api, world, "OR.E.5.2", subject="ELA", weight=4)
    fixtures.seed_cycle(api, world, subject="ELA")
    fixtures.seed_title(api, world, subject="ELA", isbn_base="9780000001301")
    fixtures.set_clock(api, fixtures.CLOCK_INSIDE_SUBMISSION_WINDOW)
    fixtures.advance_phase(api, world)

    submission_id = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id), fixtures.EDITOR
        )
    )["id"]
    entry_id = get_success_data(
        api.create_correlation(
            submission_id, factories.correlation_payload("OR.E.5.1"), fixtures.EDITOR
        )
    )["id"]

    filed = validate_success(api.file_submission(submission_id, fixtures.EDITOR))
    # Numerator 3 x 1.00 over a denominator of 3 + 4 gives 42.857..., which
    # rounds half up to exactly the state's minimum.
    assert filed["review_status"] == REVIEW_STATUS_FILED
    assert_decimal_equals(
        filed["self_reported_coverage_pct"], "42.86", "self_reported_coverage_pct"
    )
    assert_decimal_equals(
        filed["verified_coverage_pct"], "0.00", "verified_coverage_pct"
    )

    entries, _ = validate_paginated(api.list_correlations(submission_id, fixtures.EDITOR))
    assert_decimal_equals(
        {entry["id"]: entry for entry in entries}[entry_id]["effective_weight"],
        "3.00",
        "effective_weight",
    )


def test_a_passing_mention_of_the_same_standard_falls_below_the_minimum(api):
    """The same standard claimed as a MENTION reaches only 17.14 and is refused.

    PRD 3.5: "The submission's `self_reported_coverage_pct` must be at least the
    state's `min_verified_coverage_pct`, else `ERR_COVERAGE_BELOW_MINIMUM`."

    Design: Difficulty/boundary_precision_check/coverage_rounds_to_exact_minimum_while_lower_claim_is_rejected
    """
    world = fixtures.seed_state(api, "OR", min_verified_coverage_pct=42.86)
    fixtures.seed_standard(api, world, "OR.E.5.1", subject="ELA", weight=3)
    fixtures.seed_standard(api, world, "OR.E.5.2", subject="ELA", weight=4)
    fixtures.seed_cycle(api, world, subject="ELA")
    fixtures.seed_title(api, world, subject="ELA", isbn_base="9780000001301")
    title_b = get_success_data(
        api.create_title(
            factories.title_payload(
                subject="ELA", grade_low=5, grade_high=5, isbn_base="9780000001302"
            ),
            fixtures.EDITOR,
        )
    )["id"]
    get_success_data(api.release_title(title_b, fixtures.EDITOR))
    fixtures.set_clock(api, fixtures.CLOCK_INSIDE_SUBMISSION_WINDOW)
    fixtures.advance_phase(api, world)

    mastery_submission = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id), fixtures.EDITOR
        )
    )["id"]
    get_success_data(
        api.create_correlation(
            mastery_submission,
            factories.correlation_payload("OR.E.5.1"),
            fixtures.EDITOR,
        )
    )
    get_success_data(api.file_submission(mastery_submission, fixtures.EDITOR))

    mention_submission = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, title_b), fixtures.EDITOR
        )
    )["id"]
    mention_entry = get_success_data(
        api.create_correlation(
            mention_submission,
            factories.correlation_payload("OR.E.5.1", depth_level="MENTION"),
            fixtures.EDITOR,
        )
    )["id"]

    validate_error(
        api.file_submission(mention_submission, fixtures.EDITOR),
        ApiErrorId.ERR_COVERAGE_BELOW_MINIMUM,
        422,
    )

    refused = validate_success(
        api.get_submission(mention_submission, fixtures.EDITOR)
    )
    # 3 x 0.40 over 7 is 17.142..., rounding to 17.14.
    assert refused["review_status"] == REVIEW_STATUS_DRAFT
    assert_decimal_equals(
        refused["self_reported_coverage_pct"], "17.14", "self_reported_coverage_pct"
    )

    entries, _ = validate_paginated(
        api.list_correlations(mention_submission, fixtures.EDITOR)
    )
    assert_decimal_equals(
        {entry["id"]: entry for entry in entries}[mention_entry]["effective_weight"],
        "1.20",
        "effective_weight",
    )

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["submission_count"] == 1


def test_two_thirds_of_the_counted_ballots_rounds_onto_the_recommend_threshold(api):
    """An abstention leaves three counting ballots, two of them recommending.

    PRD 3.8: "The comparison is inclusive, which matters at the obvious boundary: a
    two-thirds ratio rounds to 0.6667 and therefore recommends."

    Design: Difficulty/boundary_precision_check/tally_ratio_at_exact_recommend_threshold_with_abstention
    """
    world = fixtures.seed_presented_slot(
        api,
        "AZ",
        priced=False,
        panel_overrides={"member_count": 4, "quorum_required": 3},
    )
    fixtures.cast_ballots(
        api,
        world.slot_id,
        [VOTE_RECOMMEND, VOTE_RECOMMEND, VOTE_REJECT, VOTE_ABSTAIN],
    )

    tallied = validate_success(api.tally_slot(world.slot_id, world.officer))
    assert tallied["status"] == SLOT_STATUS_TALLIED
    assert tallied["counted_vote_count"] == 4
    assert_decimal_equals(tallied["recommend_ratio"], "0.6667", "recommend_ratio")
    assert tallied["tally_outcome"] == TALLY_OUTCOME_RECOMMEND


def test_a_recommending_tally_still_adopts_nothing_while_the_price_is_unfiled(api):
    """The ratio recommends but the unpriced submission fails an adoption gate.

    PRD 3.8: "A `tally_outcome` of `REJECT` — and equally a recommending outcome
    with **any** one of the four adoption gates unmet — moves the submission's
    `review_status` from `PRESENTED` to `NOT_ADOPTED`."

    Design: Difficulty/boundary_precision_check/tally_ratio_at_exact_recommend_threshold_with_abstention
    """
    world = fixtures.seed_presented_slot(
        api,
        "AZ",
        priced=False,
        panel_overrides={"member_count": 4, "quorum_required": 3},
    )
    fixtures.cast_ballots(
        api,
        world.slot_id,
        [VOTE_RECOMMEND, VOTE_RECOMMEND, VOTE_REJECT, VOTE_ABSTAIN],
    )
    get_success_data(api.tally_slot(world.slot_id, world.officer))

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_NOT_ADOPTED
    assert submission["pricing_status"] == PRICING_STATUS_UNPRICED

    edition = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert edition["adopted_state_codes"] == []

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["adopted_count"] == 0
    assert cycle["submission_count"] == 0


def test_an_answer_one_second_before_the_deadline_is_not_overdue(api):
    """Responding at 23:59:59 on the last day beats the deadline instant.

    PRD 3.7: "Answering from `OPEN` sets `was_overdue_at_response` to true when the
    comment had already escalated or when the logical clock stands at or after
    `response_due_at`, and to false otherwise; answering from `ESCALATED` leaves
    `was_overdue_at_response` true, since the lateness is already a matter of
    record."

    Design: Difficulty/boundary_precision_check/comment_overdue_inclusive_at_exact_response_due_instant
    """
    world = fixtures.seed_filed_submission(
        api, "ID", state_overrides={"comment_response_days": 10}
    )
    comment_ids = fixtures.stack_public_comments(
        api, world, [SEVERITY_MINOR, SEVERITY_MINOR]
    )

    fixtures.set_clock(api, "2026-09-24T23:59:59Z")
    answered = validate_success(
        api.respond_to_public_comment(
            comment_ids[0], factories.comment_response_payload(), fixtures.EDITOR
        )
    )
    assert answered["status"] == COMMENT_STATUS_RESPONDED
    assert answered["was_overdue_at_response"] is False

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["overdue_response_count"] == 0
    assert submission["compliance_score"] == 100


def test_an_answer_exactly_on_the_deadline_instant_is_overdue(api):
    """The response deadline is inclusive, so 00:00:00 on the due day is late.

    PRD 3.7: "A comment is **overdue** when the logical clock stands at or after
    its `response_due_at`; the boundary is inclusive, so a response landing exactly
    on the deadline instant is late."

    Design: Difficulty/boundary_precision_check/comment_overdue_inclusive_at_exact_response_due_instant
    """
    world = fixtures.seed_filed_submission(
        api, "ID", state_overrides={"comment_response_days": 10}
    )
    comment_ids = fixtures.stack_public_comments(
        api, world, [SEVERITY_MINOR, SEVERITY_MINOR]
    )

    fixtures.set_clock(api, "2026-09-24T23:59:59Z")
    fixtures.respond_to_comment(api, comment_ids[0])

    fixtures.set_clock(api, "2026-09-25T00:00:00Z")
    late = validate_success(
        api.respond_to_public_comment(
            comment_ids[1], factories.comment_response_payload(), fixtures.EDITOR
        )
    )
    assert late["status"] == COMMENT_STATUS_RESPONDED
    assert late["was_overdue_at_response"] is True
    assert late["responded_at"].startswith("2026-09-25T00:00:00")

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    # One overdue answer docks five points; nothing else is outstanding.
    assert submission["overdue_response_count"] == 1
    assert submission["unresolved_critical_count"] == 0
    assert submission["compliance_score"] == 95
    assert submission["adoption_blocked"] is False
