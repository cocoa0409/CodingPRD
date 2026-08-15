"""Service orders and crew assignment: event-state gating, the quote revision
loop, crew category/shift/capacity checks, and the service window margin."""

from test_helpers import (
    SERVICE_COORDINATOR,
    ApiErrorId,
    approve_event,
    approve_order,
    assert_service_order,
    create_crew,
    create_event,
    create_order,
    get_invoice,
    get_order,
    make_org_requester_headers,
    quote_order,
    schedule_order,
    setup_approved_event,
    setup_approved_orders_on_rooms,
    setup_confirmed_event,
    setup_org_room,
    validate_error,
    validate_success,
)


class TestOrderGatedByEventState:
    def test_attach_rejected_while_event_requested_then_works_after_approve(self, api):
        """PRD §3.5: "The parent event must be `APPROVED` or `CONFIRMED`."
        PRD §3.5: "A quote moves a `REQUESTED` order to `QUOTED`, setting
        `quoted_total_cents` to the `quantity` multiplied by the per-unit cost,
        and requires the parent event to be `APPROVED` or `CONFIRMED` (otherwise
        `ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/service_order_lifecycle_gated_by_event_state
        """
        scn = setup_org_room(room_overrides={"capacity": 25})
        event = create_event(
            scn.org, scn.room["id"], title="Panel", expected_attendance=20,
            start_at="2026-09-16T14:00:00Z", end_at="2026-09-16T15:00:00Z",
        )
        payload = {
            "event_id": event["id"],
            "category": "AV",
            "quantity": 1,
            "service_start_at": "2026-09-16T13:30:00Z",
            "service_end_at": "2026-09-16T15:30:00Z",
        }
        requester = make_org_requester_headers(scn.org["id"])
        rejected = api.create_service_order(payload, requester)
        validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)

        approve_event(event["id"])
        created = validate_success(api.create_service_order(payload, requester), 201)
        assert_service_order(created)
        assert created["status"] == "REQUESTED"

        quoted = quote_order(created["id"], 1500)
        assert quoted["status"] == "QUOTED"
        assert quoted["quoted_total_cents"] == 1500

    def test_attach_and_quote_also_work_on_a_confirmed_event(self, api):
        """PRD §3.5: "The parent event must be `APPROVED` or `CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/service_order_lifecycle_gated_by_event_state
        """
        scn = setup_confirmed_event(
            room_overrides={"capacity": 25},
            event_overrides={
                "expected_attendance": 20,
                "start_at": "2026-09-16T14:00:00Z",
                "end_at": "2026-09-16T15:00:00Z",
            },
        )
        order = create_order(
            scn.event["id"], scn.org, category="CATERING", quantity=2,
            service_start_at="2026-09-16T13:00:00Z",
            service_end_at="2026-09-16T15:00:00Z",
        )
        assert order["status"] == "REQUESTED"
        quoted = quote_order(order["id"], 2000)
        assert quoted["status"] == "QUOTED"
        assert quoted["quoted_total_cents"] == 4000


