"""Reversals and abandonments that must still balance the books.

A confirmation undone by a cancellation has to restore the block's counters
exactly; a write-off after a part payment has to park the abandoned cents without
altering what was owed.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    InvoiceLifecycleAction,
    assertions,
    factories as f,
    fixtures as fx,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS

_AUTUMN_CUP = {
    "name": "Autumn Cup 2026",
    "start_date": "2026-09-15",
    "end_date": "2026-09-18",
    "booking_deadline": "2026-09-10T00:00:00Z",
}


def _confirmed_booking_filling_its_block_env(api) -> fx.Env:
    """A five-room confirmed booking on the event's only five-room block, which
    the confirmation has driven to `RESTRICTED`."""
    env = fx.executed_contract_env(
        api,
        tournament_overrides=dict(_AUTUMN_CUP),
        contract_overrides={"cutoff_date": "2026-08-25"},
        block_overrides={
            "block_size_rooms": 5,
            "arrival_date": "2026-09-15",
            "departure_date": "2026-09-18",
            "release_deadline": "2026-08-30",
        },
    )
    fx.add_team(env)
    fx.add_registration(env)
    fx.add_booking(
        env,
        rooms_requested=5,
        check_in_date="2026-09-15",
        check_out_date="2026-09-18",
    )
    fx.submit_rooming_list(
        env,
        entries=[f.rooming_list_entry(index + 1, occupant_count=3) for index in range(5)],
    )
    env.booking = fx.confirm_booking(env)
    return env


def _partially_paid_invoice_env(api) -> fx.Env:
    """A 16,200-cent invoice that has received a single 6,200-cent instalment."""
    env = fx.executed_contract_env(api)
    fx.add_team(env)
    fx.add_registration(env)
    fx.add_booking(env, rooms_requested=6)
    fx.submit_rooming_list(
        env,
        entries=[f.rooming_list_entry(index + 1, occupant_count=2) for index in range(6)],
    )
    env.booking = fx.confirm_booking(env)
    fx.close_booking_window(env)
    fx.actualize(env, 18, report_note="final folio")
    fx.create_invoice(env)
    fx.issue_invoice(env)
    fx.remit(env, 6200)
    return env


class TestRoomInventoryConservationConfirmThenCancel:
    """Confirming and then cancelling the same booking restores the block."""

    def test_the_cancellation_restores_all_three_block_counters_exactly(self, api):
        """The block goes back to five available rooms, nothing committed, nothing
        released unsold and a utilization of 0 — its pre-confirmation reading.

        PRD §3.5: "The block's `rooms_committed`, `rooms_available` and
        `utilization_pct` are recomputed, which may fire the `RESTRICTED → OPEN`
        flip and, through it, recompute the contract's `block_posture` and the
        tournament's `housing_pressure` — the confirm chain run in reverse from the
        block downstream."

        PRD §3.5: "This forward-and-compensating symmetry is the case the room
        inventory invariant of §2.12 pins: confirming a booking and then cancelling
        that same booking must restore all three block counters to their
        pre-confirmation values exactly."

        PRD §2.12: "While a room block's `status` is `OPEN` or `RESTRICTED`, its
        `rooms_committed` and `rooms_available` sum to exactly `block_size_rooms`,
        and its `rooms_released_unsold` is 0."

        Design: Difficulty/compensating_invariant/room_inventory_conservation_confirm_then_cancel
        """
        env = _confirmed_booking_filling_its_block_env(api)
        assert env.refresh_block()["status"] == "RESTRICTED"

        cancelled = validate_success(
            api.cancel_booking(env.booking_id, f.cancel_payload(), HM)
        )

        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["projected_room_nights"] == 15
        assert cancelled["penalty_room_nights"] == 0
        assert cancelled["penalty_cents"] == 0
        block = env.refresh_block()
        assert block["block_size_rooms"] == 5
        assert block["rooms_committed"] == 0
        assert block["rooms_available"] == 5
        assert block["rooms_released_unsold"] == 0
        assert block["utilization_pct"] == 0.0
        assert block["status"] == "OPEN"
        assertions.assert_block_inventory_conserved(block)

    def test_the_reverse_chain_walks_the_release_all_the_way_back_up(self, api):
        """The contract's posture returns to `AVAILABLE`, the event's pressure
        returns to `NORMAL`, and the team falls back to `PENDING_HOUSING`.

        PRD §3.2: "If at least one live block is `RESTRICTED` but not all of them
        are, it is `TIGHT`."

        PRD §3.2: "Otherwise it is `AVAILABLE`."

        PRD §3.2: "`housing_pressure` reads `CONSTRAINED` when
        `executed_contract_count` is at least 1 and `sold_out_contract_count`
        equals `executed_contract_count`; in every other case, including the case
        of no executed contracts at all, it reads `NORMAL`."

        PRD §3.5: "The registration's `committed_rooms` and `status` are recomputed
        too, and a team may legitimately fall back from `HOUSING_COMPLIANT` to
        `PENDING_HOUSING` when the rooms it was relying on disappear."

        Design: Difficulty/compensating_invariant/room_inventory_conservation_confirm_then_cancel
        """
        env = _confirmed_booking_filling_its_block_env(api)
        assert env.refresh_contract()["block_posture"] == "SOLD_OUT"
        assert env.refresh_tournament()["housing_pressure"] == "CONSTRAINED"
        assert env.refresh_registration()["status"] == "HOUSING_COMPLIANT"

        validate_success(api.cancel_booking(env.booking_id, f.cancel_payload(), HM))

        assert env.refresh_contract()["block_posture"] == "AVAILABLE"
        tournament = env.refresh_tournament()
        assert tournament["sold_out_contract_count"] == 0
        assert tournament["housing_pressure"] == "NORMAL"
        registration = env.refresh_registration()
        assert registration["committed_rooms"] == 0
        assert registration["status"] == "PENDING_HOUSING"


class TestRebateLedgerConservationPartialRemitThenWriteOff:
    """A part payment followed by a write-off still balances the invoice."""

    def test_the_write_off_parks_the_abandoned_cents_without_moving_the_amount_due(
        self, api
    ):
        """Of 16,200 cents due, 6,200 stay collected and the remaining 10,000 are
        written off, leaving nothing outstanding.

        PRD §3.8: "`WRITE_OFF`, a housing-manager action, moves the invoice from
        `ISSUED`, from `PARTIALLY_PAID` or from `DISPUTED` to `WRITTEN_OFF`: it
        sets `written_off_cents` to whatever `outstanding_cents` then stood at and
        drives `outstanding_cents` to 0, leaving `total_due_cents` and
        `collected_cents` untouched, exactly as the rebate ledger invariant of
        §2.12 requires."

        PRD §2.12: "A partial remittance followed by a write-off must therefore
        leave `total_due_cents` unchanged, drive `outstanding_cents` to exactly 0,
        and park the abandoned cents in `written_off_cents`."

        PRD §2.12: "On every rebate invoice, `collected_cents`, `written_off_cents`
        and `outstanding_cents` sum to exactly `total_due_cents`, and none of the
        three is ever negative."

        Design: Difficulty/compensating_invariant/rebate_ledger_conservation_partial_remit_then_write_off
        """
        env = _partially_paid_invoice_env(api)
        assert env.invoice["status"] == "PARTIALLY_PAID"
        assert env.invoice["total_due_cents"] == 16200
        assert env.invoice["outstanding_cents"] == 10000

        invoice = validate_success(
            api.invoice_lifecycle(
                env.invoice_id,
                f.lifecycle_payload(InvoiceLifecycleAction.WRITE_OFF.value),
                HM,
            )
        )

        assert invoice["status"] == "WRITTEN_OFF"
        assert invoice["total_due_cents"] == 16200
        assert invoice["collected_cents"] == 6200
        assert invoice["written_off_cents"] == 10000
        assert invoice["outstanding_cents"] == 0
        assertions.assert_rebate_ledger_conserved(invoice)

    def test_money_having_been_collected_sends_the_booking_to_short_paid(self, api):
        """Because 6,200 cents were received before the write-off, the booking's
        money axis resolves to `SHORT_PAID` rather than `WRITTEN_OFF`, and its
        reservation axis does not move.

        PRD §3.8: "Every booking of the contract whose `rebate_status` is
        `INVOICED` moves to `WRITTEN_OFF` when the invoice's `collected_cents` is
        0, and to `SHORT_PAID` when `collected_cents` is greater than 0."

        PRD §3.8: "a write-off from `PARTIALLY_PAID` always yields `SHORT_PAID`
        bookings"

        PRD §3.7: "The **money axis**, `rebate_status`, runs `NOT_DUE → ACCRUED →
        INVOICED` and then to one of `COLLECTED`, `SHORT_PAID` or `WRITTEN_OFF`,
        and every one of its transitions is system-driven and leaves
        `booking_status` untouched."

        Design: Difficulty/compensating_invariant/rebate_ledger_conservation_partial_remit_then_write_off
        """
        env = _partially_paid_invoice_env(api)

        validate_success(
            api.invoice_lifecycle(
                env.invoice_id,
                f.lifecycle_payload(InvoiceLifecycleAction.WRITE_OFF.value),
                HM,
            )
        )

        booking = env.refresh_booking()
        assert booking["rebate_status"] == "SHORT_PAID"
        assert booking["booking_status"] == "CHECKED_OUT"
        assert booking["rebate_accrued_cents"] == 16200
        assert env.refresh_tournament()["posture"] == "RECONCILING"
