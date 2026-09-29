"""Cancellations: the three-step refund arithmetic, the minimum earned premium
floor that can override it, and the negative mirror image written to the ledger.
"""

from test_helpers import (
    ERR_CANCELLATION_DATE_OUT_OF_TERM,
    ERR_FLAT_CANCELLATION_NOT_AVAILABLE,
    ERR_POLICY_NOT_ISSUED,
    assert_filing_line,
    assert_parts_sum_to,
    assert_policy_dimensions,
    by_state,
    validate_error,
    validate_success,
)


def test_policy_state_advances_through_the_full_issue_to_cancelled_pipeline(
    calculated_world,
):
    """One request retires the cancellation and moves two policy dimensions.

    PRD 3.8: "**Processing the cancellation** advances `REQUESTED → PROCESSED`,
    which is terminal, and simultaneously drives the policy's `status` dimension
    `ISSUED → CANCELLED` and its `tax_status` dimension to `ADJUSTED`."

    Design: Corner/state_machines/policy_state_advances_through_the_full_issue_to_cancelled_pipeline
    """
    world = calculated_world
    before = world.get_policy()
    assert_policy_dimensions(before, status="ISSUED", tax_status="CALCULATED")

    requested = world.request_cancellation(
        cancellation_type="PRO_RATA", cancellation_date="2026-11-01T00:00:00Z"
    )
    assert requested["status"] == "REQUESTED"
    assert requested["return_premium_cents"] == 0

    processed = world.process_cancellation(requested)
    assert processed["status"] == "PROCESSED"
    # 92 elapsed days of a 365-day term: 1,025,000 x 273 / 365 rounded half up.
    assert processed["return_premium_cents"] == 766_644
    assert processed["earned_premium_cents"] == 258_356
    assert processed["tax_refund_cents"] == 20060
    assert processed["stamping_fee_refund_cents"] == 460

    policy = world.get_policy()
    assert_policy_dimensions(policy, status="CANCELLED", tax_status="ADJUSTED")
    assert policy["version"] == before["version"] + 1

    lines = world.filing_lines(policy_id=policy["id"], line_type="CANCELLATION_RETURN")
    assert len(lines) == 3
    assert [line["state_program_id"] for line in lines] == [
        world.program_id("CA"),
        world.program_id("NV"),
        world.program_id("TX"),
    ]
    california, nevada, texas = lines
    assert_filing_line(
        california,
        status="OPEN",
        taxable_premium_cents=-255_548,
        tax_cents=-7666,
        stamping_fee_cents=-460,
        source_cancellation_id=processed["id"],
    )
    assert_filing_line(
        nevada, status="OPEN", taxable_premium_cents=-255_548, tax_cents=0, stamping_fee_cents=0
    )
    assert_filing_line(
        texas,
        status="OPEN",
        taxable_premium_cents=-255_548,
        tax_cents=-12394,
        stamping_fee_cents=0,
    )


def test_cancelling_a_policy_that_is_already_cancelled_returns_policy_not_issued(
    calculated_world,
):
    """`CANCELLED` is terminal, so the second processing has no policy to retire.

    PRD 3.8: "Two preconditions apply: the policy's `status` must be `ISSUED`, else
    `ERR_POLICY_NOT_ISSUED`, and its `tax_status` must not be `UNCALCULATED`, else
    `ERR_TAX_NOT_CALCULATED`."

    Design: Corner/state_machines/cancelling_a_policy_that_is_already_cancelled_returns_policy_not_issued
    """
    world = calculated_world
    first = world.request_cancellation(
        cancellation_type="PRO_RATA", cancellation_date="2026-11-01T00:00:00Z"
    )
    world.process_cancellation(first)
    cancelled = world.get_policy()
    assert_policy_dimensions(cancelled, status="CANCELLED")

    second = world.request_cancellation(
        cancellation_type="PRO_RATA", cancellation_date="2026-12-01T00:00:00Z"
    )
    validate_error(
        world.api.process_cancellation(second["id"], world.broker_headers),
        ERR_POLICY_NOT_ISSUED,
        409,
    )

    rows = validate_success(
        world.api.list_cancellations(cancelled["id"], world.broker_headers), 200
    )
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["PROCESSED", "REQUESTED"]
    assert world.get_policy()["version"] == cancelled["version"]


