"""
Every write is complete when its response is returned.

A request that fans out over several resources leaves nothing to settle later:
the response body already carries the accumulators the write moved, the very next
read of any affected resource shows its final value, and repeating that read gives
the same answer. No half-applied intermediate is ever observable.
"""

from typing import Any, Dict, Optional

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_fields, assert_ok, assert_unchanged
from test_helpers.constants import (
    CLOCK_EPOCH,
    COHORT_C1_OBSERVED_RATE_BP,
    DEFAULT_SEEDED_BREAKAGE_RATE_BP,
    DEFAULT_SSP_MILLICENTS_PER_POINT,
    ESTIMATE_APPROVED,
    LOT_ESCHEATED,
    MEMBER_DORMANT,
    PERIOD_OPEN,
    STATE_DE,
    apply_bp,
    points_to_cents,
    round_half_up,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    CONTROLLER_ID,
)

# ─── The reference figures every test below re-derives ───────────────────────
SSP = DEFAULT_SSP_MILLICENTS_PER_POINT              # 1200 millicents per point
SEEDED_RATE_BP = DEFAULT_SEEDED_BREAKAGE_RATE_BP    # 10000 - 7500
OBSERVED_RATE_BP = COHORT_C1_OBSERVED_RATE_BP       # the single cohort's rate
APPROVED_RATE_BP = 10000 - OBSERVED_RATE_BP         # what approval installs

# ─── The sweep scenario ──────────────────────────────────────────────────────
ISSUE_CLOCK = "2026-08-05T00:00:00Z"
SWEEP_CLOCK = "2028-08-05T00:00:00Z"
DORMANCY_DAYS_AT_SWEEP = 731

SWEPT_PERIOD_CODE = "2028-08"
SWEPT_PERIOD_START = "2028-08-01T00:00:00Z"
SWEPT_PERIOD_END = "2028-09-01T00:00:00Z"

SWEPT_LOT_POINTS = 5000
SWEPT_GROSS_CENTS = points_to_cents(SWEPT_LOT_POINTS, SSP)          # 6000
SWEPT_RESERVE_CENTS = apply_bp(SWEPT_GROSS_CENTS, SEEDED_RATE_BP)   # 1500
SWEPT_DEFERRED_CENTS = SWEPT_GROSS_CENTS - SWEPT_RESERVE_CENTS      # 4500

ESCHEAT_RATE_BP = 6000
ESCHEATED_CENTS = apply_bp(SWEPT_GROSS_CENTS, ESCHEAT_RATE_BP)      # 3600

# ─── The approval scenario ───────────────────────────────────────────────────
ESTIMATE_LOT_POINTS = 1000
ESTIMATE_GROSS_CENTS = points_to_cents(ESTIMATE_LOT_POINTS, SSP)    # 1200
SENSITIVITY_LOW_BP = 7700
SENSITIVITY_HIGH_BP = 8700

BASE_LIABILITY_CENTS = round_half_up(ESTIMATE_GROSS_CENTS * OBSERVED_RATE_BP, 10000)
LOW_LIABILITY_CENTS = round_half_up(ESTIMATE_GROSS_CENTS * SENSITIVITY_LOW_BP, 10000)
HIGH_LIABILITY_CENTS = round_half_up(ESTIMATE_GROSS_CENTS * SENSITIVITY_HIGH_BP, 10000)
BAND_RANGE_CENTS = HIGH_LIABILITY_CENTS - LOW_LIABILITY_CENTS


def _live_program(
    api,
    program_overrides: Optional[Dict[str, Any]] = None,
    rule_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
    clock: str = CLOCK_EPOCH,
) -> Dict[str, Any]:
    """
    An ACTIVE programme carrying one state expiry rule, one cohort, one member and
    one OPEN period — the minimum state an issuance needs.
    """
    fixtures.set_clock(api, clock)
    program = fixtures.new_program(api, **(program_overrides or {}))
    fixtures.new_state_expiry_rule(api, program["id"], **(rule_overrides or {}))
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(
        api, program["id"], cohort["id"], **(member_overrides or {})
    )
    period = fixtures.new_period(api, program["id"], **(period_overrides or {}))
    return {
        "program": program,
        "cohort": cohort,
        "member": member,
        "period": period,
    }


