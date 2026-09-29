"""Error surface: the auth rung, the ownership rung, the two cash ceilings, the two
invoice preconditions, the transmission-type gate, the release headroom, the posture
gate, the vendor state gate, the disputed-invoice freeze and the night-capacity gate.
"""

from test_helpers import (
    COMPLIANCE,
    CONTROLLER,
    COORDINATOR,
    assemble_block,
    carve_sub_block,
    carve_sub_block_payload,
    close_block,
    commission_invoice_payload,
    contract_block,
    create_event_payload,
    create_reservation_payload,
    cutoff_block,
    import_attendee,
    issue_invoice,
    make_attendee_headers,
    make_hotel_manager_headers,
    no_auth_headers,
    open_block,
    payment_payload,
    payment_reversal_payload,
    pickup_report_payload,
    read_block,
    record_rogue_vendor,
    register_event,
    register_hotel,
    release_sub_block_payload,
    release_sub_block_rooms,
    rooming_list_payload,
    set_clock,
    setup_block_at_cutoff,
    setup_contracted_block,
    setup_disputed_invoice,
    setup_issued_invoice,
    setup_open_block_with_reservations,
    setup_paid_invoice,
    submit_terms,
    validate_error,
    validate_paginated,
    validate_success,
)

FOUR_NIGHT_STAY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1}
]

TWO_OVERLAPPING_STAYS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
    {"check_in_date": "2026-09-15", "check_out_date": "2026-09-17", "occupants": 1},
]

MATCHING_REPORT = [
    {
        "as_of_date": "2026-08-19",
        "reported_rooms_picked_up": 1,
        "reported_room_nights": 4,
        "reported_gross_revenue_cents": 87600,
    }
]

UNDER_REPORT = [
    {
        "as_of_date": "2026-08-19",
        "reported_rooms_picked_up": 1,
        "reported_room_nights": 1,
        "reported_gross_revenue_cents": 21900,
    }
]

AIRPORT_INN = {
    "name": "Airport Inn",
    "distance_to_venue_miles": 4.5,
    "room_tax_pct": 0.12,
    "total_rooms": 120,
}


class TestHeaderAuthentication:
    def test_an_unauthenticated_create_is_refused_and_persists_nothing(self, api):
        """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
        these six strings, the request is rejected with `ERR_UNAUTHENTICATED` (401)."
        PRD §2.10: "**Header authentication.** Both `X-User-ID` and `X-User-Role`
        present, and the role one of the six declared names. Otherwise
        `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."
        PRD §2.10: "`ERR_EVENT_CODE_DUPLICATE` (409) when a registered event already
        uses the supplied `code`"

        Design: Corner/errors/missing_x_user_headers_returns_unauthenticated
        """
        payload = create_event_payload()

        anonymous = api.create_event(payload, no_auth_headers())
        validate_error(anonymous, "ERR_UNAUTHENTICATED", 401)

        # The code is still free, so the rejected request wrote nothing at all.
        event = validate_success(api.create_event(payload, COORDINATOR), 201)
        assert event["code"] == payload["code"]

        rows, meta = validate_paginated(api.list_hotel_blocks(COORDINATOR))
        assert meta["total_count"] == 0
        assert rows == []


