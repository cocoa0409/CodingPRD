"""Opening a tract: production plans, crew allocation, move-in pricing, lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_crew_assignment,
    assert_production_plan,
    assert_tract,
    build_network,
    create_crew,
    create_crew_assignment,
    create_tract,
    dispatch_load,
    read_crew,
    read_crew_assignment,
    read_production_plan,
    read_tract,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOpeningTheUnit:
    def test_new_tract_opens_planned_with_zeroed_system_counters(self, api, ops_headers):
        """PRD §3.3: "An `OperationsManager` opens a harvest unit by supplying its
        `name` of 1 to 120 characters, a `legal_description` of 1 to 200 characters
        carrying the township, range and section, the `gross_acres` inside the unit
        boundary as a number greater than zero, the `planned_volume_tons` the operator
        expects to remove as a number greater than zero, and the `access_class` that
        governs which months the ground will carry equipment."
        PRD §3.3: "A new tract opens in `PLANNED` status with a `suspension_count` of
        0, a `move_in_cost_cents` of 0 and a `produced_tons` of 0."
        PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
        mutation, and `version`, an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that resource."

        Design: Corner/entities/tract_creation_returns_201_with_system_defaults
        """
        payload = {
            "name": "Section 14 NE",
            "legal_description": "T3S R5W Sec 14 NE1/4",
            "gross_acres": 120,
            "planned_volume_tons": 4000,
            "access_class": "ALL_SEASON",
        }
        tract = validate_success(api.create_tract(payload, ops_headers), 201)

        assert_tract(tract)
        assert tract["status"] == "PLANNED"
        assert tract["access_class"] == "ALL_SEASON"
        assert tract["gross_acres"] == pytest.approx(120)
        assert tract["planned_volume_tons"] == pytest.approx(4000)
        assert tract["suspension_count"] == 0
        assert tract["move_in_cost_cents"] == 0
        assert tract["produced_tons"] == pytest.approx(0, abs=0.005)
        assert tract["version"] == 1

    def test_opening_a_tract_without_an_access_class_is_a_schema_failure(
        self, api, ops_headers
    ):
        """PRD §3.3: "An `OperationsManager` opens a harvest unit by supplying its
        `name` of 1 to 120 characters, a `legal_description` of 1 to 200 characters
        carrying the township, range and section, the `gross_acres` inside the unit
        boundary as a number greater than zero, the `planned_volume_tons` the operator
        expects to remove as a number greater than zero, and the `access_class` that
        governs which months the ground will carry equipment."
        PRD §2.7: "**Request schema.** On every write endpoint: every required input
        field present, every enum-typed value a legal member of its enumeration, every
        number inside its declared range, `window_end` strictly after `window_start`,
        `scheduled_arrive_at` strictly after `scheduled_depart_at`, `period_end` on or
        after `period_start`, and any attempt to set a derived-only status value
        (specifically a `MillContract` `status` of `FILLED`) refused. Failure is
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_tract_without_access_class_returns_validation
        """
        payload = {
            "name": "Section 14 NE",
            "legal_description": "T3S R5W Sec 14 NE1/4",
            "gross_acres": 120,
            "planned_volume_tons": 4000,
        }
        response = api.create_tract(payload, ops_headers)
        error = validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)
        assert "id" not in error, "a schema failure returns no created resource"

    def test_plan_volume_is_the_weekly_target_times_the_horizon(self, api, ops_headers):
        """PRD §3.3: "The system multiplies the weekly target by the horizon and rounds
        the product half-up to two decimal places, storing the result as the plan's own
        `planned_volume_tons`."
        PRD §3.3: "A plan is created in `DRAFT` status; creating one supersedes the
        tract's history, so every prior plan on that tract whose status is `DRAFT` or
        `APPROVED` moves to `SUPERSEDED`, and the tract's `version` is incremented by
        1."

        Design: Corner/entities/production_plan_planned_volume_tons_is_computed_not_accepted
        """
        tract = create_tract()

        plan = validate_success(
            api.create_production_plan(
                tract["id"],
                {
                    "target_tons_per_week": 137.5,
                    "plan_horizon_weeks": 6,
                    "expected_tract_version": tract["version"],
                },
                ops_headers,
            ),
            201,
        )

        assert_production_plan(plan)
        assert plan["planned_volume_tons"] == pytest.approx(825.00, abs=0.005)
        assert plan["status"] == "DRAFT"
        assert plan["tract_id"] == tract["id"]
        assert read_tract(tract["id"])["version"] == 2

    def test_crew_assignment_is_listable_from_its_crew_and_from_its_tract(
        self, api, ops_headers
    ):
        """PRD §3.3: "Crew assignments may be read individually and listed with filters
        on `crew_id`, `tract_id` and `status`."
        PRD §3.3: "Only three things feed that number: the crew named by `crew_id` (its
        `equipment_pieces` and `crew_type`), the tract's `access_class`, and the
        request's `move_in_miles`."
        PRD §3.3: "Creating the assignment adds the computed charge to the tract's own
        `move_in_cost_cents` and increments the tract's `version` by 1."

        Design: Corner/entities/crew_assignment_is_reachable_from_both_of_its_parent_aggregates
        """
        crew = create_crew()
        tract = create_tract()
        assignment = create_crew_assignment(tract["id"], crew["id"])

        assert_crew_assignment(assignment)

        by_crew, _ = validate_paginated(
            api.list_crew_assignments(ops_headers, params={"crew_id": crew["id"]})
        )
        by_tract, _ = validate_paginated(
            api.list_crew_assignments(ops_headers, params={"tract_id": tract["id"]})
        )
        assert [row["id"] for row in by_crew] == [assignment["id"]]
        assert [row["id"] for row in by_tract] == [assignment["id"]]

        assert assignment["lowboy_trips"] == 2
        assert assignment["move_in_cost_cents"] == 186_750
        assert read_tract(tract["id"])["move_in_cost_cents"] == 186_750


class TestMoveInPricing:
    def test_move_in_charge_is_clipped_by_the_ceiling_on_a_long_cable_yarding_move(
        self, api, ops_headers
    ):
        """PRD §3.3: "First, the number of lowboy trips is the crew's
        `equipment_pieces` divided by two and rounded **up** to a whole number, since
        one lowboy carries two pieces; that count is stored on the assignment as
        `lowboy_trips`."
        PRD §3.3: "Second, a tiered mileage charge is accumulated across the one-way
        distance: 900 cents for each of the first 25 miles, 725 cents for each mile
        beyond 25 up to and including 75, and 610 cents for each mile beyond 75."
        PRD §3.3: "Sixth, the subtotal is raised to a floor of 185,000 cents if it
        falls below that, and only then lowered to a ceiling of 1,250,000 cents if it
        exceeds it — the floor is applied before the cap, so a subtotal below the floor
        and a cap below the floor can never both bind."

        Design: Difficulty/combinatorial_formula/move_in_cost_tiered_waterfall_with_cap_and_floor_both_binding
        """
        crew = create_crew(
            name="Cable Bravo",
            crew_type="CABLE_YARDING",
            equipment_pieces=11,
            daily_rate_cents=910_000,
        )
        tract = create_tract(
            name="Ridge 9",
            legal_description="T1N R7W Sec 9 SW1/4",
            gross_acres=80,
            planned_volume_tons=2600,
            access_class="FROZEN_ONLY",
        )

        assignment = create_crew_assignment(
            tract["id"],
            crew["id"],
            move_in_miles=200,
            window_start="2026-08-01",
            window_end="2026-10-01",
        )

        assert assignment["lowboy_trips"] == 6, "ceil(11 / 2) lowboy trips"
        assert assignment["move_in_cost_cents"] == 1_250_000, (
            "a subtotal of 1368500 cents is lowered to the 1250000 cent ceiling"
        )
        assert read_tract(tract["id"])["move_in_cost_cents"] == 1_250_000

    def test_move_in_charge_is_lifted_by_the_floor_on_a_short_hand_falling_move(
        self, api, ops_headers
    ):
        """PRD §3.3: "Fourth, the base charge is multiplied by an access multiplier
        taken from the tract's `access_class` — 1.00 for `ALL_SEASON`, 1.15 for
        `SUMMER_ONLY` and 1.35 for `FROZEN_ONLY` — and the product is rounded half-up
        to whole cents *before* anything else is added."
        PRD §3.3: "Fifth, a flat crew-type surcharge is added to that rounded figure:
        nothing for `HAND_FALLING`, 120,000 cents for `MECHANIZED_GROUND`, and 275,000
        cents for `CABLE_YARDING`."
        PRD §3.3: "Sixth, the subtotal is raised to a floor of 185,000 cents if it
        falls below that, and only then lowered to a ceiling of 1,250,000 cents if it
        exceeds it — the floor is applied before the cap, so a subtotal below the floor
        and a cap below the floor can never both bind."

        Design: Difficulty/combinatorial_formula/move_in_cost_tiered_waterfall_with_cap_and_floor_both_binding
        """
        crew = create_crew(
            name="Hand Delta",
            crew_type="HAND_FALLING",
            equipment_pieces=3,
            daily_rate_cents=260_000,
        )
        tract = create_tract(
            name="Flat 2",
            legal_description="T1N R7W Sec 2 NE1/4",
            gross_acres=45,
            planned_volume_tons=900,
            access_class="ALL_SEASON",
        )

        assignment = create_crew_assignment(
            tract["id"],
            crew["id"],
            move_in_miles=12,
            window_start="2026-08-01",
            window_end="2026-10-01",
        )

        assert assignment["lowboy_trips"] == 2, "ceil(3 / 2) lowboy trips"
        assert assignment["move_in_cost_cents"] == 185_000, (
            "a subtotal of 21600 cents is raised to the 185000 cent floor"
        )
        assert read_tract(tract["id"])["move_in_cost_cents"] == 185_000


class TestCrewOccupationWindows:
    def test_assignment_starting_on_the_prior_window_end_hits_the_move_buffer(
        self, api, ops_headers
    ):
        """PRD §3.3: "Concretely, a proposed assignment conflicts with an existing one
        — considering only that crew's assignments whose status is anything other than
        `RELEASED` — when the proposed `window_start` falls before the existing
        `window_end` plus two days **and** the proposed `window_end` falls strictly
        after the existing `window_start`. A conflict is refused with
        `ERR_CREW_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crew_occupation_window_is_half_open_with_a_two_day_move_buffer
        """
        crew = create_crew()
        tract_a = create_tract(
            name="Unit A",
            legal_description="T2S R4W Sec 11 NW1/4",
            gross_acres=95,
            planned_volume_tons=3100,
        )
        tract_b = create_tract(
            name="Unit B",
            legal_description="T2S R4W Sec 12 NE1/4",
            gross_acres=70,
            planned_volume_tons=2400,
        )
        first = create_crew_assignment(
            tract_a["id"],
            crew["id"],
            window_start="2026-08-01",
            window_end="2026-09-01",
        )

        response = api.create_crew_assignment(
            tract_b["id"],
            {
                "crew_id": crew["id"],
                "move_in_miles": 40,
                "window_start": "2026-09-01",
                "window_end": "2026-09-20",
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_CREW_WINDOW_CONFLICT.value, 409)
        assert read_crew_assignment(first["id"])["status"] == "SCHEDULED"

    def test_assignment_starting_two_days_past_the_buffer_is_admitted(
        self, api, ops_headers
    ):
        """PRD §3.3: "Occupation windows are therefore treated as half-open intervals
        that include their start date and exclude their end date, and every existing
        assignment is widened by a two-day move buffer appended to its tail before the
        comparison is made."
        PRD §3.3: "An assignment is created in `SCHEDULED` status."

        Design: Difficulty/resource_temporal_overlap/crew_occupation_window_is_half_open_with_a_two_day_move_buffer
        """
        crew = create_crew()
        tract_a = create_tract(
            name="Unit A",
            legal_description="T2S R4W Sec 11 NW1/4",
            gross_acres=95,
            planned_volume_tons=3100,
        )
        tract_b = create_tract(
            name="Unit B",
            legal_description="T2S R4W Sec 12 NE1/4",
            gross_acres=70,
            planned_volume_tons=2400,
        )
        first = create_crew_assignment(
            tract_a["id"],
            crew["id"],
            window_start="2026-08-01",
            window_end="2026-09-01",
        )

        second = validate_success(
            api.create_crew_assignment(
                tract_b["id"],
                {
                    "crew_id": crew["id"],
                    "move_in_miles": 40,
                    "window_start": "2026-09-03",
                    "window_end": "2026-09-20",
                },
                ops_headers,
            ),
            201,
        )

        assert second["window_start"] == "2026-09-03"
        assert second["status"] == "SCHEDULED"
        assert second["move_in_cost_cents"] == 186_750
        assert read_crew_assignment(first["id"])["status"] == "SCHEDULED"


class TestMobilizeActivateComplete:
    def test_mobilize_is_refused_while_the_only_plan_is_still_draft(
        self, api, ops_headers
    ):
        """PRD §3.4: "Three conditions must hold: the tract is genuinely in `PLANNED`
        (otherwise `ERR_INVALID_TRACT_STATE`), at least one production plan on the
        tract has reached `APPROVED` (otherwise `ERR_PLAN_NOT_APPROVED`), and at least
        one crew assignment on the tract is still `SCHEDULED` (otherwise
        `ERR_NO_ELIGIBLE_CREW`). The plan check is evaluated before the crew check."

        Design: Difficulty/cross_entity_state_dependency/tract_mobilize_is_gated_by_the_production_plan_status_of_a_child_aggregate
        """
        scn = build_network(stage="route", approve_plan=False)

        response = api.mobilize_tract(scn["tract_id"], ops_headers)
        validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED.value, 409)

        assert read_tract(scn["tract_id"])["status"] == "PLANNED"
        assert read_production_plan(scn["tract_id"], scn["plan_id"])["status"] == "DRAFT"
        assert read_crew_assignment(scn["ca_id"])["status"] == "SCHEDULED"

    def test_approving_the_plan_unlocks_the_identical_mobilize_call(
        self, api, ops_headers
    ):
        """PRD §3.3: "A `DRAFT` plan is promoted to `APPROVED` by the manager, which is
        what unlocks mobilization of its tract; attempting to approve a plan that is no
        longer `DRAFT` is refused with `ERR_INVALID_PLAN_STATE`."
        PRD §3.4: "On success the cascade runs two hops deep: every crew assignment on
        the tract in `SCHEDULED` moves to `MOVED_IN`, and because an assignment moved
        to `MOVED_IN`, its crew moves `IDLE → MOBILIZING`."

        Design: Difficulty/cross_entity_state_dependency/tract_mobilize_is_gated_by_the_production_plan_status_of_a_child_aggregate
        """
        scn = build_network(stage="route", approve_plan=False)
        validate_error(
            api.mobilize_tract(scn["tract_id"], ops_headers),
            ApiErrorId.ERR_PLAN_NOT_APPROVED.value,
            409,
        )

        validate_success(api.approve_production_plan(scn["plan_id"], ops_headers))
        validate_success(api.mobilize_tract(scn["tract_id"], ops_headers))

        plan = read_production_plan(scn["tract_id"], scn["plan_id"])
        assert plan["status"] == "APPROVED"
        assert plan["planned_volume_tons"] == pytest.approx(4800.00, abs=0.005)
        assert read_tract(scn["tract_id"])["status"] == "MOBILIZING"
        assert read_crew_assignment(scn["ca_id"])["status"] == "MOVED_IN"
        assert read_crew(scn["crew_id"])["status"] == "MOBILIZING"

    def test_mobilize_without_any_crew_assignment_reports_no_eligible_crew(
        self, api, ops_headers
    ):
        """PRD §3.4: "Three conditions must hold: the tract is genuinely in `PLANNED`
        (otherwise `ERR_INVALID_TRACT_STATE`), at least one production plan on the
        tract has reached `APPROVED` (otherwise `ERR_PLAN_NOT_APPROVED`), and at least
        one crew assignment on the tract is still `SCHEDULED` (otherwise
        `ERR_NO_ELIGIBLE_CREW`). The plan check is evaluated before the crew check."

        Design: Corner/errors/mobilize_without_any_crew_assignment_returns_no_eligible_crew
        """
        tract = create_tract()
        plan = validate_success(
            api.create_production_plan(
                tract["id"],
                {
                    "target_tons_per_week": 600,
                    "plan_horizon_weeks": 8,
                    "expected_tract_version": tract["version"],
                },
                ops_headers,
            ),
            201,
        )
        validate_success(api.approve_production_plan(plan["id"], ops_headers))

        response = api.mobilize_tract(tract["id"], ops_headers)
        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_CREW.value, 409)

        assert read_tract(tract["id"])["status"] == "PLANNED"
        assert read_production_plan(tract["id"], plan["id"])["status"] == "APPROVED"

    def test_activating_a_tract_that_was_never_mobilised_is_refused(
        self, api, ops_headers
    ):
        """PRD §3.4: "**Activating** advances the tract from `MOBILIZING` to `ACTIVE`
        and starts production. The tract must be in `MOBILIZING`; at least one crew
        assignment on it must have reached `MOVED_IN`, or the call is refused with
        `ERR_NO_ELIGIBLE_CREW`; no shutdown order on the tract may still be `ACTIVE`;
        and the seasonal access gate of §2.10 must pass for the current logical-clock
        month, failing which the call is refused with `ERR_SEASONAL_ACCESS_CLOSED`."
        PRD §2.7: "**Own-resource state.** The status of the resource named in the path
        admits the requested transition: `ERR_INVALID_TRACT_STATE`,
        `ERR_INVALID_LOAD_STATE`, `ERR_INVALID_TICKET_STATE`,
        `ERR_INVALID_STATEMENT_STATE`, `ERR_INVALID_SHUTDOWN_ORDER_STATE`,
        `ERR_INVALID_PLAN_STATE` and `ERR_INVALID_MILL_CONTRACT_STATE` all live on this
        rung."

        Design: Corner/state_machines/activate_a_planned_tract_returns_invalid_tract_state
        """
        scn = build_network(stage="route")

        response = api.activate_tract(scn["tract_id"], ops_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_TRACT_STATE.value, 409)

        assert read_tract(scn["tract_id"])["status"] == "PLANNED"
        assert read_crew_assignment(scn["ca_id"])["status"] == "SCHEDULED"
        assert read_crew(scn["crew_id"])["status"] == "IDLE"

    def test_frozen_only_ground_cannot_be_activated_in_august(self, api, ops_headers):
        """PRD §2.10: "A `FROZEN_ONLY` tract may be worked only when the logical
        clock's calendar month is December, January or February."
        PRD §2.10: "A request that violates this gate is refused with
        `ERR_SEASONAL_ACCESS_CLOSED` (HTTP 422), and the gate is applied both when a
        tract is activated and when a load is dispatched from it."

        Design: Corner/validations/frozen_only_tract_cannot_be_activated_in_august
        """
        scn = build_network(stage="mobilized", tract={"access_class": "FROZEN_ONLY"})

        response = api.activate_tract(scn["tract_id"], ops_headers)
        validate_error(response, ApiErrorId.ERR_SEASONAL_ACCESS_CLOSED.value, 422)

        assert read_tract(scn["tract_id"])["status"] == "MOBILIZING"
        assert read_crew_assignment(scn["ca_id"])["status"] == "MOVED_IN"
        assert read_crew(scn["crew_id"])["status"] == "MOBILIZING"

    def test_approving_an_already_approved_plan_is_refused(self, api, ops_headers):
        """PRD §3.3: "A `DRAFT` plan is promoted to `APPROVED` by the manager, which is
        what unlocks mobilization of its tract; attempting to approve a plan that is no
        longer `DRAFT` is refused with `ERR_INVALID_PLAN_STATE`."

        Design: Corner/state_machines/approving_an_already_approved_production_plan_returns_invalid_plan_state
        """
        scn = build_network()

        response = api.approve_production_plan(scn["plan_id"], ops_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)

        assert read_production_plan(scn["tract_id"], scn["plan_id"])["status"] == "APPROVED"
        assert read_tract(scn["tract_id"])["status"] == "ACTIVE"

    def test_closing_out_releases_the_crews_and_supersedes_the_approved_plan(
        self, api, ops_headers
    ):
        """PRD §3.4: "**Closing out** advances the tract from `ACTIVE` to the terminal
        `COMPLETED`."
        PRD §3.4: "On success every crew assignment on the tract whose status is
        `MOVED_IN`, `WORKING` or `STOOD_DOWN` moves to the terminal `RELEASED`, and
        because each of those assignments was released, its crew returns to `IDLE`.
        Every production plan on the tract still in `APPROVED` moves to `SUPERSEDED`."

        Design: Corner/state_machines/tract_complete_releases_crews_and_supersedes_the_approved_plan
        """
        scn = build_network()

        validate_success(api.complete_tract(scn["tract_id"], ops_headers))

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "COMPLETED"
        assert tract["move_in_cost_cents"] == 186_750
        assert read_crew_assignment(scn["ca_id"])["status"] == "RELEASED"
        assert read_crew(scn["crew_id"])["status"] == "IDLE"
        assert (
            read_production_plan(scn["tract_id"], scn["plan_id"])["status"]
            == "SUPERSEDED"
        )

    def test_closing_out_is_refused_while_a_load_is_still_in_flight(
        self, api, ops_headers
    ):
        """PRD §3.4: "The tract must be `ACTIVE`, and no load off that tract may still
        be in flight — if any load on the tract has a `dispatch_status` of
        `DISPATCHED`, `IN_TRANSIT` or `AT_MILL`, the close-out is refused with
        `ERR_LOADS_STILL_OPEN`."

        Design: Corner/validations/completing_a_tract_with_an_open_load_is_rejected
        """
        scn = build_network()
        dispatch_load(scn)

        response = api.complete_tract(scn["tract_id"], ops_headers)
        validate_error(response, ApiErrorId.ERR_LOADS_STILL_OPEN.value, 409)

        assert read_tract(scn["tract_id"])["status"] == "ACTIVE"
        assert read_crew_assignment(scn["ca_id"])["status"] == "WORKING"
        assert (
            read_production_plan(scn["tract_id"], scn["plan_id"])["status"] == "APPROVED"
        )

    def test_completed_tract_refuses_a_new_shutdown_order(self, api, ops_headers):
        """PRD §3.5: "Declaring an order requires the tract to be `ACTIVE` and requires
        that the tract carry no other order still `ACTIVE` — and as §2.7 sets out, the
        duplicate-order check runs *first*, so a second declaration against an
        already-suspended tract reports `ERR_ACTIVE_SHUTDOWN_ORDER` rather than
        `ERR_INVALID_TRACT_STATE`."
        PRD §3.4: "**Closing out** advances the tract from `ACTIVE` to the terminal
        `COMPLETED`."

        Design: Corner/state_machines/completed_tract_is_terminal_and_refuses_a_new_shutdown_order
        """
        scn = build_network()
        validate_success(api.complete_tract(scn["tract_id"], ops_headers))

        response = api.create_shutdown_order(
            scn["tract_id"],
            {"reason": "FIRE_DANGER", "soil_moisture_index": 15},
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_TRACT_STATE.value, 409)

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "COMPLETED"
        assert tract["suspension_count"] == 0
        assert read_crew_assignment(scn["ca_id"])["status"] == "RELEASED"
        assert read_crew(scn["crew_id"])["status"] == "IDLE"
        assert (
            read_production_plan(scn["tract_id"], scn["plan_id"])["status"]
            == "SUPERSEDED"
        )
