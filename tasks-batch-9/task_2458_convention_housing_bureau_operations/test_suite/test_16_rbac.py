"""Authorization surface: three role-exclusive endpoints, the delegate's own-row
binding, the coordinator/attendee peer pair, and the two segregation-of-duties splits.
"""

from test_helpers import (
    CONTROLLER,
    COORDINATOR,
    TEST_DEFAULTS,
    approve_reduction,
    approve_sub_block,
    book_reservation,
    carve_sub_block,
    carve_sub_block_payload,
    create_reservation_payload,
    file_reduction,
    make_attendee_headers,
    make_controller_headers,
    payment_reversal_payload,
    pickup_report_payload,
    read_block,
    setup_contracted_block,
    setup_housing_program,
    setup_open_block,
    setup_paid_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)

FOUR_NIGHT_STAY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1}
]

VIP_CARVE = [{"segment": "VIP", "allotted_rooms": 3, "eligibility_code": "VIP-2026"}]

REQUESTER_AS_CONTROLLER = make_controller_headers(TEST_DEFAULTS["COORDINATOR_ID"])


class TestCarveIsNotAControllerOperation:
    def test_the_approving_controller_cannot_file_the_carve_itself(self, api):
        """PRD §4: "| POST   | `/housing/hotel-blocks/{id}/sub-blocks` | Carve a
        segregated sub-block out of the block or a parent sub-block |
        BureauCoordinator, EventOrganizer |"
        PRD §2.1: "If the headers are well formed but the declared role is not listed
        among the roles authorised for the endpoint being called, the request is
        rejected with `ERR_UNAUTHORIZED` (403)."
        PRD §2.9: "The requesting and approving capacities are also split across roles:
        a `BureauCoordinator` files sub-block carves and reduction requests, while only
        a `BureauController` may approve or reject them, reverse posted commission cash,
        or write off a disputed invoice."

        Design: Corner/rbac/bureau_controller_cannot_carve_sub_blocks
        """
        ctx = setup_contracted_block()
        block = ctx["block"]
        assert block["unassigned_rooms_per_night"] == 10

        response = api.carve_sub_block(
            block["id"],
            carve_sub_block_payload("GENERAL", 3, block["version"]),
            CONTROLLER,
        )
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        untouched = read_block(block["id"])
        assert untouched["unassigned_rooms_per_night"] == 10
        assert untouched["version"] == block["version"]

        _, meta = validate_paginated(
            api.list_sub_blocks(COORDINATOR, params={"hotel_block_id": block["id"]})
        )
        assert meta["total_count"] == 0

        # The same payload from a listed role lands, so only the role was wrong.
        organizer_carve = carve_sub_block(
            block["id"], "GENERAL", 3, headers=ctx["organizer_headers"]
        )
        assert organizer_carve["approval_status"] == "APPROVED"
        assert read_block(block["id"])["unassigned_rooms_per_night"] == 7


