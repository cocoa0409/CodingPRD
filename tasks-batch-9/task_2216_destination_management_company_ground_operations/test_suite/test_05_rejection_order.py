"""Requests that break two rules at once, and which rule the client is told about."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    confirm_assignment,
    create_program_element_payload,
    create_staff_member,
    propose_assignment,
    read_program,
    set_clock,
    setup_locked_program_with_segment,
    setup_program_with_element,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]


class TestVenueGeometryOutranksVenueCapacity:
    QUAYSIDE = {
        "name": "Quayside Supper Room",
        "capacity_seated": 50,
        "capacity_reception": 60,
        "turnover_buffer_minutes": 90,
    }
    FIRST_SEATING = {
        "element_type": "DINE_AROUND",
        "title": "First Seating",
        "starts_at": "2026-09-11T18:00:00Z",
        "ends_at": "2026-09-11T20:00:00Z",
        "planned_headcount": 40,
        "guaranteed_headcount": 40,
        "per_person_cost_cents": 11_000,
    }

    def _programme_with_one_seating(self):
        return setup_program_with_element(
            program_overrides={
                "client_name": "Sable Media",
                "group_name": "Creative Summit",
                "guaranteed_count": 90,
            },
            element_overrides=self.FIRST_SEATING,
            venue_overrides=self.QUAYSIDE,
            supplier_overrides={
                "legal_name": "Quayside Hospitality Ltd",
                "supplier_type": "VENUE_SERVICES",
            },
        )

    def _second_seating_payload(self, ctx):
        """A 20:30 seating for 80 guests: inside the turnover buffer and over capacity."""
        return create_program_element_payload(
            ctx["program"]["id"],
            ctx["supplier"]["id"],
            read_program(ctx["program"]["id"])["version"],
            venue_id=ctx["venue"]["id"],
            element_type="DINE_AROUND",
            title="Second Seating",
            starts_at="2026-09-11T20:30:00Z",
            ends_at="2026-09-11T22:30:00Z",
            planned_headcount=80,
            guaranteed_headcount=80,
            per_person_cost_cents=11_000,
        )

    def test_turnover_conflict_is_reported_rather_than_capacity(self, api):
        """PRD §2.9: "Checks are evaluated in the following fixed order, and the **first**
        failing check determines the response; later checks are not evaluated." Venue
        occupation geometry sits at band 22 and venue capacity at band 30.

        Design: Difficulty/priority_pair_validation_conflict/element_create_turnover_conflict_outranks_capacity_exceeded
        """
        ctx = self._programme_with_one_seating()

        response = api.create_program_element(self._second_seating_payload(ctx), PD)

        validate_error(response, ApiErrorId.ERR_VENUE_TURNOVER_CONFLICT.value, 409)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value
        )

    def test_the_capacity_rule_would_have_bitten_on_its_own(self, api):
        """PRD §3.2: "For a `DINE_AROUND` element, `planned_headcount` may not exceed the
        venue's `capacity_seated`; for an `ACTIVITY` or an `OFF_PREMISE_EVENT`, it may not
        exceed `capacity_reception`."

        Design: Difficulty/priority_pair_validation_conflict/element_create_turnover_conflict_outranks_capacity_exceeded
        """
        ctx = self._programme_with_one_seating()
        payload = self._second_seating_payload(ctx)
        # Push the seating clear of the 90-minute turnover buffer, leaving only the
        # capacity breach: 80 seated guests in a room that seats 50.
        payload["starts_at"] = "2026-09-11T21:30:00Z"
        payload["ends_at"] = "2026-09-11T23:30:00Z"

        response = api.create_program_element(payload, PD)

        validate_error(response, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value, 422)

    def test_the_refused_create_leaves_the_element_set_alone(self, api):
        """PRD §3.2: "A new element lands in `PLANNED`, and the create recomputes the
        programme's `element_count` and `open_element_count` and increments the programme's
        `version`."

        Design: Difficulty/priority_pair_validation_conflict/element_create_turnover_conflict_outranks_capacity_exceeded
        """
        ctx = self._programme_with_one_seating()
        version_before = read_program(ctx["program"]["id"])["version"]

        response = api.create_program_element(self._second_seating_payload(ctx), PD)

        validate_error(response, ApiErrorId.ERR_VENUE_TURNOVER_CONFLICT.value, 409)
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["element_count"] == 1
        assert program["open_element_count"] == 1
        assert program["version"] == version_before


class TestCredentialValidityOutranksRestGap:
    PINNACLE = {
        "client_name": "Pinnacle Devices",
        "group_name": "Field Service Rally",
        "guaranteed_count": 70,
    }
    SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "SHUT-02",
        "origin": "Host Hotel",
        "destination": "Expo Hall",
        "depart_at": "2026-09-11T08:00:00Z",
        "arrive_at": "2026-09-11T17:00:00Z",
        "seat_capacity": 40,
    }

    def _expired_badge_and_a_short_rest_gap(self, api):
        """One confirmed morning shift, one proposed afternoon shift, badge now lapsed."""
        ctx = setup_locked_program_with_segment(
            program_overrides=self.PINNACLE, segment_overrides=self.SHUTTLE
        )
        staff = create_staff_member(
            full_name="Marc Delacroix",
            pay_rate_cents_per_hour=4_200,
            min_rest_minutes=600,
            max_daily_minutes=720,
        )
        morning = propose_assignment(
            staff["id"],
            ctx["program"]["id"],
            target_type="SEGMENT",
            segment_id=ctx["segment"]["id"],
            role_type="COORDINATOR",
            starts_at="2026-09-11T08:00:00Z",
            ends_at="2026-09-11T12:00:00Z",
        )
        confirm_assignment(morning["id"])
        afternoon = propose_assignment(
            staff["id"],
            ctx["program"]["id"],
            target_type="SEGMENT",
            segment_id=ctx["segment"]["id"],
            role_type="COORDINATOR",
            starts_at="2026-09-11T13:00:00Z",
            ends_at="2026-09-11T17:00:00Z",
        )
        validate_success(
            api.patch_staff_member(staff["id"], {"badge_expires_on": "2026-08-20"}, PD)
        )
        set_clock("2026-09-05T00:00:00Z")
        ctx.update({"staff": staff, "morning": morning, "afternoon": afternoon})
        return ctx

    def test_the_lapsed_badge_is_reported_rather_than_the_rest_gap(self, api):
        """PRD §2.9: "Insurance and credential compliance (bands 14 to 17) deliberately
        outrank all scheduling geometry (bands 22 to 27): the DMC may not put an uninsured
        coach operator or an uncredentialed greeter in front of a client under any
        scheduling circumstance, so a request that is both uninsured and double-booked
        reports the insurance failure."

        Design: Difficulty/priority_pair_validation_conflict/assignment_confirm_credential_expired_outranks_rest_gap
        """
        ctx = self._expired_badge_and_a_short_rest_gap(api)

        response = api.confirm_staff_assignment(ctx["afternoon"]["id"], PD)

        validate_error(response, ApiErrorId.ERR_CREDENTIAL_EXPIRED.value, 422)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_STAFF_REST_GAP_VIOLATION.value
        )

    def test_the_weakest_document_drives_the_derived_credential_status(self, api):
        """PRD §3.6: "Take the **earlier** of `badge_expires_on` and
        `first_aid_expires_on` — a person is only as credentialed as their weakest
        document."

        Design: Difficulty/priority_pair_validation_conflict/assignment_confirm_credential_expired_outranks_rest_gap
        """
        ctx = self._expired_badge_and_a_short_rest_gap(api)

        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))

        assert staff["badge_expires_on"] == "2026-08-20"
        assert staff["first_aid_expires_on"] == "2027-12-31"
        assert staff["credential_status"] == "EXPIRED"

    def test_the_refused_confirm_reserves_nothing(self, api):
        """PRD §3.6: "Then the three scheduling tests run, and then the labour cost is
        stamped."

        Design: Difficulty/priority_pair_validation_conflict/assignment_confirm_credential_expired_outranks_rest_gap
        """
        ctx = self._expired_badge_and_a_short_rest_gap(api)

        response = api.confirm_staff_assignment(ctx["afternoon"]["id"], PD)

        validate_error(response, ApiErrorId.ERR_CREDENTIAL_EXPIRED.value, 422)
        afternoon = validate_success(api.get_staff_assignment(ctx["afternoon"]["id"], PD))
        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))
        assert afternoon["status"] == "PROPOSED"
        assert afternoon["planned_labor_cost_cents"] == 0
        # Only the morning shift's 240 minutes remain reserved.
        assert staff["confirmed_minutes_total"] == 240