class TestQuoteRevisionLoop:
    def _setup(self, api):
        scn = setup_approved_event(
            event_overrides={
                "expected_attendance": 50,
                "start_at": "2026-09-11T10:00:00Z",
                "end_at": "2026-09-11T12:00:00Z",
                "title": "Screening",
            },
            room_overrides={"capacity": 60},
        )
        order = create_order(
            scn.event["id"], scn.org, category="AV", quantity=2,
            service_start_at="2026-09-11T09:30:00Z",
            service_end_at="2026-09-11T12:30:00Z",
        )
        return scn, order

    def test_revision_loop_moves_the_provisional_service_charge(self, api):
        """PRD §3.5: "While an order sits in `NEEDS_REVISION` it is excluded from
        the provisional invoice's service charge."
        PRD §3.5: "which is the sum of `quoted_total_cents` over the event's
        orders in `QUOTED`, `APPROVED`, `SCHEDULED`, or `FULFILLED` status —
        deliberately forward-looking, since it anticipates work that has been
        priced even if not yet performed."
        PRD §3.5: "A fresh quote on a `NEEDS_REVISION` order moves it back to
        `QUOTED`, recomputing the quoted total and clearing the `revision_note`."

        Design: Difficulty/non_linear_state_machine/service_order_quote_revision_loop
        """
        scn, order = self._setup(api)
        invoice_id = scn.invoice["id"]

        quote_order(order["id"], 3000)
        assert get_invoice_total(api, invoice_id) == 16000, "10000 room + 6000 quote"

        response = api.request_service_order_revision(
            order["id"], {"note": "too pricey"},
            make_org_requester_headers(scn.org["id"]),
        )
        revised = validate_success(response, 200)
        assert revised["status"] == "NEEDS_REVISION"
        assert revised["revision_note"] == "too pricey"
        assert get_invoice_total(api, invoice_id) == 10000, "order excluded"

        quote_order(order["id"], 2250)
        assert get_invoice_total(api, invoice_id) == 14500, "10000 room + 4500"

    def test_requote_clears_revision_note_and_recomputes_total(self, api):
        """PRD §3.5: "A fresh quote on a `NEEDS_REVISION` order moves it back to
        `QUOTED`, recomputing the quoted total and clearing the `revision_note`."
        PRD §3.5: "The owning requester then either approves the quote, moving
        the order from `QUOTED` to `APPROVED`, or sends it back for revision
        with a `note`, moving it from `QUOTED` to `NEEDS_REVISION` with the note
        stored as `revision_note`."

        Design: Difficulty/non_linear_state_machine/service_order_quote_revision_loop
        """
        scn, order = self._setup(api)
        quote_order(order["id"], 3000)
        api.request_service_order_revision(
            order["id"], {"note": "too pricey"},
            make_org_requester_headers(scn.org["id"]),
        )
        requoted = quote_order(order["id"], 2250)
        assert requoted["status"] == "QUOTED"
        assert requoted["quoted_total_cents"] == 4500
        assert requoted["revision_note"] is None

        approved = approve_order(order["id"], scn.org)
        assert approved["status"] == "APPROVED"
        assert approved["quoted_total_cents"] == 4500


def get_invoice_total(api, invoice_id) -> int:
    return get_invoice(invoice_id)["total_cents"]


class TestCrewCapacityBoundary:
    def test_second_overlapping_assignment_allowed_third_rejected(self, api):
        """PRD §3.5: "One below capacity schedules fine; a count equal to
        capacity is rejected with `ERR_CREW_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/crew_schedule_at_exactly_concurrent_capacity
        """
        scn = setup_approved_orders_on_rooms(
            [
                ("2026-09-16T13:00:00Z", "2026-09-16T14:00:00Z"),
                ("2026-09-16T13:00:00Z", "2026-09-16T14:00:00Z"),
                ("2026-09-16T13:00:00Z", "2026-09-16T14:00:00Z"),
            ]
        )
        crew = create_crew(
            name="AV Team Alpha", category="AV", concurrent_capacity=2,
            shift_start="08:00", shift_end="20:00",
        )
        first = schedule_order(scn.orders[0]["id"], crew["id"])
        second = schedule_order(scn.orders[1]["id"], crew["id"])
        assert first["status"] == "SCHEDULED"
        assert second["status"] == "SCHEDULED"

        rejected = api.schedule_service_order(
            scn.orders[2]["id"], {"crew_id": crew["id"]}, SERVICE_COORDINATOR
        )
        validate_error(rejected, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)
        third = get_order(scn.orders[2]["id"])
        assert third["status"] == "APPROVED"
        assert third["crew_id"] is None

    def test_capacity_is_per_instant_not_a_total_booking_count(self, api):
        """PRD §3.5: "counting the crew's other `SCHEDULED` orders whose service
        windows overlap this one — half-open, so a window ending exactly when
        another begins is not an overlap — the count must be strictly below the
        crew's `concurrent_capacity`."

        Design: Difficulty/boundary_precision_check/crew_schedule_at_exactly_concurrent_capacity
        """
        scn = setup_approved_orders_on_rooms(
            [
                ("2026-09-16T13:00:00Z", "2026-09-16T14:00:00Z"),
                ("2026-09-16T13:00:00Z", "2026-09-16T14:00:00Z"),
                ("2026-09-16T15:00:00Z", "2026-09-16T16:00:00Z"),
            ]
        )
        crew = create_crew(
            name="AV Team Beta", category="AV", concurrent_capacity=2,
            shift_start="08:00", shift_end="20:00",
        )
        for order in scn.orders:
            scheduled = schedule_order(order["id"], crew["id"])
            assert scheduled["status"] == "SCHEDULED"
        # The third order never overlaps the first two, so the per-instant load
        # in its window is zero even though the crew holds two bookings.


