"""Lifecycle transitions: initial states, self-transitions, refused transitions,
terminal lockdown, the cyclic invoice axis, and the ledgers the transitions sync."""

from test_helpers import (
    COMPLIANCE,
    COORDINATOR,
    adjust_invoice,
    advance_to_cutoff_and_sweep,
    assemble_block,
    book_reservation,
    cancel_reservation,
    carve_sub_block,
    confirm_vendor,
    create_hotel_block_payload,
    dispute_invoice,
    make_attendee_headers,
    pay_invoice,
    read_block,
    register_event,
    register_hotel,
    release_sub_block_rooms,
    setup_closed_block,
    setup_contracted_block,
    setup_issued_invoice,
    setup_open_block,
    setup_open_block_with_reservations,
    setup_vendor_with_incidents,
    validate_error,
    validate_success,
)

ONE_FOUR_NIGHT_STAY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
]

# Four room nights plus two room nights at 21900 cents pre-tax.
FOUR_AND_TWO_NIGHTS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
    {"check_in_date": "2026-09-15", "check_out_date": "2026-09-17", "occupants": 1},
]

# The hotel only attributes 3 of the 6 room nights to the block.
UNDER_REPORTED_PICKUP = [
    {
        "as_of_date": "2026-08-19",
        "reported_rooms_picked_up": 1,
        "reported_room_nights": 3,
        "reported_gross_revenue_cents": 65700,
    }
]


class TestHotelBlockInitialState:
    def test_a_freshly_assembled_block_holds_no_rooms_in_any_bucket(self, api):
        """PRD §3.2: "A housing block is the junction of one event and one property,
        and it is assembled by a `BureauCoordinator` in `DRAFT`."
        PRD §3.2: "The new block starts with `revision_round` at 0,
        `unassigned_rooms_per_night` and `released_rooms_per_night` at 0,
        `attrition_liability_cents` at 0, and `confirmation_number` null; its
        `contracted_room_nights` is the product of `contracted_rooms_per_night` and
        the event's `night_count`, and is re-derived whenever either factor moves."
        PRD §2.4: "`version` — an integer that starts at 1 on creation and increases
        by exactly 1 on every mutation of the resource, including mutations the
        server performs on its own initiative as part of a cascade."

        Design: Corner/state_machines/hotel_block_starts_in_draft_with_zero_room_accounting
        """
        event = register_event()
        hotel = register_hotel()

        block = validate_success(
            api.create_hotel_block(
                create_hotel_block_payload(event["id"], hotel["id"]), COORDINATOR
            ),
            201,
        )

        assert block["status"] == "DRAFT"
        assert block["revision_round"] == 0
        assert block["contracted_rooms_per_night"] == 10
        assert block["contracted_room_nights"] == 40
        assert block["unassigned_rooms_per_night"] == 0, (
            "rooms only enter the inventory ledger at contract time, got "
            f"{block['unassigned_rooms_per_night']}"
        )
        assert block["released_rooms_per_night"] == 0
        assert block["attrition_liability_cents"] == 0
        assert block["confirmation_number"] is None
        assert block["version"] == 1


class TestSubBlockPartialRelease:
    def test_releasing_two_of_six_uncommitted_rooms_keeps_the_carve_approved(self, api):
        """PRD §3.3: "A **partial release**, where `rooms` is smaller than
        `allotted_rooms`, leaves the sub-block in `APPROVED` (an `APPROVED →
        APPROVED` self-transition): `allotted_rooms` falls by `rooms`, the
        sub-block's own `released_rooms` rises by `rooms`, and the block's
        `released_rooms_per_night` rises by `rooms`."
        PRD §3.3: "`available_rooms` is `allotted_rooms` minus `committed_rooms`."
        PRD §3.3: "The release is admissible only when `rooms` is less than or equal
        to `allotted_rooms` minus `committed_rooms`"

        Design: Corner/state_machines/sub_block_partial_release_returns_rooms_and_stays_approved
        """
        ctx = setup_contracted_block(contracted_rooms_per_night=10)
        carve = carve_sub_block(ctx["block"]["id"], "GENERAL", 6)
        assert carve["approval_status"] == "APPROVED"
        assert read_block(ctx["block"]["id"])["unassigned_rooms_per_night"] == 4

        released = release_sub_block_rooms(carve["id"], 2)

        assert released["approval_status"] == "APPROVED", (
            "a partial release is a self-transition, not a move to RELEASED, got "
            f"{released['approval_status']}"
        )
        assert released["allotted_rooms"] == 4
        assert released["released_rooms"] == 2
        assert released["available_rooms"] == 4
        assert released["version"] > carve["version"]

        block = read_block(ctx["block"]["id"])
        assert block["released_rooms_per_night"] == 2
        assert block["unassigned_rooms_per_night"] == 4


