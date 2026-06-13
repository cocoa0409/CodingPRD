"""Two-axis booking lifecycle and the session-delivery revision loop (Difficulty rules 3, 7).

Covers the parallel schedule/settlement dimensions, the cyclic delivery revision loop,
and delivery's dependence on the booking's settlement state.
"""
from test_helpers import (
    setup_studio_room_client,
    setup_engineer,
    create_booking,
    pay_deposit,
    confirm,
    set_clock,
    check_in,
    check_out,
    assign_engineer,
    pay_balance,
    deliver,
    request_revision,
    get_booking,
    validate_error,
    api_client,
    make_engineer_headers,
    delivery_payload,
)


# =====================================================================
# Difficulty rule 3 — non_linear_state_machine:
#   booking_parallel_schedule_and_settlement_dimensions
# =====================================================================
class TestParallelBookingDimensions:
    """schedule_status and settlement_status advance independently on one Booking row."""

    def _setup_deposit_paid_held(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(booking, client, 14400)
        return booking

    def test_deposit_advances_only_the_money_axis(self):
        """PRD §3.6: "A deposit is paid by the `Client` and moves `settlement_status` from
        `AWAITING_DEPOSIT` to `DEPOSIT_PAID`."
        PRD §2.7: "A single booking row advances on each axis on its own schedule".

        Design: Difficulty/non_linear_state_machine/booking_parallel_schedule_and_settlement_dimensions
        """
        booking = self._setup_deposit_paid_held()
        bk = get_booking(booking["id"])
        # money axis moved to DEPOSIT_PAID; schedule axis still HELD
        assert bk["settlement_status"] == "DEPOSIT_PAID", bk["settlement_status"]
        assert bk["schedule_status"] == "HELD", bk["schedule_status"]

    def test_confirm_advances_schedule_axis_leaving_money_axis(self):
        """PRD §3.2: "Confirmation is a `StudioManager` action that advances `schedule_status`
        from `HELD` to `CONFIRMED`."
        PRD §2.7: "The two axes only synchronize at the moments §3 calls out explicitly —
        confirmation requires a paid deposit, check-out moves settlement from `DEPOSIT_PAID` to
        `BALANCE_DUE`, and cancellation drives settlement through the refund branch."

        Design: Difficulty/non_linear_state_machine/booking_parallel_schedule_and_settlement_dimensions
        """
        booking = self._setup_deposit_paid_held()
        confirmed = confirm(booking)
        assert confirmed["schedule_status"] == "CONFIRMED", confirmed["schedule_status"]
        # the money axis did NOT move — still DEPOSIT_PAID after confirm
        assert confirmed["settlement_status"] == "DEPOSIT_PAID", confirmed["settlement_status"]


# =====================================================================
# Difficulty rule 3 — non_linear_state_machine:
#   session_delivery_revision_cycle
# =====================================================================
class TestDeliveryRevisionCycle:
    """DELIVERED -> REVISION_REQUESTED -> DELIVERED cycle; revision_round increments only on
    the re-delivery hop."""

    def _setup_delivered(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60, "overtime_grace_minutes": 10},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF",
                                  hourly_rate_cents=8000)
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        assign_engineer(booking, engineer)
        pay_deposit(booking, client, 14400)
        confirm(booking)
        set_clock("2026-07-10T09:05:00Z")
        check_in(booking)
        booking = check_out(booking, "2026-07-10T12:30:00Z")
        residue = booking["total_charge_cents"] - booking["amount_paid_cents"]
        pay_balance(booking, client, residue)
        deliver(booking, engineer, [{"name": "mix_v1.wav", "size": 1000}])
        return studio, room, client, engineer, booking

    def test_revision_round_starts_at_zero_on_first_deliver(self):
        """PRD §3.9: "the engineer hands over the files through a `SessionDelivery`, which
        references its `booking_id`, carries a `file_manifest` (a list of delivered file
        descriptors), a computed `revision_round` counter starting at zero".
        PRD §3.9: "An `Engineer` performs the initial delivery, which moves the delivery's
        `status` from `DRAFT` to `DELIVERED`."

        Design: Difficulty/non_linear_state_machine/session_delivery_revision_cycle
        """
        studio, room, client, engineer, booking = self._setup_delivered()
        delivery = api_client.list_booking_delivery(booking["id"],
                                                    make_engineer_headers(engineer["id"])).json()["data"][0]
        assert delivery["status"] == "DELIVERED", delivery["status"]
        assert delivery["revision_round"] == 0, delivery["revision_round"]

    def test_two_revision_rounds_drive_counter_to_two(self):
        """PRD §3.9: "the engineer then re-delivers, supplying a non-empty `file_manifest`, which
        moves the status from `REVISION_REQUESTED` back to `DELIVERED` and increments
        `revision_round` by one (as well as the delivery's `version`). This loop may repeat until
        the client is satisfied."

        Design: Difficulty/non_linear_state_machine/session_delivery_revision_cycle
        """
        studio, room, client, engineer, booking = self._setup_delivered()
        # round 1
        request_revision(booking, client)
        deliver(booking, engineer, [{"name": "mix_v2.wav", "size": 1100}])
        # round 2
        request_revision(booking, client)
        final = deliver(booking, engineer, [{"name": "mix_v3.wav", "size": 1200}])
        assert final["status"] == "DELIVERED", final["status"]
        assert final["revision_round"] == 2, final["revision_round"]


