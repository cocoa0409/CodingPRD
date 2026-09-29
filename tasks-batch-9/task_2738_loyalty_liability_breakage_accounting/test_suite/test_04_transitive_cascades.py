"""
Chained consequences: one request whose later links exist only because an earlier
link completed.

Two chains are exercised here. An expiry sweep expires a lot, the expiry causes
escheatment because the governing state rule demands it, the escheat accrual trips
the programme's disclosure latch, and the emptied member falls dormant — none of
which the sweep request body mentions. Approving a September estimate installs a
new programme rate, the new rate retires the reigning August estimate, and
retiring it forces August's soft close back open, which in turn drops August out
of the programme's year-to-date recognised breakage.
"""

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_fields, assert_ok
from test_helpers.constants import (
    CLOCK_EPOCH,
    COHORT_C1_ENROLLMENT_END,
    COHORT_C1_ENROLLMENT_START,
    COHORT_C2_ENROLLMENT_END,
    COHORT_C2_ENROLLMENT_START,
    ESTIMATE_APPROVED,
    ESTIMATE_SUPERSEDED,
    LOT_ESCHEATED,
    MEMBER_ACTIVE,
    MEMBER_DORMANT,
    PERIOD_AUG_END,
    PERIOD_OPEN,
    PERIOD_SEP_CODE,
    PERIOD_SEP_END,
    PERIOD_SEP_START,
    PERIOD_SOFT_CLOSED,
    REDEMPTION_FULFILLED,
    STATE_DE,
    TIER_BASE,
    TIER_GOLD,
    TIER_SILVER,
)
from test_helpers.test_users import ACCOUNTANT_HEADERS, CONTROLLER_HEADERS

# ─── The expiry → escheat → disclosure chain ─────────────────────────────────
DISCLOSURE_THRESHOLD_CENTS = 3600
ESCHEAT_RATE_BP = 6000
MIN_DORMANCY_DAYS = 730

ISSUE_INSTANT = "2026-08-05T00:00:00Z"
SWEEP_INSTANT = "2028-08-05T00:00:00Z"
EXPIRING_BASE_POINTS = 5000

# 5000 points at 1200 millicents each is 6000 cents of gross standalone price,
# 2500 bp of which is reserved, so 4500 cents of deferral is still outstanding.
EXPIRED_GROSS_SSP_CENTS = 6000
RELEASED_DEFERRAL_CENTS = 4500
# 6000 cents of expired gross at 6000 bp of escheatable share.
ESCHEATED_CENTS = 3600
DORMANCY_DAYS_AT_SWEEP = 731

SWEEP_PERIOD_CODE = "2028-08"
SWEEP_PERIOD_START = "2028-08-01T00:00:00Z"
SWEEP_PERIOD_END = "2028-09-01T00:00:00Z"

# ─── The approval → supersede → forced-reopen chain ─────────────────────────
GOLD_LOT_BASE_POINTS = 4000
GOLD_LOT_POINTS = 5000
SILVER_LOT_BASE_POINTS = 250
SILVER_PROMO_BP = 10300
SILVER_LOT_POINTS = 266

C1_OBSERVED_RATE_BP = 8200
C2_OBSERVED_RATE_BP = 400
C2_ADJUSTMENT_BP = -300
C2_SAMPLE_SIZE = 9000

FIRST_ESTIMATE_RATE_BP = 7796
FIRST_BREAKAGE_RATE_BP = 2204
FIRST_BAND_LOW_BP = 7296
FIRST_BAND_HIGH_BP = 8296

SECOND_ESTIMATE_RATE_BP = 7261
SECOND_BREAKAGE_RATE_BP = 2739
SECOND_BAND_LOW_BP = 6761
SECOND_BAND_HIGH_BP = 7761

REDEMPTION_POINTS = 3000
LOT1_REMAINING_AFTER_REDEMPTION = 2000