class TestCutoffBeforeTheCutoffDate:
    def test_sweeping_early_leaves_the_block_open_and_its_allotments_intact(self, api):
        """PRD §3.9: "The cutoff is the moment unsold inventory reverts to the
        property, and a `BureauCoordinator` triggers it once the logical clock has
        reached the block's `cutoff_date` at midnight UTC; attempting it earlier is
        rejected with `ERR_CUTOFF_NOT_REACHED`, and attempting it from any status
        other than `OPEN` is rejected with `ERR_INVALID_BLOCK_STATE`."
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; until it is repositioned it holds that value and
        never falls back to real time."

        Design: Corner/state_machines/block_cutoff_before_cutoff_date_rejected
        """
        ctx = setup_open_block(general_rooms=6)
        assert ctx["block"]["status"] == "OPEN"
        assert ctx["block"]["cutoff_date"] == "2026-08-21"

        response = api.cutoff_hotel_block(ctx["block"]["id"], COORDINATOR)
        validate_error(response, "ERR_CUTOFF_NOT_REACHED", 409)

        after = read_block(ctx["block"]["id"])
        assert after["status"] == "OPEN"
        assert after["version"] == ctx["block"]["version"]
        assert after["released_rooms_per_night"] == 0

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["allotted_rooms"] == 6


class TestCutoffSweepSideEffects:
    def test_the_sweep_releases_carve_headroom_and_unassigned_rooms_together(self, api):
        """PRD §3.9: "The sweep moves the block `OPEN → CUTOFF_PASSED` and then
        walks every sub-block of the block whose `approval_status` is `APPROVED`, in
        ascending `carve_seq` order. For each one, the released quantity is its
        `allotted_rooms` minus its `committed_rooms`: that quantity is added to the
        sub-block's `released_rooms`, the sub-block's `allotted_rooms` is set down to
        exactly its `committed_rooms`, and the same quantity is added to the block's
        `released_rooms_per_night`. The block's remaining
        `unassigned_rooms_per_night` is then added wholesale to
        `released_rooms_per_night` and set to 0."
        PRD §3.9: "Any sub-block whose `allotted_rooms` became 0 through this sweep
        moves `APPROVED → RELEASED`. The event's `housing_posture` is recomputed and
        the block's `version` is bumped."
        PRD §2.11: "Otherwise — that is, when the open group is empty but the ended
        group is not — the posture is `CLOSED`."

        Design: Corner/state_machines/cutoff_sweep_releases_unsold_and_unassigned_rooms
        """
        ctx = setup_open_block_with_reservations(
            ONE_FOUR_NIGHT_STAY, general_rooms=6, contracted_rooms_per_night=10
        )
        assert ctx["block"]["unassigned_rooms_per_night"] == 4

        ctx = advance_to_cutoff_and_sweep(ctx)

        assert ctx["block"]["status"] == "CUTOFF_PASSED"
        assert ctx["block"]["unassigned_rooms_per_night"] == 0
        assert ctx["block"]["released_rooms_per_night"] == 9, (
            "5 rooms of carve headroom plus 4 unassigned rooms go back to the "
            f"hotel, got {ctx['block']['released_rooms_per_night']}"
        )

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["allotted_rooms"] == 1
        assert sub_block["released_rooms"] == 5
        assert sub_block["approval_status"] == "APPROVED"

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["housing_posture"] == "CLOSED"

        reservation = validate_success(
            api.get_reservation(ctx["reservations"][0]["id"], COORDINATOR)
        )
        assert reservation["reservation_status"] == "CONFIRMED"


