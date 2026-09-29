"""Endorsements: the pinned five-step recomputation, the four-hop cascade into
the ledger, and the exact reversibility of a void.
"""

import pytest

from test_helpers import (
    ERR_INVALID_STATE,
    ERR_PREMIUM_WOULD_BE_NON_POSITIVE,
    ERR_STALE_POLICY_VERSION,
    ERR_SUPERSEDE_TARGET_INVALID,
    assert_allocation_row,
    assert_filing_line,
    assert_ledger_reconciles,
    assert_parts_sum_to,
    assert_policy_dimensions,
    by_state,
    endorsement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_voiding_an_already_voided_endorsement_is_locked_out(endorsed_world):
    """The first void compensates the ledger; the second has nowhere to go.

    PRD 3.8: "Otherwise the endorsement's `status` becomes `VOIDED`; the policy's
    premium, allocation rows and totals are recomputed from the *remaining* issued
    endorsement set by exactly the procedure above; one compensating tax filing
    line with `line_type` `ENDORSEMENT` and `status` `OPEN` is created per affected
    state carrying the exact negation of the voided endorsement's per-state tax and
    stamping deltas; the policy's `tax_status` advances to `ADJUSTED`; and both the
    endorsement's `version` and the policy's `version` increment by one each."

    Design: Corner/state_machines/voiding_an_already_voided_endorsement_is_locked_out
    """
    world = endorsed_world
    endorsement = world.endorsement
    assert endorsement["status"] == "ISSUED"

    voided = world.void_endorsement()
    assert voided["status"] == "VOIDED"
    assert voided["version"] == endorsement["version"] + 1
    assert_policy_dimensions(world.get_policy(), tax_status="ADJUSTED")

    endorsement_lines = world.filing_lines(line_type="ENDORSEMENT")
    assert len(endorsement_lines) == 6
    assert all(line["status"] == "OPEN" for line in endorsement_lines)
    # The three compensating lines exactly negate the three issuing lines.
    assert sum(line["tax_cents"] for line in endorsement_lines) == 0

    validate_error(
        world.api.void_endorsement(endorsement["id"], world.broker_headers),
        ERR_INVALID_STATE,
        409,
    )
    again = validate_success(
        world.api.get_endorsement(endorsement["id"], world.broker_headers), 200
    )
    assert again["status"] == "VOIDED"
    assert again["version"] == voided["version"]
    assert len(world.filing_lines(line_type="ENDORSEMENT")) == 6


def test_an_endorsement_that_would_zero_the_premium_is_refused(calculated_world):
    """A decrease that consumes the whole gross premium cannot be issued.

    PRD 3.8: "Four preconditions guard it: the policy's `status` must be `ISSUED`,
    else `ERR_POLICY_NOT_ISSUED`; the policy's `tax_status` must not be
    `UNCALCULATED`, else `ERR_TAX_NOT_CALCULATED`; when `supersedes_endorsement_id`
    is non-null, the named endorsement must have `status` `ISSUED` and belong to the
    same policy, else `ERR_SUPERSEDE_TARGET_INVALID`; and the resulting
    `gross_premium_cents` must remain strictly greater than zero, else
    `ERR_PREMIUM_WOULD_BE_NON_POSITIVE`."

    Design: Corner/errors/an_endorsement_that_would_zero_the_premium_is_refused
    """
    world = calculated_world
    policy = world.get_policy()
    assert policy["gross_premium_cents"] == 1_000_000

    wipeout = world.draft_endorsement(
        endorsement_type="PREMIUM_DECREASE", premium_delta_cents=-1_000_000
    )
    assert wipeout["status"] == "DRAFT"

    validate_error(
        world.api.issue_endorsement(wipeout["id"], world.broker_headers),
        ERR_PREMIUM_WOULD_BE_NON_POSITIVE,
        422,
    )
    after = world.get_policy()
    assert after["gross_premium_cents"] == 1_000_000
    assert after["total_tax_cents"] == 38779
    assert_policy_dimensions(after, tax_status="CALCULATED")
    assert (
        validate_success(world.api.get_endorsement(wipeout["id"], world.broker_headers), 200)[
            "status"
        ]
        == "DRAFT"
    )

    smaller = world.draft_endorsement(
        endorsement_type="PREMIUM_DECREASE", premium_delta_cents=-500_000
    )
    issued = world.issue_endorsement(smaller)
    assert issued["status"] == "ISSUED"
    assert world.get_policy()["gross_premium_cents"] == 500_000


def test_superseding_an_endorsement_that_was_never_issued_is_refused(calculated_world):
    """Only an `ISSUED` endorsement can be superseded.

    PRD 3.8: "When `supersedes_endorsement_id` is non-null, the superseded
    endorsement is moved to `VOIDED` first and its own compensating lines are
    emitted before this endorsement's."

    Design: Corner/errors/superseding_an_endorsement_that_was_never_issued_is_refused
    """
    world = calculated_world
    original = world.draft_endorsement()
    assert original["status"] == "DRAFT"
    assert original["sequence_number"] == 1

    replacement = world.draft_endorsement(supersedes_endorsement_id=original["id"])
    assert replacement["sequence_number"] == 2
    assert replacement["supersedes_endorsement_id"] == original["id"]

    validate_error(
        world.api.issue_endorsement(replacement["id"], world.broker_headers),
        ERR_SUPERSEDE_TARGET_INVALID,
        422,
    )

    # Once the target really is issued the supersede is allowed and voids it.
    world.issue_endorsement(original)
    successor = world.draft_endorsement(supersedes_endorsement_id=original["id"])
    issued = world.issue_endorsement(successor)
    assert issued["status"] == "ISSUED"
    assert (
        validate_success(world.api.get_endorsement(original["id"], world.broker_headers), 200)[
            "status"
        ]
        == "VOIDED"
    )
    assert world.get_policy()["gross_premium_cents"] == 1_200_000


def test_an_endorsement_created_from_a_pre_notice_policy_view_is_rejected_as_stale(
    policy_world,
):
    """A premium base that predates the notices and the calculation is stale.

    PRD 2.10: "Creating an endorsement requires `expected_policy_version`, matching
    the target policy's current `version`. A mismatch is rejected with
    `ERR_STALE_POLICY_VERSION` (HTTP 412). A policy legitimately carries an
    unbounded number of endorsements, so again no state field bars a second create;
    the version check is what catches a client whose premium base predates another
    writer's endorsement issuance, tax calculation or notice affixing."

    Design: Corner/cross_cutting_complexity_layers/an_endorsement_created_from_a_pre_notice_policy_view_is_rejected_as_stale
    """
    world = policy_world
    at_issue = world.policy["version"]

    world.affix_notices(["TX-SL-1", "TX-SL-2"])
    current = world.calculate_tax()
    assert current["version"] > at_issue

    validate_error(
        world.api.create_endorsement(
            current["id"], endorsement_payload(at_issue), world.broker_headers
        ),
        ERR_STALE_POLICY_VERSION,
        412,
    )
    rows, meta = validate_paginated(
        world.api.list_endorsements(world.broker_headers, {"policy_id": current["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0

    fresh = validate_success(
        world.api.create_endorsement(
            current["id"], endorsement_payload(current["version"]), world.broker_headers
        ),
        201,
    )
    assert fresh["status"] == "DRAFT"
    assert fresh["sequence_number"] == 1
    assert fresh["tax_adjustment_cents"] == 0
    assert fresh["stamping_fee_adjustment_cents"] == 0


def test_allocation_rows_keep_the_rates_pinned_at_calculation_time(calculated_world):
    """An amended program never reaches an existing row, even on recomputation.

    PRD 2.7: "Each allocation row records `premium_tax_rate_applied` and
    `stamping_fee_rate_applied`, copied from that state's program at the instant the
    row is first created. Every subsequent recomputation — endorsement issue,
    endorsement void, cancellation processing — reuses those pinned rates, never the
    program's current ones."

    Design: Corner/cross_cutting_complexity_layers/allocation_rows_keep_the_rates_pinned_at_calculation_time
    """
    world = calculated_world
    world.patch_program("TX", {"premium_tax_rate": 0.1000, "stamping_fee_rate": 0.0100})

    world.draft_endorsement()
    world.issue_endorsement()

    texas = by_state(world.allocations())["TX"]
    assert texas["premium_tax_rate_applied"] == pytest.approx(0.0485)
    assert texas["stamping_fee_rate_applied"] == pytest.approx(0.0015)
    assert texas["allocated_premium_cents"] == 408_333
    # 408,333 x 0.0485 rounded half up, not the amended 10%.
    assert texas["tax_cents"] == 19804
    assert texas["stamping_fee_cents"] == 612
    assert world.get_policy()["total_tax_cents"] == 46346


def test_the_endorsement_recomputation_follows_the_pinned_four_stage_order(
    calculated_world,
):
    """Gross, then taxable, then the pinned split, then the pinned rates.

    PRD 3.8: "The recomputation has a pinned evaluation order, because the taxable
    premium feeds the allocation, the allocation feeds the per-state tax, and the
    per-state tax feeds the adjustment; reversing any two steps yields a different
    number."

    Design: Difficulty/combinatorial_formula/endorsement_adjustment_evaluation_order_is_pinned_through_four_stages
    """
    world = calculated_world
    before = world.get_policy()
    assert before["total_tax_cents"] == 38779

    world.draft_endorsement(premium_delta_cents=200_000)
    endorsement = world.issue_endorsement()
    policy = world.get_policy()

    # Stage one and two: gross from the issued set, taxable adds the policy fee.
    assert policy["gross_premium_cents"] == 1_200_000
    assert policy["taxable_premium_cents"] == 1_225_000

    # Stage three: the frozen percentages, normalised and split by largest
    # remainder with the ascending state_code tie-break.
    rows = by_state(world.allocations())
    assert rows["CA"]["allocation_pct"] == pytest.approx(0.3333)
    assert rows["CA"]["allocated_premium_cents"] == 408_334
    assert rows["NV"]["allocated_premium_cents"] == 408_333
    assert rows["TX"]["allocated_premium_cents"] == 408_333
    assert_parts_sum_to(world.allocations(), "allocated_premium_cents", 1_225_000)

    # Stage four: each row re-derived from its own pinned rate.
    assert_allocation_row(rows["CA"], tax_cents=12250, stamping_fee_cents=735)
    assert_allocation_row(rows["NV"], tax_cents=14292)
    assert_allocation_row(rows["TX"], tax_cents=19804, stamping_fee_cents=612)
    assert policy["total_tax_cents"] == 46346

    # Stage five: the adjustment is the after-minus-before difference.
    assert endorsement["tax_adjustment_cents"] == 7567
    assert endorsement["tax_adjustment_cents"] == (
        policy["total_tax_cents"] - before["total_tax_cents"]
    )
    assert endorsement["stamping_fee_adjustment_cents"] == (
        policy["total_stamping_fee_cents"] - before["total_stamping_fee_cents"]
    )
    assert_policy_dimensions(policy, tax_status="ADJUSTED")


def test_the_premium_is_always_rebuilt_from_the_full_issued_endorsement_set(
    calculated_world,
):
    """Two increases stack, and voiding the second restores the first exactly.

    PRD 3.8: "Step one recomputes `gross_premium_cents` as
    `original_gross_premium_cents` plus the sum of `premium_delta_cents` across the
    policy's endorsements whose `status` is `ISSUED` — always from the full issued
    set, never by incrementally adding a delta to the stored figure, and that is
    precisely what makes a void exactly reversible."

    Design: Difficulty/combinatorial_formula/endorsement_adjustment_evaluation_order_is_pinned_through_four_stages
    """
    world = calculated_world
    first = world.draft_endorsement(premium_delta_cents=200_000)
    world.issue_endorsement(first)
    after_first = world.get_policy()
    assert after_first["gross_premium_cents"] == 1_200_000
    assert after_first["total_tax_cents"] == 46346

    second = world.draft_endorsement(premium_delta_cents=300_000)
    issued_second = world.issue_endorsement(second)
    stacked = world.get_policy()
    assert stacked["gross_premium_cents"] == 1_500_000
    assert stacked["taxable_premium_cents"] == 1_525_000
    rows = by_state(world.allocations())
    assert rows["CA"]["allocated_premium_cents"] == 508_334
    assert_allocation_row(rows["CA"], tax_cents=15250)
    assert_allocation_row(rows["NV"], tax_cents=17792)
    assert_allocation_row(rows["TX"], tax_cents=24654)
    assert stacked["total_tax_cents"] == 57696
    assert issued_second["tax_adjustment_cents"] == 11350

    world.void_endorsement(issued_second)
    restored = world.get_policy()
    assert restored["gross_premium_cents"] == 1_200_000
    assert restored["total_tax_cents"] == 46346
    restored_rows = by_state(world.allocations())
    assert restored_rows["CA"]["allocated_premium_cents"] == 408_334
    assert_allocation_row(restored_rows["CA"], tax_cents=12250)
    assert_allocation_row(restored_rows["NV"], tax_cents=14292)
    assert_allocation_row(restored_rows["TX"], tax_cents=19804)


def test_issuing_an_endorsement_emits_one_filing_line_per_moved_state(calculated_world):
    """The fourth hop lands in the ledger, one signed line per moved state.

    PRD 2.8: "Issuing an endorsement is a four-hop cascade. The first hop writes
    the endorsement's own `status`. The second hop, caused by the first, recomputes
    the policy's `gross_premium_cents` and `taxable_premium_cents` from the full set
    of issued endorsements. The third hop, caused by the second, recomputes every
    allocation row of the policy in place and refreshes `total_tax_cents` and
    `total_stamping_fee_cents` on the policy. The fourth hop, caused by the third,
    emits a tax filing line for each state whose figures actually moved."

    Design: Difficulty/transitive_cascade/endorsement_issue_cascades_four_hops_to_new_tax_filing_lines
    """
    world = calculated_world
    world.draft_endorsement(premium_delta_cents=200_000)
    endorsement = world.issue_endorsement()

    lines = world.filing_lines(source_endorsement_id=endorsement["id"])
    assert len(lines) == 3
    assert [line["state_program_id"] for line in lines] == [
        world.program_id("CA"),
        world.program_id("NV"),
        world.program_id("TX"),
    ]
    california, nevada, texas = lines

    assert_filing_line(
        california,
        line_type="ENDORSEMENT",
        status="OPEN",
        taxable_premium_cents=66_667,
        tax_cents=2000,
        stamping_fee_cents=120,
        source_endorsement_id=endorsement["id"],
    )
    assert_filing_line(
        nevada,
        line_type="ENDORSEMENT",
        status="OPEN",
        taxable_premium_cents=66_666,
        tax_cents=2334,
    )
    assert_filing_line(
        texas,
        line_type="ENDORSEMENT",
        status="OPEN",
        taxable_premium_cents=66_667,
        tax_cents=3233,
        stamping_fee_cents=100,
    )
    assert sum(line["taxable_premium_cents"] for line in lines) == 200_000
    assert sum(line["tax_cents"] for line in lines) == endorsement["tax_adjustment_cents"]


def test_the_endorsement_cascade_adds_ledger_lines_without_touching_the_old_ones(
    calculated_world,
):
    """The adjusting lines are new rows; the original lines are left alone.

    PRD 3.8: "One tax filing line with `line_type` `ENDORSEMENT`,
    `source_endorsement_id` set to this endorsement and `status` `OPEN` is emitted
    for each state whose `tax_cents` **or** `stamping_fee_cents` actually moved, in
    ascending `state_code` order; each such line carries as its
    `taxable_premium_cents` the change in that state's `allocated_premium_cents`, as
    its `tax_cents` that state's signed tax movement, and as its
    `stamping_fee_cents` that state's signed stamping movement."

    Design: Difficulty/transitive_cascade/endorsement_issue_cascades_four_hops_to_new_tax_filing_lines
    """
    world = calculated_world
    policy = world.get_policy()
    original = world.filing_lines(policy_id=policy["id"])
    assert len(original) == 3
    original_ids = {line["id"] for line in original}
    original_tax = {line["id"]: line["tax_cents"] for line in original}

    world.draft_endorsement(premium_delta_cents=200_000)
    endorsement = world.issue_endorsement()
    assert endorsement["status"] == "ISSUED"

    all_lines = world.filing_lines(policy_id=policy["id"])
    assert len(all_lines) == 6
    kept = [line for line in all_lines if line["id"] in original_ids]
    assert len(kept) == 3
    for line in kept:
        assert_filing_line(line, line_type="NEW_BUSINESS", status="OPEN")
        assert line["tax_cents"] == original_tax[line["id"]]
        assert line["source_endorsement_id"] is None

    added = [line for line in all_lines if line["id"] not in original_ids]
    assert len(added) == 3
    for line in added:
        assert_filing_line(
            line,
            line_type="ENDORSEMENT",
            status="OPEN",
            policy_id=policy["id"],
            source_endorsement_id=endorsement["id"],
        )
        assert line["source_cancellation_id"] is None


def test_the_ledger_reconciles_with_the_policy_tax_total_after_an_endorsement(
    calculated_world,
):
    """The signed sum of every line equals the policy's tax total, always.

    PRD 3.7: "Calculation also opens the ledger. One tax filing line with
    `line_type` `NEW_BUSINESS` and `status` `OPEN` is created per allocated state,
    in ascending `state_code` order, carrying that state's `taxable_premium_cents`,
    `tax_cents` and `stamping_fee_cents`."

    Design: Difficulty/compensating_invariant/tax_filing_line_ledger_always_reconciles_with_the_policy_tax_total
    """
    world = calculated_world
    policy = world.get_policy()
    assert_ledger_reconciles(world.filing_lines(policy_id=policy["id"]), 38779)

    world.draft_endorsement(premium_delta_cents=200_000)
    world.issue_endorsement()
    adjusted = world.get_policy()
    assert adjusted["total_tax_cents"] == 46346
    assert_ledger_reconciles(world.filing_lines(policy_id=policy["id"]), 46346)

    world.draft_endorsement(premium_delta_cents=300_000)
    world.issue_endorsement()
    stacked = world.get_policy()
    assert stacked["total_tax_cents"] == 57696
    assert_ledger_reconciles(world.filing_lines(policy_id=policy["id"]), 57696)


def test_the_ledger_reconciles_again_after_the_endorsement_is_voided(calculated_world):
    """A void writes the exact negation, so the invariant survives the round trip.

    PRD 3.8: "**The tax dimension is cyclic.** `CALCULATED → ADJUSTED` fires
    whenever an endorsement is issued, an endorsement is voided or a cancellation
    is processed while the policy's `tax_status` is anything other than
    `UNCALCULATED`; the allocation rows are recomputed in place using their pinned
    rates, an adjusting line is created per affected state, and the policy's
    `version` increments."

    Design: Difficulty/compensating_invariant/tax_filing_line_ledger_always_reconciles_with_the_policy_tax_total
    """
    world = calculated_world
    policy = world.get_policy()

    world.draft_endorsement(premium_delta_cents=200_000)
    endorsement = world.issue_endorsement()
    assert_ledger_reconciles(world.filing_lines(policy_id=policy["id"]), 46346)

    world.void_endorsement(endorsement)
    restored = world.get_policy()
    assert restored["total_tax_cents"] == 38779
    assert_policy_dimensions(restored, tax_status="ADJUSTED")

    lines = world.filing_lines(policy_id=policy["id"])
    assert len(lines) == 9
    assert_ledger_reconciles(lines, 38779)
    adjusting = world.filing_lines(policy_id=policy["id"], line_type="ENDORSEMENT")
    assert len(adjusting) == 6
    assert sum(line["tax_cents"] for line in adjusting) == 0
