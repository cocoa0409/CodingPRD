"""Two shared resources whose collision predicates are pinned exactly.

A pickup route separates slots by a drive buffer; a disposition partner buckets
intake strictly by calendar date.
"""

from test_helpers import (
    ApiErrorId,
    LOGISTICS,
    api_client,
    assert_instant,
    assert_route_capacity_identity,
    book_appointment,
    complete_appointment,
    create_disposition_partner_row,
    create_model,
    disposition_payload,
    disposition_return,
    get_success_data,
    inspect_return,
    open_return_case,
    pickup_appointment_payload,
    read_appointment,
    read_return_case,
    read_route,
    set_clock,
    setup_delivered_order,
    setup_published_route,
    validate_error,
    validate_paginated,
)


class TestPickupSlotsCollideUntilTheDriveBufferClears:
    """Two collections on one truck, the second starting the instant the first ends."""

    def _route_with_one_slot(self):
        model = create_model(sku="MDL-Q-MED-T1", firmness="MEDIUM", size="QUEEN")
        first = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "to1a@example.com",
                "full_name": "Tessa Slot",
                "household_hash": "HH-TO1A",
            },
        )
        second = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "to1b@example.com",
                "full_name": "Timo Slot",
                "household_hash": "HH-TO1B",
            },
        )
        set_clock("2026-09-10T00:00:00Z")
        first["return_case"] = open_return_case(
            first["order"]["id"], first["customer_headers"]
        )
        second["return_case"] = open_return_case(
            second["order"]["id"], second["customer_headers"]
        )
        route = setup_published_route(capacity_units=6)
        first["appointment"] = book_appointment(
            route["id"],
            first["return_case"]["id"],
            slot_start_at="2026-09-15T09:00:00Z",
            slot_end_at="2026-09-15T11:00:00Z",
        )
        return {"route": read_route(route["id"]), "first": first, "second": second}

    def test_an_exactly_adjacent_slot_collides_with_the_slot_before_it(self):
        """PRD §3.7: "One consequence is worth spelling out: two exactly adjacent slots with no gap between them collide whenever `buffer_minutes` is greater than zero."

        The route never supplied `buffer_minutes`, so it carries the default 30,
        and a slot starting at 11:00 the moment the 09:00-11:00 visit ends is
        refused; the route ledger, its version and the second return case are all
        untouched.

        Design: Difficulty/resource_temporal_overlap/pickup_slot_point_adjacency_collides_until_the_30_minute_buffer_clears
        """
        fixture = self._route_with_one_slot()
        route = fixture["route"]

        assert route["buffer_minutes"] == 30, (
            f"an omitted buffer_minutes defaults to 30, got {route['buffer_minutes']}"
        )

        response = api_client.create_pickup_appointment(
            pickup_appointment_payload(
                route["id"],
                fixture["second"]["return_case"]["id"],
                route["version"],
                slot_start_at="2026-09-15T11:00:00Z",
                slot_end_at="2026-09-15T12:00:00Z",
            ),
            LOGISTICS,
        )
        validate_error(response, ApiErrorId.ERR_SLOT_OVERLAP)

        reloaded = read_route(route["id"])
        assert reloaded["booked_units"] == 2
        assert reloaded["available_units"] == 4
        assert reloaded["version"] == route["version"]
        assert (
            read_return_case(fixture["second"]["return_case"]["id"])["logistics_status"]
            == "REQUESTED"
        )

    def test_starting_the_slot_after_the_buffer_has_cleared_is_accepted(self):
        """PRD §3.7: "Second, the slot must be separated from every other slot on the same route whose `status` is `BOOKED` or `COMPLETED` by at least the route's `buffer_minutes`: treating each slot as the half-open interval from its start up to but not including its end, the new slot's `slot_start_at` must be at or after the existing slot's `slot_end_at` advanced by the buffer, or the new slot's `slot_end_at` advanced by the buffer must be at or before the existing slot's `slot_start_at`."

        Moving the second visit to 11:30 puts its start exactly at the first
        slot's 11:00 end advanced by the 30-minute buffer, which the rule admits;
        the first slot is not shifted to make room.

        Design: Difficulty/resource_temporal_overlap/pickup_slot_point_adjacency_collides_until_the_30_minute_buffer_clears
        """
        fixture = self._route_with_one_slot()
        route = fixture["route"]

        api_client.create_pickup_appointment(
            pickup_appointment_payload(
                route["id"],
                fixture["second"]["return_case"]["id"],
                route["version"],
                slot_start_at="2026-09-15T11:00:00Z",
                slot_end_at="2026-09-15T12:00:00Z",
            ),
            LOGISTICS,
        )
        appointment = get_success_data(
            api_client.create_pickup_appointment(
                pickup_appointment_payload(
                    route["id"],
                    fixture["second"]["return_case"]["id"],
                    route["version"],
                    slot_start_at="2026-09-15T11:30:00Z",
                    slot_end_at="2026-09-15T12:30:00Z",
                ),
                LOGISTICS,
            ),
            expected_status=201,
        )

        assert appointment["status"] == "BOOKED"
        assert_instant(appointment["slot_start_at"], "2026-09-15T11:30:00Z", "slot_start_at")

        untouched = read_appointment(fixture["first"]["appointment"]["id"])
        assert_instant(untouched["slot_end_at"], "2026-09-15T11:00:00Z", "slot_end_at")

        reloaded = read_route(route["id"])
        assert reloaded["booked_units"] == 4
        assert reloaded["available_units"] == 2
        assert_route_capacity_identity(reloaded)
        assert (
            read_return_case(fixture["second"]["return_case"]["id"])["logistics_status"]
            == "PICKUP_SCHEDULED"
        )