def test_a_cancellation_dated_outside_the_policy_term_is_refused(calculated_world):
    """An elapsed day count beyond the term length cannot be processed.

    PRD 3.8: "The term length is the number of whole calendar days from the
    policy's `effective_date` to its `expiration_date`, and the elapsed length is
    the number of whole calendar days from `effective_date` to `cancellation_date`;
    if the elapsed length is negative or exceeds the term length, the request is
    refused with `ERR_CANCELLATION_DATE_OUT_OF_TERM`."

    Design: Corner/errors/a_cancellation_dated_outside_the_policy_term_is_refused
    """
    world = calculated_world
    policy = world.get_policy()
    assert policy["expiration_date"] == "2027-08-01T00:00:00Z"

    beyond = world.request_cancellation(
        cancellation_type="PRO_RATA", cancellation_date="2027-09-01T00:00:00Z"
    )
    assert beyond["status"] == "REQUESTED"
    assert beyond["earned_premium_cents"] == 0
    assert beyond["tax_refund_cents"] == 0
    assert beyond["stamping_fee_refund_cents"] == 0

    validate_error(
        world.api.process_cancellation(beyond["id"], world.broker_headers),
        ERR_CANCELLATION_DATE_OUT_OF_TERM,
        422,
    )

    after = world.get_policy()
    assert_policy_dimensions(after, status="ISSUED", tax_status="CALCULATED")
    assert after["version"] == policy["version"]
    assert world.filing_lines(policy_id=policy["id"], line_type="CANCELLATION_RETURN") == []


def test_a_flat_cancellation_after_inception_is_refused(calculated_world):
    """A flat cancellation is an inception-day privilege only.

    PRD 3.8: "A `FLAT` cancellation is available only on the effective date itself:
    if the elapsed day count is anything other than zero the request is refused
    with `ERR_FLAT_CANCELLATION_NOT_AVAILABLE`, and otherwise the whole taxable
    premium is unearned."

    Design: Corner/errors/a_flat_cancellation_after_inception_is_refused
    """
    world = calculated_world
    late = world.request_cancellation(
        cancellation_type="FLAT", cancellation_date="2026-08-15T00:00:00Z"
    )
    validate_error(
        world.api.process_cancellation(late["id"], world.broker_headers),
        ERR_FLAT_CANCELLATION_NOT_AVAILABLE,
        422,
    )
    assert_policy_dimensions(world.get_policy(), status="ISSUED")

    on_inception = world.request_cancellation(
        cancellation_type="FLAT", cancellation_date="2026-08-01T00:00:00Z"
    )
    processed = world.process_cancellation(on_inception)
    assert processed["status"] == "PROCESSED"
    assert_policy_dimensions(world.get_policy(), status="CANCELLED", tax_status="ADJUSTED")


def test_the_minimum_earned_premium_floor_overrides_the_type_calculation(
    calculated_world,
):
    """A flat cancellation would return everything; the floor keeps a quarter.

    PRD 3.8: "Step two applies the minimum earned premium floor, which is
    evaluated **after** the type calculation and is capable of overriding it
    entirely. The floor amount is the taxable premium multiplied by the policy's
    `min_earned_premium_pct`, rounded half up to whole cents. If the amount the
    carrier would otherwise earn — the taxable premium less the unearned figure —
    falls below that floor, the unearned figure is replaced by the taxable premium
    less the floor, and never allowed below zero."

    Design: Difficulty/combinatorial_formula/return_premium_minimum_earned_floor_overrides_the_type_calculation
    """
    world = calculated_world
    policy = world.get_policy()
    assert policy["min_earned_premium_pct"] == 0.25
    assert policy["taxable_premium_cents"] == 1_025_000

    flat = world.request_cancellation(
        cancellation_type="FLAT", cancellation_date="2026-08-01T00:00:00Z"
    )
    processed = world.process_cancellation(flat)

    # The type calculation made the whole 1,025,000 unearned; the 256,250 floor
    # overrode it.
    assert processed["return_premium_cents"] == 768_750
    assert processed["return_premium_cents"] != 1_025_000
    assert processed["earned_premium_cents"] == 256_250
    # 256,250 per state: CA at 3% and TX at 4.85%, Nevada non-refundable.
    assert processed["tax_refund_cents"] == 20116
    assert processed["stamping_fee_refund_cents"] == 461


