"""Crews, equipment, and assignments: input validation, pagination, the closed
working-interval overlap rules, activation date windows, and resource exclusions."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_assignment,
    assert_assignment,
    assert_crew,
    create_assignment_payload,
    create_crew_payload,
    create_equipment_payload,
    get_success_data,
    setup_mobilized_scenario,
    setup_storm_activation,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
DISPATCHER = TEST_USERS["utility_dispatcher_headers"]


class TestCrewRegistration:
    def test_invalid_crew_type_enum_rejected(self, api):
        """PRD §3.2: "A `CONTRACTOR_PM` registers a crew with a unique
        `crew_code`, a `crew_type` of `OVERHEAD`, `UNDERGROUND`, or `STORM`, a
        strictly positive `base_rate_per_hour` — the straight-time hourly rate
        that anchors storm premium pay — and an optional `home_depot` naming its
        home service center."
        PRD §2.9: "3. Request shape — required fields present, enum values drawn
        from their declared sets, numeric constraints satisfied (positive
        quantities and rates, percentages in range), otherwise
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/invalid_crew_type_enum_rejected
        """
        resp = api.create_crew(
            create_crew_payload(crew_code="CR-BAD", crew_type="HELICOPTER"),
            PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCrewListing:
    def test_crews_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned in one page; when omitted it defaults to 10, and it is bounded
        below by 1 and above by 100. The `offset` parameter sets how many items
        to skip before the page begins and defaults to 0."
        PRD §2.3: "The `meta` object of a paginated list response carries the
        fields `limit`, `offset`, `total_count`, and `has_more`, so a caller can
        always tell how many records exist in total and whether further pages
        remain."

        Design: Corner/entities/crews_list_pagination_envelope
        """
        crew_a = get_success_data(api.create_crew(
            create_crew_payload(crew_code="CR-A", crew_type="OVERHEAD"), PM))
        crew_b = get_success_data(api.create_crew(
            create_crew_payload(crew_code="CR-B", crew_type="UNDERGROUND",
                                base_rate_per_hour=58.00), PM))
        assert_crew(crew_a)
        assert_crew(crew_b)

        page1, meta1 = validate_paginated(
            api.list_crews(PM, params={"limit": 1, "offset": 0}))
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True, "A second page remains after offset 0"
        assert len(page1) == 1
        assert page1[0]["crew_code"] == "CR-A", (
            "Lists are sorted by creation timestamp, oldest first")

        page2, meta2 = validate_paginated(
            api.list_crews(PM, params={"limit": 1, "offset": 1}))
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False, "No page remains after offset 1"
        assert len(page2) == 1
        assert page2[0]["crew_code"] == "CR-B"


class TestAssignmentDateRules:
    def test_assignment_end_before_start_rejected(self, api):
        """PRD §3.2: "The foreman creates an assignment by naming a `crew_id`,
        an `equipment_id`, and a closed working interval from `start_date`
        through `end_date`, both inclusive; an `end_date` earlier than the
        `start_date` is rejected with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/assignment_end_before_start_rejected
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "CV-2"},
            wp_overrides={"name": "WP dr", "location": "L9"},
            crew_overrides={"crew_code": "CR-DR"},
            equipment_overrides={"equipment_code": "EQ-DR"})
        resp = api.create_assignment(
            scenario["work_package"]["id"],
            create_assignment_payload(scenario["crew"]["id"],
                                      scenario["equipment"]["id"],
                                      start_date="2026-08-07",
                                      end_date="2026-08-03"),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_assignment_activation_outside_date_window_rejected(self, api):
        """PRD §3.2: "Activation — from `PLANNED` to `ACTIVE` — requires the
        logical clock's date to fall on or after the `start_date` and on or
        before the `end_date`, and the work package to stand in `MOBILIZED` or
        `IN_PROGRESS`; violations surface as `ERR_INVALID_STATE`."

        Design: Corner/state_machines/assignment_activation_outside_date_window_rejected
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "CS-6"},
            wp_overrides={"name": "WP dw", "location": "L6"},
            crew_overrides={"crew_code": "CR-DW"},
            equipment_overrides={"equipment_code": "EQ-DW"})
        assignment = add_assignment(scenario, start_date="2026-08-05",
                                    end_date="2026-08-07")
        # The logical clock's date (2026-08-03) is before the window opens.
        set_logical_clock("2026-08-03T12:00:00Z")
        resp = api.transition_assignment(assignment["id"], {"to": "ACTIVE"}, FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_assignment(assignment["id"], FOREMAN))
        assert after["status"] == "PLANNED", (
            "Activation outside the working window leaves the assignment PLANNED")


