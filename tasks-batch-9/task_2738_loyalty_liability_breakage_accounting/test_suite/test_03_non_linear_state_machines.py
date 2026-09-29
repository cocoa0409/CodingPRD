"""
Two state machines that are not forward-only ladders.

A breakage estimate runs a bounded correction cycle: the resubmission edge
re-enters a state the estimate has already occupied, and the budget for those
re-entries is two. A point lot carries two state dimensions on one row, and
neither one gates the other, so one row can advance on either axis alone.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_error,
    assert_fields,
    assert_ok,
    assert_page,
    assert_unchanged,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    COHORT_C1_OBSERVED_RATE_BP,
    DEFAULT_SEEDED_BREAKAGE_RATE_BP,
    ESTIMATE_REJECTED,
    ESTIMATE_SUBMITTED,
    LOT_FULLY_REDEEMED,
    LOT_OUTSTANDING,
    METHOD_COHORT_WEIGHTED,
    REDEMPTION_ALLOCATED,
    SETTLEMENT_NOT_APPLICABLE,
    SETTLEMENT_PENDING,
    SETTLEMENT_SETTLED,
    STATEMENT_PAID,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)

# ─── The bounded review cycle ────────────────────────────────────────────────
CYCLE_BASE_POINTS = 5000

ESTIMATE_RATE_BP = COHORT_C1_OBSERVED_RATE_BP
ESTIMATE_BREAKAGE_RATE_BP = 1800
ESTIMATE_OUTSTANDING_POINTS = 5000
ESTIMATE_GROSS_CENTS = 6000
# round_half_up(6000 * 8200 / 10000)
ESTIMATE_REQUIRED_LIABILITY_CENTS = 4920

REVISION_BUDGET = 2
FIRST_REJECTION_REASON = "Sample size not evidenced"
SECOND_REJECTION_REASON = "Cohort mapping still unsupported"
THIRD_REJECTION_REASON = "Memo still incomplete"

MID_CYCLE_REDEEMED_POINTS = 3000
MID_CYCLE_REMAINING_POINTS = 2000

# ─── The two parallel lot dimensions ─────────────────────────────────────────
LOT_A_ISSUED_AT = "2026-08-01T00:00:00Z"
LOT_C_ISSUED_AT = "2026-08-02T00:00:00Z"
LOT_B_ISSUED_AT = "2026-08-03T00:00:00Z"

LOT_A_POINTS = 5000
LOT_C_POINTS = 2000
LOT_B_POINTS = 1000
REDEEMED_POINTS = 5000

PARTNER_ISSUED_POINTS = 7000
PARTNER_REDEEMED_POINTS = 0
# round_half_up(7000 * 900 / 1000)
ISSUANCE_RECEIVABLE_CENTS = 6300
REDEMPTION_PAYABLE_CENTS = 0
NET_DUE_CENTS = 6300

SETTLED_LOT_COUNT = 2
OUTSTANDING_LOT_COUNT = 2


def _rejected_estimate(api):
    """
    An estimate measured at 8200 basis points, submitted once and pushed back
    once, so it sits in REJECTED with its revision budget still untouched.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(api, program["id"])
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(api, program["id"], cohort["id"])
    period = fixtures.new_period(api, program["id"])
    lot = fixtures.issue_lot(
        api, member["id"], period["id"], base_points=CYCLE_BASE_POINTS
    )
    estimate = fixtures.submitted_estimate(api, program["id"], period["id"])
    estimate = assert_ok(
        api.reject_estimate(
            estimate["id"],
            factories.rejection_payload(FIRST_REJECTION_REASON),
            CONTROLLER_HEADERS,
        )
    )
    return {
        "program": program,
        "cohort": cohort,
        "member": member,
        "period": period,
        "lot": lot,
        "estimate": estimate,
    }


def _resubmit(api, estimate_id):
    """Re-enter SUBMITTED from REJECTED, spending one unit of the budget."""
    return api.submit_estimate(estimate_id, None, ACCOUNTANT_HEADERS)


