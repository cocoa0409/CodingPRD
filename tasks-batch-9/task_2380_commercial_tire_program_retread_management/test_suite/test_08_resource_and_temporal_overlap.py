"""Three resources contended over time, each with its own interval geometry."""

from test_helpers import (
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestRetreadLineIntervalGeometry:
    """Half-open slots, with the cooldown held by the incumbent only."""

    def test_the_cooldown_buffer_is_asymmetric_between_incumbent_and_candidate(
        self, api
    ):
        """PRD §3.5: "The candidate, by contrast, occupies only its own half-open
        interval from `scheduled_start_at` up to but not including
        `scheduled_end_at`, because its own cooldown lands *after* it and will be
        accounted for when the next job is booked behind it."
        PRD §3.5: "The two intervals conflict when the candidate's start falls
        strictly before the occupied interval's end **and** the occupied interval's
        start falls strictly before the candidate's end."

        Design: Difficulty/resource_temporal_overlap/retread_line_half_open_slots_with_asymmetric_cooldown_buffer
        """
        program = fixtures.setup_line_with_occupied_slot(
            incumbent_start="2026-08-20T08:00:00Z",
            incumbent_end="2026-08-20T12:00:00Z",
        )
        line_id = program["line"]["id"]
        fleet_id = program["fleet"]["id"]
        location_id = program["location"]["id"]

        inside = fixtures.create_inspected_casing(fleet_id, location_id, grade="B")
        validate_error(
            api.create_retread_job(
                factories.retread_job_payload(
                    inside["id"], line_id, "2026-08-20T09:00:00Z", "2026-08-20T10:00:00Z"
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_RETREAD_SLOT_CONFLICT",
            expected_status=409,
        )

        on_the_cooldown = fixtures.create_inspected_casing(
            fleet_id, location_id, grade="B"
        )
        validate_error(
            api.create_retread_job(
                factories.retread_job_payload(
                    on_the_cooldown["id"],
                    line_id,
                    "2026-08-20T12:00:00Z",
                    "2026-08-20T13:00:00Z",
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_RETREAD_SLOT_CONFLICT",
            expected_status=409,
        )
        assert fixtures.read_line(line_id)["booked_minutes"] == 270

        # A candidate ending exactly where the incumbent begins is accepted: the
        # candidate's own cooldown is not held against itself.
        ahead = fixtures.create_inspected_casing(fleet_id, location_id, grade="B")
        job = validate_success(
            api.create_retread_job(
                factories.retread_job_payload(
                    ahead["id"], line_id, "2026-08-20T06:00:00Z", "2026-08-20T08:00:00Z"
                ),
                fixtures.SCHEDULER,
            ),
            expected_status=201,
        )

        assert job["status"] == "SCHEDULED"
        assert job["slot_minutes"] == 120
        assert fixtures.read_line(line_id)["booked_minutes"] == 420

    def test_the_conflict_is_scoped_to_the_one_line_that_is_busy(self, api):
        """PRD §2.10: "A retread line's `booked_minutes` is the sum, over jobs on
        that line whose `status` is `SCHEDULED` or `IN_PRODUCTION`, of that job's
        whole-minute slot length plus the line's `cure_cooldown_minutes`."
        PRD §3.5: "The jobs that occupy a line are those whose `status` is
        `SCHEDULED` or `IN_PRODUCTION`; jobs that are `COMPLETED`, `FAILED_CURE` or
        `CANCELLED` have released their slot and are ignored."

        Design: Difficulty/resource_temporal_overlap/retread_line_half_open_slots_with_asymmetric_cooldown_buffer
        """
        program = fixtures.setup_line_with_occupied_slot(
            incumbent_start="2026-08-20T08:00:00Z",
            incumbent_end="2026-08-20T12:00:00Z",
            line_count=2,
        )
        line_a, line_b = program["lines"]
        casing = fixtures.create_inspected_casing(
            program["fleet"]["id"], program["location"]["id"], grade="B"
        )

        job = validate_success(
            api.create_retread_job(
                factories.retread_job_payload(
                    casing["id"], line_b["id"], "2026-08-20T12:00:00Z", "2026-08-20T13:00:00Z"
                ),
                fixtures.SCHEDULER,
            ),
            expected_status=201,
        )

        assert job["retread_line_id"] == line_b["id"]
        assert fixtures.read_line(line_b["id"])["booked_minutes"] == 90, (
            "60 slot minutes plus this line's own 30-minute cooldown"
        )
        assert fixtures.read_line(line_a["id"])["booked_minutes"] == 270, (
            "the busy line is untouched by a booking somewhere else"
        )


class TestAgreementWindowGeometry:
    """Closed date windows: merely touching is an overlap."""

    def test_a_window_starting_on_the_incumbent_last_day_cannot_activate(self, api):
        """PRD §3.2: "The consequence deserves emphasis: two windows that merely
        touch on a single day — where the new `effective_from` equals an existing
        `effective_to` — **do** conflict, and the activation is rejected with
        `ERR_AGREEMENT_WINDOW_OVERLAP`."
        PRD §3.2: "A freshly drafted agreement is `DRAFT`. A `DRAFT` agreement prices
        nothing and blocks no window — it is inert."

        Design: Difficulty/resource_temporal_overlap/agreement_windows_closed_inclusive_touching_endpoints_conflict
        """
        program = fixtures.setup_fleet_program(with_agreement=True)
        assert program["agreement"]["effective_to"] == "2026-12-31"

        touching = validate_success(
            api.create_national_agreement(
                factories.national_agreement_payload(
                    program["fleet"]["id"],
                    effective_from="2026-12-31",
                    effective_to="2027-06-30",
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )
        assert touching["status"] == "DRAFT", "drafting itself is never blocked"

        validate_error(
            api.activate_national_agreement(touching["id"], {}, fixtures.ADMIN),
            "ERR_AGREEMENT_WINDOW_OVERLAP",
            expected_status=409,
        )

        still_draft = fixtures.read_agreement(touching["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft.get("activated_at") is None
        assert fixtures.read_agreement(program["agreement"]["id"])["status"] == "ACTIVE"

    def test_a_window_starting_one_day_later_abuts_cleanly(self, api):
        """PRD §3.2: "To abut cleanly, the new window must begin at least one calendar
        day after the existing window ends."
        PRD §3.2: "Activation moves it `DRAFT → ACTIVE`, sets `activated_at` to the
        logical clock, and increments the agreement's `version`."

        Design: Difficulty/resource_temporal_overlap/agreement_windows_closed_inclusive_touching_endpoints_conflict
        """
        program = fixtures.setup_fleet_program(with_agreement=True)

        successor = validate_success(
            api.create_national_agreement(
                factories.national_agreement_payload(
                    program["fleet"]["id"],
                    effective_from="2027-01-01",
                    effective_to="2027-06-30",
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )

        activated = validate_success(
            api.activate_national_agreement(successor["id"], {}, fixtures.ADMIN)
        )

        assert activated["status"] == "ACTIVE"
        assert activated["activated_at"].startswith("2026-08-01"), (
            "activation stamps the logical clock, which still sits at its default"
        )
        assert activated["version"] == successor["version"] + 1
        assert fixtures.read_agreement(program["agreement"]["id"])["status"] == "ACTIVE", (
            "two non-intersecting windows are simultaneously active"
        )


class TestWheelPositionSingleOccupancy:
    """One wheel, one assembly — a flagged tire is still on the truck."""

    def test_a_pull_flagged_assembly_still_occupies_its_wheel(self, api):
        """PRD §3.3: "Finally, no other asset may already occupy the same wheel: if
        another asset on that `vehicle_id` at that `position` is `MOUNTED` or
        `PULL_FLAGGED`, the mount is rejected with `ERR_POSITION_OCCUPIED`."
        PRD §3.3: "When `pull_recommended` is true and the asset is `MOUNTED`, the
        asset advances `MOUNTED → PULL_FLAGGED`."

        Design: Difficulty/resource_temporal_overlap/vehicle_wheel_position_single_occupancy
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        casing_one = fixtures.create_casing(program["fleet"]["id"])
        incumbent = fixtures.create_mounted_asset(
            program["fleet"]["id"], casing_one["id"], vehicle["id"]
        )

        survey = fixtures.record_survey(
            incumbent["id"], "2026-08-15T09:00:00Z", 100, 6, 130000
        )
        assert survey["finding_code"] == "TREAD_AT_PULL_POINT", (
            "six thirty-seconds is exactly the policy pull point"
        )
        assert survey["pull_recommended"] is True
        assert fixtures.read_tire_asset(incumbent["id"])["status"] == "PULL_FLAGGED"

        casing_two = fixtures.create_casing(program["fleet"]["id"])
        challenger = fixtures.create_tire_asset(
            program["fleet"]["id"], casing_two["id"]
        )
        validate_error(
            api.mount_tire_asset(
                challenger["id"],
                factories.mount_payload(
                    vehicle["id"], "2026-08-16T08:00:00Z", 130000, 24, "DRIVE"
                ),
                fixtures.TECH,
            ),
            "ERR_POSITION_OCCUPIED",
            expected_status=409,
        )

        blocked = fixtures.read_tire_asset(challenger["id"])
        assert blocked["status"] == "IN_INVENTORY"
        assert blocked.get("position") is None
        assert blocked.get("vehicle_id") is None

    def test_the_wheel_frees_up_only_when_the_incumbent_is_pulled(self, api):
        """PRD §3.3: "Both `vehicle_id` and `position` are deliberately **retained**
        after the pull, so the asset continues to group correctly under the vehicle
        type and position it actually wore out on when cost-per-mile is computed."
        PRD §3.3: "A `TireTechnician` supplies a `pull_reason` and the asset moves
        from `MOUNTED` or `PULL_FLAGGED` to `PULLED`, incrementing its `version`."

        Design: Difficulty/resource_temporal_overlap/vehicle_wheel_position_single_occupancy
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        casing_one = fixtures.create_casing(program["fleet"]["id"])
        incumbent = fixtures.create_mounted_asset(
            program["fleet"]["id"], casing_one["id"], vehicle["id"]
        )
        casing_two = fixtures.create_casing(program["fleet"]["id"])
        challenger = fixtures.create_tire_asset(
            program["fleet"]["id"], casing_two["id"]
        )
        mount = factories.mount_payload(
            vehicle["id"], "2026-08-16T08:00:00Z", 130000, 24, "DRIVE"
        )
        validate_error(
            api.mount_tire_asset(challenger["id"], mount, fixtures.TECH),
            "ERR_POSITION_OCCUPIED",
            expected_status=409,
        )

        pulled = validate_success(
            api.pull_tire_asset(
                incumbent["id"], factories.pull_payload(), fixtures.TECH
            )
        )
        assert pulled["status"] == "PULLED"
        assert pulled["vehicle_id"] == vehicle["id"]
        assert pulled["position"] == "DRIVE"
        assert pulled["version"] == incumbent["version"] + 1

        mounted = validate_success(
            api.mount_tire_asset(challenger["id"], mount, fixtures.TECH)
        )
        assert mounted["status"] == "MOUNTED"
        assert mounted["position"] == "DRIVE"
        assert mounted["vehicle_id"] == vehicle["id"]