AUG_ISSUANCE_DEFERRED_CENTS = 4739
AUG_REDEMPTION_RECOGNIZED_CENTS = 2700
AUG_REMEASUREMENT_DELTA_CENTS = 107
AUG_PRE_CATCHUP_CENTS = 1932
AUG_REQUIRED_CENTS = 2120
AUG_CATCH_UP_CENTS = 188
AUG_CLOSING_CENTS = 2120
AUG_BREAKAGE_RECOGNIZED_CENTS = -188

CLOSE_FIGURES_AFTER_FORCED_REOPEN = {
    "opening_liability_cents": 0,
    "pre_catchup_liability_cents": 0,
    "required_liability_cents": 0,
    "catch_up_adjustment_cents": 0,
    "closing_liability_cents": 0,
    "breakage_recognized_cents": 0,
    "approved_estimate_rate_bp": 0,
}


def _escheat_chain_ready(api):
    """
    A lot one day past its expiry horizon, held by a member resident in a state
    whose rule both permits expiry and demands escheatment, plus a second OPEN
    period that the sweep will be run against.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(
        api, escheat_disclosure_threshold_cents=DISCLOSURE_THRESHOLD_CENTS
    )
    fixtures.new_state_expiry_rule(
        api,
        program["id"],
        state_code=STATE_DE,
        expiry_permitted=True,
        min_dormancy_days=MIN_DORMANCY_DAYS,
        escheatment_required=True,
        escheat_rate_bp=ESCHEAT_RATE_BP,
    )
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(
        api, program["id"], cohort["id"], state_code=STATE_DE, tier=TIER_BASE
    )
    issuing_period = fixtures.new_period(api, program["id"])

    fixtures.set_clock(api, ISSUE_INSTANT)
    lot = fixtures.issue_lot(
        api, member["id"], issuing_period["id"], EXPIRING_BASE_POINTS
    )

    fixtures.set_clock(api, SWEEP_INSTANT)
    sweep_period = fixtures.new_period(
        api,
        program["id"],
        period_code=SWEEP_PERIOD_CODE,
        start_at=SWEEP_PERIOD_START,
        end_at=SWEEP_PERIOD_END,
    )
    return {
        "program": program,
        "member": member,
        "issuing_period": issuing_period,
        "sweep_period": sweep_period,
        "lot": lot,
    }


def _supersede_chain_ready(api):
    """
    An August period taken all the way to SOFT_CLOSED on the strength of one
    approved estimate, plus a September period carrying a second estimate that is
    submitted and waiting for approval.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(
        api, program["id"], escheatment_required=False, escheat_rate_bp=0
    )
    first_cohort = fixtures.new_cohort(
        api,
        program["id"],
        enrollment_start_date=COHORT_C1_ENROLLMENT_START,
        enrollment_end_date=COHORT_C1_ENROLLMENT_END,
        observed_redemption_rate_bp=C1_OBSERVED_RATE_BP,
    )
    second_cohort = fixtures.new_cohort(
        api,
        program["id"],
        enrollment_start_date=COHORT_C2_ENROLLMENT_START,
        enrollment_end_date=COHORT_C2_ENROLLMENT_END,
        observed_redemption_rate_bp=C2_OBSERVED_RATE_BP,
        sample_size=C2_SAMPLE_SIZE,
        program_change_adjustment_bp=C2_ADJUSTMENT_BP,
    )
    program = fixtures.activate(api, program["id"])

    gold_member = fixtures.new_member(
        api, program["id"], first_cohort["id"], tier=TIER_GOLD
    )
    silver_member = fixtures.new_member(
        api, program["id"], second_cohort["id"], tier=TIER_SILVER
    )
    august = fixtures.new_period(api, program["id"])
    gold_lot = fixtures.issue_lot(
        api, gold_member["id"], august["id"], GOLD_LOT_BASE_POINTS
    )
    silver_lot = fixtures.issue_lot(
        api,
        silver_member["id"],
        august["id"],
        SILVER_LOT_BASE_POINTS,
        promo_multiplier_bp=SILVER_PROMO_BP,
    )

    first_estimate = fixtures.approved_estimate(
        api,
        program["id"],
        august["id"],
        memo_narrative="August cohort-weighted measurement.",
        sensitivity_low_bp=FIRST_BAND_LOW_BP,
        sensitivity_high_bp=FIRST_BAND_HIGH_BP,
    )
    event = fixtures.fulfilled_redemption(
        api, gold_member["id"], august["id"], REDEMPTION_POINTS
    )

    fixtures.set_clock(api, PERIOD_AUG_END)
    august = fixtures.soft_close(api, august["id"])

    september = fixtures.new_period(
        api,
        program["id"],
        period_code=PERIOD_SEP_CODE,
        start_at=PERIOD_SEP_START,
        end_at=PERIOD_SEP_END,
    )
    second_estimate = fixtures.submitted_estimate(
        api,
        program["id"],
        september["id"],
        memo_narrative="September re-estimate after the August redemption.",
        sensitivity_low_bp=SECOND_BAND_LOW_BP,
        sensitivity_high_bp=SECOND_BAND_HIGH_BP,
    )
    return {
        "program": program,
        "august": august,
        "september": september,
        "gold_lot": gold_lot,
        "silver_lot": silver_lot,
        "event": event,
        "first_estimate": first_estimate,
        "second_estimate": second_estimate,
    }