class TestCrewOverlapSemantics:
    def test_adjacent_windows_do_not_overlap_partial_overlap_does(self, api):
        """PRD §3.5: "counting the crew's other `SCHEDULED` orders whose service
        windows overlap this one — half-open, so a window ending exactly when
        another begins is not an overlap — the count must be strictly below the
        crew's `concurrent_capacity`."

        Design: Difficulty/resource_temporal_overlap/crew_overlap_aggregate_capacity_no_buffer
        """
        scn = setup_approved_orders_on_rooms(
            [
                ("2026-09-16T13:00:00Z", "2026-09-16T14:00:00Z"),
                ("2026-09-16T14:00:00Z", "2026-09-16T15:00:00Z"),
                ("2026-09-16T13:30:00Z", "2026-09-16T14:30:00Z"),
            ]
        )
        crew = create_crew(
            name="AV Solo", category="AV", concurrent_capacity=1,
            shift_start="08:00", shift_end="20:00",
        )
        assert schedule_order(scn.orders[0]["id"], crew["id"])["status"] == "SCHEDULED"

        adjacent = schedule_order(scn.orders[1]["id"], crew["id"])
        assert adjacent["status"] == "SCHEDULED", (
            "14:00 start touches the 14:00 end — half-open adjacency"
        )

        rejected = api.schedule_service_order(
            scn.orders[2]["id"], {"crew_id": crew["id"]}, SERVICE_COORDINATOR
        )
        validate_error(rejected, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)

    def test_adjacency_chain_schedules_under_capacity_one(self, api):
        """PRD §3.5: "counting the crew's other `SCHEDULED` orders whose service
        windows overlap this one — half-open, so a window ending exactly when
        another begins is not an overlap — the count must be strictly below the
        crew's `concurrent_capacity`."

        Design: Difficulty/resource_temporal_overlap/crew_overlap_aggregate_capacity_no_buffer
        """
        scn = setup_approved_orders_on_rooms(
            [
                ("2026-09-16T13:00:00Z", "2026-09-16T14:00:00Z"),
                ("2026-09-16T14:00:00Z", "2026-09-16T15:00:00Z"),
                ("2026-09-16T15:00:00Z", "2026-09-16T16:00:00Z"),
            ]
        )
        crew = create_crew(
            name="AV Chain", category="AV", concurrent_capacity=1,
            shift_start="08:00", shift_end="20:00",
        )
        for order in scn.orders:
            scheduled = schedule_order(order["id"], crew["id"])
            assert scheduled["status"] == "SCHEDULED"
            assert scheduled["crew_id"] == crew["id"]


