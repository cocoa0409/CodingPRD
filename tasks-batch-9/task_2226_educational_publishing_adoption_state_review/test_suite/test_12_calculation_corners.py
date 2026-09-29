"""Corner cases of the numbers the adoption record maintains eagerly.

Coverage percentages, the sampling running total, the print-unit ledger and the
committee's recommendation ratio are all stored values, never derived at read
time, so each test here drives the contract's own endpoints from an empty
database and then reads the counters back off the resources.
"""

import pytest

from test_helpers import (
    COMMITTEE_MEMBER_HEADERS,
    DEPTH_MASTERY,
    DEPTH_PRACTICE,
    REVIEW_STATUS_NOT_ADOPTED,
    SAMPLING_STATUS_PARTIAL,
    SAMPLING_STATUS_PENDING,
    SAMPLING_STATUS_SHIPPED,
    SLOT_STATUS_TALLIED,
    TALLY_OUTCOME_RECOMMEND_WITH_CONDITIONS,
    TALLY_OUTCOME_REJECT,
    VOTE_RECOMMEND,
    VOTE_RECOMMEND_WITH_CONDITIONS,
    VOTE_REJECT,
    assert_decimal_equals,
    assert_print_unit_ledger_balances,
    assert_ratio_scale,
    factories as f,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    EDITOR,
    PRICING,
    cast_ballots,
    seed_cycle,
    seed_draft_submission,
    seed_presented_slot,
    seed_standard,
    seed_state,
    seed_title,
    ship_sampling_copies_to,
)


def test_out_of_grade_band_citation_is_stored_yet_leaves_coverage_at_seventy(api):
    """PRD 3.4: "Correlation entries citing a framework code that is outside the
    grade-band overlap are stored and returned by the API but contribute nothing
    to either percentage, because their standard is not in the denominator set."
    "Each entry also stores an `effective_weight`, the cited standard's `weight`
    multiplied by the depth multiplier of the claimed `depth_level`, rounded half
    up to 2 decimal places." "The computation starts from the **denominator
    set**: every `StateStandard` whose `state_id` equals the cycle's state and
    whose `subject` equals the cycle's subject, and whose grade band overlaps the
    edition's — meaning the standard's `grade_high` is at least the edition's
    `grade_low` and the standard's `grade_low` is at most the edition's
    `grade_high`." "The depth multipliers are 0.40 for `MENTION`, 0.70 for
    `PRACTICE` and 1.00 for `MASTERY`." "The coverage percentage is then 100
    multiplied by the numerator, divided by the denominator, rounded half up to 2
    decimal places, and finally capped at 100.00." "The **committee-verified**
    variant accepts only entries whose `reviewer_verdict` is `ACCEPTED`,
    discarding both `PENDING` and `INSUFFICIENT` evidence, and is stored in
    `verified_coverage_pct`; it is the gate at adoption time."

    The Tennessee framework carries a grade 8 MATH standard alongside the grade 6
    one. A grade 6 edition may cite the eighth-grade code — it is a real code in
    the state's MATH framework — and the entry keeps its own weight, but the
    eighth-grade standard is outside the denominator set and so moves neither
    half of the fraction.

    Design: Corner/calculations/out_of_grade_band_standard_is_stored_but_excluded_from_coverage
    """
    world = seed_state(api, "TN", min_verified_coverage_pct=50.00)
    seed_standard(
        api, world, "TN.M.6.1", subject="MATH", grade_low=6, grade_high=6, weight=4
    )
    seed_standard(
        api, world, "TN.M.8.1", subject="MATH", grade_low=8, grade_high=8, weight=5
    )
    seed_cycle(api, world, subject="MATH", cycle_year=2027)
    seed_title(
        api,
        world,
        subject="MATH",
        grade_low=6,
        grade_high=6,
        content_tags=["RATIO_REASONING"],
        page_count=320,
        list_price_cents=9100,
    )

    # The grade 6 standard, weight 4, cited at PRACTICE: 4 x 0.70 over a
    # denominator of 4 is 70.00 percent.
    seed_draft_submission(
        api,
        world,
        depth_levels=(DEPTH_PRACTICE,),
        standard_codes=["TN.M.6.1"],
    )
    in_band_entry_id = world.correlation_ids[0]

    out_of_band = validate_success(
        api.create_correlation(
            world.submission_id,
            f.correlation_payload(
                "TN.M.8.1",
                depth_level=DEPTH_MASTERY,
                page_reference="pp. 300-318",
                evidence_citation=(
                    "The stretch appendix develops the eighth-grade standard to mastery."
                ),
            ),
            EDITOR,
        ),
        expected_status=201,
    )
    assert_decimal_equals(
        out_of_band["effective_weight"], "5.00", "out-of-band effective_weight"
    )

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert_decimal_equals(
        submission["self_reported_coverage_pct"], "70.00", "self_reported_coverage_pct"
    )
    assert_decimal_equals(
        submission["verified_coverage_pct"], "0.00", "verified_coverage_pct"
    )

    entries, meta = validate_paginated(
        api.list_correlations(world.submission_id, EDITOR)
    )
    assert meta["total_count"] == 2, "Both citations must be stored and returned"
    by_id = {entry["id"]: entry for entry in entries}
    assert_decimal_equals(
        by_id[in_band_entry_id]["effective_weight"], "2.80", "in-band effective_weight"
    )
    assert_decimal_equals(
        by_id[out_of_band["id"]]["effective_weight"],
        "5.00",
        "out-of-band effective_weight",
    )