def test_without_a_minimum_earned_premium_the_type_calculation_stands(searched_world):
    """With the floor at zero the flat cancellation returns the whole premium.

    PRD 3.8: "If the amount the carrier would otherwise earn — the taxable premium
    less the unearned figure — falls below that floor, the unearned figure is
    replaced by the taxable premium less the floor, and never allowed below zero.
    The cancellation's `return_premium_cents` is the resulting unearned figure and
    its `earned_premium_cents` is the taxable premium less that figure."

    Design: Difficulty/combinatorial_formula/return_premium_minimum_earned_floor_overrides_the_type_calculation
    """
    world = searched_world
    policy = world.issue_policy(
        policy_number="SL-2026-0900", min_earned_premium_pct=0
    )
    assert policy["min_earned_premium_pct"] == 0
    calculated = world.calculate_tax()
    assert calculated["taxable_premium_cents"] == 1_025_000

    flat = world.request_cancellation(
        cancellation_type="FLAT", cancellation_date="2026-08-01T00:00:00Z"
    )
    processed = world.process_cancellation(flat)

    assert processed["return_premium_cents"] == 1_025_000
    assert processed["earned_premium_cents"] == 0
    # 341,667 / 341,667 / 341,666 refunded at the pinned rates, Nevada excluded.
    assert processed["tax_refund_cents"] == 26821
    assert processed["stamping_fee_refund_cents"] == 615


def test_the_allocation_parts_always_sum_to_the_taxable_premium_being_split(
    calculated_world,
):
    """Largest remainder loses no cent, at calculation and at recomputation.

    PRD 2.6: "Wherever integer cents are apportioned across states, the
    distribution uses the **largest-remainder** method against the *exact* rational
    share, never against the four-decimal `allocation_pct` that is displayed. Each
    state first receives the floor of its exact share. The cents left over after
    all floors are handed out are then distributed one cent at a time, in
    descending order of the fractional part that was truncated, with ties broken by
    `state_code` in ascending ASCII order. This guarantees that the apportioned
    parts sum exactly to the amount being apportioned, with no residual cent lost
    or invented."

    Design: Difficulty/compensating_invariant/state_allocation_parts_always_sum_to_the_amount_being_split
    """
    world = calculated_world
    rows = world.allocations()
    assert_parts_sum_to(rows, "allocated_premium_cents", 1_025_000)
    # The displayed percentages do not themselves sum to one.
    assert sum(row["allocation_pct"] for row in rows) < 1.0
    indexed = by_state(rows)
    assert indexed["CA"]["allocated_premium_cents"] == 341_667
    assert indexed["NV"]["allocated_premium_cents"] == 341_667
    assert indexed["TX"]["allocated_premium_cents"] == 341_666

    world.draft_endorsement(premium_delta_cents=200_000)
    world.issue_endorsement()
    assert world.get_policy()["taxable_premium_cents"] == 1_225_000
    assert_parts_sum_to(world.allocations(), "allocated_premium_cents", 1_225_000)


def test_the_refund_parts_always_sum_to_the_returned_premium(calculated_world):
    """The same invariant holds for the money flowing back out.

    PRD 3.8: "The returned premium is apportioned across the **same** allocation
    rows the policy already carries, using the pinned `allocation_pct` set
    normalised by the sum of those pinned percentages, split by largest remainder
    ordered by ascending `state_code`, so the parts sum exactly to the returned
    premium."

    Design: Difficulty/compensating_invariant/state_allocation_parts_always_sum_to_the_amount_being_split
    """
    world = calculated_world
    requested = world.request_cancellation(
        cancellation_type="PRO_RATA", cancellation_date="2026-11-01T00:00:00Z"
    )
    processed = world.process_cancellation(requested)
    assert processed["return_premium_cents"] == 766_644

    lines = world.filing_lines(
        policy_id=world.policy["id"], line_type="CANCELLATION_RETURN"
    )
    assert len(lines) == 3
    parts = [-line["taxable_premium_cents"] for line in lines]
    assert parts == [255_548, 255_548, 255_548]
    assert sum(parts) == processed["return_premium_cents"]
    assert sum(line["tax_cents"] for line in lines) == -processed["tax_refund_cents"]
    assert (
        sum(line["stamping_fee_cents"] for line in lines)
        == -processed["stamping_fee_refund_cents"]
    )
