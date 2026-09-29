"""Two resources, two interval semantics: the inspector's buffered clock and the crew's calendar."""

from test_helpers import (
    ApiErrorId,
    InspectionStatus,
    InspectionType,
    MEASURE_HP_HVAC,
    ProjectStatus,
    REVIEWER_HEADERS,
    assert_program_buckets,
    build_assessment_measure,
    build_hvac_heat_pump_payload,
    build_inspection_payload,
    build_installation_payload,
    build_measure_result,
    build_world,
    cancel_inspection,
    create_approved_assessment,
    create_inspector,
    create_project,
    create_verified_household,
    read_inspection,
    read_program,
    read_project,
    report_installation,
    reserve_project,
    review_project,
    schedule_inspection,
    submit_project,
    validate_error,
    validate_paginated,
    validate_success,
)

INSTALL_RESULTS = [build_measure_result(MEASURE_HP_HVAC, 1, 700000)]


def _second_reserved_project(api, world, applicant_name, email, address):
    """Another dwelling served by the same contractor, reserved for 800000."""
    verified = create_verified_household(
        api,
        world["program_id"],
        applicant_name=applicant_name,
        email=email,
        service_address_line1=address,
    )
    assessment = create_approved_assessment(
        api,
        verified["household"]["id"],
        world["contractor_id"],
        [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
    )
    project = create_project(
        api,
        verified["household"]["id"],
        assessment["id"],
        world["contractor_id"],
        verified["income_verification"]["id"],
    )
    submit_project(api, project["id"], world["contractor_id"])
    review_project(api, project["id"])
    reserve_project(api, project["id"], world["program_id"])
    return read_project(api, project["id"])


class TestInspectorBufferedWindows:
    def test_one_minute_inside_the_buffer_conflicts_and_the_buffer_instant_itself_does_not(
        self, api
    ):
        """11:44Z loses to 11:00Z plus 45 minutes; 11:45Z ties and therefore wins.

        PRD §3.8: "The travel buffer is 45 minutes. A requested window conflicts with an
        existing one when the requested start falls before the existing `scheduled_end` plus
        the buffer **and** the existing `scheduled_start` falls before the requested end plus
        the buffer. Capacity is exactly one, so a single conflicting window is enough to
        refuse the request with `ERR_INSPECTOR_WINDOW_CONFLICT`. Timestamps are compared at
        minute resolution and the interval is half-open on the right, so a window beginning
        exactly 45 minutes after another ends is accepted."

        PRD §3.8: "The occupied windows are every inspection of the **same** inspector —
        across every program and every project, since the candidate project is irrelevant —
        whose status is `SCHEDULED`, `PASSED`, `CONDITIONAL_PASS`, or `FAILED`; a `CANCELLED`
        inspection frees its slot."

        PRD §2.10: "**Inspector window availability** → otherwise
        `ERR_INSPECTOR_WINDOW_CONFLICT` (409). Applies to `POST /inspections`."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_with_forty_five_minute_travel_buffer
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        inspector = create_inspector(api, world["program_id"], inspector_name="Lena Fuchs")
        project_id = world["project_id"]

        first = schedule_inspection(
            api,
            project_id,
            inspector["id"],
            InspectionType.SPOT,
            scheduled_start="2026-09-01T09:00:00Z",
            scheduled_end="2026-09-01T11:00:00Z",
        )
        assert first["status"] == InspectionStatus.SCHEDULED

        #  11:44Z is one minute inside the buffered end of 11:45Z.
        validate_error(
            api.create_inspection(
                build_inspection_payload(
                    project_id,
                    inspector["id"],
                    InspectionType.SPOT,
                    scheduled_start="2026-09-01T11:44:00Z",
                    scheduled_end="2026-09-01T12:44:00Z",
                ),
                REVIEWER_HEADERS,
            ),
            ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT,
            expected_status=409,
        )
        rows, meta = validate_paginated(
            api.list_inspections(
                REVIEWER_HEADERS,
                {"inspector_id": inspector["id"], "status": InspectionStatus.SCHEDULED},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first["id"]]

        #  11:45Z is not strictly before 11:45Z, so the adjacent window is legal.
        second = validate_success(
            api.create_inspection(
                build_inspection_payload(
                    project_id,
                    inspector["id"],
                    InspectionType.SPOT,
                    scheduled_start="2026-09-01T11:45:00Z",
                    scheduled_end="2026-09-01T12:45:00Z",
                ),
                REVIEWER_HEADERS,
            ),
            201,
        )
        assert second["status"] == InspectionStatus.SCHEDULED
        assert second["scheduled_start"].startswith("2026-09-01T11:45:00")
        _rows, meta = validate_paginated(
            api.list_inspections(
                REVIEWER_HEADERS,
                {"inspector_id": inspector["id"], "status": InspectionStatus.SCHEDULED},
            )
        )
        assert meta["total_count"] == 2

        #  Capacity is exactly one, so the accepted window immediately blocks its own replay.
        validate_error(
            api.create_inspection(
                build_inspection_payload(
                    project_id,
                    inspector["id"],
                    InspectionType.SPOT,
                    scheduled_start="2026-09-01T11:45:00Z",
                    scheduled_end="2026-09-01T12:45:00Z",
                ),
                REVIEWER_HEADERS,
            ),
            ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT,
            expected_status=409,
        )

    def test_cancelling_frees_the_slot_and_the_buffer_guards_the_earlier_side_too(self, api):
        """A CANCELLED window stops occupying, and the second arm of the test has its own edge.

        PRD §3.8: "The occupied windows are every inspection of the **same** inspector —
        across every program and every project, since the candidate project is irrelevant —
        whose status is `SCHEDULED`, `PASSED`, `CONDITIONAL_PASS`, or `FAILED`; a `CANCELLED`
        inspection frees its slot."

        PRD §3.8: "A requested window conflicts with an existing one when the requested start
        falls before the existing `scheduled_end` plus the buffer **and** the existing
        `scheduled_start` falls before the requested end plus the buffer."

        PRD §3.8: "A scheduled inspection may be cancelled by a `ProgramReviewer` or
        `ProgramAdmin` with an optional `cancellation_reason`, moving it `SCHEDULED →
        CANCELLED` and incrementing its version; the cancelled window stops participating in
        the conflict rule."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_with_forty_five_minute_travel_buffer
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        inspector = create_inspector(api, world["program_id"], inspector_name="Lena Fuchs")
        project_id = world["project_id"]

        first = schedule_inspection(
            api,
            project_id,
            inspector["id"],
            InspectionType.SPOT,
            scheduled_start="2026-09-01T09:00:00Z",
            scheduled_end="2026-09-01T11:00:00Z",
        )
        morning = build_inspection_payload(
            project_id,
            inspector["id"],
            InspectionType.SPOT,
            scheduled_start="2026-09-01T08:00:00Z",
            scheduled_end="2026-09-01T09:30:00Z",
        )
        validate_error(
            api.create_inspection(morning, REVIEWER_HEADERS),
            ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT,
            expected_status=409,
        )

        assert (
            cancel_inspection(api, first["id"], cancellation_reason="Inspector reassigned")[
                "status"
            ]
            == InspectionStatus.CANCELLED
        )

        #  The identical request now succeeds even though it overlaps the cancelled window
        #  outright.
        replacement = validate_success(api.create_inspection(morning, REVIEWER_HEADERS), 201)
        assert replacement["status"] == InspectionStatus.SCHEDULED
        assert read_inspection(api, first["id"])["status"] == InspectionStatus.CANCELLED

        #  Against the new 08:00Z-09:30Z window, a request ending at 07:16Z is refused
        #  because 08:00Z falls before 07:16Z plus the buffer.
        validate_error(
            api.create_inspection(
                build_inspection_payload(
                    project_id,
                    inspector["id"],
                    InspectionType.SPOT,
                    scheduled_start="2026-09-01T06:00:00Z",
                    scheduled_end="2026-09-01T07:16:00Z",
                ),
                REVIEWER_HEADERS,
            ),
            ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT,
            expected_status=409,
        )

        #  Ending one minute earlier puts the buffered end exactly at 08:00Z, which is not
        #  strictly before it.
        earlier = validate_success(
            api.create_inspection(
                build_inspection_payload(
                    project_id,
                    inspector["id"],
                    InspectionType.SPOT,
                    scheduled_start="2026-09-01T06:00:00Z",
                    scheduled_end="2026-09-01T07:15:00Z",
                ),
                REVIEWER_HEADERS,
            ),
            201,
        )
        assert earlier["scheduled_end"].startswith("2026-09-01T07:15:00")

        _rows, meta = validate_paginated(
            api.list_inspections(
                REVIEWER_HEADERS,
                {"inspector_id": inspector["id"], "status": InspectionStatus.SCHEDULED},
            )
        )
        assert meta["total_count"] == 2
        _cancelled, cancelled_meta = validate_paginated(
            api.list_inspections(
                REVIEWER_HEADERS,
                {"inspector_id": inspector["id"], "status": InspectionStatus.CANCELLED},
            )
        )
        assert cancelled_meta["total_count"] == 1


class TestCrewCapacityOverClosedDates:
    def test_a_shared_calendar_date_counts_as_an_overlap_and_two_of_them_exhaust_the_crew(
        self, api
    ):
        """Two overlaps refuse the report; shifting the start one day leaves only one.

        PRD §3.7: "Two windows overlap when the requested start is on or before the existing
        end **and** the existing start is on or before the requested end — closed on both
        ends, so sharing a single calendar date is an overlap. Comparison is on whole dates,
        not timestamps. If the number of overlapping occupied windows is greater than or equal
        to the contractor's `crew_capacity`, the report is refused with
        `ERR_CONTRACTOR_CREW_CAPACITY_EXCEEDED`; overlaps are therefore permitted right up to
        one fewer than the crew capacity."

        PRD §3.7: "The occupied windows are those of *other* rebate projects with the same
        `contractor_id` whose status is `INSTALLED`, `INSPECTION_FAILED`, `REMEDIATION`,
        `VERIFIED`, or `PAID` and whose `install_start_date` and `install_end_date` are both
        non-null."

        PRD §2.10: "**Contractor crew capacity** → otherwise
        `ERR_CONTRACTOR_CREW_CAPACITY_EXCEEDED` (409). Applies to `POST
        /rebate-projects/{id}/installation`. This is a different resource and a different
        interval semantics from rung 16."

        Design: Difficulty/resource_temporal_overlap/contractor_crew_capacity_over_closed_date_intervals
        """
        world = build_world(api, stage="reserved", catalog=[build_hvac_heat_pump_payload()])
        assert world["contractor"]["crew_capacity"] == 2
        project_b = _second_reserved_project(
            api, world, "Ines Marchetti", "ines@example.com", "88 Copper Way"
        )
        project_c = _second_reserved_project(
            api, world, "Tobias Vance", "tobias@example.com", "91 Copper Way"
        )
        assert_program_buckets(
            read_program(api, world["program_id"]), available=47600000, reserved=2400000
        )

        report_installation(
            api,
            world["project_id"],
            world["contractor_id"],
            INSTALL_RESULTS,
            install_start_date="2026-08-10",
            install_end_date="2026-08-20",
            actual_project_cost_cents=700000,
        )
        #  One overlap is fewer than the crew capacity of two, so B is accepted.
        installed_b = report_installation(
            api,
            project_b["id"],
            world["contractor_id"],
            INSTALL_RESULTS,
            install_start_date="2026-08-15",
            install_end_date="2026-08-25",
            actual_project_cost_cents=700000,
        )
        assert installed_b["status"] == ProjectStatus.INSTALLED

        #  C's window shares only the single date 2026-08-20 with A, which still counts.
        validate_error(
            api.report_installation(
                project_c["id"],
                build_installation_payload(
                    INSTALL_RESULTS,
                    install_start_date="2026-08-20",
                    install_end_date="2026-08-30",
                    actual_project_cost_cents=700000,
                ),
                world["contractor_headers"],
            ),
            ApiErrorId.ERR_CONTRACTOR_CREW_CAPACITY_EXCEEDED,
            expected_status=409,
        )
        refused = read_project(api, project_c["id"])
        assert refused["status"] == ProjectStatus.RESERVED
        assert refused["install_start_date"] is None

        #  One day later A drops out of the overlap set, leaving only B.
        installed_c = validate_success(
            api.report_installation(
                project_c["id"],
                build_installation_payload(
                    INSTALL_RESULTS,
                    install_start_date="2026-08-21",
                    install_end_date="2026-08-30",
                    actual_project_cost_cents=700000,
                ),
                world["contractor_headers"],
            )
        )
        assert installed_c["status"] == ProjectStatus.INSTALLED
        assert installed_c["install_start_date"] == "2026-08-21"
        assert installed_c["install_end_date"] == "2026-08-30"

        _rows, meta = validate_paginated(
            api.list_rebate_projects(
                REVIEWER_HEADERS,
                {"contractor_id": world["contractor_id"], "status": ProjectStatus.INSTALLED},
            )
        )
        assert meta["total_count"] == 3

        #  The capacity rule refuses work, never funding.
        assert_program_buckets(
            read_program(api, world["program_id"]),
            available=47600000,
            reserved=2400000,
            committed=0,
        )

    def test_a_single_crew_tolerates_no_overlap_and_adjacent_dates_need_no_buffer(self, api):
        """With crew_capacity 1 even one shared day is fatal, yet 08-20 and 08-21 coexist.

        PRD §3.7: "Crew capacity is an **aggregate** constraint over closed calendar-date
        intervals. The requested window is the closed interval from `install_start_date`
        through `install_end_date` inclusive."

        PRD §3.7: "Two windows overlap when the requested start is on or before the existing
        end **and** the existing start is on or before the requested end — closed on both
        ends, so sharing a single calendar date is an overlap. Comparison is on whole dates,
        not timestamps. If the number of overlapping occupied windows is greater than or equal
        to the contractor's `crew_capacity`, the report is refused with
        `ERR_CONTRACTOR_CREW_CAPACITY_EXCEEDED`; overlaps are therefore permitted right up to
        one fewer than the crew capacity."

        PRD §3.7: "Projects in `DRAFT`, `SUBMITTED`, `APPROVED`, or `RESERVED` have no install
        window yet, and windows belonging to projects in `EXPIRED`, `FAILED_FINAL`,
        `CLAWED_BACK`, or `REJECTED` are released."

        Design: Difficulty/resource_temporal_overlap/contractor_crew_capacity_over_closed_date_intervals
        """
        world = build_world(
            api,
            stage="reserved",
            catalog=[build_hvac_heat_pump_payload()],
            contractor_overrides={"crew_capacity": 1},
        )
        assert world["contractor"]["crew_capacity"] == 1
        project_b = _second_reserved_project(
            api, world, "Ines Marchetti", "ines@example.com", "88 Copper Way"
        )
        project_c = _second_reserved_project(
            api, world, "Tobias Vance", "tobias@example.com", "91 Copper Way"
        )

        #  The first report has no other window to overlap.
        report_installation(
            api,
            world["project_id"],
            world["contractor_id"],
            INSTALL_RESULTS,
            install_start_date="2026-08-10",
            install_end_date="2026-08-20",
            actual_project_cost_cents=700000,
        )

        #  A single shared date is already one overlap, which is not fewer than one.
        validate_error(
            api.report_installation(
                project_b["id"],
                build_installation_payload(
                    INSTALL_RESULTS,
                    install_start_date="2026-08-20",
                    install_end_date="2026-08-20",
                    actual_project_cost_cents=700000,
                ),
                world["contractor_headers"],
            ),
            ApiErrorId.ERR_CONTRACTOR_CREW_CAPACITY_EXCEEDED,
            expected_status=409,
        )
        assert read_project(api, project_b["id"])["status"] == ProjectStatus.RESERVED

        #  Dates are compared whole, with no buffer between them, so the very next day is
        #  free even for a single crew.
        installed_b = validate_success(
            api.report_installation(
                project_b["id"],
                build_installation_payload(
                    INSTALL_RESULTS,
                    install_start_date="2026-08-21",
                    install_end_date="2026-08-30",
                    actual_project_cost_cents=700000,
                ),
                world["contractor_headers"],
            )
        )
        assert installed_b["status"] == ProjectStatus.INSTALLED

        #  A window that ends the day before the first one starts is equally free.
        installed_c = validate_success(
            api.report_installation(
                project_c["id"],
                build_installation_payload(
                    INSTALL_RESULTS,
                    install_start_date="2026-08-05",
                    install_end_date="2026-08-09",
                    actual_project_cost_cents=700000,
                ),
                world["contractor_headers"],
            )
        )
        assert installed_c["status"] == ProjectStatus.INSTALLED
        assert installed_c["install_end_date"] == "2026-08-09"

        _rows, meta = validate_paginated(
            api.list_rebate_projects(
                REVIEWER_HEADERS,
                {"contractor_id": world["contractor_id"], "status": ProjectStatus.INSTALLED},
            )
        )
        assert meta["total_count"] == 3
