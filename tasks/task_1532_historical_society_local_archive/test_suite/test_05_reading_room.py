"""Reading-room booking: request/item gates, ownership, temporal gates, seat
capacity with half-open intervals, no-show strikes, and zone-hold reschedules."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_request,
    catalog_item,
    create_accessioned,
    create_appointment,
    create_collection,
    create_item,
    create_published_finding_aid,
    create_request,
    create_zone,
    get_appointment,
    get_item,
    get_researcher,
    get_ticket,
    get_zone,
    make_item_available,
    make_researcher_headers,
    post_breach_run,
    post_clean_run,
    record_no_show_at,
    register_researcher,
    set_clock,
    setup_approved_request,
    setup_available_item,
    setup_claimed_ticket,
    validate_error,
    validate_success,
)

ARCH = {"X-User-ID": "arch-1", "X-User-Role": "Archivist", "Content-Type": "application/json"}
RRS = {"X-User-ID": "rrs-1", "X-User-Role": "ReadingRoomStaff", "Content-Type": "application/json"}


def _multi_item_booking_setup(n_items=4):
    """One collection with n AVAILABLE items and one APPROVED request per item,
    all owned by a single researcher. Returns (items, researcher, requests)."""
    zone = create_zone()
    collection = create_collection(zone["id"])
    accession, _deed = create_accessioned()
    create_published_finding_aid(collection["id"])
    items = []
    for k in range(1, n_items + 1):
        item = create_item(accession["id"], collection["id"], title=f"I{k}")
        catalog_item(item["id"], appraised_value_cents=1000,
                     format="MANUSCRIPT")
        items.append(make_item_available(item["id"]))
    researcher = register_researcher()
    requests = []
    for k, item in enumerate(items, start=1):
        rq = create_request(researcher["id"], [item["id"]], topic=f"t{k}")
        requests.append(approve_request(rq["id"]))
    return items, researcher, requests


class TestRequestItemGates:

    def test_request_create_requires_available_items(self):
        """PRD §3.6: "Every referenced item must exist (`ERR_NOT_FOUND`) and
        must be `AVAILABLE`; the first offending id in the order the array
        presents them is reported as `ERR_ITEM_NOT_AVAILABLE`."

        Design: Corner/validations/request_create_requires_available_items
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        accession, _deed = create_accessioned()
        i1 = create_item(accession["id"], collection["id"], title="I1")
        i2 = create_item(accession["id"], collection["id"], title="I2")
        catalog_item(i1["id"])  # I1 reaches CATALOGED only; I2 PENDING_CATALOG
        researcher = register_researcher()

        resp = api_client.create_research_request(
            {"item_ids": [i1["id"], i2["id"]], "topic": "t",
             "purpose": "PERSONAL"},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_AVAILABLE)

    def test_input_shape_precedes_existence(self):
        """PRD §3.6: "The array must hold at least one and no more than ten
        entries; eleven or more is rejected with `ERR_TOO_MANY_ITEMS` and
        duplicate entries with `ERR_INVALID_REQUEST`, both before any item is
        looked up."
        PRD §2.8: "3. **Request body shape**, validated before any resource
        lookup — required fields are present; enum values fall in their declared
        sets; time ranges are coherent (an appointment's `start_time` strictly
        precedes its `end_time`, and a recording's `session_start` strictly
        precedes its `session_end`); logged hours are a positive multiple of
        0.25; item-id arrays are duplicate-free; a research request carries at
        least one and no more than ten item ids (more than ten yields
        `ERR_TOO_MANY_ITEMS`)"
        PRD §2.8: "4. **Existence** — resource identifiers resolve, path
        identifiers first in left-to-right order, then body-referenced
        identifiers, else `ERR_NOT_FOUND`."

        Design: Corner/validations/input_shape_precedes_existence
        """
        researcher = register_researcher()
        fake_ids = [
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333",
            "44444444-4444-4444-8444-444444444444",
            "55555555-5555-4555-8555-555555555555",
            "66666666-6666-4666-8666-666666666666",
            "77777777-7777-4777-8777-777777777777",
            "88888888-8888-4888-8888-888888888888",
            "99999999-9999-4999-8999-999999999999",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        ]
        # 11 > 10 fails the tier-3 shape check; none of these UUIDs exists, so
        # an implementation that dereferenced first would 404 instead.
        resp = api_client.create_research_request(
            {"item_ids": fake_ids, "topic": "t", "purpose": "PERSONAL"},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_TOO_MANY_ITEMS)
        assert resp.status_code == 422

    def test_request_not_approved_gates_appointment(self):
        """PRD §3.6: "The booking cascade of checks: the request must be
        `APPROVED` (`ERR_REQUEST_NOT_APPROVED`) and owned by the caller
        (`ERR_REQUEST_OWNERSHIP_MISMATCH`); the caller must be `ACTIVE`
        (`ERR_RESEARCHER_SUSPENDED`)"

        Design: Corner/validations/request_not_approved_gates_appointment
        """
        ctx = setup_available_item()
        researcher = register_researcher()
        request = create_request(researcher["id"], [ctx["item"]["id"]])
        assert request["status"] == "SUBMITTED"

        resp = api_client.create_appointment(
            {"research_request_id": request["id"], "room_code": "MAIN",
             "scheduled_date": "2026-08-10", "start_time": "10:00",
             "end_time": "11:00"},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_APPROVED)