class TestCrewScheduleOverlap:
    def test_crew_overlap_shared_endpoint_day_rejected(self, api):
        """PRD §3.2: "Three independent exclusions then apply: equipment whose
        `maintenance_flag` is true cannot be assigned and yields
        `ERR_EQUIPMENT_DOWN`; a crew holding an `ACTIVE` storm activation cannot
        take a regular assignment and yields `ERR_CREW_ON_STORM_DUTY`; and
        neither the crew nor the equipment may already hold an assignment in
        `PLANNED` or `ACTIVE` whose closed date interval overlaps the requested
        one — intervals overlap when each starts on or before the other ends,
        while pure adjacency, where the next assignment starts after the prior
        one ends, is allowed — yielding `ERR_CREW_SCHEDULE_CONFLICT` or
        `ERR_EQUIPMENT_SCHEDULE_CONFLICT` respectively."
        The existing interval 2026-08-03..2026-08-07 and the requested
        2026-08-07..2026-08-10 share the closed endpoint day 2026-08-07.

        Design: Difficulty/resource_temporal_overlap/crew_assignment_closed_interval_overlap
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "C-900"},
            bid_item_overrides={"item_code": "OH-GUY",
                                "description": "Guy wire install",
                                "unit_price": 45.00, "estimated_quantity": 80},
            wp_overrides={"name": "Guarding G-1", "location": "Feeder F-2"},
            crew_overrides={"crew_code": "CR-D"},
            equipment_overrides={"equipment_code": "EQ-D1"})
        spare_eq = get_success_data(api.create_equipment(
            create_equipment_payload(equipment_code="EQ-D2",
                                     kind="DIGGER_DERRICK", daily_rate=200.00),
            PM))
        first = add_assignment(scenario, "2026-08-03", "2026-08-07")
        assert first["status"] == "PLANNED"

        resp = api.create_assignment(
            scenario["work_package"]["id"],
            create_assignment_payload(scenario["crew"]["id"], spare_eq["id"],
                                      start_date="2026-08-07",
                                      end_date="2026-08-10"),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT)

    def test_crew_adjacent_assignment_allowed(self, api):
        """PRD §3.2: "Three independent exclusions then apply: equipment whose
        `maintenance_flag` is true cannot be assigned and yields
        `ERR_EQUIPMENT_DOWN`; a crew holding an `ACTIVE` storm activation cannot
        take a regular assignment and yields `ERR_CREW_ON_STORM_DUTY`; and
        neither the crew nor the equipment may already hold an assignment in
        `PLANNED` or `ACTIVE` whose closed date interval overlaps the requested
        one — intervals overlap when each starts on or before the other ends,
        while pure adjacency, where the next assignment starts after the prior
        one ends, is allowed — yielding `ERR_CREW_SCHEDULE_CONFLICT` or
        `ERR_EQUIPMENT_SCHEDULE_CONFLICT` respectively."
        Starting 2026-08-08, the day after the prior interval ends, is adjacent
        and allowed.

        Design: Difficulty/resource_temporal_overlap/crew_assignment_closed_interval_overlap
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "C-900"},
            bid_item_overrides={"item_code": "OH-GUY",
                                "description": "Guy wire install",
                                "unit_price": 45.00, "estimated_quantity": 80},
            wp_overrides={"name": "Guarding G-1", "location": "Feeder F-2"},
            crew_overrides={"crew_code": "CR-D"},
            equipment_overrides={"equipment_code": "EQ-D1"})
        spare_eq = get_success_data(api.create_equipment(
            create_equipment_payload(equipment_code="EQ-D2",
                                     kind="DIGGER_DERRICK", daily_rate=200.00),
            PM))
        add_assignment(scenario, "2026-08-03", "2026-08-07")

        resp = api.create_assignment(
            scenario["work_package"]["id"],
            create_assignment_payload(scenario["crew"]["id"], spare_eq["id"],
                                      start_date="2026-08-08",
                                      end_date="2026-08-10"),
            FOREMAN)
        second = validate_success(resp, 201)
        assert_assignment(second)
        assert second["status"] == "PLANNED", "A new assignment stands in PLANNED"


