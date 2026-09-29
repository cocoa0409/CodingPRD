"""Two ledgers that must come back to where they started: the room-per-night
ledger of a block after a carve is rejected, and the cash ledger of an event after
a commission payment is reversed."""

from test_helpers import (
    COORDINATOR,
    assert_block_inventory_invariant,
    carve_sub_block,
    read_block,
    reject_sub_block,
    reverse_payment,
    setup_contracted_block,
    setup_paid_invoice,
    validate_success,
)

GENERAL_THEN_STAFF = [
    {"segment": "GENERAL", "allotted_rooms": 6},
    {"segment": "STAFF", "allotted_rooms": 4, "eligibility_code": "STAFF-GOLD"},
]

# Six room nights of confirmed stays: 4 nights plus 2 nights at 21900 cents.
TWO_STAYS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 2},
    {"check_in_date": "2026-09-15", "check_out_date": "2026-09-17", "occupants": 1},
]

FULL_COMMISSION_CENTS = 15768


def _carve_general_and_staff():
    """Carve the whole block into a GENERAL and a STAFF allotment."""
    ctx = setup_contracted_block(contracted_rooms_per_night=10)
    general = carve_sub_block(ctx["block"]["id"], "GENERAL", 6)
    staff = carve_sub_block(
        ctx["block"]["id"], "STAFF", 4, eligibility_code="STAFF-GOLD"
    )
    ctx["sub_blocks"] = [general, staff]
    return ctx


class TestSubBlockRejectionRestoresTheRoomLedger:
    """Rejecting a carve puts every room back where it came from."""

    def test_rejection_returns_the_allotment_to_the_unassigned_pool(self, api):
        """PRD §2.7: "For any contracted block, the current
        `contracted_rooms_per_night` always equals the sum of three quantities:
        the `unassigned_rooms_per_night` still available to carve, the
        `released_rooms_per_night` permanently handed back to the hotel, and the
        total `allotted_rooms` across every sub-block of the block whose
        `approval_status` is `PENDING_APPROVAL`, `APPROVED`, or `RELEASED`."
        PRD §2.7: "Sub-blocks whose `approval_status` is `REJECTED` contribute
        nothing, because rejection returns their rooms to the pool and zeroes
        their allotment."
        PRD §3.3: "Controller rejection moves it `PENDING_APPROVAL → REJECTED`, a
        terminal state, and unwinds the carve completely: the rooms go back where
        they came from — added to the block's `unassigned_rooms_per_night` when
        `parent_sub_block_id` is null, or added back to the parent sub-block's
        `allotted_rooms` when it is not — and the rejected sub-block's own
        `allotted_rooms` is set to 0."

        Design: Difficulty/compensating_invariant/sub_block_reject_restores_room_per_night_conservation
        """
        ctx = _carve_general_and_staff()
        general, staff = ctx["sub_blocks"]

        rejected = reject_sub_block(staff["id"])
        assert rejected["approval_status"] == "REJECTED"
        assert rejected["allotted_rooms"] == 0

        block = read_block(ctx["block"]["id"])
        assert block["contracted_rooms_per_night"] == 10
        assert block["unassigned_rooms_per_night"] == 4, (
            "the 4 rejected rooms must return to the unassigned pool, got "
            f"{block['unassigned_rooms_per_night']}"
        )
        assert block["released_rooms_per_night"] == 0

        general_after = validate_success(api.get_sub_block(general["id"], COORDINATOR))
        assert general_after["allotted_rooms"] == 6
        assert_block_inventory_invariant(block, [general_after, rejected])

    def test_the_ledger_also_balances_while_the_carve_is_still_pending(self, api):
        """PRD §2.7: "Rooms move between the three buckets and never appear or
        vanish. Carving a sub-block moves rooms out of
        `unassigned_rooms_per_night` (or, for a nested carve, out of the parent
        sub-block's `allotted_rooms`)."
        PRD §3.3: "on success the rooms are debited from the source:
        `unassigned_rooms_per_night` falls by `allotted_rooms` on a direct carve,
        and the parent's `allotted_rooms` falls by the same amount on a nested
        one."

        Design: Difficulty/compensating_invariant/sub_block_reject_restores_room_per_night_conservation
        """
        ctx = _carve_general_and_staff()
        general, staff = ctx["sub_blocks"]
        assert staff["approval_status"] == "PENDING_APPROVAL"

        mid_flight = read_block(ctx["block"]["id"])
        assert mid_flight["unassigned_rooms_per_night"] == 0
        assert mid_flight["released_rooms_per_night"] == 0
        # The pending STAFF allotment still counts toward the ledger.
        assert_block_inventory_invariant(mid_flight, [general, staff])

        reject_sub_block(staff["id"])
        after = read_block(ctx["block"]["id"])
        assert after["unassigned_rooms_per_night"] == 4
        assert after["version"] > mid_flight["version"]