# =====================================================================
# Difficulty rule 7 — cross_entity_state_dependency:
#   deliver_depends_on_booking_settlement_state
# =====================================================================
class TestDeliverDependsOnSettlement:
    """An engineer's first deliver is rejected while the booking is COMPLETED but not SETTLED."""

    def _setup_completed_balance_due(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60, "overtime_grace_minutes": 10},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF",
                                  hourly_rate_cents=8000)
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        assign_engineer(booking, engineer)
        pay_deposit(booking, client, 14400)
        confirm(booking)
        set_clock("2026-07-10T09:05:00Z")
        check_in(booking)
        booking = check_out(booking, "2026-07-10T12:30:00Z")  # COMPLETED, settlement BALANCE_DUE
        return engineer, booking

    def test_deliver_before_settled_returns_not_deliverable(self):
        """PRD §3.9: "This is permitted only when the booking's schedule_status is COMPLETED and
        its settlement_status is SETTLED, and only when the file_manifest is non-empty; an
        attempt before the booking is both completed and settled, or after the delivery has
        already been ACCEPTED, is rejected with ERR_SESSION_NOT_DELIVERABLE."

        Design: Difficulty/cross_entity_state_dependency/deliver_depends_on_booking_settlement_state
        """
        engineer, booking = self._setup_completed_balance_due()
        bk = get_booking(booking["id"])
        assert bk["settlement_status"] == "BALANCE_DUE", bk["settlement_status"]
        res = api_client.deliver_session(booking["id"], delivery_payload([{"name": "mix.wav", "size": 1000}]),
                                         make_engineer_headers(engineer["id"]))
        validate_error(res, "ERR_SESSION_NOT_DELIVERABLE", expected_status=409)

    def test_completed_balance_due_booking_is_not_settled(self):
        """PRD §3.3: "Check-out advances schedule_status from IN_SESSION to COMPLETED and, on the
        money axis, moves settlement_status from DEPOSIT_PAID to BALANCE_DUE, because the full
        bill is now known and the balance is owed."

        Design: Difficulty/cross_entity_state_dependency/deliver_depends_on_booking_settlement_state
        """
        engineer, booking = self._setup_completed_balance_due()
        res = api_client.deliver_session(booking["id"], delivery_payload([{"name": "mix.wav", "size": 1000}]),
                                         make_engineer_headers(engineer["id"]))
        # still rejected: the booking is COMPLETED but settlement_status != SETTLED
        validate_error(res, "ERR_SESSION_NOT_DELIVERABLE", expected_status=409)