class TestDispositionBucketsCollideOnlyWithinTheSameIntakeDate:
    """A recycler with two units of intake per day and two QUEEN units to place."""

    def _two_inspected_cases(self):
        model = create_model(
            sku="MDL-Q-MED-T2",
            firmness="MEDIUM",
            size="QUEEN",
            donation_eligible=False,
        )
        partner = create_disposition_partner_row(
            name="Foam Cycle Narrow",
            partner_type="RECYCLER",
            region_code="CA",
            daily_intake_capacity_units=2,
            accepts_condition_grades=["A", "B", "C", "D"],
            soil_policy="ACCEPT_SOILED",
            priority_rank=1,
            recycle_fee_cents_per_unit=5000,
        )
        first = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "to2a@example.com",
                "full_name": "Dana Bucket",
                "household_hash": "HH-TO2A",
            },
        )
        second = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "to2b@example.com",
                "full_name": "Devi Bucket",
                "household_hash": "HH-TO2B",
            },
        )
        set_clock("2026-09-10T00:00:00Z")
        first["return_case"] = open_return_case(
            first["order"]["id"], first["customer_headers"]
        )
        second["return_case"] = open_return_case(
            second["order"]["id"], second["customer_headers"]
        )
        route = setup_published_route(capacity_units=6)
        appointment_one = book_appointment(
            route["id"],
            first["return_case"]["id"],
            slot_start_at="2026-09-15T09:00:00Z",
            slot_end_at="2026-09-15T10:00:00Z",
        )
        appointment_two = book_appointment(
            route["id"],
            second["return_case"]["id"],
            slot_start_at="2026-09-15T11:00:00Z",
            slot_end_at="2026-09-15T12:00:00Z",
        )
        set_clock("2026-09-15T00:00:00Z")
        complete_appointment(appointment_one["id"], "COMPLETED")
        complete_appointment(appointment_two["id"], "COMPLETED")
        inspect_return(first["return_case"]["id"], "A", False, False)
        inspect_return(second["return_case"]["id"], "A", False, False)
        first["assignment"] = disposition_return(
            first["return_case"]["id"], "RECYCLE", "2026-09-16"
        )
        return {"partner": partner, "first": first, "second": second}

    def test_a_second_unit_on_the_same_intake_date_exhausts_the_day_bucket(self):
        """PRD §3.8: "If some partner of the last type tried satisfies every eligibility clause except the capacity clause — the right region, the right grade, the right soil policy, but its day is already full — the refusal is `ERR_PARTNER_INTAKE_CAPACITY_EXCEEDED`."

        The only recycler in the region takes two units a day and the first QUEEN
        collection already booked both of them for 2026-09-16, so the second
        request for that same date is refused and its case stays INSPECTED with
        its disposition still PENDING.

        Design: Difficulty/resource_temporal_overlap/disposition_partner_day_bucket_collides_only_within_the_same_intake_date
        """
        fixture = self._two_inspected_cases()

        response = api_client.disposition_return_case(
            fixture["second"]["return_case"]["id"],
            disposition_payload("RECYCLE", "2026-09-16"),
            LOGISTICS,
        )
        validate_error(response, ApiErrorId.ERR_PARTNER_INTAKE_CAPACITY_EXCEEDED)

        reloaded = read_return_case(fixture["second"]["return_case"]["id"])
        assert reloaded["logistics_status"] == "INSPECTED"
        assert reloaded["disposition"] == "PENDING"

    def test_the_very_next_calendar_date_opens_a_fresh_bucket(self):
        """PRD §2.10: "Buckets are keyed strictly by calendar date, so assignments on adjacent intake dates never contend with each other no matter what time of day the pickups happened."

        The identical request for 2026-09-17 succeeds against the same
        two-unit-per-day partner, booking two units at the 5000-cent per-unit
        recycling fee, and the partner now holds exactly two assignments.

        Design: Difficulty/resource_temporal_overlap/disposition_partner_day_bucket_collides_only_within_the_same_intake_date
        """
        fixture = self._two_inspected_cases()

        api_client.disposition_return_case(
            fixture["second"]["return_case"]["id"],
            disposition_payload("RECYCLE", "2026-09-16"),
            LOGISTICS,
        )
        assignment = get_success_data(
            api_client.disposition_return_case(
                fixture["second"]["return_case"]["id"],
                disposition_payload("RECYCLE", "2026-09-17"),
                LOGISTICS,
            ),
            expected_status=201,
        )

        assert assignment["units"] == 2
        assert assignment["intake_date"] == "2026-09-17"
        assert assignment["disposition_type"] == "RECYCLE"
        assert assignment["fee_cents"] == 10000, (
            f"two units at 5000 cents each is 10000, got {assignment['fee_cents']}"
        )

        reloaded = read_return_case(fixture["second"]["return_case"]["id"])
        assert reloaded["logistics_status"] == "DISPOSITIONED"
        assert reloaded["disposition"] == "RECYCLE"

        _rows, meta = validate_paginated(
            api_client.list_disposition_assignments(
                LOGISTICS, params={"partner_id": fixture["partner"]["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            f"the partner holds one assignment per date, got {meta['total_count']}"
        )
