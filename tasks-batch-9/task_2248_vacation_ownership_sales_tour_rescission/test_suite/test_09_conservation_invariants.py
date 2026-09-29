"""Quantities that must return to their prior value when a step is compensated."""

from test_helpers import (
    TEST_USERS,
    assert_escrow_conservation,
    assert_instant_equals,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
TOUR_DAY_UTC = "2026-08-16T07:00:00Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"
INTAKE_UTC = "2026-08-18T10:00:00Z"
TX_DEADLINE = "2026-08-20T23:59:59.999Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
DISBURSER = TEST_USERS["contract_admin_disburser_headers"]


# ---------------------------------------------------------------------------
# Gift liability: an accrual ledger, never a rewrite of the booking row
# ---------------------------------------------------------------------------


def _two_gifted_tours_ready_to_check_in():
    """Two bookings on one channel whose gift is worth 12500 cents each."""
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 2)
    channel = fx.create_channel(incentive_gift_value_cents=12500)
    prospect = fx.create_prospect()
    bookings = [
        fx.create_booking(
            channel["id"],
            prospect["id"],
            gallery["id"],
            scheduled_start_utc=TOUR_DAY_UTC,
        )
        for _ in range(2)
    ]
    assert fx.read_channel(channel["id"])["gift_liability_cents"] == 0
    fx.pin_clock(TOUR_DAY_UTC)
    return {"gallery": gallery, "channel": channel, "bookings": bookings}


def _accruing_gift_total(channel_id):
    """The sum the PRD defines: gifted bookings that are CHECKED_IN or TOURED."""
    rows = fx.get_success_data(
        api.list_tour_bookings(MARKETING, params={"channel_id": channel_id})
    )
    return sum(
        row["gift_value_cents"]
        for row in rows
        if row["gift_issued"] and row["status"] in ("CHECKED_IN", "TOURED")
    )


def test_two_gifted_check_ins_accrue_the_liability_one_gift_at_a_time():
    """The ledger climbs 0 to 12500 to 25000 and matches its defining sum at each step.

    The PRD states: "When `issue_incentive_gift` is true, `gift_issued` is set to
    true, `gift_value_cents` is copied from the channel's
    `incentive_gift_value_cents` as of that instant, and the channel's
    `gift_liability_cents` is recomputed."

    Design: Difficulty/compensating_invariant/gift_liability_conserved_across_check_in_and_cancel
    """
    scene = _two_gifted_tours_ready_to_check_in()
    channel_id = scene["channel"]["id"]

    first = fx.check_in(scene["bookings"][0]["id"], True)
    assert first["gift_issued"] is True
    assert first["gift_value_cents"] == 12500
    assert fx.read_channel(channel_id)["gift_liability_cents"] == 12500
    assert _accruing_gift_total(channel_id) == 12500

    second = fx.check_in(scene["bookings"][1]["id"], True)
    assert second["gift_value_cents"] == 12500
    assert fx.read_channel(channel_id)["gift_liability_cents"] == 25000
    assert _accruing_gift_total(channel_id) == 25000


def test_cancelling_both_tours_unwinds_the_liability_without_erasing_the_gifts():
    """The liability returns to 0 while both cancelled rows keep gift_value_cents 12500.

    The PRD states: "The pair of check-in followed by cancel therefore leaves both
    `gift_liability_cents` and `booked_slot_count` at their pre-check-in values."

    Design: Difficulty/compensating_invariant/gift_liability_conserved_across_check_in_and_cancel
    """
    scene = _two_gifted_tours_ready_to_check_in()
    channel_id = scene["channel"]["id"]
    fx.check_in(scene["bookings"][0]["id"], True)
    fx.check_in(scene["bookings"][1]["id"], True)

    first = fx.cancel_booking(
        scene["bookings"][0]["id"], "Prospect walked out before the presentation"
    )
    assert first["status"] == "CANCELLED"
    assert first["gift_issued"] is True
    assert first["gift_value_cents"] == 12500
    assert fx.read_channel(channel_id)["gift_liability_cents"] == 12500
    assert _accruing_gift_total(channel_id) == 12500

    second = fx.cancel_booking(
        scene["bookings"][1]["id"], "Prospect walked out before the presentation"
    )
    assert second["status"] == "CANCELLED"
    assert second["gift_value_cents"] == 12500

    channel = fx.read_channel(channel_id)
    assert channel["gift_liability_cents"] == 0
    assert _accruing_gift_total(channel_id) == 0
    assert channel["toured_count"] == 0
    assert channel["no_show_count"] == 0
    assert channel["status"] == "ACTIVE"
    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 0