class TestPaymentReversalRestoresTheCashLedger:
    """A full reversal returns the invoice and the event aggregate to issuance."""

    def test_full_reversal_reopens_the_invoice_and_zeroes_collected_commission(
        self, api
    ):
        """PRD §3.9: "A **full reversal**, where `amount_cents` equals
        `paid_cents`, sets `paid_cents` to 0 and `outstanding_cents` back to
        `commission_due_cents` minus `written_off_cents`, and returns the invoice
        to `ISSUED` from either starting point — `PARTIALLY_PAID → ISSUED` or
        `PAID → ISSUED`."
        PRD §3.9: "Either way the event's `commission_collected_cents` is
        recomputed and the invoice's `version` is bumped."
        PRD §3.1: "`commission_collected_cents` accumulates the `paid_cents` of
        every commission invoice raised against any block of the event."

        Design: Difficulty/compensating_invariant/commission_payment_reversal_restores_collected_cash_ledger
        """
        ctx = setup_paid_invoice(
            FULL_COMMISSION_CENTS, stays=TWO_STAYS, general_rooms=6
        )
        paid = ctx["invoice"]
        assert paid["status"] == "PAID"
        assert paid["commission_due_cents"] == FULL_COMMISSION_CENTS
        assert paid["paid_cents"] == FULL_COMMISSION_CENTS
        assert paid["outstanding_cents"] == 0

        settled_event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert settled_event["commission_collected_cents"] == FULL_COMMISSION_CENTS

        reversed_invoice = reverse_payment(paid["id"], FULL_COMMISSION_CENTS)
        assert reversed_invoice["status"] == "ISSUED"
        assert reversed_invoice["paid_cents"] == 0
        assert reversed_invoice["written_off_cents"] == 0
        assert reversed_invoice["outstanding_cents"] == FULL_COMMISSION_CENTS
        assert reversed_invoice["version"] > paid["version"]

        event_after = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event_after["commission_collected_cents"] == 0, (
            "reversing the only payment must return the event's collected cash to "
            f"zero, got {event_after['commission_collected_cents']}"
        )

    def test_the_reversal_leaves_the_billed_figures_untouched(self, api):
        """PRD §3.9: "On `BUREAU_CONFIRMED`, `commission_due_cents` takes
        `bureau_confirmed_commission_cents` and `billable_room_nights` takes the
        bureau room-night total — so rooms the hotel failed to attribute to the
        block are still billed."
        PRD §3.9: "`rebate_due_cents`, the money owed to the organizer, is the
        block's `rebate_per_room_night_cents` multiplied by
        `billable_room_nights`."

        Design: Difficulty/compensating_invariant/commission_payment_reversal_restores_collected_cash_ledger
        """
        ctx = setup_paid_invoice(
            FULL_COMMISSION_CENTS, stays=TWO_STAYS, general_rooms=6
        )
        reversed_invoice = reverse_payment(ctx["invoice"]["id"], FULL_COMMISSION_CENTS)

        assert reversed_invoice["basis"] == "BUREAU_CONFIRMED"
        assert (
            reversed_invoice["bureau_confirmed_commission_cents"]
            == FULL_COMMISSION_CENTS
        )
        assert reversed_invoice["commission_due_cents"] == FULL_COMMISSION_CENTS
        assert reversed_invoice["billable_room_nights"] == 6
        assert reversed_invoice["rebate_due_cents"] == 4200
        assert reversed_invoice["hotel_block_id"] == ctx["block"]["id"]