def _sweep_bundle(api) -> Dict[str, Any]:
    """
    A programme whose disclosure threshold is exactly the escheat the sweep will
    accrue, one member resident in a state that both permits expiry and requires
    escheatment, two open periods, and a lot whose expiry horizon has just passed.
    """
    bundle = _live_program(
        api,
        program_overrides={"escheat_disclosure_threshold_cents": ESCHEATED_CENTS},
        rule_overrides={
            "state_code": STATE_DE,
            "escheatment_required": True,
            "escheat_rate_bp": ESCHEAT_RATE_BP,
        },
        member_overrides={"state_code": STATE_DE},
    )
    bundle["swept_period"] = fixtures.new_period(
        api,
        bundle["program"]["id"],
        period_code=SWEPT_PERIOD_CODE,
        start_at=SWEPT_PERIOD_START,
        end_at=SWEPT_PERIOD_END,
    )
    fixtures.set_clock(api, ISSUE_CLOCK)
    bundle["lot"] = fixtures.issue_lot(
        api, bundle["member"]["id"], bundle["period"]["id"], SWEPT_LOT_POINTS
    )
    fixtures.set_clock(api, SWEEP_CLOCK)
    return bundle


def test_the_sweep_response_itself_carries_the_period_it_just_moved(api):
    """
    The sweep's own response is the swept period, and it already reports both
    accumulators the sweep moved: the released deferral of the expired lot and the
    escheat accrued from its gross. Nothing further has to be called to see the
    write, and the period is still OPEN because a sweep books movements rather than
    closing anything.

    "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    "The captured released deferral is added to the **swept** period's `expiry_released_cents`, and the lot's `version` increments by 1."
    "Escheatment is a second link, caused by the expiry completing rather than by the sweep request. When the governing rule's `escheatment_required` is true, `escheated_cents` is `expired_gross_ssp_cents` multiplied by the rule's `escheat_rate_bp`, divided by 10000, rounded half up; `lifecycle_state` moves `EXPIRED → ESCHEATED`, which is terminal for the lifecycle dimension; the amount is added both to the swept period's `escheat_accrual_cents` and to the programme's `total_escheat_accrual_cents`; and a third link fires from that accrual — once the programme's `total_escheat_accrual_cents` reaches `escheat_disclosure_threshold_cents`, the boundary being inclusive, `escheat_disclosure_required` latches to true and is never cleared again, even if a later reopen reduces other figures."

    Design: Corner/consistency_model/consistency_immediate_full_cascade_readable_in_the_next_request
    """
    bundle = _sweep_bundle(api)

    swept = assert_ok(
        api.run_expiry_sweep(bundle["swept_period"]["id"], None, ACCOUNTANT_HEADERS)
    )
    assert_fields(
        swept,
        state=PERIOD_OPEN,
        expiry_released_cents=SWEPT_DEFERRED_CENTS,
        escheat_accrual_cents=ESCHEATED_CENTS,
    )


def test_the_whole_three_level_fan_out_is_readable_on_the_next_request(api):
    """
    One sweep drives three levels: the lot expires and continues to ESCHEATED, the
    emptied member falls dormant, and the escheat accrual latches the programme's
    disclosure flag at exactly the threshold. Every one of those is final on the
    first read that follows, and the programme's derived deferred revenue has
    already dropped the escheated lot.

    "Some cascades are chains, where a later link is caused by an earlier link's completion rather than by the original request."
    "`expired_gross_ssp_cents` is captured from the lot's current `remaining_gross_ssp_cents`, and the released deferral is captured from its current `remaining_deferred_cents`."
    "A member whose `status` is `ACTIVE`, whose `point_balance` is 0 after the pass, and whose `dormancy_days` is at least 730 — two years since `last_activity_at` — moves `ACTIVE → DORMANT` with `version` incremented by 1."
    "`total_deferred_revenue_cents` is the sum, over this programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`, of each lot's `remaining_deferred_cents`."

    Design: Corner/consistency_model/consistency_immediate_full_cascade_readable_in_the_next_request
    """
    bundle = _sweep_bundle(api)

    assert_ok(api.run_expiry_sweep(bundle["swept_period"]["id"], None, ACCOUNTANT_HEADERS))

    assert_fields(
        assert_ok(api.get_point_lot(bundle["lot"]["id"], ACCOUNTANT_HEADERS)),
        lifecycle_state=LOT_ESCHEATED,
        points_remaining=0,
        expired_gross_ssp_cents=SWEPT_GROSS_CENTS,
        escheated_cents=ESCHEATED_CENTS,
        remaining_gross_ssp_cents=0,
        remaining_deferred_cents=0,
    )

    assert_fields(
        assert_ok(api.get_member(bundle["member"]["id"], ACCOUNTANT_HEADERS)),
        status=MEMBER_DORMANT,
        point_balance=0,
        outstanding_gross_ssp_cents=0,
        dormancy_days=DORMANCY_DAYS_AT_SWEEP,
    )

    assert_fields(
        assert_ok(api.get_program(bundle["program"]["id"], CONTROLLER_HEADERS)),
        total_escheat_accrual_cents=ESCHEATED_CENTS,
        escheat_disclosure_required=True,
        total_deferred_revenue_cents=0,
    )