# ---------------------------------------------------------------------------
# Escrow cash: withheld at settlement, never at disbursement creation
# ---------------------------------------------------------------------------


def _texas_agreement_cancelled_inside_its_window():
    """A gifted TX right-to-use sale rescinded by hand delivery on 2026-08-18."""
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=1,
        issue_incentive_gift=True,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
        agreement_overrides={
            "product_type": "RIGHT_TO_USE",
            "state_code": "TX",
            "purchase_price_cents": 3_200_000,
            "down_payment_cents": 320_000,
            "pos_delivered_at": POS_DELIVERED_AT,
        },
    )
    agreement = scene["agreement"]
    assert agreement["refund_policy"] == "CONTRACTUAL_NET_OF_GIFT"
    assert agreement["escrow_collected_cents"] == 320000
    assert agreement["retained_cents"] == 0
    assert_instant_equals(
        agreement["rescission_deadline_utc"], TX_DEADLINE, "rescission_deadline_utc"
    )
    assert agreement["business_day_rolled"] is False

    fx.pin_clock(INTAKE_UTC)
    request = fx.intake_rescission(agreement["id"], "HAND_DELIVERED")
    assert request["timeliness_basis"] == "RECEIPT"
    assert_instant_equals(request["effective_utc"], INTAKE_UTC, "effective_utc")
    assert request["is_timely"] is True

    scene["rescission_request"] = fx.adjudicate_rescission(request["id"])
    scene["agreement"] = fx.read_agreement(agreement["id"])
    return scene


def test_the_waterfall_is_computed_at_creation_while_escrow_is_still_intact():
    """A PENDING disbursement plans 12500 and 19900 without touching retained_cents.

    The PRD states: "To make the fork concrete: an escrow of 320000 cents with a
    recorded gift value of 12500 disburses the full 320000 under `STATUTORY_FULL`,
    and under `CONTRACTUAL_NET_OF_GIFT` recaptures 12500, retains 19900, and
    disburses 287600."

    Design: Difficulty/compensating_invariant/escrow_cash_conserved_across_refund_settlement
    """
    scene = _texas_agreement_cancelled_inside_its_window()
    assert scene["rescission_request"]["status"] == "VALIDATED"
    assert scene["agreement"]["rescission_status"] == "RESCINDED"
    assert scene["agreement"]["fulfillment_status"] == "VOIDED"

    disbursement = fx.create_disbursement(scene["rescission_request"]["id"], "ACH")
    assert disbursement["refund_policy_applied"] == "CONTRACTUAL_NET_OF_GIFT"
    assert disbursement["base_refund_cents"] == 320000
    assert disbursement["gift_recapture_cents"] == 12500
    assert disbursement["doc_fee_retained_cents"] == 19900
    assert disbursement["disbursed_amount_cents"] == 287600
    assert disbursement["status"] == "PENDING"
    assert disbursement["settlement_reference"] is None
    assert disbursement["settled_at"] is None

    assert fx.read_agreement(scene["agreement"]["id"])["retained_cents"] == 0


def test_settlement_moves_the_withheld_cash_onto_the_agreement_exactly_once():
    """320000 splits into 287600 disbursed and 32400 retained with no remainder.

    The PRD states: "It supplies a `settlement_reference`, moves the disbursement
    `PENDING → ISSUED`, stamps `settled_at`, advances the rescission request
    `VALIDATED → REFUNDED`, and writes the agreement's `retained_cents` as
    `gift_recapture_cents` plus `doc_fee_retained_cents`."

    Design: Difficulty/compensating_invariant/escrow_cash_conserved_across_refund_settlement
    """
    scene = _texas_agreement_cancelled_inside_its_window()
    disbursement = fx.create_disbursement(scene["rescission_request"]["id"], "ACH")

    settled = validate_success(
        api.settle_refund_disbursement(
            disbursement["id"], fac.settle_payload("ACH-77120"), DISBURSER
        )
    )
    assert settled["status"] == "ISSUED"
    assert settled["settlement_reference"] == "ACH-77120"
    assert settled["disbursed_amount_cents"] == 287600

    assert (
        fx.read_rescission_request(scene["rescission_request"]["id"])["status"]
        == "REFUNDED"
    )

    agreement = fx.read_agreement(scene["agreement"]["id"])
    assert agreement["retained_cents"] == 32400
    assert agreement["escrow_collected_cents"] == 320000
    assert_escrow_conservation(agreement, settled)


# ---------------------------------------------------------------------------
# The slot ledger: only NO_SHOW and CANCELLED release occupancy
# ---------------------------------------------------------------------------