def test_sampling_running_total_walks_pending_partial_shipped_with_the_ledger(api):
    """PRD 3.4: "Each accepted shipment adds its `units` to the submission's
    cumulative `sample_copies_shipped`, and simultaneously draws the copies out
    of the warehouse: the edition's `on_hand_units` decreases by `units` and its
    `sample_reserved_units` increases by the same `units`." "After each shipment,
    `sampling_status` is recomputed against the state's
    `sampling_copies_required`: it is `NOT_REQUIRED` when the state requires zero
    copies; otherwise it is `SHIPPED` once `sample_copies_shipped` has reached
    the required number or gone beyond it, `PARTIAL` when at least one copy has
    shipped but the requirement is not yet met, and `PENDING` when nothing has
    shipped." "Creation also seeds `sampling_status` from the state's sampling
    requirement and computes the compliance counters and `compliance_score` from
    the state's content rules, so an editor can see at a glance what still stands
    between the draft and a filing." PRD 2.10: "The **print-unit ledger** of a
    title states that `total_received_units` always equals the sum of
    `on_hand_units`, `committed_units`, `sample_reserved_units`,
    `fulfilled_units` and `written_off_units`."

    Kansas asks for thirty sample copies. Ten copies leave the warehouse, then
    twenty more land the running total exactly on the requirement, which is the
    inclusive edge of `SHIPPED`.

    Design: Corner/calculations/sampling_status_walks_pending_partial_shipped_with_ledger
    """
    world = seed_state(
        api, "KS", sampling_copies_required=30, min_verified_coverage_pct=50.00
    )
    seed_cycle(api, world, subject="ELA", cycle_year=2027)
    seed_title(
        api,
        world,
        receipt_units=100,
        subject="ELA",
        grade_low=2,
        grade_high=2,
        content_tags=["PHONICS"],
        page_count=260,
        list_price_cents=8300,
    )

    created = validate_success(
        api.create_submission(
            f.submission_payload(world.cycle_id, world.title_id), EDITOR
        ),
        expected_status=201,
    )
    world.submission_id = created["id"]
    assert created["sample_copies_shipped"] == 0
    assert created["sampling_status"] == SAMPLING_STATUS_PENDING

    ship_sampling_copies_to(api, world, 10)
    after_first = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert after_first["sample_copies_shipped"] == 10
    assert after_first["sampling_status"] == SAMPLING_STATUS_PARTIAL

    ship_sampling_copies_to(api, world, 20)
    after_second = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert after_second["sample_copies_shipped"] == 30
    assert after_second["sampling_status"] == SAMPLING_STATUS_SHIPPED

    title = validate_success(api.get_title(world.title_id, EDITOR))
    assert title["on_hand_units"] == 70
    assert title["sample_reserved_units"] == 30
    assert title["total_received_units"] == 100
    assert_print_unit_ledger_balances(title)