class TestCloseFromOpen:
    def test_closing_an_open_block_reports_the_state_error_not_the_clock_error(
        self, api
    ):
        """PRD §3.9: "A `BureauCoordinator` moves the block `CUTOFF_PASSED → CLOSED`
        — the block's terminal state — and this is admissible only once the logical
        clock has reached the event's `event_end_date` at midnight UTC; earlier
        attempts are rejected with `ERR_EVENT_NOT_ENDED`, and attempts from any other
        block status with `ERR_INVALID_BLOCK_STATE`."
        PRD §2.10: "**Own-state transition legality** — the target resource is in a
        state from which the requested transition exists."
        PRD §2.10: "**Logical-clock gates on the block lifecycle and reservation
        writes.**"

        Design: Corner/state_machines/block_close_directly_from_open_rejected
        """
        ctx = setup_open_block(general_rooms=6)

        response = api.close_hotel_block(ctx["block"]["id"], COORDINATOR)
        validate_error(response, "ERR_INVALID_BLOCK_STATE", 409)

        after = read_block(ctx["block"]["id"])
        assert after["status"] == "OPEN"
        assert after["attrition_liability_cents"] == 0
        assert after["version"] == ctx["block"]["version"]


class TestClosedBlockLockdown:
    def test_no_transition_survives_the_close_and_the_liability_stays_frozen(
        self, api
    ):
        """PRD §3.9: "A `BureauCoordinator` moves the block `CUTOFF_PASSED → CLOSED`
        — the block's terminal state — and this is admissible only once the logical
        clock has reached the event's `event_end_date` at midnight UTC; earlier
        attempts are rejected with `ERR_EVENT_NOT_ENDED`, and attempts from any other
        block status with `ERR_INVALID_BLOCK_STATE`."
        PRD §3.9: "Closure freezes the attrition exposure:
        `attrition_liability_cents` is set to the post-reduction attrition penalty
        exposure defined in §3.7, computed against the block as it finally stands."
        PRD §3.4: "A block reaches the attendee portal when a `BureauCoordinator`
        opens it, advancing it `CONTRACTED → OPEN`; an open attempted from any status
        other than `CONTRACTED` is rejected with `ERR_INVALID_BLOCK_STATE`."

        Design: Corner/state_machines/closed_block_terminal_lockdown_rejects_further_transitions
        """
        ctx = setup_closed_block(
            ONE_FOUR_NIGHT_STAY, general_rooms=2, contracted_rooms_per_night=2
        )
        closed = ctx["block"]
        assert closed["status"] == "CLOSED"
        assert closed["attrition_liability_cents"] == 30660

        block_id = closed["id"]
        validate_error(
            api.close_hotel_block(block_id, COORDINATOR), "ERR_INVALID_BLOCK_STATE", 409
        )
        validate_error(
            api.cutoff_hotel_block(block_id, COORDINATOR),
            "ERR_INVALID_BLOCK_STATE",
            409,
        )
        validate_error(
            api.open_hotel_block(block_id, COORDINATOR), "ERR_INVALID_BLOCK_STATE", 409
        )

        after = read_block(block_id)
        assert after["status"] == "CLOSED"
        assert after["version"] == closed["version"], (
            "three refused transitions must leave the block's version alone, got "
            f"{after['version']} against {closed['version']}"
        )
        assert after["attrition_liability_cents"] == 30660


class TestSecondCancelIsRefused:
    def test_cancelling_twice_does_not_free_the_room_twice(self, api):
        """PRD §3.5: "Cancellation, available to the delegate who owns the stay and
        to a `BureauCoordinator`, moves the reservation `CONFIRMED → CANCELLED`. It
        requires the parent block to be in `OPEN` or `CUTOFF_PASSED`; from any other
        block status, or from a reservation that is not `CONFIRMED`, the attempt is
        rejected with `ERR_RESERVATION_NOT_MODIFIABLE`."
        PRD §3.5: "`reservation_status` tracks occupancy and runs `CONFIRMED`,
        `WAITLISTED`, `CANCELLED` and `NO_SHOW`, with `CANCELLED` and `NO_SHOW`
        terminal."
        PRD §3.3: "Only `CONFIRMED` reservations occupy inventory: `WAITLISTED`,
        `CANCELLED` and `NO_SHOW` rows count for nothing."

        Design: Corner/state_machines/second_cancel_of_cancelled_reservation_rejected
        """
        ctx = setup_open_block_with_reservations(ONE_FOUR_NIGHT_STAY, general_rooms=6)
        reservation = ctx["reservations"][0]
        guest = ctx["attendees"][0]

        cancelled = cancel_reservation(reservation["id"], guest["id"])
        assert cancelled["reservation_status"] == "CANCELLED"

        response = api.cancel_reservation(
            reservation["id"], make_attendee_headers(guest["id"])
        )
        validate_error(response, "ERR_RESERVATION_NOT_MODIFIABLE", 409)

        after = validate_success(api.get_reservation(reservation["id"], COORDINATOR))
        assert after["reservation_status"] == "CANCELLED"
        assert after["version"] == cancelled["version"]

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 0

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 0