class TestOwnershipReferentialGates:

    def test_ownership_referential_gates(self):
        """PRD §2.8: "11. **Referential integrity and ownership** — an
        appointment or reproduction order may reference only a research request
        owned by the caller (`ERR_REQUEST_OWNERSHIP_MISMATCH`); cancellations,
        ticket actions, and hour logging are restricted to the owning researcher
        or volunteer (`ERR_OWNERSHIP_MISMATCH`); an order's items must be a
        subset of the request's items (`ERR_ITEM_NOT_IN_REQUEST`)."
        PRD §2.1: "When `X-User-Role` is `Researcher`, `X-User-ID` is the `id`
        of the acting `Researcher` record; ownership checks on any resource that
        references a researcher — a research request, a reading-room
        appointment, a reproduction order — compare the resource's
        `researcher_id` field to `X-User-ID`."

        Design: Corner/validations/ownership_referential_gates
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        accession, _deed = create_accessioned()
        create_published_finding_aid(collection["id"])
        i1 = create_item(accession["id"], collection["id"], title="I1")
        i2 = create_item(accession["id"], collection["id"], title="I2")
        for it in (i1, i2):
            catalog_item(it["id"])
            make_item_available(it["id"])

        ra = register_researcher(full_name="A. One", email="a@example.org")
        rb = register_researcher(full_name="B. Two", email="b@example.org")
        request = create_request(ra["id"], [i1["id"]], topic="t")
        approve_request(request["id"])
        appointment = create_appointment(
            request["id"], ra["id"], scheduled_date="2026-08-10",
            start_time="10:00", end_time="11:00")

        # B booking against A's APPROVED request.
        resp1 = api_client.create_appointment(
            {"research_request_id": request["id"], "room_code": "MAIN",
             "scheduled_date": "2026-08-11", "start_time": "10:00",
             "end_time": "11:00"},
            make_researcher_headers(rb["id"]))
        validate_error(resp1, ApiErrorId.ERR_REQUEST_OWNERSHIP_MISMATCH)
        assert resp1.status_code == 403

        # B cancelling A's appointment.
        resp2 = api_client.cancel_appointment(
            appointment["id"], make_researcher_headers(rb["id"]))
        validate_error(resp2, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        # A second volunteer releasing vol_1's ticket.
        _project, ticket = setup_claimed_ticket(i2["id"], volunteer_id="vol_1")
        resp3 = api_client.release_ticket(
            ticket["id"],
            {"X-User-ID": "vol_2", "X-User-Role": "Volunteer",
             "Content-Type": "application/json"})
        validate_error(resp3, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        held = get_ticket(ticket["id"])
        assert held["status"] == "CLAIMED"
        assert held["claimed_by_user_id"] == "vol_1"


class TestFragileSafetyPriority:

    def test_fragile_gate_precedes_ownership_on_booking(self):
        """PRD §2.8: "Checks are evaluated in the following sequence, and the
        first failing tier determines the response"
        PRD §2.8: "8. **Conservation and compliance gates** — fragile items may
        not be pulled to the reading room (`ERR_ITEM_TOO_FRAGILE`)"
        PRD §2.8: "11. **Referential integrity and ownership** — an appointment
        or reproduction order may reference only a research request owned by the
        caller (`ERR_REQUEST_OWNERSHIP_MISMATCH`)"

        Design: Difficulty/priority_pair_validation_conflict/fragile_safety_beats_ownership_referential
        """
        ctx = setup_available_item(
            title="Vellum deed", condition_grade="FRAGILE",
            appraised_value_cents=250000, item_format="MANUSCRIPT")
        item_id = ctx["item"]["id"]
        ra = register_researcher(full_name="A. One", email="a@example.org")
        rb = register_researcher(full_name="B. Two", email="b@example.org")
        request = create_request(ra["id"], [item_id], topic="Charters",
                                 purpose="ACADEMIC")
        approve_request(request["id"])

        # B does not own the request AND the item is FRAGILE: the tier-8
        # safety gate fires ahead of the tier-11 ownership gate.
        resp = api_client.create_appointment(
            {"research_request_id": request["id"], "room_code": "MAIN",
             "scheduled_date": "2026-08-10", "start_time": "10:00",
             "end_time": "12:00", "seats": 1},
            make_researcher_headers(rb["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_TOO_FRAGILE)

    def test_fragile_gate_fires_for_owning_researcher(self):
        """PRD §3.6: "no item on the request may be `FRAGILE` — fragile material
        is never pulled to the reading room (`ERR_ITEM_TOO_FRAGILE`)"

        Design: Difficulty/priority_pair_validation_conflict/fragile_safety_beats_ownership_referential
        """
        ctx = setup_available_item(
            title="Vellum deed", condition_grade="FRAGILE",
            appraised_value_cents=250000, item_format="MANUSCRIPT")
        item_id = ctx["item"]["id"]
        ra = register_researcher(full_name="A. One", email="a@example.org")
        request = create_request(ra["id"], [item_id], topic="Charters",
                                 purpose="ACADEMIC")
        approve_request(request["id"])

        # The owner satisfies the ownership gate; the safety gate still fires.
        resp = api_client.create_appointment(
            {"research_request_id": request["id"], "room_code": "MAIN",
             "scheduled_date": "2026-08-10", "start_time": "10:00",
             "end_time": "12:00", "seats": 1},
            make_researcher_headers(ra["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_TOO_FRAGILE)


class TestAppointmentTemporalGates:

    def test_appointment_temporal_gates(self):
        """PRD §2.8: "9. **Temporal gates** — an appointment's start is strictly
        in the future (`ERR_APPOINTMENT_IN_PAST`); a no-show may be recorded
        only once the appointment has ended (`ERR_APPOINTMENT_NOT_ENDED`); a
        deaccession finalize before the cooling-off instant fails
        (`ERR_COOLING_OFF_NOT_ELAPSED`)."
        PRD §3.6: "the appointment start — the `scheduled_date` at `start_time`,
        UTC — must lie strictly in the future of the logical clock
        (`ERR_APPOINTMENT_IN_PAST`)."
        PRD §3.6: "the logical clock must have reached or passed the
        appointment's end datetime — its `scheduled_date` at `end_time`, UTC —
        else `ERR_APPOINTMENT_NOT_ENDED`."

        Design: Corner/errors/appointment_temporal_gates
        """
        ctx = setup_available_item()
        researcher, request = setup_approved_request([ctx["item"]["id"]])

        # Logical clock is at the 2026-08-01T00:00:00Z startup default: a
        # 2026-07-01 slot is in the past.
        resp1 = api_client.create_appointment(
            {"research_request_id": request["id"], "room_code": "MAIN",
             "scheduled_date": "2026-07-01", "start_time": "10:00",
             "end_time": "11:00"},
            make_researcher_headers(researcher["id"]))
        validate_error(resp1, ApiErrorId.ERR_APPOINTMENT_IN_PAST)
        assert resp1.status_code == 422

        appointment = create_appointment(
            request["id"], researcher["id"], scheduled_date="2026-08-10",
            start_time="10:00", end_time="11:00")
        assert appointment["status"] == "CONFIRMED"

        # 2026-08-01T00:00:00Z has not reached the slot's 2026-08-10T11:00 end.
        resp2 = api_client.record_no_show(appointment["id"], RRS)
        validate_error(resp2, ApiErrorId.ERR_APPOINTMENT_NOT_ENDED)
        after = get_appointment(appointment["id"])
        assert after["status"] == "CONFIRMED"


class TestSeatCapacityAndAdjacency:

    def test_full_house_admits_no_further_seat(self):
        """PRD §3.6: "The candidate is admitted only when occupied seats plus
        the requested `seats` come to no more than the room's capacity — a full
        house admits zero further seats, and overflow is rejected with
        `ERR_APPOINTMENT_CAPACITY_EXCEEDED`."
        PRD §3.6: "The two rooms differ in capacity: `MAIN` seats 8 and
        `MAP_ROOM` seats 4."

        Design: Difficulty/boundary_precision_check/seat_capacity_full_and_half_open_adjacency
        """
        _items, researcher, requests = _multi_item_booking_setup(3)
        a = create_appointment(requests[0]["id"], researcher["id"],
                               scheduled_date="2026-08-10", start_time="10:00",
                               end_time="12:00", seats=5)
        b = create_appointment(requests[1]["id"], researcher["id"],
                               scheduled_date="2026-08-10", start_time="10:00",
                               end_time="12:00", seats=3)
        assert a["status"] == "CONFIRMED" and b["status"] == "CONFIRMED"
        # 5 + 3 == 8 == capacity: full house.
        resp = api_client.create_appointment(
            {"research_request_id": requests[2]["id"], "room_code": "MAIN",
             "scheduled_date": "2026-08-10", "start_time": "10:00",
             "end_time": "12:00", "seats": 1},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_CAPACITY_EXCEEDED)

    def test_back_to_back_books_full_room(self):
        """PRD §3.6: "The time interval is half-open — the start is inclusive
        and the end exclusive — so the start must strictly precede the end
        (`ERR_INVALID_REQUEST`), and an appointment that ends exactly when
        another begins does not overlap it."
        PRD §3.6: "Two appointments overlap when the first starts before the
        second ends and the second starts before the first ends."

        Design: Difficulty/boundary_precision_check/seat_capacity_full_and_half_open_adjacency
        """
        _items, researcher, requests = _multi_item_booking_setup(2)
        create_appointment(requests[0]["id"], researcher["id"],
                           scheduled_date="2026-08-10", start_time="10:00",
                           end_time="12:00", seats=8)
        # Adjacent at the boundary: [12:00, 14:00) touches [10:00, 12:00) but
        # does not overlap, so all 8 seats are free again.
        d = create_appointment(requests[1]["id"], researcher["id"],
                               scheduled_date="2026-08-10", start_time="12:00",
                               end_time="14:00", seats=8)
        assert d["status"] == "CONFIRMED"


class TestHalfOpenIntervalSemantics:

    def test_adjacent_intervals_do_not_overlap(self):
        """PRD §3.6: "The time interval is half-open — the start is inclusive
        and the end exclusive — so the start must strictly precede the end
        (`ERR_INVALID_REQUEST`), and an appointment that ends exactly when
        another begins does not overlap it."

        Design: Difficulty/resource_temporal_overlap/reading_room_half_open_interval_semantics
        """
        _items, researcher, requests = _multi_item_booking_setup(2)
        first = create_appointment(requests[0]["id"], researcher["id"],
                                   scheduled_date="2026-08-10",
                                   start_time="10:00", end_time="12:00",
                                   seats=2)
        assert first["status"] == "CONFIRMED"
        second = create_appointment(requests[1]["id"], researcher["id"],
                                    scheduled_date="2026-08-10",
                                    start_time="12:00", end_time="13:00",
                                    seats=2)
        assert second["status"] == "CONFIRMED", (
            "touching bounds do not overlap under half-open semantics")

    def test_same_item_same_date_double_booked(self):
        """PRD §3.6: "Independently of times, a single item appearing on two
        distinct `CONFIRMED` appointments on the same `scheduled_date` is
        rejected with `ERR_ITEM_DOUBLE_BOOKED` at whole-day granularity."

        Design: Difficulty/resource_temporal_overlap/reading_room_half_open_interval_semantics
        """
        _items, researcher, requests = _multi_item_booking_setup(1)
        create_appointment(requests[0]["id"], researcher["id"],
                           scheduled_date="2026-08-10", start_time="10:00",
                           end_time="12:00", seats=2)
        # No time overlap with the morning slot, but the same request item on
        # the same calendar date is a whole-day double booking.
        resp = api_client.create_appointment(
            {"research_request_id": requests[0]["id"], "room_code": "MAIN",
             "scheduled_date": "2026-08-10", "start_time": "14:00",
             "end_time": "15:00", "seats": 1},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_DOUBLE_BOOKED)


class TestNoShowStrikeThreshold:

    def _drive_two_strikes(self):
        """Researcher with two recorded no-shows inside the rolling window;
        returns (item_id, researcher, request)."""
        ctx = setup_available_item()
        item_id = ctx["item"]["id"]
        researcher, request = setup_approved_request([item_id])

        set_clock("2026-02-01T00:00:00Z")
        ap1 = create_appointment(request["id"], researcher["id"],
                                 scheduled_date="2026-02-02",
                                 start_time="10:00", end_time="11:00", seats=1)
        record_no_show_at(ap1["id"], "2026-02-02T12:00:00Z")

        ap2 = create_appointment(request["id"], researcher["id"],
                                 scheduled_date="2026-03-02",
                                 start_time="10:00", end_time="11:00", seats=1)
        record_no_show_at(ap2["id"], "2026-03-02T12:00:00Z")
        return item_id, researcher, request

    def test_two_strikes_leave_researcher_active(self):
        """PRD §3.6: "When a freshly recorded no-show brings the count to at
        least three and the researcher is still `ACTIVE`, the researcher becomes
        `SUSPENDED` and every one of their future-dated `CONFIRMED` appointments
        is cancelled; exactly three strikes suspends, two does not."

        Design: Difficulty/boundary_precision_check/third_strike_suspends_at_threshold
        """
        _item_id, researcher, _request = self._drive_two_strikes()
        after_two = get_researcher(researcher["id"])
        assert after_two["no_show_strikes"] == 2
        assert after_two["status"] == "ACTIVE", (
            "two strikes must not suspend (the threshold is three)")

    def test_third_strike_suspends_and_cancels_future_appointments(self):
        """PRD §3.6: "When a freshly recorded no-show brings the count to at
        least three and the researcher is still `ACTIVE`, the researcher becomes
        `SUSPENDED` and every one of their future-dated `CONFIRMED` appointments
        is cancelled; exactly three strikes suspends, two does not."
        PRD §3.6: "The appointment becomes `NO_SHOW`, and the researcher's
        `no_show_strikes` is recomputed: the count of that researcher's
        `NO_SHOW` appointments whose `scheduled_date` falls on or after the date
        180 days before the current logical date — the window boundary is
        inclusive, and dates are compared as UTC calendar dates."

        Design: Difficulty/boundary_precision_check/third_strike_suspends_at_threshold
        """
        _item_id, researcher, request = self._drive_two_strikes()
        ap3 = create_appointment(request["id"], researcher["id"],
                                 scheduled_date="2026-06-02",
                                 start_time="10:00", end_time="11:00", seats=1)
        ap4 = create_appointment(request["id"], researcher["id"],
                                 scheduled_date="2026-06-20",
                                 start_time="10:00", end_time="11:00", seats=1)

        third = record_no_show_at(ap3["id"], "2026-06-02T12:00:00Z")
        assert third["status"] == "NO_SHOW"

        suspended = get_researcher(researcher["id"])
        # All three dates (2026-02-02, 2026-03-02, 2026-06-02) lie inside the
        # 180-day window ending 2026-06-02.
        assert suspended["no_show_strikes"] == 3
        assert suspended["status"] == "SUSPENDED", (
            "exactly three strikes suspends (>= threshold)")

        future = get_appointment(ap4["id"])
        assert future["status"] == "CANCELLED", (
            "the suspension cascade cancels future CONFIRMED appointments")


class TestStrikeWindowEdge:

    def test_strike_window_edge_inclusion(self):
        """PRD §3.6: "The appointment becomes `NO_SHOW`, and the researcher's
        `no_show_strikes` is recomputed: the count of that researcher's
        `NO_SHOW` appointments whose `scheduled_date` falls on or after the date
        180 days before the current logical date — the window boundary is
        inclusive, and dates are compared as UTC calendar dates."
        PRD §3.6: "exactly three strikes suspends, two does not."

        Design: Corner/calculations/strike_window_edge_inclusion
        """
        ctx = setup_available_item()
        item_id = ctx["item"]["id"]
        researcher, request = setup_approved_request([item_id])

        set_clock("2026-01-31T00:00:00Z")
        ap1 = create_appointment(request["id"], researcher["id"],
                                 scheduled_date="2026-02-01",
                                 start_time="10:00", end_time="11:00", seats=1)
        ap2 = create_appointment(request["id"], researcher["id"],
                                 scheduled_date="2026-02-02",
                                 start_time="10:00", end_time="11:00", seats=1)
        record_no_show_at(ap1["id"], "2026-02-01T12:00:00Z")
        record_no_show_at(ap2["id"], "2026-02-02T12:00:00Z")

        set_clock("2026-07-31T00:00:00Z")
        ap3 = create_appointment(request["id"], researcher["id"],
                                 scheduled_date="2026-08-01",
                                 start_time="10:00", end_time="11:00", seats=1)
        record_no_show_at(ap3["id"], "2026-08-01T12:00:00Z")

        researcher_after = get_researcher(researcher["id"])
        # As of 2026-08-01 the window floor is 2026-02-02 (inclusive): the
        # 2026-02-01 strike (181 days back) is excluded, the other two count.
        assert researcher_after["no_show_strikes"] == 2, (
            f"expected 2 strikes inside the inclusive 180-day window; got "
            f"{researcher_after['no_show_strikes']}")
        assert researcher_after["status"] == "ACTIVE"


class TestSuspensionAndReinstatement:

    def test_suspended_researcher_blocked_and_reinstated(self):
        """PRD §3.6: "The caller's researcher record is stamped onto the request
        as `researcher_id` from `X-User-ID`, and the caller must be `ACTIVE` — a
        suspended researcher is rejected with `ERR_RESEARCHER_SUSPENDED`."
        PRD §3.6: "The check is a level check evaluated on each no-show event,
        so reinstatement — staff moving a `SUSPENDED` researcher back to
        `ACTIVE` — deliberately does not erase strike history, and a later
        no-show recorded while the rolling count still stands at three or more
        suspends the researcher again."

        Design: Corner/errors/suspended_researcher_blocked_and_reinstated
        """
        ctx = setup_available_item()
        item_id = ctx["item"]["id"]
        researcher, request = setup_approved_request([item_id])

        set_clock("2026-05-31T00:00:00Z")
        appointments = [
            create_appointment(request["id"], researcher["id"],
                               scheduled_date=f"2026-06-0{day}",
                               start_time="10:00", end_time="11:00", seats=1)
            for day in (1, 2, 3)
        ]
        set_clock("2026-06-03T12:00:00Z")
        for ap in appointments:
            validate_success(api_client.record_no_show(ap["id"], RRS))

        suspended = get_researcher(researcher["id"])
        assert suspended["status"] == "SUSPENDED"

        resp = api_client.create_research_request(
            {"item_ids": [item_id], "topic": "t2", "purpose": "PERSONAL"},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_RESEARCHER_SUSPENDED)

        reinstated = validate_success(
            api_client.reinstate_researcher(researcher["id"], RRS))
        assert reinstated["status"] == "ACTIVE"

        request2 = create_request(researcher["id"], [item_id], topic="t2")
        assert request2["status"] == "SUBMITTED"


class TestRescheduleAfterZoneHold:

    def test_reschedule_flow_after_zone_hold(self):
        """PRD §3.6: "The owning researcher reschedules by supplying a new
        `scheduled_date`, `start_time`, and `end_time`: the appointment returns
        to `CONFIRMED` with seats re-reserved for the new interval, but only
        after passing the same capacity, double-booking, and future-start
        validations as creation, plus a fresh check that every item on the
        underlying request is `AVAILABLE` at reschedule time
        (`ERR_ITEM_NOT_AVAILABLE`)."
        PRD §2.6: "When a zone returns to `OPEN`, the zone's `ZONE_HOLD` items
        become `AVAILABLE` again — but appointments in `NEEDS_RESCHEDULE` are
        deliberately **not** auto-restored; the researcher must explicitly
        reschedule or cancel them."

        Design: Corner/endpoints/reschedule_flow_after_zone_hold
        """
        ctx = setup_available_item()
        zone_id = ctx["zone"]["id"]
        item_id = ctx["item"]["id"]
        researcher, request, appointment = self._book(ctx, item_id)

        # Three consecutive breaches -> RESTRICTED -> item ZONE_HOLD ->
        # appointment NEEDS_RESCHEDULE.
        post_breach_run(zone_id, 3)
        held = get_appointment(appointment["id"])
        assert held["status"] == "NEEDS_RESCHEDULE"
        assert get_item(item_id)["status"] == "ZONE_HOLD"

        # While the item is held, rescheduling is refused.
        resp = api_client.reschedule_appointment(
            appointment["id"],
            {"scheduled_date": "2026-08-12", "start_time": "10:00",
             "end_time": "12:00"},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_AVAILABLE)
        assert get_appointment(appointment["id"])["status"] == "NEEDS_RESCHEDULE"

        # Three in-range readings return the zone to OPEN and the item to
        # AVAILABLE; the appointment itself is not auto-restored.
        zone = post_clean_run(zone_id, 3, start_hour=4)
        assert zone["posture"] == "OPEN"
        assert get_item(item_id)["status"] == "AVAILABLE"
        assert get_appointment(appointment["id"])["status"] == "NEEDS_RESCHEDULE"

        rescheduled = validate_success(api_client.reschedule_appointment(
            appointment["id"],
            {"scheduled_date": "2026-08-12", "start_time": "10:00",
             "end_time": "12:00"},
            make_researcher_headers(researcher["id"])))
        assert rescheduled["status"] == "CONFIRMED"
        assert rescheduled["scheduled_date"] == "2026-08-12"

    @staticmethod
    def _book(ctx, item_id):
        researcher, request = setup_approved_request([item_id])
        appointment = create_appointment(
            request["id"], researcher["id"], scheduled_date="2026-08-10",
            start_time="10:00", end_time="12:00", seats=1)
        return researcher, request, appointment