def test_member_revote_supersedes_the_first_ballot_and_flips_the_outcome(api):
    """PRD 3.8: "**Ballots are an append-only log**: a member who changes
    position simply casts another ballot, and the server assigns each new ballot
    a `sequence_no`, a monotonic per-slot integer starting at 1, and sets
    `superseded` to true on every earlier ballot of that same member on that same
    slot." "The ballot log can be listed in full, superseded entries included,
    filtered by `vote` and by `superseded`." "The projection keeps exactly one
    ballot per distinct `member_user_id`: the one with the latest `created_at`,
    and among ballots tied on `created_at` the one with the higher `sequence_no`
    — never the one with any particular `id`." "The number of surviving ballots,
    abstentions included, is `counted_vote_count`." "Otherwise a weighted
    recommendation total is formed: each counted `RECOMMEND` ballot contributes
    1, and each counted `RECOMMEND_WITH_CONDITIONS` ballot contributes one half."
    "`recommend_ratio` is that total divided by the number of counted
    non-abstaining ballots, rounded half up to 4 decimal places." "When
    `recommend_ratio` is at or above 0.6667, the slot's `tally_outcome` is
    `RECOMMEND_WITH_CONDITIONS` if at least one counted ballot was
    `RECOMMEND_WITH_CONDITIONS`, and `RECOMMEND` otherwise; when
    `recommend_ratio` is below 0.6667, the `tally_outcome` is `REJECT`." "The
    slot's `status` moves from `PRESENTED` to `TALLIED`, a terminal slot state."
    "A `tally_outcome` of `REJECT` — and equally a recommending outcome with
    **any** one of the four adoption gates unmet — moves the submission's
    `review_status` from `PRESENTED` to `NOT_ADOPTED`."

    Three members recommend and one rejects, which alone would carry the slot at
    three quarters. The first member then changes position, and because only the
    latest ballot of each member is counted the ratio halves and the hearing ends
    in a rejection.

    Design: Corner/calculations/member_revote_supersedes_earlier_ballot_and_flips_outcome
    """
    world = seed_presented_slot(
        api,
        "ID",
        subject="MATH",
        grade=3,
        priced=False,
        panel_overrides={"member_count": 4, "quorum_required": 3},
    )
    seats = COMMITTEE_MEMBER_HEADERS

    first_ballot = validate_success(
        api.cast_vote(
            world.slot_id,
            f.vote_payload(VOTE_RECOMMEND, rationale="Strong alignment on the whole."),
            seats[0],
        ),
        expected_status=201,
    )
    for seat, vote, rationale in (
        (seats[1], VOTE_RECOMMEND, "Clear teacher supports."),
        (seats[2], VOTE_RECOMMEND, "Assessment bank is adequate."),
        (seats[3], VOTE_REJECT, "Manipulatives are missing."),
    ):
        validate_success(
            api.cast_vote(world.slot_id, f.vote_payload(vote, rationale=rationale), seat),
            expected_status=201,
        )

    recast = validate_success(
        api.cast_vote(
            world.slot_id,
            f.vote_payload(
                VOTE_REJECT, rationale="On reflection the pacing guide is unusable."
            ),
            seats[0],
        ),
        expected_status=201,
    )
    assert recast["sequence_no"] == 5, "The fifth ballot on the slot is the recast one"
    assert recast["superseded"] is False

    ballots, meta = validate_paginated(api.list_votes(world.slot_id, world.officer))
    assert meta["total_count"] == 5, "The log keeps the superseded ballot"
    logged = {ballot["id"]: ballot for ballot in ballots}
    assert logged[first_ballot["id"]]["superseded"] is True

    slot = validate_success(api.tally_slot(world.slot_id, world.officer))
    assert slot["counted_vote_count"] == 4
    assert_ratio_scale(slot["recommend_ratio"])
    assert_decimal_equals(slot["recommend_ratio"], "0.5000", "recommend_ratio")
    assert slot["tally_outcome"] == TALLY_OUTCOME_REJECT
    assert slot["status"] == SLOT_STATUS_TALLIED

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_NOT_ADOPTED


