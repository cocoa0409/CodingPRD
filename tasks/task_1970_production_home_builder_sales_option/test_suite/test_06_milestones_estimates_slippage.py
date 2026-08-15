"""Construction milestones: sequential completion, the stage-advance sweep over
selections, and the two closing-estimate variants with slippage detection
(PRD §2.7, §3.6)."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    complete_milestones_in_order,
    create_agreement_payload,
    create_lot,
    create_selection,
    get_selection,
    list_agreement_milestones,
    make_buyer_headers,
    release_lot,
    reserve_lot,
    setup_released_scenario,
    setup_signed_agreement,
    validate_error,
    validate_success,
)

AGENT = TEST_USERS["sales_agent_headers"]
MANAGER = TEST_USERS["construction_manager_headers"]


def _get_agreement(agreement_id):
    return validate_success(api_client.get_agreement(agreement_id, AGENT), 200)


def test_milestone_complete_out_of_order_rejected():
    """PRD §3.6: "Completion is strictly sequential: the milestone must be in
    `NOT_STARTED` (a repeat completion is rejected with
    `ERR_MILESTONE_ALREADY_COMPLETE`), every milestone of the same agreement
    with a lower `sequence_no` must already be `COMPLETE` (else
    `ERR_MILESTONE_OUT_OF_ORDER`), and the agreement must be in
    `PENDING_CONTINGENCIES` or `CONTINGENCIES_CLEARED` (else
    `ERR_AGREEMENT_INVALID_STATE`)."

    Design: Corner/state_machines/milestone_complete_out_of_order_rejected
    """
    bundle = setup_signed_agreement()
    milestones = list_agreement_milestones(bundle["agreement"]["id"])
    second = milestones[1]

    resp = api_client.complete_milestone(second["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_OUT_OF_ORDER)

    after = validate_success(api_client.get_milestone(second["id"], AGENT), 200)
    assert after["status"] == "NOT_STARTED"
    agreement = _get_agreement(bundle["agreement"]["id"])
    assert agreement["current_stage"] == "PRE_CONSTRUCTION"


def test_milestone_double_complete_rejected():
    """PRD §3.6: "Completion is strictly sequential: the milestone must be in
    `NOT_STARTED` (a repeat completion is rejected with
    `ERR_MILESTONE_ALREADY_COMPLETE`), every milestone of the same agreement
    with a lower `sequence_no` must already be `COMPLETE` (else
    `ERR_MILESTONE_OUT_OF_ORDER`), and the agreement must be in
    `PENDING_CONTINGENCIES` or `CONTINGENCIES_CLEARED` (else
    `ERR_AGREEMENT_INVALID_STATE`)."

    Design: Corner/state_machines/milestone_double_complete_rejected
    """
    bundle = setup_signed_agreement()
    milestones = list_agreement_milestones(bundle["agreement"]["id"])
    first = milestones[0]

    done = validate_success(api_client.complete_milestone(first["id"], MANAGER), 200)
    assert done["status"] == "COMPLETE"

    resp = api_client.complete_milestone(first["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_ALREADY_COMPLETE)

    agreement = _get_agreement(bundle["agreement"]["id"])
    assert agreement["current_stage"] == "FOUNDATION", (
        "the rejected repeat completion changed nothing"
    )


def test_milestone_completion_advances_stage_and_recomputes_estimates():
    """PRD §3.6: "Completion advances the agreement's `current_stage` to the
    stage of its earliest remaining `NOT_STARTED` milestone, or to `COMPLETE`
    when none remain."
    PRD §3.6: "The internal `estimated_close_standard` is the current logical
    timestamp plus the raw `planned_duration_days` of every remaining stage
    plus the 7-day close buffer."
    PRD §3.6: "The buyer-facing `estimated_close_padded` inflates each
    remaining stage's planned duration by the 15 percent weather buffer, rounds
    each stage's inflated value up to the next whole day before any summation,
    then adds those whole-day values and the same 7-day buffer to the current
    timestamp."
    PRD §3.6: "On completion the milestone stamps `completed_at` with the
    current instant and sets `buyer_notified_at` equal to it — that equality is
    the buyer-facing milestone communication, the moment the buyer is told the
    stage finished."

    Design: Difficulty/transitive_cascade/milestone_completion_stage_lock_reprice_cascade
    """
    bundle = setup_signed_agreement(with_quartz=True, with_ev=True)
    agreement_id = bundle["agreement"]["id"]
    buyer_id = bundle["buyer"]["id"]
    create_selection(agreement_id, bundle["quartz"]["id"], buyer_id)
    create_selection(agreement_id, bundle["ev"]["id"], buyer_id)

    completed = complete_milestones_in_order(agreement_id, 2)
    last = completed[-1]
    assert last["status"] == "COMPLETE"
    assert_instant_equals(
        last["completed_at"], DEFAULT_CLOCK_ISO, "completed_at stamped to the clock"
    )
    assert_instant_equals(
        last["buyer_notified_at"], DEFAULT_CLOCK_ISO,
        "buyer_notified_at equals completed_at (buyer communication)",
    )

    agreement = _get_agreement(agreement_id)
    assert agreement["current_stage"] == "FRAMING"
    # Remaining stages FRAMING 28 + DRYWALL 35 + FINAL_WALKTHROUGH 14 = 77 days;
    # standard: 77 + 7 = 84 days from 2026-08-01 -> 2026-10-24.
    assert_instant_equals(
        agreement["estimated_close_standard"], "2026-10-24T00:00:00Z",
        "standard estimate over the 3 remaining stages",
    )
    # Padded: ceil(28*1.15)=33, ceil(35*1.15)=41, ceil(14*1.15)=17 -> 91 + 7 = 98
    # days from 2026-08-01 -> 2026-11-07.
    assert_instant_equals(
        agreement["estimated_close_padded"], "2026-11-07T00:00:00Z",
        "padded estimate with per-stage ceiling before summation",
    )


def test_stage_advance_sweeps_cutoff_selections_and_recomputes_options_total():
    """PRD §3.6: "First, every selection still in `SELECTED` whose option's
    `cutoff_stage` ordinal now lies strictly behind the new `current_stage`
    ordinal is cancelled with `cancel_reason` `CUTOFF_EXPIRED` and no change
    fee — unconfirmed selections simply lapse."
    PRD §3.6: "After both sweeps the agreement's `options_total_cents` is
    recomputed over the surviving non-cancelled lines."

    Design: Difficulty/transitive_cascade/milestone_completion_stage_lock_reprice_cascade
    """
    bundle = setup_signed_agreement(with_quartz=True, with_ev=True)
    agreement_id = bundle["agreement"]["id"]
    buyer_id = bundle["buyer"]["id"]
    quartz = create_selection(agreement_id, bundle["quartz"]["id"], buyer_id)
    ev = create_selection(agreement_id, bundle["ev"]["id"], buyer_id)
    assert _get_agreement(agreement_id)["options_total_cents"] == 950_000

    complete_milestones_in_order(agreement_id, 2)  # -> current_stage FRAMING

    swept = get_selection(quartz["id"])
    assert swept["status"] == "CANCELLED"
    assert swept["cancel_reason"] == "CUTOFF_EXPIRED"
    assert swept["change_fee_cents"] == 0, "unconfirmed selections lapse free"

    survivor = get_selection(ev["id"])
    assert survivor["status"] == "SELECTED", (
        "cutoff DRYWALL is not strictly behind FRAMING, so the EV line survives"
    )

    agreement = _get_agreement(agreement_id)
    assert agreement["options_total_cents"] == 150_000
    assert agreement["change_fees_total_cents"] == 0


def test_sign_computes_standard_and_padded_estimates():
    """PRD §3.6: "The internal `estimated_close_standard` is the current logical
    timestamp plus the raw `planned_duration_days` of every remaining stage
    plus the 7-day close buffer."
    PRD §3.6: "The buyer-facing `estimated_close_padded` inflates each
    remaining stage's planned duration by the 15 percent weather buffer, rounds
    each stage's inflated value up to the next whole day before any summation,
    then adds those whole-day values and the same 7-day buffer to the current
    timestamp."
    PRD §3.6: "Whenever any milestone remains, the padded estimate is strictly
    later than the standard one."
    PRD §2.7: "Each build stage carries a planned duration used by the closing
    forecast: 30 days for `PRE_CONSTRUCTION`, 21 days for `FOUNDATION`, 28 days
    for `FRAMING`, 35 days for `DRYWALL`, and 14 days for `FINAL_WALKTHROUGH`."

    Design: Difficulty/dual_variant_calc/closing_estimate_standard_vs_padded_divergence
    """
    bundle = setup_signed_agreement(
        agreement_overrides={"outside_close_date": "2026-12-20T00:00:00Z"}
    )
    agreement = bundle["agreement"]
    # 30+21+28+35+14 = 128 remaining stage-days + 7 buffer days from 2026-08-01.
    assert_instant_equals(
        agreement["estimated_close_standard"], "2026-12-14T00:00:00Z",
        "standard variant",
    )
    # 35+25+33+41+17 = 151 padded stage-days + 7 buffer days.
    assert_instant_equals(
        agreement["estimated_close_padded"], "2027-01-06T00:00:00Z",
        "padded variant",
    )
    assert agreement["estimated_close_padded"] != agreement["estimated_close_standard"]


def test_slippage_flag_driven_by_padded_variant_only():
    """PRD §3.6: "The `slippage_flag` is recomputed alongside: it is true
    exactly when `estimated_close_padded` falls strictly later than the
    agreement's `outside_close_date`, compared to the second — a padded
    estimate landing exactly on the outside date is not slippage."

    Design: Difficulty/dual_variant_calc/closing_estimate_standard_vs_padded_divergence
    """
    bundle = setup_signed_agreement(
        agreement_overrides={"outside_close_date": "2026-12-20T00:00:00Z"}
    )
    agreement = bundle["agreement"]
    # Standard 2026-12-14 < outside 2026-12-20 < padded 2027-01-06: the flag
    # follows the padded variant alone.
    assert agreement["slippage_flag"] is True
    assert_instant_equals(
        agreement["estimated_close_standard"], "2026-12-14T00:00:00Z", "standard"
    )
    assert_instant_equals(
        agreement["estimated_close_padded"], "2027-01-06T00:00:00Z", "padded"
    )


def test_slippage_flag_strict_greater_than_outside_date():
    """PRD §3.6: "The `slippage_flag` is recomputed alongside: it is true
    exactly when `estimated_close_padded` falls strictly later than the
    agreement's `outside_close_date`, compared to the second — a padded
    estimate landing exactly on the outside date is not slippage."

    Design: Corner/calculations/slippage_flag_strict_greater_than_outside_date
    """
    bundle = setup_released_scenario()
    community_id = bundle["community"]["id"]
    buyer = bundle["buyer"]
    plan_id = bundle["plan"]["id"]
    lot_a = bundle["lot"]
    lot_b = release_lot(
        create_lot(
            community_id, lot_number="L-102", base_price_cents=5_000_000,
            lot_type="STANDARD", view_adjustment_cents=0,
        )["id"]
    )

    def draft_and_sign(lot, outside_close_date, elevation="B"):
        reserved = reserve_lot(lot["id"], buyer["id"])
        payload = create_agreement_payload(
            buyer_id=buyer["id"], lot_id=lot["id"], plan_id=plan_id,
            elevation_name=elevation, outside_close_date=outside_close_date,
            expected_lot_version=reserved["version"],
        )
        agreement = validate_success(api_client.create_agreement(payload, AGENT), 201)
        return validate_success(
            api_client.sign_agreement(
                agreement["id"], make_buyer_headers(buyer["id"])
            ),
            200,
        )

    # Padded estimate for both agreements: 2027-01-06T00:00:00Z (same stage
    # calendar, same signing instant).
    agr_a = draft_and_sign(lot_a, "2027-01-06T00:00:00Z")
    assert_instant_equals(
        agr_a["estimated_close_padded"], "2027-01-06T00:00:00Z", "padded A"
    )
    assert agr_a["slippage_flag"] is False, (
        "padded estimate landing exactly on the outside date is not slippage"
    )

    agr_b = draft_and_sign(lot_b, "2027-01-05T23:59:59Z", elevation="A")
    assert_instant_equals(
        agr_b["estimated_close_padded"], "2027-01-06T00:00:00Z", "padded B"
    )
    assert agr_b["slippage_flag"] is True, (
        "padded one second strictly later than the outside date is slippage"
    )