class TestInvoiceDisputeAdjustCycle:
    def test_a_disputed_invoice_is_written_down_and_then_settled(self, api):
        """PRD §3.9: "On `HOTEL_REPORTED`, `commission_due_cents` takes
        `hotel_reported_commission_cents` and `billable_room_nights` takes the latest
        report's `reported_room_nights` — so unattributed rooms silently disappear
        from the bill and surface only as variance."
        PRD §3.9: "The tolerance is the greater of a floor of 5,000 cents — fifty
        dollars — and one percent of `bureau_confirmed_commission_cents` rounded half
        up to whole cents."
        PRD §3.9: "It raises `written_off_cents` by `write_off_cents`, re-derives
        `outstanding_cents`, moves the invoice `DISPUTED → ADJUSTED`, and bumps its
        `version`. From `ADJUSTED` the hotel settles the remainder, closing the
        loop."
        PRD §3.9: "A payment exactly equal to `outstanding_cents` settles it:
        `ISSUED → PAID`, `PARTIALLY_PAID → PAID`, or `ADJUSTED → PAID`."

        Design: Corner/state_machines/invoice_dispute_adjust_cycle_returns_invoice_to_paid
        """
        ctx = setup_issued_invoice(
            stays=FOUR_AND_TWO_NIGHTS,
            basis="HOTEL_REPORTED",
            pickup_reports=UNDER_REPORTED_PICKUP,
            general_rooms=6,
        )
        invoice = ctx["invoice"]
        assert invoice["status"] == "ISSUED"
        assert invoice["bureau_confirmed_commission_cents"] == 15768
        assert invoice["hotel_reported_commission_cents"] == 7884
        assert invoice["variance_cents"] == 7884
        assert invoice["commission_due_cents"] == 7884
        assert invoice["billable_room_nights"] == 3
        assert invoice["rebate_due_cents"] == 2100
        assert invoice["outstanding_cents"] == 7884

        disputed = dispute_invoice(invoice["id"], ctx["hotel"]["id"])
        assert disputed["status"] == "DISPUTED"

        adjusted = adjust_invoice(invoice["id"], 3884)
        assert adjusted["status"] == "ADJUSTED"
        assert adjusted["written_off_cents"] == 3884
        assert adjusted["outstanding_cents"] == 4000

        settled = pay_invoice(invoice["id"], ctx["hotel"]["id"], 4000)
        assert settled["status"] == "PAID", (
            "the adjusted remainder is payable, so the cycle re-enters PAID, got "
            f"{settled['status']}"
        )
        assert settled["written_off_cents"] == 3884
        assert settled["paid_cents"] == 4000
        assert settled["outstanding_cents"] == 0

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["commission_collected_cents"] == 4000


class TestEventRoomNightLedgerSync:
    def test_the_event_ledger_follows_each_confirmation_and_the_cancellation(
        self, api
    ):
        """PRD §3.1: "`total_confirmed_room_nights` accumulates the `room_nights` of
        every reservation whose `reservation_status` is `CONFIRMED`, across every
        sub-block of every block of the event."
        PRD §3.4: "`room_nights` is the number of whole days between `check_in_date`
        and `check_out_date`."
        PRD §3.5: "The sub-block's `committed_rooms`, `available_rooms` and
        `inventory_status` and the event's `total_confirmed_room_nights` are
        recomputed, and the reservation's `version` is bumped."

        Design: Corner/state_machines/reservation_confirm_syncs_event_room_night_ledger
        """
        ctx = setup_open_block(general_rooms=6, num_attendees=2)
        first, second = ctx["attendees"]
        event_id = ctx["event"]["id"]

        assert (
            validate_success(api.get_event(event_id, COORDINATOR))[
                "total_confirmed_room_nights"
            ]
            == 0
        )

        long_stay = book_reservation(
            ctx["sub_block"]["id"], first, "2026-09-14", "2026-09-18"
        )
        assert (
            validate_success(api.get_event(event_id, COORDINATOR))[
                "total_confirmed_room_nights"
            ]
            == 4
        )

        short_stay = book_reservation(
            ctx["sub_block"]["id"], second, "2026-09-15", "2026-09-17"
        )
        assert (
            validate_success(api.get_event(event_id, COORDINATOR))[
                "total_confirmed_room_nights"
            ]
            == 6
        )

        cancel_reservation(long_stay["id"], first["id"])

        event = validate_success(api.get_event(event_id, COORDINATOR))
        assert event["total_confirmed_room_nights"] == 2, (
            "only the surviving 2-night stay may remain in the ledger, got "
            f"{event['total_confirmed_room_nights']}"
        )
        assert short_stay["room_nights"] == 2

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 1
        assert sub_block["available_rooms"] == 5