def _reject(api, estimate_id, reason):
    """Push a submitted estimate back to REJECTED."""
    return assert_ok(
        api.reject_estimate(
            estimate_id, factories.rejection_payload(reason), CONTROLLER_HEADERS
        )
    )


def _parallel_dimension_world(api):
    """
    Three lots on one member: two partner-issued and one programme-issued, each
    at its own issuance instant so first-in-first-out order is unambiguous, plus
    a 5000-point catalogue request that has not yet been allocated.
    """
    fixtures.set_clock(api, LOT_A_ISSUED_AT)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(api, program["id"])
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(api, program["id"], cohort["id"])
    period = fixtures.new_period(api, program["id"])
    agreement = fixtures.new_agreement(api, program["id"])

    lot_a = fixtures.issue_lot(
        api,
        member["id"],
        period["id"],
        base_points=LOT_A_POINTS,
        partner_agreement_id=agreement["id"],
    )
    fixtures.set_clock(api, LOT_C_ISSUED_AT)
    lot_c = fixtures.issue_lot(
        api,
        member["id"],
        period["id"],
        base_points=LOT_C_POINTS,
        partner_agreement_id=agreement["id"],
    )
    fixtures.set_clock(api, LOT_B_ISSUED_AT)
    lot_b = fixtures.issue_lot(
        api, member["id"], period["id"], base_points=LOT_B_POINTS
    )
    event = fixtures.request_redemption(
        api, member["id"], period["id"], REDEEMED_POINTS
    )
    return {
        "program": program,
        "member": member,
        "period": period,
        "agreement": agreement,
        "lot_a": lot_a,
        "lot_b": lot_b,
        "lot_c": lot_c,
        "event": event,
    }


def _settled_statement(api, world):
    """Measure, issue and pay the one statement for this agreement and period."""
    statement = fixtures.draft_statement(
        api, world["agreement"]["id"], world["period"]["id"]
    )
    assert_ok(api.issue_statement(statement["id"], None, ACCOUNTANT_HEADERS))
    return assert_ok(api.pay_statement(statement["id"], None, CONTROLLER_HEADERS))


def test_two_resubmissions_re_enter_submitted_and_spend_the_budget(api):
    """
    The rejection edge does not end the estimate's life: from REJECTED it may
    re-enter SUBMITTED, a state it has already occupied. The first rejection
    leaves the counter at 0 because only the re-entry spends the budget, and the
    two permitted re-entries then take it to 1 and to 2 while the estimate lands
    back in SUBMITTED each time.

    "A `LoyaltyAccountant` submits a `DRAFT` estimate, moving it `DRAFT → SUBMITTED`, which requires the supporting period to be `OPEN`, sets `submitted_at` to the clock reading and increments `version` by 1."
    "A `Controller` may push back, moving the estimate `SUBMITTED → REJECTED` with a `rejection_reason` that is stored on the estimate, incrementing `version` by 1."
    "A rejected estimate may be resubmitted, `REJECTED → SUBMITTED`, provided the period is still `OPEN` and `revision_count` is below 2; that path increments `revision_count` by 1, refreshes `submitted_at` to the clock reading and increments `version` by 1, and a third attempt is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."
    "Review is a bounded loop."

    Design: Difficulty/non_linear_state_machine/nonlinear_estimate_reject_resubmit_cycle_bounded_at_two
    """
    world = _rejected_estimate(api)
    estimate = world["estimate"]
    assert_fields(
        estimate,
        state=ESTIMATE_REJECTED,
        revision_count=0,
        rejection_reason=FIRST_REJECTION_REASON,
    )

    first = assert_ok(_resubmit(api, estimate["id"]))
    assert_fields(first, state=ESTIMATE_SUBMITTED, revision_count=1)
    assert first["version"] == estimate["version"] + 1, (
        "A resubmission increments the estimate's version"
    )

    rejected_again = _reject(api, estimate["id"], SECOND_REJECTION_REASON)
    assert_fields(
        rejected_again,
        state=ESTIMATE_REJECTED,
        revision_count=1,
        rejection_reason=SECOND_REJECTION_REASON,
    )

    second = assert_ok(_resubmit(api, estimate["id"]))
    assert_fields(second, state=ESTIMATE_SUBMITTED, revision_count=REVISION_BUDGET)