def test_the_release_lands_only_on_the_swept_period_and_not_on_the_issuing_one(api):
    """
    The sweep sweeps the whole programme's lots but books its movements into the one
    period it was addressed against. The period the lot was issued into keeps the
    deferral it accumulated at issuance and gains neither the release nor the
    accrual, so no read of it ever shows a partially rewritten history.

    "Expiry is swept, not scheduled. A `LoyaltyAccountant` runs a sweep against one accounting period, which must be `OPEN` because the sweep books its releases and accruals into that period, and the sweep then examines the lots of that period's **whole programme** — not merely the lots booked to the swept period."
    "`issuance_deferred_cents` grows by each issued lot's `deferred_revenue_cents`."
    "`expiry_released_cents` grows by the deferral released whenever the sweep expires a lot into this period."

    Design: Corner/consistency_model/consistency_immediate_full_cascade_readable_in_the_next_request
    """
    bundle = _sweep_bundle(api)
    issuing_period_id = bundle["period"]["id"]

    assert_ok(api.run_expiry_sweep(bundle["swept_period"]["id"], None, ACCOUNTANT_HEADERS))

    assert_fields(
        assert_ok(api.get_period(issuing_period_id, CONTROLLER_HEADERS)),
        state=PERIOD_OPEN,
        issuance_deferred_cents=SWEPT_DEFERRED_CENTS,
        expiry_released_cents=0,
        escheat_accrual_cents=0,
    )

    assert_fields(
        assert_ok(api.get_period(bundle["swept_period"]["id"], CONTROLLER_HEADERS)),
        issuance_deferred_cents=0,
        expiry_released_cents=SWEPT_DEFERRED_CENTS,
        escheat_accrual_cents=ESCHEATED_CENTS,
    )


def _submitted_estimate_bundle(api) -> Dict[str, Any]:
    """
    A programme holding one 1000-point lot and one SUBMITTED estimate whose
    sensitivity band straddles the single cohort's observed rate.
    """
    bundle = _live_program(api)
    bundle["estimate"] = fixtures.submitted_estimate(
        api,
        bundle["program"]["id"],
        bundle["period"]["id"],
        sensitivity_low_bp=SENSITIVITY_LOW_BP,
        sensitivity_high_bp=SENSITIVITY_HIGH_BP,
    )
    return bundle