class TestPoacherCascadeSkipsCancelledStay:
    def test_a_cancelled_stay_is_not_stamped_for_eligibility_review(self, api):
        """PRD §3.8: "Because `housing_risk_flag` flipped from false to true, every
        reservation of that delegate whose `reservation_status` is `CONFIRMED` gets
        `eligibility_review_required` set to true, and any such reservation sitting
        in `TRANSMITTED` moves `TRANSMITTED → CHANGE_PENDING` so the hotel is warned
        in the next batch."
        PRD §3.8: "Because a warning was issued, the target delegate's
        `warning_count` rises by one for each warning they receive, and when that
        counter reaches the housing-risk threshold of 2 the delegate's
        `housing_risk_flag` flips from false to true."
        PRD §3.8: "**Confirming** the vendor moves it `UNDER_REVIEW →
        CONFIRMED_POACHER`, a terminal state, and requires at least one incident with
        `verified` true still sitting in `RECORDED`"
        PRD §3.4: "The reservation is created with `reservation_status` `CONFIRMED`,
        `transmission_status` `NOT_TRANSMITTED`, `eligibility_review_required` false
        and `no_show_billed_cents` 0"
        PRD §3.8: "The score starts from a base of 10, adds 25 for each counted
        incident, adds 15 for each distinct `contact_channel` appearing among the
        counted incidents, and adds a further 20 if any counted incident has
        `solicited_payment` true — that bonus is awarded once, not per incident."
        PRD §3.8: "The moment a newly recorded incident pushes `risk_score` to 60 or
        above while the vendor is still in `REPORTED`, the vendor transitions
        `REPORTED → UNDER_REVIEW` inside that same request and its `version` is
        bumped."

        Design: Corner/state_machines/poacher_cascade_skips_cancelled_reservation
        """
        ctx = setup_open_block_with_reservations(ONE_FOUR_NIGHT_STAY, general_rooms=6)
        guest = ctx["attendees"][0]
        cancelled = cancel_reservation(ctx["reservations"][0]["id"], guest["id"])
        assert cancelled["reservation_status"] == "CANCELLED"
        assert cancelled["transmission_status"] == "NOT_TRANSMITTED"

        vendor_ctx = setup_vendor_with_incidents(
            ctx["event"]["id"],
            [
                {
                    "attendee_id": guest["id"],
                    "contact_channel": "EMAIL",
                    "occurred_at": "2026-07-20T10:00:00Z",
                },
                {
                    "attendee_id": guest["id"],
                    "contact_channel": "PHONE",
                    "occurred_at": "2026-07-22T09:00:00Z",
                },
            ],
        )
        under_review = validate_success(
            api.get_rogue_vendor(vendor_ctx["vendor"]["id"], COMPLIANCE)
        )
        assert under_review["risk_score"] == 90
        assert under_review["status"] == "UNDER_REVIEW"

        confirmed = confirm_vendor(vendor_ctx["vendor"]["id"])
        assert confirmed["status"] == "CONFIRMED_POACHER"

        attendee = validate_success(api.get_attendee(guest["id"], COORDINATOR))
        assert attendee["warning_count"] == 2
        assert attendee["housing_risk_flag"] is True

        reservation = validate_success(
            api.get_reservation(cancelled["id"], COORDINATOR)
        )
        assert reservation["reservation_status"] == "CANCELLED"
        assert reservation["eligibility_review_required"] is False, (
            "the stamp only reaches CONFIRMED stays, so a cancelled row stays clean"
        )
        assert reservation["transmission_status"] == "NOT_TRANSMITTED"
