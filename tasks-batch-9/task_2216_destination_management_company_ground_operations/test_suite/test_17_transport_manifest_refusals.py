"""Departing an empty vehicle, colliding guest references and an inaccessible coach."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_to_in_execution,
    create_manifest_entry_payload,
    create_program,
    create_transport_segment,
    manifest_guest,
    read_program,
    set_clock,
    setup_program_with_contracted_element,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]


class TestDepartureNeedsSomebodyOnBoard:
    ANCHOR_ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Empty Bus Anchor Element",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }
    EMPTY_SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "EMPTY-01",
        "origin": "Host Hotel",
        "destination": "Rooftop Bar",
        "depart_at": "2026-09-11T18:00:00Z",
        "arrive_at": "2026-09-11T18:30:00Z",
        "seat_capacity": 12,
    }

    def _shuttle_past_its_departure_instant_with_nobody_on_it(self):
        ctx = setup_program_with_contracted_element(
            program_overrides={
                "client_name": "Empty Bus Client",
                "group_name": "Empty Bus Group",
                "guaranteed_count": 20,
            },
            element_overrides=self.ANCHOR_ELEMENT,
            venue_overrides={"name": "Empty Bus Venue"},
            supplier_overrides={
                "legal_name": "Empty Bus Supplier",
                "supplier_type": "TRANSPORT",
            },
            contract_overrides={"contract_value_cents": 80_000},
        )
        ctx["segment"] = create_transport_segment(
            ctx["program"]["id"], wheelchair_accessible=True, **self.EMPTY_SHUTTLE
        )
        advance_to_in_execution(ctx["program"]["id"])
        # Five minutes past depart_at, so the vehicle is genuinely due.
        set_clock("2026-09-11T18:05:00Z")
        return ctx

    def test_a_due_but_unoccupied_shuttle_cannot_depart(self, api):
        """PRD §3.5: "It requires the programme to be `IN_EXECUTION`
        (`ERR_PROGRAM_NOT_IN_EXECUTION`), the logical clock to have reached the segment's
        `depart_at` (`ERR_SEGMENT_NOT_DUE`), and the segment to have at least one seat booked
        (`ERR_EMPTY_MANIFEST`)."

        Design: Corner/errors/depart_segment_with_empty_manifest_rejected
        """
        ctx = self._shuttle_past_its_departure_instant_with_nobody_on_it()

        response = api.depart_transport_segment(ctx["segment"]["id"], OC)

        validate_error(response, ApiErrorId.ERR_EMPTY_MANIFEST.value, 409)
        # The clock is past depart_at, so the due-time gate is not what fired.
        assert (
            response.json()["data"]["error_id"] != ApiErrorId.ERR_SEGMENT_NOT_DUE.value
        )
        stored = validate_success(api.get_transport_segment(ctx["segment"]["id"], OC))
        assert stored["status"] == "SCHEDULED"
        assert stored["booked_seat_count"] == 0
        assert stored["departed_at"] is None


class TestGuestReferenceUniquenessIsPerSegment:
    FIRST_SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "DUP-01",
        "origin": "Host Hotel",
        "destination": "Museum",
        "depart_at": "2026-09-11T18:00:00Z",
        "arrive_at": "2026-09-11T18:30:00Z",
        "seat_capacity": 12,
    }
    SECOND_SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "DUP-02",
        "origin": "Host Hotel",
        "destination": "Museum",
        "depart_at": "2026-09-11T19:00:00Z",
        "arrive_at": "2026-09-11T19:30:00Z",
        "seat_capacity": 12,
    }
    DARA = {"guest_ref": "G-400", "guest_name": "Dara Okonkwo", "seat_count": 2}

    def _one_party_already_booked_on_the_first_shuttle(self):
        program = create_program(
            client_name="Duplicate Client",
            group_name="Duplicate Group",
            guaranteed_count=20,
        )
        first = create_transport_segment(
            program["id"], wheelchair_accessible=True, **self.FIRST_SHUTTLE
        )
        second = create_transport_segment(
            program["id"], wheelchair_accessible=True, **self.SECOND_SHUTTLE
        )
        manifest_guest(first["id"], **self.DARA)
        return {"program": program, "first": first, "second": second}

    def test_the_same_reference_collides_on_one_vehicle_and_fits_on_another(self, api):
        """PRD §3.5: "And the same `guest_ref` may not appear twice on one segment among
        entries in `ASSIGNED` or `CHECKED_IN`, with a collision reported as
        `ERR_DUPLICATE_MANIFEST_ENTRY`."

        Design: Corner/errors/duplicate_guest_ref_on_the_same_segment_rejected
        """
        ctx = self._one_party_already_booked_on_the_first_shuttle()

        collision = api.create_manifest_entry(
            create_manifest_entry_payload(ctx["first"]["id"], **self.DARA), OC
        )
        accepted = api.create_manifest_entry(
            create_manifest_entry_payload(ctx["second"]["id"], **self.DARA), OC
        )

        validate_error(collision, ApiErrorId.ERR_DUPLICATE_MANIFEST_ENTRY.value, 409)
        entry = validate_success(accepted, 201)
        assert entry["segment_id"] == ctx["second"]["id"]
        assert (
            validate_success(api.get_transport_segment(ctx["first"]["id"], OC))[
                "booked_seat_count"
            ]
            == 2
        )
        assert (
            validate_success(api.get_transport_segment(ctx["second"]["id"], OC))[
                "booked_seat_count"
            ]
            == 2
        )
        assert read_program(ctx["program"]["id"])["seated_guest_count"] == 4


class TestMobilityAssistNeedsAnAccessibleVehicle:
    STANDARD_COACH = {
        "segment_type": "ARRIVAL_TRANSFER",
        "vehicle_code": "COACH-STD",
        "origin": "Terminal B",
        "destination": "Host Hotel",
        "depart_at": "2026-09-10T15:00:00Z",
        "arrive_at": "2026-09-10T15:45:00Z",
        "seat_capacity": 20,
        "wheelchair_accessible": False,
    }
    ACCESSIBLE_COACH = {
        "segment_type": "ARRIVAL_TRANSFER",
        "vehicle_code": "COACH-ADA",
        "origin": "Terminal B",
        "destination": "Host Hotel",
        "depart_at": "2026-09-10T15:30:00Z",
        "arrive_at": "2026-09-10T16:15:00Z",
        "seat_capacity": 20,
        "wheelchair_accessible": True,
    }
    ELIN = {
        "guest_ref": "G-500",
        "guest_name": "Elin Haas",
        "seat_count": 1,
        "mobility_assist": True,
    }

    def _two_coaches_one_of_them_accessible(self):
        program = create_program(
            client_name="Access Client", group_name="Access Group", guaranteed_count=20
        )
        standard = create_transport_segment(program["id"], **self.STANDARD_COACH)
        accessible = create_transport_segment(program["id"], **self.ACCESSIBLE_COACH)
        return {"program": program, "standard": standard, "accessible": accessible}

    def test_the_guest_is_refused_on_the_standard_coach_and_taken_on_the_lift_coach(
        self, api
    ):
        """PRD §3.5: "A guest requiring `mobility_assist` may only be placed on a segment
        whose `wheelchair_accessible` is true, with failure reported as
        `ERR_ACCESSIBILITY_UNMET`."

        Design: Corner/errors/mobility_assist_guest_on_an_inaccessible_vehicle_rejected
        """
        ctx = self._two_coaches_one_of_them_accessible()

        refused = api.create_manifest_entry(
            create_manifest_entry_payload(ctx["standard"]["id"], **self.ELIN), OC
        )
        accepted = api.create_manifest_entry(
            create_manifest_entry_payload(ctx["accessible"]["id"], **self.ELIN), OC
        )

        validate_error(refused, ApiErrorId.ERR_ACCESSIBILITY_UNMET.value, 422)
        # Nineteen seats were still free, so the capacity gate never came into play.
        assert (
            refused.json()["data"]["error_id"]
            != ApiErrorId.ERR_SEGMENT_CAPACITY_EXCEEDED.value
        )
        entry = validate_success(accepted, 201)
        assert entry["status"] == "ASSIGNED"
        assert (
            validate_success(api.get_transport_segment(ctx["standard"]["id"], OC))[
                "booked_seat_count"
            ]
            == 0
        )
        assert (
            validate_success(api.get_transport_segment(ctx["accessible"]["id"], OC))[
                "booked_seat_count"
            ]
            == 1
        )
        assert read_program(ctx["program"]["id"])["seated_guest_count"] == 1