class TestPickupReportOwnership:
    def test_a_manager_of_another_property_cannot_file_on_this_block(self, api):
        """PRD §3.6: "Each report is a cumulative snapshot, filed by the owning
        `HotelManager` against a `hotel_block_id`"
        PRD §2.1: "When `X-User-Role` is `HotelManager`, `X-User-ID` is the `id` of the
        acting `Hotel`; ownership checks on any resource that references a `Hotel`
        compare the resource's foreign-key field to `X-User-ID`."
        PRD §2.10: "**Ownership.** `ERR_NOT_RESOURCE_OWNER` (403) on exactly nine write
        operations"

        Design: Corner/errors/pickup_report_for_another_hotels_block_forbidden
        """
        ctx = setup_contracted_block()
        other_hotel = register_hotel(**AIRPORT_INN)
        assert other_hotel["id"] != ctx["hotel"]["id"]

        response = api.create_pickup_report(
            ctx["block"]["id"],
            pickup_report_payload("2026-08-05", 3, 6, 131400),
            make_hotel_manager_headers(other_hotel["id"]),
        )
        validate_error(response, "ERR_NOT_RESOURCE_OWNER", 403)

        _, meta = validate_paginated(
            api.list_pickup_reports(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 0

        owner_report = validate_success(
            api.create_pickup_report(
                ctx["block"]["id"],
                pickup_report_payload("2026-08-05", 3, 6, 131400),
                ctx["hotel_headers"],
            ),
            201,
        )
        assert owner_report["hotel_block_id"] == ctx["block"]["id"]


class TestPaymentCeiling:
    def test_a_remittance_above_the_outstanding_balance_is_refused(self, api):
        """PRD §3.9: "the `amount_cents` may not exceed `outstanding_cents`, and a
        larger figure is rejected with `ERR_PAYMENT_EXCEEDS_OUTSTANDING`"
        PRD §3.9: "Every payment raises `paid_cents` by `amount_cents`, re-derives
        `outstanding_cents` (which becomes exactly 0 on a settling payment), recomputes
        the event's `commission_collected_cents`, and bumps the invoice's `version`."
        PRD §2.10: "**Payment and write-off ceiling.**
        `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (422) on an invoice payment or an invoice
        adjustment."

        Design: Corner/errors/payment_above_outstanding_rejected
        """
        ctx = setup_issued_invoice(FOUR_NIGHT_STAY)
        invoice = ctx["invoice"]
        # One 4-night stay at 21900 pre-tax cents is 87600; 12 percent is 10512.
        assert invoice["commission_due_cents"] == 10512
        assert invoice["outstanding_cents"] == 10512

        response = api.pay_commission_invoice(
            invoice["id"],
            payment_payload(20000, reference="WIRE-OVER"),
            ctx["hotel_headers"],
        )
        validate_error(response, "ERR_PAYMENT_EXCEEDS_OUTSTANDING", 422)

        after = validate_success(api.get_commission_invoice(invoice["id"], COORDINATOR))
        assert after["paid_cents"] == 0
        assert after["outstanding_cents"] == 10512
        assert after["status"] == "ISSUED"
        assert after["version"] == invoice["version"]

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["commission_collected_cents"] == 0


class TestReversalCeiling:
    def test_a_reversal_above_the_cash_on_hand_is_refused(self, api):
        """PRD §3.9: "the `amount_cents` may not exceed `paid_cents`, a larger figure
        being rejected with `ERR_REVERSAL_EXCEEDS_PAID`"
        PRD §3.9: "A payment smaller than `outstanding_cents` moves the invoice
        `ISSUED → PARTIALLY_PAID`, or holds it at `PARTIALLY_PAID → PARTIALLY_PAID` if
        it was already part-paid."
        PRD §2.10: "**Reversal ceiling.** `ERR_REVERSAL_EXCEEDS_PAID` (422) on a
        commission payment reversal."

        Design: Corner/errors/reversal_above_paid_cash_rejected
        """
        ctx = setup_paid_invoice(4000, stays=FOUR_NIGHT_STAY)
        invoice = ctx["invoice"]
        assert invoice["status"] == "PARTIALLY_PAID"
        assert invoice["paid_cents"] == 4000
        assert invoice["outstanding_cents"] == 6512

        response = api.reverse_commission_payment(
            invoice["id"], payment_reversal_payload(5000, reference="REV-1"), CONTROLLER
        )
        validate_error(response, "ERR_REVERSAL_EXCEEDS_PAID", 422)

        after = validate_success(api.get_commission_invoice(invoice["id"], COORDINATOR))
        assert after["paid_cents"] == 4000, (
            "the ceiling is the cash collected, not the invoice total, got "
            f"{after['paid_cents']}"
        )
        assert after["outstanding_cents"] == 6512
        assert after["status"] == "PARTIALLY_PAID"
        assert after["version"] == invoice["version"]

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["commission_collected_cents"] == 4000


class TestOneInvoicePerBlock:
    def test_a_second_issuance_on_the_other_basis_is_still_a_duplicate(self, api):
        """PRD §3.9: "A `BureauCoordinator` issues **one** commission invoice per block
        — a second attempt is rejected with `ERR_INVOICE_ALREADY_EXISTS` — declaring a
        `basis` of either `BUREAU_CONFIRMED` or `HOTEL_REPORTED`."
        PRD §3.9: "`variance_cents` is the signed difference
        `bureau_confirmed_commission_cents` minus `hotel_reported_commission_cents`,
        and is null when no pickup report exists."
        PRD §2.10: "**Invoice uniqueness.** `ERR_INVOICE_ALREADY_EXISTS` (409) on a
        second commission invoice for the same block."

        Design: Corner/errors/second_invoice_for_the_same_block_rejected
        """
        ctx = setup_issued_invoice(FOUR_NIGHT_STAY, pickup_reports=MATCHING_REPORT)
        invoice = ctx["invoice"]
        assert invoice["basis"] == "BUREAU_CONFIRMED"
        # The hotel reported the same 87600 pre-tax cents, so the two sides agree.
        assert invoice["variance_cents"] == 0

        response = api.issue_commission_invoice(
            ctx["block"]["id"], commission_invoice_payload("HOTEL_REPORTED"), COORDINATOR
        )
        validate_error(response, "ERR_INVOICE_ALREADY_EXISTS", 409)

        rows, meta = validate_paginated(
            api.list_block_commission_invoices(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == invoice["id"]
        assert rows[0]["basis"] == "BUREAU_CONFIRMED"
        assert rows[0]["variance_cents"] == 0


class TestHotelReportedBasisPrecondition:
    def test_the_hotel_basis_needs_a_report_the_bureau_basis_does_not(self, api):
        """PRD §3.9: "Because that basis is meaningless without a report, issuing on
        `HOTEL_REPORTED` against a block with no pickup report is rejected with
        `ERR_PICKUP_REPORT_REQUIRED`."
        PRD §3.9: "When the block has no pickup report at all,
        `hotel_reported_commission_cents` is null."
        PRD §2.10: "**Pickup report availability.** `ERR_PICKUP_REPORT_REQUIRED` (422)
        on a commission invoice issued on the `HOTEL_REPORTED` basis."

        Design: Corner/errors/hotel_reported_basis_without_a_pickup_report_rejected
        """
        ctx = setup_block_at_cutoff(FOUR_NIGHT_STAY)
        block_id = ctx["block"]["id"]

        refused = api.issue_commission_invoice(
            block_id, commission_invoice_payload("HOTEL_REPORTED"), COORDINATOR
        )
        validate_error(refused, "ERR_PICKUP_REPORT_REQUIRED", 422)

        invoice = issue_invoice(block_id, "BUREAU_CONFIRMED")
        assert invoice["commission_due_cents"] == 10512
        assert invoice["hotel_reported_commission_cents"] is None
        assert invoice["variance_cents"] is None
        assert invoice["billable_room_nights"] == 4

        _, meta = validate_paginated(
            api.list_block_commission_invoices(block_id, COORDINATOR)
        )
        assert meta["total_count"] == 1


class TestTransmissionTypeLegality:
    def test_a_change_batch_needs_a_predecessor_but_initial_does_not(self, api):
        """PRD §3.6: "`INITIAL` is admissible only when the block has never transmitted
        before, `CHANGE` only when at least one prior transmission exists, and `FINAL`
        only when the block's `status` is `CUTOFF_PASSED` or `CLOSED`. A type that does
        not fit is rejected with `ERR_INVALID_TRANSMISSION_TYPE`."
        PRD §3.6: "The batch's `batch_seq` is one more than the number of transmissions
        the block already has"
        PRD §2.10: "**Transmission type legality.** `ERR_INVALID_TRANSMISSION_TYPE`
        (409) on a rooming-list transmission."

        Design: Corner/errors/change_transmission_before_any_initial_rejected
        """
        ctx = setup_open_block_with_reservations(FOUR_NIGHT_STAY)
        block_id = ctx["block"]["id"]
        reservation = ctx["reservations"][0]

        premature = api.transmit_rooming_list(
            block_id, rooming_list_payload("CHANGE"), COORDINATOR
        )
        validate_error(premature, "ERR_INVALID_TRANSMISSION_TYPE", 409)

        batch = validate_success(
            api.transmit_rooming_list(
                block_id, rooming_list_payload("INITIAL"), COORDINATOR
            ),
            201,
        )
        assert batch["batch_seq"] == 1
        assert batch["reservation_count"] == 1

        after = validate_success(api.get_reservation(reservation["id"], COORDINATOR))
        assert after["transmission_status"] == "TRANSMITTED"

        _, meta = validate_paginated(api.list_rooming_lists(block_id, COORDINATOR))
        assert meta["total_count"] == 1


class TestReleaseHeadroom:
    def test_a_release_may_only_reach_down_to_the_committed_rooms(self, api):
        """PRD §3.3: "The release is admissible only when `rooms` is less than or equal
        to `allotted_rooms` minus `committed_rooms`; anything larger would strand a
        confirmed guest and is rejected with `ERR_SUB_BLOCK_HAS_COMMITTED_ROOMS`."
        PRD §3.3: "A **partial release**, where `rooms` is smaller than
        `allotted_rooms`, leaves the sub-block in `APPROVED` (an `APPROVED → APPROVED`
        self-transition): `allotted_rooms` falls by `rooms`, the sub-block's own
        `released_rooms` rises by `rooms`, and the block's `released_rooms_per_night`
        rises by `rooms`."
        PRD §3.3: "`inventory_status` is the enum `FULL` when `available_rooms` is
        exactly zero and `OPEN` otherwise."

        Design: Corner/errors/release_below_committed_rooms_rejected
        """
        ctx = setup_open_block_with_reservations(TWO_OVERLAPPING_STAYS, general_rooms=3)
        sub_block = ctx["sub_block"]
        assert sub_block["allotted_rooms"] == 3

        refused = api.release_sub_block(
            sub_block["id"], release_sub_block_payload(2), COORDINATOR
        )
        validate_error(refused, "ERR_SUB_BLOCK_HAS_COMMITTED_ROOMS", 409)

        released = release_sub_block_rooms(sub_block["id"], 1)
        assert released["allotted_rooms"] == 2
        assert released["released_rooms"] == 1
        assert released["committed_rooms"] == 2
        assert released["approval_status"] == "APPROVED"
        assert released["inventory_status"] == "FULL"

        assert read_block(ctx["block"]["id"])["released_rooms_per_night"] == 1


class TestPostureGateOnCarves:
    def test_a_closed_posture_freezes_carving_on_a_sibling_block(self, api):
        """PRD §3.3: "Carving is also gated on the event's posture: while
        `housing_posture` is `CLOSED`, no further inventory may be carved and the
        request is rejected with `ERR_EVENT_NOT_ACCEPTING_HOUSING`."
        PRD §2.11: "Otherwise — that is, when the open group is empty but the ended
        group is not — the posture is `CLOSED`."
        PRD §2.10: "**Event posture.** `ERR_EVENT_NOT_ACCEPTING_HOUSING` (409) on a
        sub-block carve while the event's `housing_posture` is `CLOSED`."

        Design: Corner/errors/carve_while_event_housing_closed_rejected
        """
        event = register_event()
        hotel_a = register_hotel()
        hotel_b = register_hotel(**AIRPORT_INN)

        block_b = assemble_block(
            event["id"],
            hotel_b["id"],
            contracted_rooms_per_night=5,
            negotiated_nightly_rate_cents=15900,
        )
        block_b = submit_terms(block_b, negotiated_nightly_rate_cents=15900)
        block_b = contract_block(
            block_b["id"], hotel_b["id"], confirmation_number="CN-SUM26-037B"
        )
        assert block_b["unassigned_rooms_per_night"] == 5

        block_a = assemble_block(
            event["id"], hotel_a["id"], contracted_rooms_per_night=1
        )
        block_a = submit_terms(block_a)
        block_a = contract_block(
            block_a["id"], hotel_a["id"], confirmation_number="CN-SUM26-037A"
        )
        carve_sub_block(block_a["id"], "GENERAL", 1)
        open_block(block_a["id"])
        set_clock("2026-08-21T00:00:00Z")
        cutoff_block(block_a["id"])
        set_clock("2026-09-18T00:00:00Z")
        assert close_block(block_a["id"])["status"] == "CLOSED"

        event_after = validate_success(api.get_event(event["id"], COORDINATOR))
        assert event_after["housing_posture"] == "CLOSED"

        refused = api.carve_sub_block(
            block_b["id"],
            carve_sub_block_payload("GENERAL", 2, block_b["version"]),
            COORDINATOR,
        )
        validate_error(refused, "ERR_EVENT_NOT_ACCEPTING_HOUSING", 409)

        untouched = read_block(block_b["id"])
        assert untouched["status"] == "CONTRACTED"
        assert untouched["unassigned_rooms_per_night"] == 5
        assert untouched["version"] == block_b["version"]

        _, meta = validate_paginated(
            api.list_sub_blocks(COORDINATOR, params={"hotel_block_id": block_b["id"]})
        )
        assert meta["total_count"] == 0


class TestVendorExitStates:
    def test_neither_exit_is_reachable_from_the_reported_state(self, api):
        """PRD §3.8: "From `UNDER_REVIEW` the officer has two exits, and attempting
        either from any other `status` is rejected with `ERR_INVALID_VENDOR_STATE`."
        PRD §3.8: "The vendor starts in `status` `REPORTED` with
        `warning_issued_count` at 0, and with its `risk_score` and
        `verified_incident_count` derived immediately — which, with no incidents on
        file, puts the score at the base value of 10."
        PRD §3.8: "No warning is issued, no `warning_count` moves, no
        `housing_risk_flag` flips, and no delegate counter of any kind changes."

        Design: Corner/errors/vendor_confirm_from_reported_state_rejected
        """
        event = register_event()
        attendee = import_attendee(event["id"])
        vendor = record_rogue_vendor(event["id"])
        assert vendor["status"] == "REPORTED"
        assert vendor["risk_score"] == 10

        validate_error(
            api.confirm_rogue_vendor(vendor["id"], COMPLIANCE),
            "ERR_INVALID_VENDOR_STATE",
            409,
        )
        validate_error(
            api.clear_rogue_vendor(vendor["id"], COMPLIANCE),
            "ERR_INVALID_VENDOR_STATE",
            409,
        )

        after = validate_success(api.get_rogue_vendor(vendor["id"], COMPLIANCE))
        assert after["status"] == "REPORTED"
        assert after["risk_score"] == 10
        assert after["warning_issued_count"] == 0
        assert after["version"] == vendor["version"]

        guest = validate_success(api.get_attendee(attendee["id"], COORDINATOR))
        assert guest["warning_count"] == 0
        assert guest["housing_risk_flag"] is False


class TestDisputeSuspendsCollection:
    def test_no_cash_moves_while_the_invoice_is_disputed(self, api):
        """PRD §3.9: "A payment is accepted only from `ISSUED`, `PARTIALLY_PAID` or
        `ADJUSTED`, and from `DISPUTED` or `PAID` it is rejected with
        `ERR_INVOICE_NOT_PAYABLE`"
        PRD §3.9: "The tolerance is the greater of a floor of 5,000 cents — fifty
        dollars — and one percent of `bureau_confirmed_commission_cents` rounded half
        up to whole cents."
        PRD §3.9: "A successful dispute moves the invoice `ISSUED → DISPUTED` or
        `PARTIALLY_PAID → DISPUTED` and bumps its `version`; no disputing identity is
        stored, the dispute is asserted through `status` alone."

        Design: Corner/errors/payment_on_a_disputed_invoice_rejected
        """
        ctx = setup_disputed_invoice(stays=FOUR_NIGHT_STAY, pickup_reports=UNDER_REPORT)
        invoice = ctx["invoice"]
        assert invoice["status"] == "DISPUTED"
        # Bureau 10512 against the hotel's 21900 x 0.12 == 2628: variance 7884 clears
        # the 5000-cent floor, which is the greater of 5000 and 105.
        assert invoice["variance_cents"] == 7884

        response = api.pay_commission_invoice(
            invoice["id"],
            payment_payload(1000, reference="WIRE-DISP"),
            ctx["hotel_headers"],
        )
        validate_error(response, "ERR_INVOICE_NOT_PAYABLE", 409)

        after = validate_success(api.get_commission_invoice(invoice["id"], COORDINATOR))
        assert after["status"] == "DISPUTED"
        assert after["variance_cents"] == 7884
        assert after["paid_cents"] == 0
        assert after["outstanding_cents"] == 10512
        assert after["version"] == invoice["version"]


class TestNightCapacityOverflow:
    def test_an_overflow_booking_errors_instead_of_waitlisting(self, api):
        """PRD §3.4: "Third, the **night capacity admission test**, which uses the
        half-open geometry of §3.3 instead: for every night the candidate stay would
        occupy, the count of `CONFIRMED` reservations already covering that night, plus
        one for the candidate, must be less than or equal to the sub-block's
        `allotted_rooms`. A single night that fails rejects the whole booking with
        `ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED`."
        PRD §3.3: "`committed_rooms` is the largest of those per-night counts."
        PRD §2.10: "**Sub-block night capacity.**
        `ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED` (409) on a reservation booking or
        change."

        Design: Corner/errors/night_capacity_overflow_rejected
        """
        ctx = setup_open_block_with_reservations(
            FOUR_NIGHT_STAY, general_rooms=1, contracted_rooms_per_night=1
        )
        second_guest = import_attendee(ctx["event"]["id"], index=2)

        response = api.create_reservation(
            create_reservation_payload(
                ctx["sub_block"]["id"],
                second_guest["id"],
                check_in_date="2026-09-17",
                check_out_date="2026-09-18",
            ),
            make_attendee_headers(second_guest["id"]),
        )
        validate_error(response, "ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED", 409)

        _, meta = validate_paginated(
            api.list_reservations(
                COORDINATOR, params={"attendee_id": second_guest["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "an overflow booking creates no row at all, waitlisting is reachable only "
            "through the reduction cascade"
        )

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 1
        assert sub_block["inventory_status"] == "FULL"

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 4