def test_the_third_resubmission_is_refused_and_leaves_the_estimate_rejected(api):
    """
    Once the counter has reached 2 the cycle is closed off. The third attempt to
    re-enter SUBMITTED is refused, and because a refused transition changes
    nothing, the estimate is still REJECTED, still carrying the reason from the
    rejection that preceded the attempt, still at exactly 2 revisions and at the
    same version.

    "A rejected estimate may be resubmitted, `REJECTED → SUBMITTED`, provided the period is still `OPEN` and `revision_count` is below 2; that path increments `revision_count` by 1, refreshes `submitted_at` to the clock reading and increments `version` by 1, and a third attempt is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."
    "A rejected breakage estimate may be revised and resubmitted while its `revision_count` is below 2, and each resubmission after a rejection increments that counter; a third resubmission is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."
    "None of the three counters is ever reset — not by a resolution, not by a reopen, not by any other operation."

    Design: Difficulty/non_linear_state_machine/nonlinear_estimate_reject_resubmit_cycle_bounded_at_two
    """
    world = _rejected_estimate(api)
    estimate_id = world["estimate"]["id"]

    assert_ok(_resubmit(api, estimate_id))
    _reject(api, estimate_id, SECOND_REJECTION_REASON)
    assert_ok(_resubmit(api, estimate_id))
    exhausted = _reject(api, estimate_id, THIRD_REJECTION_REASON)
    assert_fields(exhausted, state=ESTIMATE_REJECTED, revision_count=REVISION_BUDGET)

    assert_error(_resubmit(api, estimate_id), ApiErrorId.REVISION_LIMIT_EXCEEDED)

    after = assert_ok(api.get_estimate(estimate_id, ACCOUNTANT_HEADERS))
    assert_fields(
        after,
        state=ESTIMATE_REJECTED,
        revision_count=REVISION_BUDGET,
        rejection_reason=THIRD_REJECTION_REASON,
    )
    assert_unchanged(exhausted, after, "version", "submitted_at", "updated_at")