def test_one_conditional_ballot_lands_the_submission_in_adopted_with_conditions(api):
    """PRD 3.8: "Otherwise a weighted recommendation total is formed: each
    counted `RECOMMEND` ballot contributes 1, and each counted
    `RECOMMEND_WITH_CONDITIONS` ballot contributes one half."
    "`recommend_ratio` is that total divided by the number of counted
    non-abstaining ballots, rounded half up to 4 decimal places." "When
    `recommend_ratio` is at or above 0.6667, the slot's `tally_outcome` is
    `RECOMMEND_WITH_CONDITIONS` if at least one counted ballot was
    `RECOMMEND_WITH_CONDITIONS`, and `RECOMMEND` otherwise; when
    `recommend_ratio` is below 0.6667, the `tally_outcome` is `REJECT`." "A
    `tally_outcome` of `RECOMMEND` moves the submission's `review_status` from
    `PRESENTED` to `ADOPTED` **provided every adoption gate is met**; a
    `tally_outcome` of `RECOMMEND_WITH_CONDITIONS` does the same but lands on
    `ADOPTED_WITH_CONDITIONS`." "The adoption gates are four: the submission's
    `pricing_status` must be `PRICE_APPROVED`, its `verified_coverage_pct` must
    be at least the state's `min_verified_coverage_pct`, its `adoption_blocked`
    must be false, and its `unresolved_critical_count` must be zero." "When
    adoption succeeds, the edition's `adopted_state_codes` gains the state's
    `state_code`, the edition's `status` moves from `DRAFT` to `ACTIVE` if it
    happened still to be `DRAFT`, the submission's `APPROVED` pricing proposal
    sets `contract_locked` to true, the cycle's `adopted_count` increases by 1
    and its `submission_count` decreases by 1."

    Three plain recommendations and one conditional one weigh 3.5 across four
    non-abstaining ballots. The ratio clears the two-thirds threshold, but the
    single conditional ballot is enough to carry the conditions through to the
    submission's terminal status.

    Design: Corner/calculations/conditions_weight_lifts_ratio_to_adopted_with_conditions
    """
    world = seed_presented_slot(
        api,
        "VA",
        subject="MATH",
        grade=5,
        priced=True,
        panel_overrides={"member_count": 4, "quorum_required": 3},
        title_overrides={"content_tags": ["FRACTION_MODELS"]},
    )
    cast_ballots(api, world.slot_id, [VOTE_RECOMMEND] * 3)
    validate_success(
        api.cast_vote(
            world.slot_id,
            f.vote_payload(
                VOTE_RECOMMEND_WITH_CONDITIONS,
                rationale="Adopt only if the errata sheet ships with the first order.",
            ),
            COMMITTEE_MEMBER_HEADERS[3],
        ),
        expected_status=201,
    )

    slot = validate_success(api.tally_slot(world.slot_id, world.officer))
    assert slot["counted_vote_count"] == 4
    assert_ratio_scale(slot["recommend_ratio"])
    assert_decimal_equals(slot["recommend_ratio"], "0.8750", "recommend_ratio")
    assert slot["tally_outcome"] == TALLY_OUTCOME_RECOMMEND_WITH_CONDITIONS

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == "ADOPTED_WITH_CONDITIONS"
    assert_decimal_equals(
        submission["verified_coverage_pct"], "100.00", "verified_coverage_pct"
    )

    proposal = validate_success(api.get_pricing_proposal(world.proposal_id, PRICING))
    assert proposal["contract_locked"] is True

    title = validate_success(api.get_title(world.title_id, EDITOR))
    assert "VA" in title["adopted_state_codes"]

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["adopted_count"] == 1
    assert cycle["submission_count"] == 0