def _three_bookings_in_one_slot():
    """Three tours at 07:00 on a four-slot gallery, so the ledger reads 3."""
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    bookings = [
        fx.create_booking(
            channel["id"],
            prospect["id"],
            gallery["id"],
            scheduled_start_utc=TOUR_DAY_UTC,
        )
        for _ in range(3)
    ]
    assert fx.read_gallery(gallery["id"])["booked_slot_count"] == 3
    assert fx.read_channel(channel["id"])["booked_count"] == 3
    return {"gallery": gallery, "channel": channel, "bookings": bookings}


def _occupying_booking_count(gallery_id):
    """The count the PRD defines: SCHEDULED, RESCHEDULE_PENDING, CHECKED_IN, TOURED."""
    rows = fx.get_success_data(
        api.list_tour_bookings(MARKETING, params={"gallery_id": gallery_id})
    )
    return sum(
        1
        for row in rows
        if row["status"] in ("SCHEDULED", "RESCHEDULE_PENDING", "CHECKED_IN", "TOURED")
    )


def test_a_reschedule_cycle_holds_its_slot_through_both_legs():
    """RESCHEDULE_PENDING keeps the count at 3, and so does the committed 13:00 slot.

    The PRD states: "The gallery's `booked_slot_count` is unchanged by this leg,
    since `RESCHEDULE_PENDING` remains an occupying status; the booking's own
    `updated_at` is refreshed and its `version` incremented."

    Design: Difficulty/compensating_invariant/gallery_slot_ledger_conserved_across_booking_and_cancel
    """
    scene = _three_bookings_in_one_slot()
    gallery_id = scene["gallery"]["id"]
    booking_id = scene["bookings"][0]["id"]

    pending = fx.get_success_data(
        api.open_reschedule_request(
            booking_id,
            fac.reschedule_request_payload("Prospect asked for an afternoon tour"),
            MARKETING,
        )
    )
    assert pending["status"] == "RESCHEDULE_PENDING"
    assert fx.read_gallery(gallery_id)["booked_slot_count"] == 3
    assert _occupying_booking_count(gallery_id) == 3

    committed = fx.get_success_data(
        api.commit_reschedule(
            booking_id,
            fac.reschedule_commit_payload("2026-08-16T13:00:00Z"),
            MARKETING,
        )
    )
    assert committed["status"] == "SCHEDULED"
    assert committed["reschedule_count"] == 1
    assert_instant_equals(
        committed["scheduled_start_utc"], "2026-08-16T13:00:00Z", "scheduled_start_utc"
    )
    assert_instant_equals(
        committed["scheduled_end_utc"], "2026-08-16T15:00:00Z", "scheduled_end_utc"
    )

    assert fx.read_gallery(gallery_id)["booked_slot_count"] == 3
    assert _occupying_booking_count(gallery_id) == 3
    assert fx.read_channel(scene["channel"]["id"])["booked_count"] == 3


def test_only_the_no_show_and_the_cancellation_release_occupancy():
    """The ledger falls 3 to 2 to 1 while the lifetime booked_count stays at 3.

    The PRD states: "A gallery's `booked_slot_count` is recomputed as the number of
    bookings at that gallery whose `status` is `SCHEDULED`, `RESCHEDULE_PENDING`,
    `CHECKED_IN` or `TOURED`; bookings in `NO_SHOW` and `CANCELLED` are excluded."

    Design: Difficulty/compensating_invariant/gallery_slot_ledger_conserved_across_booking_and_cancel
    """
    scene = _three_bookings_in_one_slot()
    gallery_id = scene["gallery"]["id"]

    fx.pin_clock(TOUR_DAY_UTC)
    no_show = fx.mark_no_show(scene["bookings"][1]["id"])
    assert no_show["status"] == "NO_SHOW"
    assert fx.read_gallery(gallery_id)["booked_slot_count"] == 2
    assert _occupying_booking_count(gallery_id) == 2

    channel = fx.read_channel(scene["channel"]["id"])
    assert channel["no_show_count"] == 1
    assert channel["historical_no_show_rate"] == 1.0
    assert channel["status"] == "ACTIVE"
    assert channel["booked_count"] == 3

    cancelled = fx.cancel_booking(
        scene["bookings"][2]["id"], "Prospect cancelled by phone"
    )
    assert cancelled["status"] == "CANCELLED"
    assert fx.read_gallery(gallery_id)["booked_slot_count"] == 1
    assert _occupying_booking_count(gallery_id) == 1
    assert fx.read_channel(scene["channel"]["id"])["booked_count"] == 3