class TestCrewValidation:
    def test_crew_category_mismatch_rejected(self, api):
        """PRD §3.5: "The crew's `category` must equal the order's `category`
        (`ERR_CREW_CATEGORY_MISMATCH`)."

        Design: Corner/validations/schedule_crew_category_mismatch_rejected
        """
        scn = setup_approved_event(
            event_overrides={
                "expected_attendance": 5,
                "start_at": "2026-09-16T14:00:00Z",
                "end_at": "2026-09-16T15:00:00Z",
            }
        )
        order = create_order(
            scn.event["id"], scn.org, category="CATERING", quantity=1,
            service_start_at="2026-09-16T13:00:00Z",
            service_end_at="2026-09-16T15:00:00Z",
        )
        quote_order(order["id"], 1000)
        approve_order(order["id"], scn.org)
        crew = create_crew(
            name="AV Team", category="AV", concurrent_capacity=2,
            shift_start="08:00", shift_end="20:00",
        )
        response = api.schedule_service_order(
            order["id"], {"crew_id": crew["id"]}, SERVICE_COORDINATOR
        )
        validate_error(response, ApiErrorId.ERR_CREW_CATEGORY_MISMATCH)
        after = get_order(order["id"])
        assert after["status"] == "APPROVED"
        assert after["crew_id"] is None

    def test_crew_shift_must_cover_the_full_service_window(self, api):
        """PRD §3.5: "The crew's shift — the span from its `shift_start` to its
        `shift_end` — must cover the entire service window
        (`ERR_CREW_SHIFT_MISMATCH`)."

        Design: Corner/validations/schedule_crew_shift_mismatch_rejected
        """
        scn = setup_approved_event(
            event_overrides={
                "expected_attendance": 5,
                "start_at": "2026-09-16T12:00:00Z",
                "end_at": "2026-09-16T16:00:00Z",
            }
        )
        order1 = create_order(
            scn.event["id"], scn.org, category="AV", quantity=1,
            service_start_at="2026-09-16T13:00:00Z",
            service_end_at="2026-09-16T15:00:00Z",
        )
        order2 = create_order(
            scn.event["id"], scn.org, category="AV", quantity=1,
            service_start_at="2026-09-16T13:00:00Z",
            service_end_at="2026-09-16T14:00:00Z",
        )
        for order in (order1, order2):
            quote_order(order["id"], 1000)
            approve_order(order["id"], scn.org)
        crew = create_crew(
            name="Day AV", category="AV", concurrent_capacity=5,
            shift_start="08:00", shift_end="14:00",
        )
        response = api.schedule_service_order(
            order1["id"], {"crew_id": crew["id"]}, SERVICE_COORDINATOR
        )
        validate_error(response, ApiErrorId.ERR_CREW_SHIFT_MISMATCH)
        assert get_order(order1["id"])["status"] == "APPROVED"

        covered = schedule_order(order2["id"], crew["id"])
        assert covered["status"] == "SCHEDULED", (
            "window ends exactly at shift_end — covered"
        )

    def test_service_window_outside_two_hour_margin_rejected(self, api):
        """PRD §3.5: "must lie within the margin from two hours before the
        event's `start_at` to two hours after its `end_at`
        (`ERR_SERVICE_WINDOW_OUT_OF_RANGE`)"

        Design: Corner/validations/service_window_outside_event_pad_rejected
        """
        scn = setup_approved_event(
            event_overrides={
                "expected_attendance": 5,
                "start_at": "2026-09-16T14:00:00Z",
                "end_at": "2026-09-16T15:00:00Z",
            }
        )
        requester = make_org_requester_headers(scn.org["id"])

        def attempt(start, end):
            return api.create_service_order(
                {
                    "event_id": scn.event["id"],
                    "category": "CUSTODIAL",
                    "quantity": 1,
                    "service_start_at": start,
                    "service_end_at": end,
                },
                requester,
            )

        rejected = attempt("2026-09-16T11:59:00Z", "2026-09-16T13:00:00Z")
        validate_error(rejected, ApiErrorId.ERR_SERVICE_WINDOW_OUT_OF_RANGE)

        accepted = attempt("2026-09-16T12:00:00Z", "2026-09-16T13:00:00Z")
        order = validate_success(accepted, 201)
        assert order["status"] == "REQUESTED", (
            "exactly event.start - 2h is inside the inclusive margin"
        )