def _approve(api, bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Approve the bundle's estimate at the programme's current version."""
    program_id = bundle["program"]["id"]
    return assert_ok(
        api.approve_estimate(
            bundle["estimate"]["id"],
            factories.approval_payload(fixtures.program_version(api, program_id)),
            CONTROLLER_HEADERS,
        )
    )


def test_the_approval_response_already_shows_the_finished_approval(api):
    """
    Approval is atomic from the caller's point of view: the response to the approve
    request is already the APPROVED estimate, naming the acting Controller as its
    approver and carrying the frozen measurement — the cohort's rate, the breakage
    complement of that rate, and the liability that rate requires. There is no
    intermediate state to observe between submission and approval.

    "On success it sets `approved_by_user_id` to the acting `X-User-ID` and `approved_at` to the clock reading, increments the estimate's `version` by 1, and then fires a three-link chain:"
    "From the measured rate, `breakage_rate_bp` is 10000 basis points less `estimated_redemption_rate_bp`."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."

    Design: Corner/consistency_model/consistency_immediate_reads_are_repeatable_and_never_transitional
    """
    bundle = _live_program(api)
    fixtures.issue_lot(
        api, bundle["member"]["id"], bundle["period"]["id"], ESTIMATE_LOT_POINTS
    )
    bundle["estimate"] = fixtures.submitted_estimate(
        api,
        bundle["program"]["id"],
        bundle["period"]["id"],
        sensitivity_low_bp=SENSITIVITY_LOW_BP,
        sensitivity_high_bp=SENSITIVITY_HIGH_BP,
    )

    approved = _approve(api, bundle)
    assert_fields(
        approved,
        state=ESTIMATE_APPROVED,
        approved_by_user_id=CONTROLLER_ID,
        estimated_redemption_rate_bp=OBSERVED_RATE_BP,
        breakage_rate_bp=APPROVED_RATE_BP,
        outstanding_gross_ssp_cents_at_estimate=ESTIMATE_GROSS_CENTS,
        required_liability_cents=BASE_LIABILITY_CENTS,
    )
    assert approved["approved_at"] is not None, (
        "The approve response must already carry the instant it was approved at, "
        f"got {approved['approved_at']!r}"
    )


def test_the_installed_rate_reads_the_same_for_two_consecutive_callers(api):
    """
    The rate the approval installs on the programme is readable on the very next
    request and is identical when a second caller in a different role reads it
    again, with no drift and no propagation delay between the two reads. Installing
    a rate closes nothing: the supporting period is still OPEN with its closing
    liability untouched, so there is no half-finished close to observe either.

    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."
    "A new period is born in `state` `OPEN`, with `reopen_count` at 0, with `soft_closed_at` null, and with all eleven of its currency and rate rollforward figures at 0: `opening_liability_cents`, `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents`, `expiry_released_cents`, `escheat_accrual_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `breakage_recognized_cents`, `closing_liability_cents` and `approved_estimate_rate_bp`."
    "Five of those figures are **movement accumulators** maintained incrementally as the period lives, not computed at close."

    Design: Corner/consistency_model/consistency_immediate_reads_are_repeatable_and_never_transitional
    """
    bundle = _live_program(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]
    fixtures.issue_lot(api, bundle["member"]["id"], period_id, ESTIMATE_LOT_POINTS)
    bundle["estimate"] = fixtures.submitted_estimate(
        api,
        program_id,
        period_id,
        sensitivity_low_bp=SENSITIVITY_LOW_BP,
        sensitivity_high_bp=SENSITIVITY_HIGH_BP,
    )

    _approve(api, bundle)

    first = assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    second = assert_ok(api.get_program(program_id, ACCOUNTANT_HEADERS))
    assert_fields(first, current_breakage_rate_bp=APPROVED_RATE_BP)
    assert_fields(second, current_breakage_rate_bp=APPROVED_RATE_BP)
    assert_unchanged(
        first, second, "current_breakage_rate_bp", "version", "updated_at"
    )

    assert_fields(
        assert_ok(api.get_period(period_id, CONTROLLER_HEADERS)),
        state=PERIOD_OPEN,
        closing_liability_cents=0,
        required_liability_cents=0,
        approved_estimate_rate_bp=0,
        reopen_count=0,
    )


def test_the_sensitivity_band_is_identical_on_two_successive_reads(api):
    """
    The sensitivity read is computed from the estimate's own frozen gross rather
    than from a fresh measurement, so two successive reads by different roles return
    the same three liabilities and the same band width even though the programme's
    live rate has just been replaced by this very approval. Each band is rounded
    independently from the frozen gross.

    "Audit support reads the frozen snapshot rather than live data."
    "The response reports that frozen gross as `outstanding_gross_ssp_cents`, echoes the three scenarios as `low_bp`, `base_bp` and `high_bp` (respectively `sensitivity_low_bp`, the measured `estimated_redemption_rate_bp`, and `sensitivity_high_bp`), and gives `low_required_liability_cents`, `base_required_liability_cents` and `high_required_liability_cents` as the frozen gross multiplied by each of those three rates in turn, divided by 10000, each rounded half up **independently** — deriving the high band by adding a rounded delta onto the rounded base drifts and is wrong."
    "`band_range_cents` is the high band less the low band, and `memo_narrative` is echoed from the estimate."
    "Because everything is drawn from the snapshot, the band is identical before and after the estimate is approved or superseded."

    Design: Corner/consistency_model/consistency_immediate_reads_are_repeatable_and_never_transitional
    """
    bundle = _live_program(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]
    fixtures.issue_lot(api, bundle["member"]["id"], period_id, ESTIMATE_LOT_POINTS)
    bundle["estimate"] = fixtures.submitted_estimate(
        api,
        program_id,
        period_id,
        sensitivity_low_bp=SENSITIVITY_LOW_BP,
        sensitivity_high_bp=SENSITIVITY_HIGH_BP,
    )
    estimate_id = bundle["estimate"]["id"]

    _approve(api, bundle)

    expected = {
        "outstanding_gross_ssp_cents": ESTIMATE_GROSS_CENTS,
        "low_bp": SENSITIVITY_LOW_BP,
        "base_bp": OBSERVED_RATE_BP,
        "high_bp": SENSITIVITY_HIGH_BP,
        "low_required_liability_cents": LOW_LIABILITY_CENTS,
        "base_required_liability_cents": BASE_LIABILITY_CENTS,
        "high_required_liability_cents": HIGH_LIABILITY_CENTS,
        "band_range_cents": BAND_RANGE_CENTS,
    }

    first = assert_ok(api.get_sensitivity(estimate_id, ACCOUNTANT_HEADERS))
    second = assert_ok(api.get_sensitivity(estimate_id, CONTROLLER_HEADERS))
    assert_fields(first, **expected)
    assert_fields(second, **expected)
    assert first == second, (
        "Two successive sensitivity reads must be identical, got "
        f"{first!r} then {second!r}"
    )