class TestPickupReportIsHotelSideOnly:
    def test_the_organizer_reads_the_history_but_cannot_write_it(self, api):
        """PRD §4: "| POST   | `/housing/hotel-blocks/{id}/pickup-reports` | Hotel files
        a cumulative pickup snapshot for the block | HotelManager |"
        PRD §4: "| GET    | `/housing/hotel-blocks/{id}/pickup-reports` | Pickup report
        history of a block, ordered by as-of date | BureauCoordinator,
        BureauController, EventOrganizer, HotelManager |"
        PRD §2.10: "**Role authorization.** The acting role appears in the endpoint's
        authorised list. Otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        Design: Corner/rbac/pickup_report_by_event_organizer_forbidden
        """
        ctx = setup_contracted_block()
        organizer = ctx["organizer_headers"]

        response = api.create_pickup_report(
            ctx["block"]["id"],
            pickup_report_payload("2026-08-05", 3, 6, 131400),
            organizer,
        )
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        rows, meta = validate_paginated(
            api.list_pickup_reports(ctx["block"]["id"], organizer)
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestReversalIsControllerOnly:
    def test_the_coordinator_who_issued_the_invoice_cannot_reverse_cash(self, api):
        """PRD §4: "| POST   | `/housing/commission-invoices/{id}/payment-reversals` |
        Reverse previously posted commission cash | BureauController |"
        PRD §3.9: "A `BureauController` can push cash back out again with a
        compensating reversal, naming an `amount_cents` and an optional `reference`."
        PRD §2.10: "**Role authorization.** The acting role appears in the endpoint's
        authorised list. Otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        Design: Corner/rbac/payment_reversal_by_coordinator_forbidden
        """
        ctx = setup_paid_invoice(4000, stays=FOUR_NIGHT_STAY)
        invoice = ctx["invoice"]
        assert invoice["status"] == "PARTIALLY_PAID"

        response = api.reverse_commission_payment(
            invoice["id"], payment_reversal_payload(4000, reference="REV-1"), COORDINATOR
        )
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        after = validate_success(api.get_commission_invoice(invoice["id"], COORDINATOR))
        assert after["paid_cents"] == 4000
        assert after["status"] == "PARTIALLY_PAID"
        assert after["version"] == invoice["version"]

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["commission_collected_cents"] == 4000


class TestDelegateBooksOnlyForHerself:
    def test_a_delegate_cannot_book_the_room_of_another_delegate(self, api):
        """PRD §3.4: "A delegate booking for someone else — an `attendee_id` other than
        their own `X-User-ID` — is rejected with `ERR_NOT_RESOURCE_OWNER`."
        PRD §2.1: "When `X-User-Role` is `Attendee`, `X-User-ID` is the `id` of the
        acting `Attendee`; ownership checks on a reservation compare the reservation's
        `attendee_id` to `X-User-ID`."
        PRD §3.4: "Booking is performed by the delegate themselves or by a
        `BureauCoordinator` acting on their behalf"

        Design: Corner/rbac/attendee_cannot_book_for_another_attendee
        """
        ctx = setup_open_block(num_attendees=2)
        first, second = ctx["attendees"]
        sub_block_id = ctx["sub_block"]["id"]

        response = api.create_reservation(
            create_reservation_payload(sub_block_id, second["id"]),
            make_attendee_headers(first["id"]),
        )
        validate_error(response, "ERR_NOT_RESOURCE_OWNER", 403)

        _, meta = validate_paginated(
            api.list_reservations(COORDINATOR, params={"attendee_id": second["id"]})
        )
        assert meta["total_count"] == 0
        assert validate_success(api.get_sub_block(sub_block_id, COORDINATOR))[
            "committed_rooms"
        ] == 0

        # The bureau may open exactly the stay the first delegate was refused.
        on_behalf = book_reservation(sub_block_id, second, headers=COORDINATOR)
        assert on_behalf["attendee_id"] == second["id"]
        assert on_behalf["reservation_status"] == "CONFIRMED"


class TestBookingPeers:
    def test_a_coordinator_booking_and_a_self_booking_differ_only_in_intake_order(
        self, api
    ):
        """PRD §4: "| POST   | `/housing/reservations` | Attendee portal booking into a
        specific sub-block | Attendee, BureauCoordinator |"
        PRD §3.4: "A reservation that survives every check is stamped with an
        `intake_seq` drawn from a single monotonic one-based global counter"
        PRD §3.3: "`committed_rooms` is the largest of those per-night counts."

        Design: Corner/rbac/coordinator_and_attendee_are_peers_on_reservation_create
        """
        ctx = setup_open_block(num_attendees=2)
        first, second = ctx["attendees"]
        sub_block_id = ctx["sub_block"]["id"]

        by_bureau = book_reservation(sub_block_id, second, headers=COORDINATOR)
        by_delegate = book_reservation(sub_block_id, first)

        assert by_bureau["reservation_status"] == "CONFIRMED"
        assert by_delegate["reservation_status"] == "CONFIRMED"
        assert by_bureau["intake_seq"] == 1
        assert by_delegate["intake_seq"] == 2
        assert by_bureau["attendee_id"] == second["id"]
        assert by_delegate["attendee_id"] == first["id"]
        assert by_bureau["total_room_charge_cents"] == by_delegate[
            "total_room_charge_cents"
        ]

        sub_block = validate_success(api.get_sub_block(sub_block_id, COORDINATOR))
        assert sub_block["committed_rooms"] == 2

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 8


class TestSubBlockApprovalSegregation:
    def test_the_requester_cannot_approve_her_own_carve_under_the_controller_role(
        self, api
    ):
        """PRD §2.9: "On sub-block approval, on sub-block rejection, on
        attrition-reduction approval and on attrition-reduction rejection, the acting
        `X-User-ID` must differ from the `requested_by_user_id` recorded on the target
        resource when it was filed. If they are equal, the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (403)."
        PRD §2.9: "Where an approval succeeds, the acting identifier is persisted as
        `approved_by_user_id` on the resource, giving an auditable requester/approver
        pair"
        PRD §2.10: "**Segregation of duties.** `ERR_SEGREGATION_OF_DUTIES` (403) on
        exactly four operations"

        Design: Corner/rbac/sub_block_approval_by_its_own_requester_rejected
        """
        ctx = setup_housing_program(carves=VIP_CARVE)
        sub_block = ctx["sub_blocks"][0]
        assert sub_block["requested_by_user_id"] == TEST_DEFAULTS["COORDINATOR_ID"]
        assert sub_block["approval_status"] == "PENDING_APPROVAL"

        self_approval = api.approve_sub_block(sub_block["id"], REQUESTER_AS_CONTROLLER)
        validate_error(self_approval, "ERR_SEGREGATION_OF_DUTIES", 403)

        still_pending = validate_success(
            api.get_sub_block(sub_block["id"], COORDINATOR)
        )
        assert still_pending["approval_status"] == "PENDING_APPROVAL"
        assert still_pending["approved_by_user_id"] is None
        assert still_pending["version"] == sub_block["version"]

        approved = approve_sub_block(sub_block["id"], CONTROLLER)
        assert approved["approval_status"] == "APPROVED"
        assert approved["requested_by_user_id"] == TEST_DEFAULTS["COORDINATOR_ID"]
        assert approved["approved_by_user_id"] == TEST_DEFAULTS["CONTROLLER_ID"]


class TestReductionApprovalSegregation:
    def test_the_filer_cannot_approve_her_own_reduction_request(self, api):
        """PRD §2.9: "Four decisions in this system require a second pair of eyes, and
        the system refuses to let one person be both pairs."
        PRD §3.7: "A `BureauController` then approves or rejects, and both branches
        enforce the segregation rule of §2.9 against `requested_by_user_id`. Approval
        moves the reduction `SUBMITTED → APPROVED`, records the acting `X-User-ID` as
        `approved_by_user_id`, and bumps the reduction's `version`"
        PRD §2.10: "**Segregation of duties.** `ERR_SEGREGATION_OF_DUTIES` (403) on
        exactly four operations"

        Design: Corner/rbac/reduction_approval_by_its_own_filer_rejected
        """
        ctx = setup_open_block(general_rooms=6)
        reduction = file_reduction(ctx["block"]["id"], 2, effective_date="2026-08-16")
        assert reduction["status"] == "SUBMITTED"
        assert reduction["requested_by_user_id"] == TEST_DEFAULTS["COORDINATOR_ID"]

        self_approval = api.approve_attrition_reduction(
            reduction["id"], REQUESTER_AS_CONTROLLER
        )
        validate_error(self_approval, "ERR_SEGREGATION_OF_DUTIES", 403)

        still_submitted = validate_success(
            api.get_attrition_reduction(reduction["id"], COORDINATOR)
        )
        assert still_submitted["status"] == "SUBMITTED"
        assert still_submitted["approved_by_user_id"] is None
        assert still_submitted["version"] == reduction["version"]

        approved = approve_reduction(reduction["id"], CONTROLLER)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == TEST_DEFAULTS["CONTROLLER_ID"]

        # Approval is a paper move: no room accounting shifts until the exercise.
        assert read_block(ctx["block"]["id"])["contracted_rooms_per_night"] == 10
        assert validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )["allotted_rooms"] == 6
