"""Jurisdiction-driven variant selection: anchor mode, refund policy, timeliness basis."""

from test_helpers import (
    TEST_USERS,
    assert_escrow_conservation,
    assert_instant_equals,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"


def _two_cleared_presentations(issue_incentive_gift=False):
    fx.pin_clock(CLOCK_START)
    return fx.setup_parallel_cleared_presentations(
        count=2, issue_incentive_gift=issue_incentive_gift
    )


# ---------------------------------------------------------------------------
# Anchor selection
# ---------------------------------------------------------------------------


def test_florida_and_hawaii_agreements_pick_different_anchor_instants():
    """Two agreements executed at one instant diverge on the anchor they freeze.

    The PRD states: "The anchor instant, recorded as `rescission_anchor_utc`, is
    chosen by `anchor_mode`: under `EXECUTION` it is the agreement's
    `executed_at`; under `POS_DELIVERY` it is the agreement's `pos_delivered_at`;
    under `LATER_OF_EXECUTION_OR_POS` it is whichever of those two instants is
    later."

    Design: Difficulty/dual_variant_calc/rescission_deadline_anchor_variant_divergence_fl_vs_hi
    """
    scene = _two_cleared_presentations()
    fx.pin_clock(EXECUTION_UTC)

    florida = fx.execute_agreement(
        scene["presentations"][0]["id"],
        scene["assigned_rep_ids"][0],
        state_code="FL",
        product_type="DEEDED_INTEREST",
        pos_delivered_at=POS_DELIVERED_AT,
    )
    hawaii = fx.execute_agreement(
        scene["presentations"][1]["id"],
        scene["assigned_rep_ids"][1],
        state_code="HI",
        product_type="RIGHT_TO_USE",
        pos_delivered_at=POS_DELIVERED_AT,
    )

    assert_instant_equals(florida["executed_at"], EXECUTION_UTC, "executed_at")
    assert_instant_equals(hawaii["executed_at"], EXECUTION_UTC, "executed_at")

    assert florida["anchor_mode"] == "LATER_OF_EXECUTION_OR_POS"
    assert florida["statutory_rescission_days"] == 10
    assert_instant_equals(
        florida["rescission_anchor_utc"], EXECUTION_UTC, "rescission_anchor_utc"
    )
    assert florida["refund_policy"] == "STATUTORY_FULL"

    assert hawaii["anchor_mode"] == "POS_DELIVERY"
    assert hawaii["statutory_rescission_days"] == 7
    assert_instant_equals(
        hawaii["rescission_anchor_utc"], POS_DELIVERED_AT, "rescission_anchor_utc"
    )
    assert hawaii["refund_policy"] == "CONTRACTUAL_NET_OF_GIFT"


def test_identical_execution_instants_produce_deadlines_seven_days_apart():
    """The two frozen deadlines differ by exactly seven calendar days.

    The PRD states: "The UTC calendar date of the anchor is then advanced by the
    jurisdiction's number of calendar days."

    Design: Difficulty/dual_variant_calc/rescission_deadline_anchor_variant_divergence_fl_vs_hi
    """
    scene = _two_cleared_presentations()
    fx.pin_clock(EXECUTION_UTC)

    florida = fx.execute_agreement(
        scene["presentations"][0]["id"],
        scene["assigned_rep_ids"][0],
        state_code="FL",
        pos_delivered_at=POS_DELIVERED_AT,
    )
    hawaii = fx.execute_agreement(
        scene["presentations"][1]["id"],
        scene["assigned_rep_ids"][1],
        state_code="HI",
        product_type="RIGHT_TO_USE",
        pos_delivered_at=POS_DELIVERED_AT,
    )

    assert_instant_equals(
        florida["rescission_deadline_utc"],
        "2026-08-24T23:59:59.999Z",
        "rescission_deadline_utc",
    )
    assert_instant_equals(
        hawaii["rescission_deadline_utc"],
        "2026-08-17T23:59:59.999Z",
        "rescission_deadline_utc",
    )
    assert florida["business_day_rolled"] is False
    assert hawaii["business_day_rolled"] is False

    window = validate_success(
        api.get_rescission_window(
            hawaii["id"], TEST_USERS["contract_administrator_headers"]
        )
    )
    assert window["anchor_mode"] == "POS_DELIVERY"
    assert_instant_equals(window["anchor_utc"], POS_DELIVERED_AT, "anchor_utc")
    assert window["statutory_days"] == 7
    assert_instant_equals(
        window["rescission_deadline_utc"],
        "2026-08-17T23:59:59.999Z",
        "rescission_deadline_utc",
    )


# ---------------------------------------------------------------------------
# Refund policy selection
# ---------------------------------------------------------------------------


def _rescind_and_settle(presentation, rep_id, state_code, product_type):
    agreement = fx.execute_agreement(
        presentation["id"],
        rep_id,
        state_code=state_code,
        product_type=product_type,
        pos_delivered_at=POS_DELIVERED_AT,
    )
    request = fx.intake_rescission(agreement["id"], "HAND_DELIVERED")
    fx.adjudicate_rescission(request["id"])
    disbursement = fx.create_disbursement(request["id"], "ACH")
    settled = fx.settle_disbursement(disbursement["id"])
    return fx.read_agreement(agreement["id"]), settled


def test_statutory_full_withholds_nothing_while_net_of_gift_withholds_the_waterfall():
    """One escrow balance settles two ways because the jurisdiction differs.

    The PRD states: "Under `STATUTORY_FULL` nothing whatsoever may be withheld:
    `gift_recapture_cents` is 0, `doc_fee_retained_cents` is 0, and
    `disbursed_amount_cents` equals the whole escrow balance."

    Design: Difficulty/dual_variant_calc/refund_settlement_policy_variant_divergence_fl_vs_tx
    """
    scene = _two_cleared_presentations(issue_incentive_gift=True)
    fx.pin_clock(EXECUTION_UTC)

    florida_agreement, florida_refund = _rescind_and_settle(
        scene["presentations"][0],
        scene["assigned_rep_ids"][0],
        "FL",
        "DEEDED_INTEREST",
    )
    texas_agreement, texas_refund = _rescind_and_settle(
        scene["presentations"][1],
        scene["assigned_rep_ids"][1],
        "TX",
        "RIGHT_TO_USE",
    )

    assert florida_refund["refund_policy_applied"] == "STATUTORY_FULL"
    assert florida_refund["base_refund_cents"] == 320000
    assert florida_refund["gift_recapture_cents"] == 0
    assert florida_refund["doc_fee_retained_cents"] == 0
    assert florida_refund["disbursed_amount_cents"] == 320000
    assert florida_agreement["retained_cents"] == 0

    assert texas_refund["refund_policy_applied"] == "CONTRACTUAL_NET_OF_GIFT"
    assert texas_refund["base_refund_cents"] == 320000
    assert texas_refund["gift_recapture_cents"] == 12500
    assert texas_refund["doc_fee_retained_cents"] == 19900
    assert texas_refund["disbursed_amount_cents"] == 287600
    assert texas_agreement["retained_cents"] == 32400

    assert (
        florida_refund["disbursed_amount_cents"]
        - texas_refund["disbursed_amount_cents"]
        == 32400
    )


def test_divergent_refunds_start_from_identical_escrow_and_gift_inputs():
    """The 32400-cent gap is caused by policy alone, not by different inputs.

    The PRD states: "To make the fork concrete: an escrow of 320000 cents with a
    recorded gift value of 12500 disburses the full 320000 under
    `STATUTORY_FULL`, and under `CONTRACTUAL_NET_OF_GIFT` recaptures 12500,
    retains 19900, and disburses 287600."

    Design: Difficulty/dual_variant_calc/refund_settlement_policy_variant_divergence_fl_vs_tx
    """
    scene = _two_cleared_presentations(issue_incentive_gift=True)
    fx.pin_clock(EXECUTION_UTC)

    florida_agreement, florida_refund = _rescind_and_settle(
        scene["presentations"][0],
        scene["assigned_rep_ids"][0],
        "FL",
        "DEEDED_INTEREST",
    )
    texas_agreement, texas_refund = _rescind_and_settle(
        scene["presentations"][1],
        scene["assigned_rep_ids"][1],
        "TX",
        "DEEDED_INTEREST",
    )

    first_booking = fx.read_booking(scene["bookings"][0]["id"])
    second_booking = fx.read_booking(scene["bookings"][1]["id"])
    assert first_booking["gift_value_cents"] == 12500
    assert second_booking["gift_value_cents"] == 12500
    assert florida_agreement["escrow_collected_cents"] == 320000
    assert texas_agreement["escrow_collected_cents"] == 320000

    assert_escrow_conservation(florida_agreement, florida_refund)
    assert_escrow_conservation(texas_agreement, texas_refund)


# ---------------------------------------------------------------------------
# Timeliness basis selection
# ---------------------------------------------------------------------------


def test_certified_mail_with_a_postmark_is_judged_on_the_mailing_instant():
    """A notice received after the deadline still validates when postmarked inside it.

    The PRD states: "When `delivery_method` is `CERTIFIED_MAIL` *and*
    `postmark_utc` is supplied, `timeliness_basis` is `POSTMARK` and
    `effective_utc` is the `postmark_utc` instant — timeliness is judged on the
    mailing, so a notice received after the deadline is still valid when it was
    mailed inside the window."

    Design: Difficulty/dual_variant_calc/rescission_timeliness_basis_variant_postmark_vs_receipt
    """
    scene = _two_cleared_presentations()
    fx.pin_clock(EXECUTION_UTC)
    agreement = fx.execute_agreement(
        scene["presentations"][0]["id"],
        scene["assigned_rep_ids"][0],
        state_code="FL",
        pos_delivered_at=POS_DELIVERED_AT,
    )
    assert_instant_equals(
        agreement["rescission_deadline_utc"],
        "2026-08-24T23:59:59.999Z",
        "rescission_deadline_utc",
    )

    fx.pin_clock("2026-08-25T10:00:00Z")
    request = fx.intake_rescission(
        agreement["id"], "CERTIFIED_MAIL", postmark_utc="2026-08-24T12:00:00Z"
    )
    assert request["timeliness_basis"] == "POSTMARK"
    assert_instant_equals(
        request["effective_utc"], "2026-08-24T12:00:00Z", "effective_utc"
    )
    assert_instant_equals(
        request["received_at"], "2026-08-25T10:00:00Z", "received_at"
    )
    assert request["is_timely"] is True

    adjudicated = fx.adjudicate_rescission(request["id"])
    assert adjudicated["status"] == "VALIDATED"

    voided = fx.read_agreement(agreement["id"])
    assert voided["rescission_status"] == "RESCINDED"
    assert voided["fulfillment_status"] == "VOIDED"


def test_certified_mail_without_a_postmark_falls_back_to_the_receipt_instant():
    """The same calendar facts adjudicate the other way with no postmark supplied.

    The PRD states: "In every other case — hand delivery, email, or certified
    mail with no postmark — `timeliness_basis` is `RECEIPT` and `effective_utc`
    is the `received_at` intake instant, so identical calendar facts adjudicate
    the other way."

    Design: Difficulty/dual_variant_calc/rescission_timeliness_basis_variant_postmark_vs_receipt
    """
    scene = _two_cleared_presentations()
    fx.pin_clock(EXECUTION_UTC)
    agreement = fx.execute_agreement(
        scene["presentations"][1]["id"],
        scene["assigned_rep_ids"][1],
        state_code="FL",
        pos_delivered_at=POS_DELIVERED_AT,
    )

    fx.pin_clock("2026-08-25T10:00:00Z")
    request = fx.intake_rescission(agreement["id"], "CERTIFIED_MAIL")
    assert request["timeliness_basis"] == "RECEIPT"
    assert_instant_equals(
        request["effective_utc"], "2026-08-25T10:00:00Z", "effective_utc"
    )
    assert request["is_timely"] is False

    adjudicated = fx.adjudicate_rescission(request["id"])
    assert adjudicated["status"] == "REJECTED_LATE"

    untouched = fx.read_agreement(agreement["id"])
    assert untouched["rescission_status"] == "OPEN"
    assert untouched["fulfillment_status"] == "AWAITING_FUNDING"