class TestEquipmentExclusions:
    def test_equipment_schedule_conflict_rejected(self, api):
        """PRD §3.2: "Three independent exclusions then apply: equipment whose
        `maintenance_flag` is true cannot be assigned and yields
        `ERR_EQUIPMENT_DOWN`; a crew holding an `ACTIVE` storm activation cannot
        take a regular assignment and yields `ERR_CREW_ON_STORM_DUTY`; and
        neither the crew nor the equipment may already hold an assignment in
        `PLANNED` or `ACTIVE` whose closed date interval overlaps the requested
        one — intervals overlap when each starts on or before the other ends,
        while pure adjacency, where the next assignment starts after the prior
        one ends, is allowed — yielding `ERR_CREW_SCHEDULE_CONFLICT` or
        `ERR_EQUIPMENT_SCHEDULE_CONFLICT` respectively."
        Here a different crew keeps the crew check clear so the equipment rule
        fires alone.

        Design: Corner/validations/equipment_schedule_conflict
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "CV-9"},
            wp_overrides={"name": "WP es", "location": "L15"},
            crew_overrides={"crew_code": "CR-E1"},
            equipment_overrides={"equipment_code": "EQ-SH",
                                 "kind": "DIGGER_DERRICK", "daily_rate": 200.00})
        crew2 = get_success_data(api.create_crew(
            create_crew_payload(crew_code="CR-E2"), PM))
        add_assignment(scenario, "2026-08-03", "2026-08-07")

        resp = api.create_assignment(
            scenario["work_package"]["id"],
            create_assignment_payload(crew2["id"],
                                      scenario["equipment"]["id"],
                                      start_date="2026-08-05",
                                      end_date="2026-08-09"),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_SCHEDULE_CONFLICT)

    def test_equipment_maintenance_flag_blocks_assignment(self, api):
        """PRD §3.2: "Three independent exclusions then apply: equipment whose
        `maintenance_flag` is true cannot be assigned and yields
        `ERR_EQUIPMENT_DOWN`; a crew holding an `ACTIVE` storm activation cannot
        take a regular assignment and yields `ERR_CREW_ON_STORM_DUTY`; and
        neither the crew nor the equipment may already hold an assignment in
        `PLANNED` or `ACTIVE` whose closed date interval overlaps the requested
        one — intervals overlap when each starts on or before the other ends,
        while pure adjacency, where the next assignment starts after the prior
        one ends, is allowed — yielding `ERR_CREW_SCHEDULE_CONFLICT` or
        `ERR_EQUIPMENT_SCHEDULE_CONFLICT` respectively."

        Design: Corner/validations/equipment_maintenance_flag_blocks_assignment
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "CV-8"},
            wp_overrides={"name": "WP eq", "location": "L14"},
            crew_overrides={"crew_code": "CR-EM"})
        down_eq = get_success_data(api.create_equipment(
            create_equipment_payload(equipment_code="EQ-DOWN", kind="TRENCHER",
                                     daily_rate=180.00, maintenance_flag=True),
            PM))
        assert down_eq["maintenance_flag"] is True

        resp = api.create_assignment(
            scenario["work_package"]["id"],
            create_assignment_payload(scenario["crew"]["id"], down_eq["id"]),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_DOWN)

    def test_crew_on_storm_duty_blocks_assignment(self, api):
        """PRD §3.2: "Three independent exclusions then apply: equipment whose
        `maintenance_flag` is true cannot be assigned and yields
        `ERR_EQUIPMENT_DOWN`; a crew holding an `ACTIVE` storm activation cannot
        take a regular assignment and yields `ERR_CREW_ON_STORM_DUTY`; and
        neither the crew nor the equipment may already hold an assignment in
        `PLANNED` or `ACTIVE` whose closed date interval overlaps the requested
        one — intervals overlap when each starts on or before the other ends,
        while pure adjacency, where the next assignment starts after the prior
        one ends, is allowed — yielding `ERR_CREW_SCHEDULE_CONFLICT` or
        `ERR_EQUIPMENT_SCHEDULE_CONFLICT` respectively."

        Design: Corner/validations/crew_on_storm_duty_blocks_assignment
        """
        scenario = setup_mobilized_scenario(
            contract_overrides={"contract_number": "CV-7"},
            wp_overrides={"name": "WP sd", "location": "L13"},
            crew_overrides={"crew_code": "CR-SD", "crew_type": "STORM"},
            equipment_overrides={"equipment_code": "EQ-SD"})
        activation = setup_storm_activation(scenario["contract"]["id"],
                                            scenario["crew"]["id"],
                                            kind="CALLOUT")
        assert activation["status"] == "ACTIVE"

        resp = api.create_assignment(
            scenario["work_package"]["id"],
            create_assignment_payload(scenario["crew"]["id"],
                                      scenario["equipment"]["id"]),
            FOREMAN)
        validate_error(resp, ApiErrorId.ERR_CREW_ON_STORM_DUTY)
