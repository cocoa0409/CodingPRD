"""Cyclic and parallel lifecycles: the negotiation loop, the two booking
dimensions and the technical-advance revision loop.

Each test drives the loops itself from an empty database and moves the logical
clock explicitly whenever a temporal rule is in play.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    expected_settlement_total_cents,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import (
    MAX_ADVANCE_SUBMISSIONS,
    MAX_NEGOTIATION_ROUNDS,
    STAGE_CHANNEL_ADVISORY,
    STAGE_CHANNEL_HARD_MAX,
)
from test_helpers.factories import advance_packet_payload, counter_payload, revise_payload


# --------------------------------------------------------------------------
# Composite state builders used by the tests below.
# --------------------------------------------------------------------------
def _issued_offer_at_1500000(api):
    """Single-tier edition with one issued offer at guarantee 1500000."""
    ctx = fx.single_tier_edition(api)
    offer = fx.issued_offer(api, ctx, guarantee_cents=1500000)
    return {"ctx": ctx, "offer": offer, "artist_headers": ctx["artist_headers"]}


def _offer_parked_in_countered_after_three_rounds(api):
    """Offer walked twice around the counter-and-revise loop, then countered again."""
    state = _issued_offer_at_1500000(api)
    offer_id = state["offer"]["id"]
    headers = state["artist_headers"]
    validate_success(
        api.counter_offer(
            offer_id,
            counter_payload(
                counter_guarantee_cents=1750000, counter_note="Agency asks for 17.5k"
            ),
            headers,
        )
    )
    first_revision = validate_success(
        api.revise_offer(offer_id, revise_payload(guarantee_cents=1600000), TALENT_BUYER)
    )
    validate_success(
        api.counter_offer(
            offer_id,
            counter_payload(counter_guarantee_cents=1750000, counter_note="Still short"),
            headers,
        )
    )
    second_revision = validate_success(
        api.revise_offer(offer_id, revise_payload(guarantee_cents=1700000), TALENT_BUYER)
    )
    countered = validate_success(
        api.counter_offer(
            offer_id,
            counter_payload(counter_guarantee_cents=1800000, counter_note="Last ask"),
            headers,
        )
    )
    state.update(
        {
            "first_revision": first_revision,
            "second_revision": second_revision,
            "countered": countered,
        }
    )
    return state


def _booking_walked_through_both_dimensions(api):
    """Accepted booking carried to a paid balance, snapshotting both dimensions.

    The deposit is paid while the contracting dimension is still
    `PENDING_RIDER`; the rider, the advance and the countersignature then move
    the contracting dimension, and the balance payment closes the loop.
    """
    ctx = fx.single_tier_edition(api)
    artist_id = ctx["artist"]["id"]
    artist_headers = make_artist_rep_headers(artist_id)
    booking = fx.accepted_booking(api, ctx)
    installments = fx.installments_of(api, booking["id"])
    deposit, balance = installments["DEPOSIT"], installments["BALANCE"]

    fx.set_clock(api, "2026-08-25T09:00:00Z")
    validate_success(api.release_installment(deposit["id"], FINANCE_CONTROLLER))
    validate_success(
        api.mark_installment_paid(
            deposit["id"], {"paid_amount_cents": 900000}, FINANCE_CONTROLLER
        )
    )
    after_deposit_paid = validate_success(api.get_booking(booking["id"], TALENT_BUYER))

    line = fx.add_rider_line(api, booking["id"], artist_id, unit_cost_cents=100000)
    fx.decide_rider_line(api, line["id"], "APPROVED")
    after_rider = validate_success(api.get_booking(booking["id"], TALENT_BUYER))

    fx.approved_advance_packet(api, booking["id"], artist_id)
    after_countersign = validate_success(
        api.countersign_booking(booking["id"], BUSINESS_AFFAIRS)
    )

    fx.set_clock(api, "2026-11-28T09:00:00Z")
    validate_success(api.release_installment(balance["id"], FINANCE_CONTROLLER))
    after_balance_release = validate_success(api.get_booking(booking["id"], TALENT_BUYER))
    validate_success(
        api.mark_installment_paid(
            balance["id"], {"paid_amount_cents": 900000}, FINANCE_CONTROLLER
        )
    )
    after_balance_paid = validate_success(api.get_booking(booking["id"], TALENT_BUYER))

    return {
        "booking": booking,
        "artist_headers": artist_headers,
        "after_accept": booking,
        "after_deposit_paid": after_deposit_paid,
        "after_rider": after_rider,
        "after_countersign": after_countersign,
        "after_balance_release": after_balance_release,
        "after_balance_paid": after_balance_paid,
    }


def _stage_day_with_sibling_advance_packet(api):
    """Two rider-settled bookings on the 2026-12-05 flagship stage-day.

    The sibling booking already carries an APPROVED packet of 40 input
    channels, and the packet under test opens as a DRAFT of 60 channels.
    """
    ctx = fx.single_tier_edition(api)
    artist_one = ctx["artist"]
    booking_one = fx.accepted_booking(api, ctx)
    line_one = fx.add_rider_line(
        api, booking_one["id"], artist_one["id"], unit_cost_cents=100000
    )
    fx.decide_rider_line(api, line_one["id"], "APPROVED")

    artist_two = fx.create_artist(
        api,
        legal_name="Glass Harbor Inc",
        performing_name="Glass Harbor",
        primary_genre="ELECTRONIC",
        agency="Meridian Talent",
        draw_score=72,
        default_radius_miles=150,
    )
    booking_two = fx.accepted_booking(
        api,
        ctx,
        artist_two,
        billing_position=2,
        slot_start_utc="2026-12-05T17:00:00Z",
    )
    line_two = fx.add_rider_line(
        api,
        booking_two["id"],
        artist_two["id"],
        description="Sub-hire monitor console",
        unit_cost_cents=90000,
    )
    fx.decide_rider_line(api, line_two["id"], "APPROVED")

    sibling_packet = fx.approved_advance_packet(
        api,
        booking_two["id"],
        artist_two["id"],
        stage_plot_ref="PLOT-GH-01",
        input_channel_count=40,
        monitor_mix_count=6,
        travel_party_size=9,
        load_in_offset_minutes=180,
    )

    packet = validate_success(
        api.create_advance_packet(
            advance_packet_payload(
                booking_one["id"],
                input_channel_count=60,
                monitor_mix_count=10,
                travel_party_size=18,
            ),
            make_artist_rep_headers(artist_one["id"]),
        ),
        201,
    )
    return {
        "booking_one": booking_one,
        "artist_one": artist_one,
        "artist_one_headers": make_artist_rep_headers(artist_one["id"]),
        "sibling_packet": sibling_packet,
        "packet": packet,
    }


def _packet_after_three_submissions(api):
    """Packet driven three times around submit-and-return, ending in RETURNED."""
    state = _stage_day_with_sibling_advance_packet(api)
    packet_id = state["packet"]["id"]
    reasons = (
        "Stage plot missing monitor world position",
        "Channel list still disagrees with the plot",
        "Load-in offset conflicts with changeover",
    )
    for reason in reasons:
        validate_success(
            api.submit_advance_packet(packet_id, state["artist_one_headers"])
        )
        validate_success(
            api.return_advance_packet(
                packet_id, {"return_reason": reason}, PRODUCTION_MANAGER
            )
        )
    state["last_return_reason"] = reasons[-1]
    return state


# --------------------------------------------------------------------------
# the offer negotiation loop
# --------------------------------------------------------------------------
def test_counter_records_the_agent_ask_without_consuming_a_round(api):
    """The agent-side edge of the loop moves the state but not the round counter.

    "Critically, `round_number` does not change — only promoter-side issuances consume rounds — and `guarantee_cents`, `billing_position`, `set_length_minutes` and the slot itself are untouched."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_bounded_at_three_rounds
    """
    state = _issued_offer_at_1500000(api)
    assert state["offer"]["status"] == "ISSUED"
    assert state["offer"]["round_number"] == 1

    countered = validate_success(
        api.counter_offer(
            state["offer"]["id"],
            counter_payload(
                counter_guarantee_cents=1750000, counter_note="Agency asks for 17.5k"
            ),
            state["artist_headers"],
        )
    )

    assert countered["status"] == "COUNTERED"
    assert countered["round_number"] == 1
    assert countered["counter_guarantee_cents"] == 1750000
    assert countered["guarantee_cents"] == 1500000
    assert countered["set_length_minutes"] == state["offer"]["set_length_minutes"]
    assert countered["slot_start_utc"] == state["offer"]["slot_start_utc"]


def test_each_revision_consumes_a_round_and_clears_the_counter_fields(api):
    """The promoter-side edge returns the offer to ISSUED and resets the ask.

    "On success `round_number` increases by one, `guarantee_ceiling_cents` and `genre_balance_factor` are recomputed and re-stamped, `counter_guarantee_cents`, `counter_billing_position`, `counter_set_length_minutes` and `counter_note` are all reset to null, and `issued_by_user_id` is overwritten with the reviser's `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_bounded_at_three_rounds
    """
    state = _offer_parked_in_countered_after_three_rounds(api)

    first = state["first_revision"]
    assert first["status"] == "ISSUED"
    assert first["round_number"] == 2
    assert first["guarantee_cents"] == 1600000
    assert first["counter_guarantee_cents"] is None
    assert first["counter_billing_position"] is None
    assert first["counter_set_length_minutes"] is None
    assert first["counter_note"] is None
    assert first["guarantee_ceiling_cents"] == 1800000

    second = state["second_revision"]
    assert second["status"] == "ISSUED"
    assert second["round_number"] == 3
    assert second["guarantee_cents"] == 1700000
    assert second["guarantee_ceiling_cents"] == 1800000


def test_fourth_promoter_issuance_exhausts_the_negotiation_rounds(api):
    """The loop terminates on its counter while the row stays inside the cycle.

    "`round_number` must still be below three before the revision runs, and the fourth promoter-side issuance is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` — the cap is what terminates the `ISSUED → COUNTERED → ISSUED` loop."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_bounded_at_three_rounds
    """
    state = _offer_parked_in_countered_after_three_rounds(api)
    assert state["countered"]["status"] == "COUNTERED"
    assert state["countered"]["round_number"] == MAX_NEGOTIATION_ROUNDS

    validate_error(
        api.revise_offer(
            state["offer"]["id"], revise_payload(guarantee_cents=1750000), TALENT_BUYER
        ),
        "ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
        409,
    )

    unchanged = validate_success(api.get_offer(state["offer"]["id"], TALENT_BUYER))
    assert unchanged["status"] == "COUNTERED"
    assert unchanged["round_number"] == 3
    assert unchanged["guarantee_cents"] == 1700000


# --------------------------------------------------------------------------
# the two booking dimensions
# --------------------------------------------------------------------------
def test_deposit_payment_advances_only_the_money_dimension(api):
    """Dimension B reaches DEPOSIT_PAID while dimension A has not moved at all.

    "A booking's `contract_status` and its `settlement_status` are two independent dimensions of the same row."
    "A deposit payment recomputes the booking's `deposit_paid_cents`, defined as the sum of `paid_amount_cents` over that booking's deposit installments whose `status` is `PAID`, `CLAWBACK_PENDING` or `RECOVERED`, and moves the booking's `settlement_status` `UNFUNDED → DEPOSIT_PAID`."

    Design: Difficulty/non_linear_state_machine/booking_parallel_contract_and_settlement_dimensions
    """
    state = _booking_walked_through_both_dimensions(api)

    assert state["after_accept"]["contract_status"] == "PENDING_RIDER"
    assert state["after_accept"]["settlement_status"] == "UNFUNDED"

    assert state["after_deposit_paid"]["contract_status"] == "PENDING_RIDER"
    assert state["after_deposit_paid"]["settlement_status"] == "DEPOSIT_PAID"
    assert state["after_deposit_paid"]["deposit_paid_cents"] == 900000


def test_balance_payment_bubbles_the_contract_dimension_to_closed_out(api):
    """The contracting dimension reaches its terminal state only from the money one.

    "Releasing the balance installment additionally moves the booking's `settlement_status` `DEPOSIT_PAID → BALANCE_DUE`."
    "A balance payment moves `settlement_status` `BALANCE_DUE → SETTLED`, and that in turn bubbles the contract dimension `COUNTERSIGNED → CLOSED_OUT` when the booking's `contract_status` is `COUNTERSIGNED` at that moment."

    Design: Difficulty/non_linear_state_machine/booking_parallel_contract_and_settlement_dimensions
    """
    state = _booking_walked_through_both_dimensions(api)

    assert state["after_rider"]["contract_status"] == "RIDER_SETTLED"
    assert state["after_rider"]["settlement_status"] == "DEPOSIT_PAID"

    assert state["after_countersign"]["contract_status"] == "COUNTERSIGNED"
    assert state["after_countersign"]["settlement_status"] == "DEPOSIT_PAID"

    assert state["after_balance_release"]["contract_status"] == "COUNTERSIGNED"
    assert state["after_balance_release"]["settlement_status"] == "BALANCE_DUE"

    assert state["after_balance_paid"]["contract_status"] == "CLOSED_OUT"
    assert state["after_balance_paid"]["settlement_status"] == "SETTLED"
    assert state["after_balance_paid"]["settlement_total_cents"] == 990000
    assert state["after_balance_paid"][
        "settlement_total_cents"
    ] == expected_settlement_total_cents(1800000, 100000, 0, 900000)


def test_countersigning_a_closed_out_booking_is_refused(api):
    """Nothing on the contracting dimension survives CLOSED_OUT.

    "The contracting dimension walks `PENDING_RIDER`, `RIDER_SETTLED`, `COUNTERSIGNED` and terminates in `CLOSED_OUT` or `CANCELLED`; once it reaches `CLOSED_OUT` no further contract transition is accepted."

    Design: Difficulty/non_linear_state_machine/booking_parallel_contract_and_settlement_dimensions
    """
    state = _booking_walked_through_both_dimensions(api)
    assert state["after_balance_paid"]["contract_status"] == "CLOSED_OUT"

    validate_error(
        api.countersign_booking(state["booking"]["id"], BUSINESS_AFFAIRS),
        "ERR_INVALID_BOOKING_STATE",
        409,
    )

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    assert booking["contract_status"] == "CLOSED_OUT"
    assert booking["settlement_status"] == "SETTLED"


# --------------------------------------------------------------------------
# the technical-advance revision loop
# --------------------------------------------------------------------------
def test_advance_packet_submit_and_return_cycle_counts_every_submission(api):
    """Each submission counts and re-stamps the advisory stage-day overage.

    "On success `status` moves to `SUBMITTED`, `submission_count` increases by one, `submitted_by_user_id` is overwritten with the submitter's `X-User-ID` on every submission, and `channel_overage` is re-stamped as the amount by which that same stage-day channel total including this packet exceeds the advisory comfort level of 96 channels, or 0 when it does not exceed it."
    "Production returns a packet for revision with a `return_reason`, which is recorded on the packet and moves `status` `SUBMITTED → RETURNED`."

    Design: Difficulty/non_linear_state_machine/advance_packet_return_resubmit_cycle
    """
    state = _stage_day_with_sibling_advance_packet(api)
    packet_id = state["packet"]["id"]
    assert state["packet"]["status"] == "DRAFT"
    assert state["packet"]["submission_count"] == 0
    assert state["packet"]["channel_overage"] == 0

    reasons = (
        "Stage plot missing monitor world position",
        "Channel list still disagrees with the plot",
        "Load-in offset conflicts with changeover",
    )
    for expected_count, reason in enumerate(reasons, start=1):
        submitted = validate_success(
            api.submit_advance_packet(packet_id, state["artist_one_headers"])
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_count"] == expected_count
        assert submitted["submitted_by_user_id"] == state["artist_one"]["id"]
        assert submitted["channel_overage"] == 4
        assert submitted["channel_overage"] == (40 + 60) - STAGE_CHANNEL_ADVISORY
        assert 40 + 60 <= STAGE_CHANNEL_HARD_MAX

        returned = validate_success(
            api.return_advance_packet(
                packet_id, {"return_reason": reason}, PRODUCTION_MANAGER
            )
        )
        assert returned["status"] == "RETURNED"
        assert returned["return_reason"] == reason

    sibling = validate_success(
        api.get_advance_packet(state["sibling_packet"]["id"], PRODUCTION_MANAGER)
    )
    assert sibling["channel_overage"] == 0


def test_fourth_advance_submission_exhausts_the_loop_in_returned(api):
    """The submission cap terminates the loop away from where it started.

    "Submitting the packet is available from `DRAFT` and from `RETURNED`, requires the parent booking's `contract_status` to be `PENDING_RIDER` or `RIDER_SETTLED`, and requires `submission_count` to be below the cap of three — the fourth attempt is `ERR_ADVANCE_SUBMISSIONS_EXHAUSTED`, and that cap is what terminates the `DRAFT → SUBMITTED → RETURNED → SUBMITTED` loop."

    Design: Difficulty/non_linear_state_machine/advance_packet_return_resubmit_cycle
    """
    state = _packet_after_three_submissions(api)

    validate_error(
        api.submit_advance_packet(state["packet"]["id"], state["artist_one_headers"]),
        "ERR_ADVANCE_SUBMISSIONS_EXHAUSTED",
        409,
    )

    packet = validate_success(
        api.get_advance_packet(state["packet"]["id"], PRODUCTION_MANAGER)
    )
    assert packet["status"] == "RETURNED"
    assert packet["submission_count"] == MAX_ADVANCE_SUBMISSIONS
    assert packet["return_reason"] == state["last_return_reason"]


def test_exhausted_advance_loop_blocks_the_countersignature(api):
    """With no approved packet the booking cannot be executed.

    "It requires the booking's `contract_status` to be `RIDER_SETTLED`, requires the booking's radius clause to be in `ACTIVE` or `WAIVED` — a `BREACHED` clause is refused with `ERR_RADIUS_BREACH_ACTIVE` — and requires the booking to have at least one advance packet in `APPROVED`, without which the answer is `ERR_ADVANCE_NOT_APPROVED`."

    Design: Difficulty/non_linear_state_machine/advance_packet_return_resubmit_cycle
    """
    state = _packet_after_three_submissions(api)

    validate_error(
        api.countersign_booking(state["booking_one"]["id"], BUSINESS_AFFAIRS),
        "ERR_ADVANCE_NOT_APPROVED",
        409,
    )

    booking = validate_success(
        api.get_booking(state["booking_one"]["id"], BUSINESS_AFFAIRS)
    )
    assert booking["contract_status"] == "RIDER_SETTLED"