def _approve(api, program_id, estimate_id):
    """Approve one submitted estimate under the programme's current version."""
    return assert_ok(
        api.approve_estimate(
            estimate_id,
            factories.approval_payload(fixtures.program_version(api, program_id)),
            CONTROLLER_HEADERS,
        )
    )


# ─── expiry → escheat → disclosure ──────────────────────────────────────────
def test_expiry_sweep_chains_into_escheatment_and_latches_the_disclosure_flag(api):
    """
    One sweep request drives three chained links: the lot expires, escheatment
    follows because the governing state rule demands it, and the programme's
    disclosure flag latches because the resulting accrual reached the threshold.
    The hard part is the third link's inclusive boundary — 3600 cents accrued
    against a 3600-cent threshold must latch, so a strictly-greater comparison
    fails — and the fact that nothing in the request body names escheatment or
    disclosure at all.

    "Expiry causes escheatment where state law requires it, and the escheat accrual in turn causes the programme's disclosure latch to flip."
    "When the governing rule's `escheatment_required` is true, `escheated_cents` is `expired_gross_ssp_cents` multiplied by the rule's `escheat_rate_bp`, divided by 10000, rounded half up; `lifecycle_state` moves `EXPIRED → ESCHEATED`, which is terminal for the lifecycle dimension; the amount is added both to the swept period's `escheat_accrual_cents` and to the programme's `total_escheat_accrual_cents`; and a third link fires from that accrual — once the programme's `total_escheat_accrual_cents` reaches `escheat_disclosure_threshold_cents`, the boundary being inclusive, `escheat_disclosure_required` latches to true and is never cleared again, even if a later reopen reduces other figures."

    Design: Difficulty/transitive_cascade/cascade_expiry_to_escheat_to_program_disclosure_latch
    """
    setup = _escheat_chain_ready(api)

    assert_ok(
        api.run_expiry_sweep(setup["sweep_period"]["id"], None, ACCOUNTANT_HEADERS)
    )

    lot = assert_ok(api.get_point_lot(setup["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        lifecycle_state=LOT_ESCHEATED,
        points_remaining=0,
        expired_gross_ssp_cents=EXPIRED_GROSS_SSP_CENTS,
        escheated_cents=ESCHEATED_CENTS,
    )

    program = assert_ok(api.get_program(setup["program"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        program,
        total_escheat_accrual_cents=ESCHEATED_CENTS,
        escheat_disclosure_required=True,
    )


def test_expiry_release_and_escheat_accrual_land_in_the_swept_period(api):
    """
    The sweep books its release and its accrual into the period it was run
    against, not into the period the lot was issued to. The issuing period is a
    tempting home for the release because the lot still names it, so the test
    pins both sides: the swept period absorbs 4500 cents of released deferral and
    3600 cents of escheat accrual, while the issuing period stays at zero and
    stays OPEN.

    "The captured released deferral is added to the **swept** period's `expiry_released_cents`, and the lot's `version` increments by 1."
    "the sweep then examines the lots of that period's **whole programme** — not merely the lots booked to the swept period"

    Design: Difficulty/transitive_cascade/cascade_expiry_to_escheat_to_program_disclosure_latch
    """
    setup = _escheat_chain_ready(api)

    swept = assert_ok(
        api.run_expiry_sweep(setup["sweep_period"]["id"], None, ACCOUNTANT_HEADERS)
    )
    assert_fields(
        swept,
        id=setup["sweep_period"]["id"],
        expiry_released_cents=RELEASED_DEFERRAL_CENTS,
        escheat_accrual_cents=ESCHEATED_CENTS,
    )

    issuing_period = assert_ok(
        api.get_period(setup["issuing_period"]["id"], CONTROLLER_HEADERS)
    )
    assert_fields(
        issuing_period,
        state=PERIOD_OPEN,
        expiry_released_cents=0,
        escheat_accrual_cents=0,
    )


def test_expiry_pass_drives_the_emptied_member_dormant(api):
    """
    The dormancy move is a fan-out that fires only because the expiry pass drove
    the member's balance to zero; the sweep request never mentions the member. It
    is the hard case because all three of its conditions must hold at once — the
    member was ACTIVE, its balance is zero only after the pass, and its dormancy
    has reached the threshold — and because the balance is a derived figure that
    reads the same lot the sweep just emptied.

    "Dormancy is a fan-out evaluated once per member touched by the sweep's expiry pass, in `created_at` ascending order."
    "A member whose `status` is `ACTIVE`, whose `point_balance` is 0 after the pass, and whose `dormancy_days` is at least 730 — two years since `last_activity_at` — moves `ACTIVE → DORMANT` with `version` incremented by 1."

    Design: Difficulty/transitive_cascade/cascade_expiry_to_escheat_to_program_disclosure_latch
    """
    setup = _escheat_chain_ready(api)

    before = assert_ok(api.get_member(setup["member"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        before,
        status=MEMBER_ACTIVE,
        point_balance=EXPIRING_BASE_POINTS,
        dormancy_days=DORMANCY_DAYS_AT_SWEEP,
    )

    assert_ok(
        api.run_expiry_sweep(setup["sweep_period"]["id"], None, ACCOUNTANT_HEADERS)
    )

    after = assert_ok(api.get_member(setup["member"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(after, status=MEMBER_DORMANT, point_balance=0)


def test_second_sweep_does_not_reapply_the_chain_to_an_escheated_lot(api):
    """
    Repeating the sweep is accepted but must be inert: an already escheated lot is
    never a candidate again, so no second release, no second accrual and no second
    escheat amount may appear. This is the hard case because every one of those
    figures is an accumulator, so a re-swept lot would silently double the
    programme's escheat liability rather than raise an error.

    "Lots already `EXPIRED` or `ESCHEATED` are never re-swept, and `settlement_state` is irrelevant to eligibility."

    Design: Difficulty/transitive_cascade/cascade_expiry_to_escheat_to_program_disclosure_latch
    """
    setup = _escheat_chain_ready(api)
    sweep_period_id = setup["sweep_period"]["id"]

    assert_ok(api.run_expiry_sweep(sweep_period_id, None, ACCOUNTANT_HEADERS))
    second = assert_ok(api.run_expiry_sweep(sweep_period_id, None, ACCOUNTANT_HEADERS))

    assert_fields(
        second,
        expiry_released_cents=RELEASED_DEFERRAL_CENTS,
        escheat_accrual_cents=ESCHEATED_CENTS,
    )
    lot = assert_ok(api.get_point_lot(setup["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        lifecycle_state=LOT_ESCHEATED,
        escheated_cents=ESCHEATED_CENTS,
        expired_gross_ssp_cents=EXPIRED_GROSS_SSP_CENTS,
    )
    program = assert_ok(api.get_program(setup["program"]["id"], CONTROLLER_HEADERS))
    assert_fields(program, total_escheat_accrual_cents=ESCHEATED_CENTS)


# ─── approval → supersede → forced reopen ───────────────────────────────────
def test_approval_installs_the_new_rate_and_retires_the_reigning_estimate(api):
    """
    Approving the September estimate overwrites the programme rate with 2739 basis
    points and, purely because that displaced the reigning rate, drives the
    already-approved August estimate to SUPERSEDED and records it as the new
    estimate's predecessor. The second link is the hard one: it is caused by the
    first link rather than by anything in the request, and the back-reference must
    point at the estimate that was retired.

    "Estimate approval installs a new programme rate, the new rate retires the reigning estimate, and retiring that estimate forces its supporting period back open."
    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."
    "The programme's other estimate whose `state` is `APPROVED` — there is at most one — moves `APPROVED → SUPERSEDED` with its `version` incremented by 1, and the newly approved estimate's `supersedes_estimate_id` is set to that retired estimate's `id`."

    Design: Difficulty/transitive_cascade/cascade_estimate_supersede_forces_soft_closed_period_reopen
    """
    setup = _supersede_chain_ready(api)
    program_id = setup["program"]["id"]
    first_id = setup["first_estimate"]["id"]

    before = assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assert_fields(before, current_breakage_rate_bp=FIRST_BREAKAGE_RATE_BP)

    approved = _approve(api, program_id, setup["second_estimate"]["id"])
    assert_fields(
        approved,
        state=ESTIMATE_APPROVED,
        estimated_redemption_rate_bp=SECOND_ESTIMATE_RATE_BP,
        breakage_rate_bp=SECOND_BREAKAGE_RATE_BP,
        supersedes_estimate_id=first_id,
    )

    program = assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assert_fields(program, current_breakage_rate_bp=SECOND_BREAKAGE_RATE_BP)

    retired = assert_ok(api.get_estimate(first_id, CONTROLLER_HEADERS))
    assert_fields(
        retired,
        state=ESTIMATE_SUPERSEDED,
        estimated_redemption_rate_bp=FIRST_ESTIMATE_RATE_BP,
    )


def test_retiring_the_estimate_forces_its_soft_closed_period_back_open(api):
    """
    The third link reaches backwards: because the August estimate was retired,
    August's soft close no longer rests on a live approved estimate, so the period
    is driven SOFT_CLOSED → OPEN and all seven close-derived figures are wiped.
    The hard part is that this reopen is not the manual one — it is not gated on
    the reopen budget at all — yet it still consumes that budget by incrementing
    the counter from 0 to 1.

    "The retired estimate's own accounting period, **if and only if** that period is `SOFT_CLOSED`, is force-reopened `SOFT_CLOSED → OPEN`, because its close no longer rests on a live approved estimate."
    "That forced reopen resets the period's `opening_liability_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `closing_liability_cents`, `breakage_recognized_cents` and `approved_estimate_rate_bp` to 0, sets `soft_closed_at` to null, increments `reopen_count` by 1 and increments the period's `version` by 1."
    "Unlike the manual reopen, this forced reopen is not gated on `reopen_count` being below 2 — but it does consume that budget, since the counter still increments."

    Design: Difficulty/transitive_cascade/cascade_estimate_supersede_forces_soft_closed_period_reopen
    """
    setup = _supersede_chain_ready(api)
    august_id = setup["august"]["id"]

    assert_fields(
        setup["august"],
        state=PERIOD_SOFT_CLOSED,
        pre_catchup_liability_cents=AUG_PRE_CATCHUP_CENTS,
        required_liability_cents=AUG_REQUIRED_CENTS,
        catch_up_adjustment_cents=AUG_CATCH_UP_CENTS,
        closing_liability_cents=AUG_CLOSING_CENTS,
        breakage_recognized_cents=AUG_BREAKAGE_RECOGNIZED_CENTS,
        approved_estimate_rate_bp=FIRST_ESTIMATE_RATE_BP,
        reopen_count=0,
    )

    _approve(api, setup["program"]["id"], setup["second_estimate"]["id"])

    august = assert_ok(api.get_period(august_id, CONTROLLER_HEADERS))
    assert_fields(august, state=PERIOD_OPEN, reopen_count=1)
    assert_fields(august, **CLOSE_FIGURES_AFTER_FORCED_REOPEN)
    assert august["soft_closed_at"] is None, (
        f"soft_closed_at must be null after a forced reopen, got "
        f"{august['soft_closed_at']!r}"
    )


def test_forced_reopen_drops_the_period_out_of_recognized_breakage_ytd(api):
    """
    A fourth-order consequence nobody asked for: the programme's year-to-date
    recognised breakage sums only soft-closed and hard-closed periods, so the
    forced reopen moves that derived figure from -188 back to 0. The estimate's own
    September period must be left alone — only the retired estimate's period is
    reopened — which is the discrimination a blanket reopen would get wrong.

    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."
    "A period that is `HARD_CLOSED`, or already `OPEN`, is left entirely untouched."

    Design: Difficulty/transitive_cascade/cascade_estimate_supersede_forces_soft_closed_period_reopen
    """
    setup = _supersede_chain_ready(api)
    program_id = setup["program"]["id"]

    before = assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assert_fields(before, recognized_breakage_ytd_cents=AUG_BREAKAGE_RECOGNIZED_CENTS)

    _approve(api, program_id, setup["second_estimate"]["id"])

    after = assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assert_fields(after, recognized_breakage_ytd_cents=0)

    september = assert_ok(api.get_period(setup["september"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        september, state=PERIOD_OPEN, reopen_count=0, closing_liability_cents=0
    )


def test_forced_reopen_leaves_the_movement_accumulators_and_the_ledger_alone(api):
    """
    The reopen is a compensation of the close, not of the events that fed it, so
    August's four movement accumulators must survive untouched even though the six
    liability figures above them were wiped. The lot balance and the fulfilled
    redemption behind those accumulators must survive too — this is the line
    between unwinding a close and unwinding a member's history.

    "The movement accumulators are deliberately **not** reset — they belong to the events that produced them, not to the close."
    "`remeasurement_delta_cents` grows by an event's own `remeasurement_delta_cents` at fulfilment and shrinks by the same amount on reversal."

    Design: Difficulty/transitive_cascade/cascade_estimate_supersede_forces_soft_closed_period_reopen
    """
    setup = _supersede_chain_ready(api)

    _approve(api, setup["program"]["id"], setup["second_estimate"]["id"])

    august = assert_ok(api.get_period(setup["august"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        august,
        issuance_deferred_cents=AUG_ISSUANCE_DEFERRED_CENTS,
        redemption_recognized_cents=AUG_REDEMPTION_RECOGNIZED_CENTS,
        remeasurement_delta_cents=AUG_REMEASUREMENT_DELTA_CENTS,
        expiry_released_cents=0,
    )

    lot = assert_ok(api.get_point_lot(setup["gold_lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        points_issued=GOLD_LOT_POINTS,
        points_remaining=LOT1_REMAINING_AFTER_REDEMPTION,
    )
    event = assert_ok(api.get_redemption(setup["event"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(event, state=REDEMPTION_FULFILLED)