def test_the_measured_rate_survives_the_whole_cycle_and_installs_nothing(api):
    """
    Re-entering SUBMITTED is not a re-measurement. Three thousand of the lot's
    5000 points are redeemed in the middle of the cycle, which would move a live
    measurement, yet the estimate still reports the 8200 basis points, 1800 of
    breakage, 5000 points, 6000 cents of gross and 4920 of required liability it
    froze at creation — and because nothing was ever approved, the programme's
    live rate is still the 2500 basis points activation seeded.

    "Measurement runs at creation and is frozen thereafter."
    "Crucially, `estimated_redemption_rate_bp` is **never** re-measured on resubmission — it stays frozen at the value computed when the estimate was created, however much the underlying balances have moved in the meantime."
    "That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`."
    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/nonlinear_estimate_reject_resubmit_cycle_bounded_at_two
    """
    world = _rejected_estimate(api)
    estimate = world["estimate"]
    frozen = dict(
        estimated_redemption_rate_bp=ESTIMATE_RATE_BP,
        breakage_rate_bp=ESTIMATE_BREAKAGE_RATE_BP,
        method_applied=METHOD_COHORT_WEIGHTED,
        outstanding_points_at_estimate=ESTIMATE_OUTSTANDING_POINTS,
        outstanding_gross_ssp_cents_at_estimate=ESTIMATE_GROSS_CENTS,
        required_liability_cents=ESTIMATE_REQUIRED_LIABILITY_CENTS,
    )
    assert_fields(estimate, **frozen)

    event = fixtures.allocated_redemption(
        api, world["member"]["id"], world["period"]["id"], MID_CYCLE_REDEEMED_POINTS
    )
    assert_fields(event, state=REDEMPTION_ALLOCATED)
    lot = assert_ok(api.get_point_lot(world["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(lot, points_remaining=MID_CYCLE_REMAINING_POINTS)

    first = assert_ok(_resubmit(api, estimate["id"]))
    assert_fields(first, **frozen)
    rejected_again = _reject(api, estimate["id"], SECOND_REJECTION_REASON)
    assert_fields(rejected_again, **frozen)
    second = assert_ok(_resubmit(api, estimate["id"]))
    assert_fields(second, **frozen)

    program = assert_ok(api.get_program(world["program"]["id"], PROGRAM_ADMIN_HEADERS))
    assert_fields(program, current_breakage_rate_bp=DEFAULT_SEEDED_BREAKAGE_RATE_BP)


def test_allocation_moves_the_lifecycle_dimension_and_leaves_settlement_alone(api):
    """
    First-in-first-out takes the whole of the earliest lot and nothing else, so
    lot A ends the allocation FULLY_REDEEMED on the redemption axis while still
    PENDING_SETTLEMENT on the billing axis — a combination that only exists
    because the two dimensions are independent. The two later lots keep both of
    their own states and their whole balances.

    "A lot carries **two independent state dimensions on one row**, and neither is a precondition of the other."
    "The independence is real and testable: an `OUTSTANDING` lot may be `SETTLED`, and a `FULLY_REDEEMED` lot may still be `PENDING_SETTLEMENT`."
    "The candidates are walked in order of `issued_at` ascending and then `created_at` ascending — never by identifier — so a lot recorded later but carrying an earlier issuance instant is still consumed first."
    "A lot that was `OUTSTANDING` and gives up exactly its `points_remaining` moves `OUTSTANDING → FULLY_REDEEMED`, with `points_remaining` set to 0, one `ALLOCATION` row appended, and its `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/nonlinear_pointlot_parallel_lifecycle_and_settlement_dimensions
    """
    world = _parallel_dimension_world(api)
    assert_fields(
        world["lot_a"],
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_PENDING,
        issued_at=LOT_A_ISSUED_AT,
    )
    assert_fields(
        world["lot_b"],
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
        issued_at=LOT_B_ISSUED_AT,
    )

    event = assert_ok(
        api.allocate_redemption(world["event"]["id"], None, ACCOUNTANT_HEADERS)
    )
    assert_fields(event, state=REDEMPTION_ALLOCATED)

    lot_a = assert_ok(api.get_point_lot(world["lot_a"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_a,
        lifecycle_state=LOT_FULLY_REDEEMED,
        settlement_state=SETTLEMENT_PENDING,
        points_remaining=0,
        points_issued=LOT_A_POINTS,
    )

    lot_c = assert_ok(api.get_point_lot(world["lot_c"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_c,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_PENDING,
        points_remaining=LOT_C_POINTS,
    )
    lot_b = assert_ok(api.get_point_lot(world["lot_b"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_b,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
        points_remaining=LOT_B_POINTS,
    )


def test_payment_moves_the_settlement_dimension_without_touching_lifecycle(api):
    """
    Paying the statement drives both partner lots to SETTLED regardless of where
    they stand on the redemption axis, leaving three distinct combined states on
    three rows: lot A FULLY_REDEEMED and SETTLED, lot C still OUTSTANDING yet
    SETTLED, and the programme-issued lot B OUTSTANDING and permanently
    NOT_APPLICABLE. The bill itself is struck on all 7000 partner-issued points
    even though 5000 of them have already been redeemed.

    "`partner_issued_points` is the sum of `points_issued` over the matching lots, with every `lifecycle_state` included — issuance is billable the moment it happens, and a later redemption, expiry or escheatment does not un-bill it."
    "Under `GROSS`, the billable candidate is `issuance_receivable_cents` plus `carried_forward_cents`."
    "Payment moves the statement `ISSUED → PAID`, which is terminal: it sets `paid_at` to the clock reading, subtracts `net_due_cents` from the agreement's `outstanding_settlement_cents`, increments the agreement's `version` by 1 and the statement's `version` by 1, and drives every lot sharing the statement's `partner_agreement_id` and `period_id` whose `settlement_state` is `PENDING_SETTLEMENT` to `SETTLED`, walking those lots in `created_at` ascending order and incrementing each lot's `version` by 1."
    "The independence is real and testable: an `OUTSTANDING` lot may be `SETTLED`, and a `FULLY_REDEEMED` lot may still be `PENDING_SETTLEMENT`."

    Design: Difficulty/non_linear_state_machine/nonlinear_pointlot_parallel_lifecycle_and_settlement_dimensions
    """
    world = _parallel_dimension_world(api)
    assert_ok(api.allocate_redemption(world["event"]["id"], None, ACCOUNTANT_HEADERS))

    statement = _settled_statement(api, world)
    assert_fields(
        statement,
        state=STATEMENT_PAID,
        partner_issued_points=PARTNER_ISSUED_POINTS,
        partner_redeemed_points=PARTNER_REDEEMED_POINTS,
        issuance_receivable_cents=ISSUANCE_RECEIVABLE_CENTS,
        redemption_payable_cents=REDEMPTION_PAYABLE_CENTS,
        carried_forward_cents=0,
        net_due_cents=NET_DUE_CENTS,
        deferred_below_minimum_cents=0,
    )

    lot_a = assert_ok(api.get_point_lot(world["lot_a"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_a,
        lifecycle_state=LOT_FULLY_REDEEMED,
        settlement_state=SETTLEMENT_SETTLED,
        points_remaining=0,
    )
    lot_c = assert_ok(api.get_point_lot(world["lot_c"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_c,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_SETTLED,
        points_remaining=LOT_C_POINTS,
    )
    lot_b = assert_ok(api.get_point_lot(world["lot_b"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_b,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
        points_remaining=LOT_B_POINTS,
    )

    agreement = assert_ok(
        api.get_agreement(world["agreement"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(agreement, outstanding_settlement_cents=0)


def test_the_two_dimensions_partition_the_same_three_rows_differently(api):
    """
    The clinching evidence that the axes are orthogonal is that filtering on one
    of them cuts the same three rows a different way. After the payment, two lots
    are SETTLED — the fully redeemed A and the untouched C — and two lots are
    OUTSTANDING — that same C plus the programme-issued B. Lot C appears in both
    answers and lot A in neither of the lifecycle-outstanding ones.

    "Lists PointLots; filterable by member, period, partner agreement and either state dimension."
    "Unless a specific read says otherwise, list results are ordered by `created_at` ascending."
    "A lot carries **two independent state dimensions on one row**, and neither is a precondition of the other."

    Design: Difficulty/non_linear_state_machine/nonlinear_pointlot_parallel_lifecycle_and_settlement_dimensions
    """
    world = _parallel_dimension_world(api)
    assert_ok(api.allocate_redemption(world["event"]["id"], None, ACCOUNTANT_HEADERS))
    _settled_statement(api, world)

    settled = api.list_point_lots(
        ACCOUNTANT_HEADERS, settlement_state=SETTLEMENT_SETTLED
    )
    assert_page(
        settled,
        expected_ids=[world["lot_a"]["id"], world["lot_c"]["id"]],
        total_count=SETTLED_LOT_COUNT,
    )

    outstanding = api.list_point_lots(
        ACCOUNTANT_HEADERS, lifecycle_state=LOT_OUTSTANDING
    )
    assert_page(
        outstanding,
        expected_ids=[world["lot_c"]["id"], world["lot_b"]["id"]],
        total_count=OUTSTANDING_LOT_COUNT,
    )

    not_applicable = api.list_point_lots(
        ACCOUNTANT_HEADERS, settlement_state=SETTLEMENT_NOT_APPLICABLE
    )
    assert_page(
        not_applicable, expected_ids=[world["lot_b"]["id"]], total_count=1
    )

    fully_redeemed = api.list_point_lots(
        ACCOUNTANT_HEADERS, lifecycle_state=LOT_FULLY_REDEEMED
    )
    assert_page(
        fully_redeemed, expected_ids=[world["lot_a"]["id"]], total_count=1
    )
