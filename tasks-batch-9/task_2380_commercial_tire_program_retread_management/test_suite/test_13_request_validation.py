"""Declared guards: monotonicity, ownership, ordering within a slot, and scope."""

from test_helpers import (
    assert_sla_pricing,
    factories,
    fixtures,
    make_tire_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOdometerMonotonicity:
    def test_a_reading_below_the_stored_value_is_refused_but_an_equal_one_is_not(
        self, api
    ):
        """PRD §3.1: "Odometer history is monotone: a reading below the vehicle's
        current `current_odometer_miles` is rejected with `ERR_ODOMETER_REGRESSION`."
        PRD §3.1: "Odometer readings are posted separately by a `DealerAdmin`, a
        `FleetManager` or a `TireTechnician`, supplying `odometer_miles` and the
        `reading_at` instant the reading was taken; the reading updates
        `current_odometer_miles`, records `reading_at` as `last_odometer_reading_at`,
        and increments the vehicle's `version`."

        Design: Corner/validations/odometer_reading_below_current_value_rejected
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(
            program["fleet"]["id"], current_odometer_miles=400000
        )
        headers = fixtures.fleet_manager_headers_for(program)

        validate_error(
            api.post_odometer(
                vehicle["id"],
                factories.odometer_payload(399999, "2026-08-21T09:00:00Z"),
                headers,
            ),
            "ERR_ODOMETER_REGRESSION",
            expected_status=422,
        )
        assert fixtures.read_vehicle(vehicle["id"])["current_odometer_miles"] == 400000

        level = validate_success(
            api.post_odometer(
                vehicle["id"],
                factories.odometer_payload(400000, "2026-08-21T09:05:00Z"),
                headers,
            )
        )
        assert level["current_odometer_miles"] == 400000, (
            "the guard rejects readings below the stored value, so an identical "
            "reading is accepted"
        )
        assert level["last_odometer_reading_at"] == "2026-08-21T09:05:00Z"
        assert level["version"] == vehicle["version"] + 1

        advanced = validate_success(
            api.post_odometer(
                vehicle["id"],
                factories.odometer_payload(400001, "2026-08-21T09:10:00Z"),
                headers,
            )
        )
        assert advanced["current_odometer_miles"] == 400001


class TestFullySatisfiedEmergencyCall:
    def test_a_call_that_clears_every_guard_is_accepted_and_priced(self, api):
        """PRD §3.6: "`gross_cents` is the sum of the base service call charge of 9500
        cents (ninety-five dollars), the labour charge, the mileage charge and the
        surcharge."
        PRD §3.6: "On an `EMERGENCY` call with no covering agreement, the commitment is
        the location baseline unchanged."

        Design: Corner/validations/emergency_call_within_all_limits_passes_and_prices
        """
        program = fixtures.setup_fleet_program(
            location_overrides={"road_service_response_minutes_committed": 120}
        )
        assert program["agreement"] is None, "the standard rate of 11000 applies"
        vehicle = fixtures.create_vehicle(
            program["fleet"]["id"], current_odometer_miles=250000
        )
        technician = fixtures.create_technician(
            program["location"]["id"], certification_level="TIA_CERTIFIED"
        )

        call = fixtures.open_call(
            program["fleet"]["id"],
            vehicle["id"],
            program["location"]["id"],
            "2026-08-20T10:00:00Z",
            priority="EMERGENCY",
        )
        fixtures.dispatch_call(
            call["id"], "2026-08-20T10:05:00Z", 10, technician["id"]
        )
        fixtures.arrive_call(call["id"], "2026-08-20T11:30:00Z", technician["id"])

        closed = validate_success(
            api.complete_road_service_call(
                call["id"],
                factories.complete_call_payload("2026-08-20T12:30:00Z", 1.0),
                make_tire_technician_headers(technician["id"]),
            )
        )

        assert closed["committed_response_minutes"] == 120, (
            "an emergency gets no NORMAL grace hour"
        )
        assert closed["actual_response_minutes"] == 90
        assert closed["sla_met"] is True
        assert closed["sla_credit_cents"] == 0
        # base 9500 + labour 11000 * 1.0 + mileage 285 * 10 = 23350, and the 0.75
        # emergency surcharge on that is 17513, comfortably under the 40000 cap.
        assert closed["gross_cents"] == 40863
        assert closed["invoice_total_cents"] == 40863
        assert closed["dispatch_status"] == "COMPLETED"
        assert closed["billing_status"] == "UNBILLED"
        assert_sla_pricing(closed)

        released = fixtures.read_technician(technician["id"])
        assert released["status"] == "AVAILABLE"
        assert released["completed_call_count"] == 1
        assert fixtures.read_vehicle(vehicle["id"])["status"] == "IN_SERVICE"


class TestMountBrandBeforeSpecification:
    def test_the_specification_error_is_unreachable_until_the_brand_is_right(self, api):
        """PRD §3.3: "The asset's `brand` must appear in the policy's
        `approved_brands`, otherwise `ERR_BRAND_NOT_APPROVED`; and the underlying
        casing's `casing_spec_code` must equal the policy's `casing_spec_code` unless
        the policy's value is the wildcard `ANY`, otherwise `ERR_CASING_SPEC_MISMATCH`
        — with brand checked before specification, so an asset failing both reports the
        brand error."
        PRD §3.3: "The supplied `tread_depth_at_mount_32nds` must be **strictly
        greater** than the policy's `min_tread_depth_32nds`; a depth equal to the legal
        minimum is not mountable and is rejected with
        `ERR_TREAD_BELOW_POLICY_MINIMUM`."

        Design: Corner/validations/mount_with_bad_brand_and_bad_spec_reports_brand_first
        """
        program = fixtures.setup_fleet_program(
            policy_overrides={"casing_spec_code": "R22.5"}
        )
        fleet_id = program["fleet"]["id"]
        vehicle = fixtures.create_vehicle(fleet_id)

        doubly_wrong = fixtures.create_tire_asset(
            fleet_id,
            fixtures.create_casing(
                fleet_id, brand="Goodyear", casing_spec_code="R19.5"
            )["id"],
            brand="Goodyear",
        )
        spec_wrong = fixtures.create_tire_asset(
            fleet_id,
            fixtures.create_casing(
                fleet_id, brand="Bridgestone", casing_spec_code="R19.5"
            )["id"],
            brand="Bridgestone",
        )

        mount = factories.mount_payload(
            vehicle["id"], "2026-08-22T09:00:00Z", 100000, 24, "DRIVE"
        )
        validate_error(
            api.mount_tire_asset(doubly_wrong["id"], mount, fixtures.TECH),
            "ERR_BRAND_NOT_APPROVED",
            expected_status=422,
        )
        validate_error(
            api.mount_tire_asset(spec_wrong["id"], mount, fixtures.TECH),
            "ERR_CASING_SPEC_MISMATCH",
            expected_status=422,
        )

        for asset in (doubly_wrong, spec_wrong):
            refused = fixtures.read_tire_asset(asset["id"])
            assert refused["status"] == "IN_INVENTORY"
            assert refused.get("vehicle_id") is None

        # The wheel was never taken, so a compliant assembly still mounts.
        compliant = fixtures.create_tire_asset(
            fleet_id,
            fixtures.create_casing(
                fleet_id, brand="Bridgestone", casing_spec_code="R22.5"
            )["id"],
        )
        mounted = validate_success(
            api.mount_tire_asset(compliant["id"], mount, fixtures.TECH)
        )
        assert mounted["status"] == "MOUNTED"


class TestCallOwnership:
    def test_a_call_may_not_name_another_fleets_unit(self, api):
        """PRD §3.6: "The fleet must be `ACTIVE`, otherwise `ERR_FLEET_SUSPENDED`; and
        the unit must belong to that fleet, otherwise `ERR_FLEET_MISMATCH`."
        PRD §2.6: "Because the topology is flat, every relationship is navigable in
        reverse through a filter on the child collection."

        Design: Corner/validations/road_service_call_naming_foreign_fleet_vehicle_rejected
        """
        program = fixtures.setup_fleet_program()
        fleet_a = program["fleet"]
        fleet_b = fixtures.create_fleet(program["location"]["id"])
        unit_of_b = fixtures.create_vehicle(fleet_b["id"], current_odometer_miles=60000)

        validate_error(
            api.create_road_service_call(
                factories.road_service_call_payload(
                    fleet_a["id"],
                    unit_of_b["id"],
                    program["location"]["id"],
                    "2026-08-23T09:00:00Z",
                ),
                fixtures.DISPATCHER,
            ),
            "ERR_FLEET_MISMATCH",
            expected_status=422,
        )

        _rows, meta = validate_paginated(
            api.list_road_service_calls(
                fixtures.DISPATCHER, params={"fleet_account_id": fleet_a["id"]}
            )
        )
        assert meta["total_count"] == 0, "both rows exist, so this is not a not-found"
        assert fixtures.read_vehicle(unit_of_b["id"])["status"] == "IN_SERVICE"


class TestJobStartWindow:
    def test_a_start_one_minute_early_is_refused_and_the_scheduled_minute_is_not(
        self, api
    ):
        """PRD §3.5: "The job must be `SCHEDULED`, the line must still be `AVAILABLE`
        — a line that went down between booking and start rejects the start with
        `ERR_LINE_DOWN` — and `started_at` must fall on or after the job's
        `scheduled_start_at`; an earlier instant is rejected with
        `ERR_JOB_START_TOO_EARLY`."
        PRD §3.5: "The job advances `SCHEDULED → IN_PRODUCTION` and cascades the casing
        `RETREAD_QUEUED → IN_RETREAD`."

        Design: Corner/validations/retread_job_started_before_scheduled_window_rejected
        """
        program = fixtures.setup_scheduled_job(
            grade="A",
            scheduled_start_at="2026-08-25T08:00:00Z",
            scheduled_end_at="2026-08-25T12:00:00Z",
        )
        job_id = program["job"]["id"]
        casing_id = program["casing"]["id"]

        validate_error(
            api.start_retread_job(
                job_id,
                factories.start_job_payload("2026-08-25T07:59:00Z"),
                fixtures.SCHEDULER,
            ),
            "ERR_JOB_START_TOO_EARLY",
            expected_status=422,
        )

        refused = fixtures.read_job(job_id)
        assert refused["status"] == "SCHEDULED"
        assert fixtures.read_casing(casing_id)["status"] == "RETREAD_QUEUED", (
            "the refused start moved no carcass"
        )

        started = validate_success(
            api.start_retread_job(
                job_id,
                factories.start_job_payload("2026-08-25T08:00:00Z"),
                fixtures.SCHEDULER,
            )
        )

        assert started["status"] == "IN_PRODUCTION", "the comparison is inclusive"
        assert fixtures.read_casing(casing_id)["status"] == "IN_RETREAD"
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 270, (
            "a job in production is still in the booked set"
        )


class TestSuspensionScope:
    def test_suspension_blocks_new_work_without_freezing_bookkeeping(self, api):
        """PRD §3.1: "Suspension is forward-looking only: work already in flight is
        untouched, but a suspended fleet may not have a new road service call opened for
        it and may not have a new retread scheduled — both are rejected with
        `ERR_FLEET_SUSPENDED`."
        PRD §2.11: "31. The fleet is not suspended — otherwise `ERR_FLEET_SUSPENDED`.
        Applies to road service call creation and retread job scheduling."

        Design: Corner/validations/fleet_suspension_guard_applies_only_to_two_endpoints
        """
        program = fixtures.setup_fleet_program()
        fleet_id = program["fleet"]["id"]
        vehicle = fixtures.create_vehicle(fleet_id, current_odometer_miles=30000)
        suspended = fixtures.suspend_fleet(fleet_id, reason="Credit hold")
        assert suspended["status"] == "SUSPENDED"

        validate_error(
            api.create_road_service_call(
                factories.road_service_call_payload(
                    fleet_id,
                    vehicle["id"],
                    program["location"]["id"],
                    "2026-08-24T09:00:00Z",
                ),
                fixtures.DISPATCHER,
            ),
            "ERR_FLEET_SUSPENDED",
            expected_status=409,
        )

        casing = validate_success(
            api.create_casing(
                factories.casing_payload(fleet_id, scrap_weight_lbs=130),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )
        assert casing["status"] == "ON_WHEEL", (
            "registering inventory is outside the guard"
        )

        reading = validate_success(
            api.post_odometer(
                vehicle["id"],
                factories.odometer_payload(31000, "2026-08-24T09:10:00Z"),
                fixtures.fleet_manager_headers_for(program),
            )
        )
        assert reading["current_odometer_miles"] == 31000

        assert fixtures.read_fleet(fleet_id)["status"] == "SUSPENDED", (
            "the two successes are not an accidental reinstatement"
        )
