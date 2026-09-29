"""Gates owned by another record, shared resources in time, and ledgers.

The first group refuses a request over the state of an entity the request never
names. The second group hands the same physical resource to two claimants. The
third group takes a quantity apart and puts it back, checking the total both
times.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_build_order_unit_conservation,
    assert_lot_piece_conservation,
    build_assembly_line,
    build_allocatable_plant,
    build_certification_family,
    build_engine_platform,
    build_order_version,
    build_product_model,
    build_released_order_plant,
    build_safety_certification,
    build_service_part,
    cancel_engine_unit,
    certify_family,
    complete_durability_run,
    create_build_order_payload,
    create_durability_test_payload,
    create_parts_request_payload,
    family_version,
    hot_test_payload,
    inspect_component_lot,
    plan_build_order,
    raise_parts_request,
    read_build_order,
    read_durability_run,
    read_engine_unit,
    read_family,
    read_lot,
    read_model,
    read_platform,
    read_service_part,
    receive_component_lot,
    record_torque,
    release_product_model,
    reset_allocations,
    run_allocations,
    schedule_durability_run,
    stage_engine_unit,
    submit_family,
    supersede_service_part,
    torque_record_payload,
    validate_error,
)

PLANT_ADMIN = TEST_USERS["plant_admin_headers"]
CERTIFICATION_ENGINEER = TEST_USERS["certification_engineer_headers"]
QUALITY_ENGINEER = TEST_USERS["quality_engineer_headers"]
PRODUCTION_PLANNER = TEST_USERS["production_planner_headers"]
CHANNEL_PARTNER = TEST_USERS["channel_partner_headers"]

FIRST_WINDOW_END = "2026-08-24T09:00:00Z"
SECOND_WINDOW_END = "2026-09-14T09:00:00Z"
INTRUDING_WINDOW_START = "2026-08-23T09:00:00Z"
INTRUDING_WINDOW_END = "2026-09-01T09:00:00Z"


def _planned_order_behind_a_draft_family():
    """A flawless order whose platform posture is the only thing still wrong."""
    family = build_certification_family()
    platform = build_engine_platform(family["id"])
    model = build_product_model(platform["id"])
    build_safety_certification(model["id"])
    release_product_model(model["id"])
    line = build_assembly_line()
    order = plan_build_order(model["id"], line["id"])
    assert order["status"] == "PLANNED"
    return family, platform, model, order


def _certify(family, platform):
    run = schedule_durability_run(family["id"], platform["id"])
    complete_durability_run(run["id"])
    submit_family(family["id"])
    return certify_family(family["id"])


def _staged_unit_quarantined_by_a_sibling_lot():
    """A clean unit dragged down by a rejection on another lot of its supplier.

    PRD §3.4 reaches "every engine unit whose `build_state` is `STAGED`", so the
    unit is deliberately left at staging while the sibling lot is inspected.
    """
    scenario = build_released_order_plant()
    staged = stage_engine_unit(scenario, "SN-0001")
    assert staged["build_state"] == "STAGED"
    assert staged["conformance_state"] == "PENDING"

    second_lot = receive_component_lot(
        scenario.suppliers["carburetor"]["id"], lot_code="CB-002", lot_quantity=200
    )
    rejected = inspect_component_lot(second_lot["id"], defects_found=2)
    assert rejected["status"] == "REJECTED"
    return scenario, staged, second_lot


def _two_active_service_parts():
    family = build_certification_family()
    platform = build_engine_platform(family["id"])
    predecessor = build_service_part(
        platform["id"], part_number="PN-CARB-KIT-1", on_hand_qty=3
    )
    successor = build_service_part(
        platform["id"], part_number="PN-CARB-KIT-2", on_hand_qty=5
    )
    assert predecessor["status"] == "ACTIVE"
    assert successor["status"] == "ACTIVE"
    return predecessor, successor


def _platform_carrying_one_scheduled_run():
    family = build_certification_family()
    platform = build_engine_platform(family["id"])
    first_run = schedule_durability_run(family["id"], platform["id"])
    return family, platform, first_run


def _line_loaded_exactly_to_capacity_for_two_weeks():
    """One order putting ceil(1000 / 2) = 500 units into each of two weeks."""
    family = build_certification_family()
    platform = build_engine_platform(family["id"])
    model = build_product_model(platform["id"])
    build_safety_certification(model["id"])
    release_product_model(model["id"])
    line = build_assembly_line(weekly_capacity_units=500, changeover_gap_weeks=1)
    order = plan_build_order(
        model["id"],
        line["id"],
        production_week="2026-09-14",
        week_span=2,
        planned_quantity=1000,
    )
    return model, line, order


class TestBuildOrderReleaseGatedByPlatformPosture:
    """The order is faultless; the platform two hops away is not."""

    def test_a_faultless_order_is_refused_over_its_platform_posture(
        self, canonical_clock
    ):
        """PRD §3.6: "Releasing a planned order to the floor is again a `ProductionPlanner` action, and it is where every upstream gate is collected."
        PRD §3.6: "And the model's platform must carry `certification_posture` `OPEN`, else `ERR_FAMILY_NOT_CERTIFIED`."
        PRD §3.3: "On success the model moves to `RELEASED` and `released_at` is stamped from the clock."

        Design: Difficulty/cross_entity_state_dependency/build_order_release_gated_by_engine_platform_posture
        """
        family, platform, model, order = _planned_order_behind_a_draft_family()
        assert read_family(family["id"])["status"] == "DRAFT"
        assert read_platform(platform["id"])["certification_posture"] == "PENDING"

        response = api_client.release_build_order(order["id"], PRODUCTION_PLANNER)

        validate_error(response, ApiErrorId.ERR_FAMILY_NOT_CERTIFIED.value)

        refused = read_build_order(order["id"])
        assert refused["status"] == "PLANNED"
        assert refused["released_at"] is None
        # The model was released while the posture was PENDING all along.
        assert read_model(model["id"])["status"] == "RELEASED"

    def test_the_identical_release_succeeds_once_the_family_is_certified(
        self, canonical_clock
    ):
        """PRD §3.2: "On success the family moves `SUBMITTED → CERTIFIED`, `certified_by_user_id` records the certifying operator, `certified_at` is stamped from the clock, and every platform of the family has its posture recomputed to `OPEN`."
        PRD §2.7: "Only a platform whose posture is `OPEN` may have production released against it."
        PRD §3.6: "On success the order moves `PLANNED → RELEASED` and `released_at` is stamped from the clock."

        Design: Difficulty/cross_entity_state_dependency/build_order_release_gated_by_engine_platform_posture
        """
        family, platform, model, order = _planned_order_behind_a_draft_family()
        first_attempt = api_client.release_build_order(order["id"], PRODUCTION_PLANNER)
        validate_error(first_attempt, ApiErrorId.ERR_FAMILY_NOT_CERTIFIED.value)

        _certify(family, platform)

        assert read_family(family["id"])["status"] == "CERTIFIED"
        assert read_platform(platform["id"])["certification_posture"] == "OPEN"

        # Nothing about the order changed between the two calls.
        second_attempt = api_client.release_build_order(order["id"], PRODUCTION_PLANNER)
        released = second_attempt.json()["data"]

        assert released["status"] == "RELEASED"
        assert released["released_at"].startswith("2026-08-03T08:00:00")
        assert read_model(model["id"])["status"] == "RELEASED"


class TestEngineUnitHotTestGatedByLotState:
    """The engine's own result is clean; the lot it came from is not."""

    def test_a_clean_unit_cannot_be_hot_tested_once_its_lot_is_quarantined(
        self, canonical_clock
    ):
        """PRD §3.4: "Finally, every engine unit whose `build_state` is `STAGED` and whose `carburetor_lot_id` or `ignition_lot_id` is one of those newly quarantined lots has its `conformance_state` moved to `QUARANTINED`, its `build_state` left exactly where it was."
        PRD §3.7: "Recording torque is admitted only when the unit's `build_state` is `STAGED`, else `ERR_UNIT_STATE_INVALID`, and only when its `conformance_state` is `PENDING` or `NONCONFORMING`; a unit whose conformance has been moved to `QUARANTINED` cannot be advanced and is refused with `ERR_UNIT_NONCONFORMING`."
        PRD §3.7: "It is admitted only when `build_state` is `ASSEMBLED`, else `ERR_UNIT_STATE_INVALID`, and only when `conformance_state` is `PENDING`, else `ERR_UNIT_NONCONFORMING` — a nonconforming unit must be reworked before it can be hot-tested, and a quarantined unit is refused outright."
        PRD §3.7: "A quarantine cascade moves only the conformance axis and leaves the build axis untouched; a rework moves the build axis backwards and resets the conformance axis; a cancellation moves the build axis to its terminal value and leaves the conformance axis exactly as it was."

        Design: Difficulty/cross_entity_state_dependency/engine_unit_hot_test_gated_by_component_lot_state
        """
        scenario, staged, second_lot = _staged_unit_quarantined_by_a_sibling_lot()

        blocked = read_engine_unit(staged["id"])
        # The cascade moved the conformance axis only.
        assert blocked["build_state"] == "STAGED"
        assert blocked["conformance_state"] == "QUARANTINED"
        assert blocked["out_of_spec_fastener_count"] is None
        assert blocked["hot_test_emission_threshold"] is None

        # The unit cannot be advanced at all: torque recording is refused on the
        # conformance axis, ...
        validate_error(
            api_client.torque_record_engine_unit(
                staged["id"], torque_record_payload(), QUALITY_ENGINEER
            ),
            ApiErrorId.ERR_UNIT_NONCONFORMING.value,
        )
        # ... and the hot test is refused on the build axis the cascade left
        # exactly where it was, so it never reaches its own conformance gate.
        validate_error(
            api_client.hot_test_engine_unit(
                staged["id"], hot_test_payload(), QUALITY_ENGINEER
            ),
            ApiErrorId.ERR_UNIT_STATE_INVALID.value,
        )

        still_blocked = read_engine_unit(staged["id"])
        assert still_blocked["build_state"] == "STAGED"
        assert still_blocked["conformance_state"] == "QUARANTINED"
        assert still_blocked["torque_readings"] is None
        assert still_blocked["measured_emission_g_per_kwh"] is None

        assert read_lot(scenario.carburetor_lot_id)["status"] == "QUARANTINED"
        assert read_lot(second_lot["id"])["status"] == "REJECTED"
        # The ignition lot is untouched, and the unit is blocked all the same.
        assert read_lot(scenario.ignition_lot_id)["status"] == "ACCEPTED"

    def test_the_quarantined_unit_can_still_be_scrapped_and_refunds_both_lots(
        self, canonical_clock
    ):
        """PRD §3.7: "A unit whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED` may be scrapped; a unit already `RELEASED` or `CANCELLED` is refused with `ERR_UNIT_STATE_INVALID`."
        PRD §3.7: "Cancellation moves `build_state` to the terminal `CANCELLED`, leaves `conformance_state` untouched, returns one piece to each of the carburetor and ignition lots by subtracting 1 from `consumed_qty` and adding 1 to `remaining_qty` on each, and subtracts 1 from the order's `staged_quantity`."

        Design: Difficulty/cross_entity_state_dependency/engine_unit_hot_test_gated_by_component_lot_state
        """
        scenario, staged, _ = _staged_unit_quarantined_by_a_sibling_lot()

        cancelled = cancel_engine_unit(staged["id"])

        assert cancelled["build_state"] == "CANCELLED"
        assert cancelled["conformance_state"] == "QUARANTINED"

        carburetor = read_lot(scenario.carburetor_lot_id)
        assert carburetor["consumed_qty"] == 0
        assert carburetor["remaining_qty"] == 800
        ignition = read_lot(scenario.ignition_lot_id)
        assert ignition["consumed_qty"] == 0
        assert ignition["remaining_qty"] == 800

        order = read_build_order(scenario.build_order_id)
        assert order["staged_quantity"] == 0
        assert order["built_quantity"] == 0


class TestPartsRequestGatedByServicePartStatus:
    """The parent's status decides whether the child may exist at all."""

    def test_a_superseded_part_refuses_a_request_it_has_the_stock_to_fill(
        self, canonical_clock
    ):
        """PRD §3.9: "The part must be `ACTIVE`; requesting a part that is `SUPERSEDED` or `OBSOLETE` is refused with `ERR_PART_STATE_INVALID`."
        PRD §3.9: "The part moves `ACTIVE → SUPERSEDED` and its `superseded_by_part_id` is set to the successor."
        PRD §3.9: "The request is minted in `BACKORDERED` and settles within the very same call when stock allows: if the part's `on_hand_qty` is at least `requested_quantity`, the request becomes `FILLED`, its `shipped_from_part_id` is set to the part it was requested from, and the part's `on_hand_qty` is reduced by `requested_quantity`."

        Design: Difficulty/cross_entity_state_dependency/parts_request_gated_by_service_part_status
        """
        predecessor, successor = _two_active_service_parts()
        first = raise_parts_request(predecessor["id"], requested_quantity=1)
        assert first["status"] == "FILLED"
        assert first["shipped_from_part_id"] == predecessor["id"]
        assert first["promised_ship_date"] == "2026-08-05"

        supersede_service_part(predecessor["id"], successor["id"])

        response = api_client.create_parts_request(
            create_parts_request_payload(predecessor["id"], requested_quantity=1),
            CHANNEL_PARTNER,
        )

        validate_error(response, ApiErrorId.ERR_PART_STATE_INVALID.value)

        # The refusal is a status decision, not a stock-out.
        stale = read_service_part(predecessor["id"])
        assert stale["status"] == "SUPERSEDED"
        assert stale["on_hand_qty"] == 2
        assert stale["filled_request_count"] == 1
        assert stale["backordered_request_count"] == 0

    def test_the_same_body_pointed_at_the_active_successor_is_accepted(
        self, canonical_clock
    ):
        """PRD §3.9: "A request that is `FILLED` or `SUBSTITUTED` gets `promised_ship_date` equal to the clock date plus the lead time its channel earns — `dealer_lead_time_days` for a `DEALER` request and `mass_retail_lead_time_days` for a `MASS_RETAIL` request, read from the part the pieces actually ship from."
        PRD §3.9: "Requests are attributed to a part by where the pieces came from: a `FILLED` or `SUBSTITUTED` request counts against its `shipped_from_part_id`, while a `BACKORDERED` request counts against its `service_part_id`."
        PRD §3.9: "Otherwise it is the served count divided by the total, multiplied by 100, rounded half up to 2 decimal places."

        Design: Difficulty/cross_entity_state_dependency/parts_request_gated_by_service_part_status
        """
        predecessor, successor = _two_active_service_parts()
        raise_parts_request(predecessor["id"], requested_quantity=1)
        supersede_service_part(predecessor["id"], successor["id"])
        refused = api_client.create_parts_request(
            create_parts_request_payload(predecessor["id"], requested_quantity=1),
            CHANNEL_PARTNER,
        )
        validate_error(refused, ApiErrorId.ERR_PART_STATE_INVALID.value)

        accepted = raise_parts_request(successor["id"], requested_quantity=2)

        assert accepted["status"] == "FILLED"
        assert accepted["shipped_from_part_id"] == successor["id"]
        assert accepted["promised_ship_date"] == "2026-08-05"

        taking_over = read_service_part(successor["id"])
        assert taking_over["status"] == "ACTIVE"
        assert taking_over["on_hand_qty"] == 3
        assert taking_over["filled_request_count"] == 1
        assert taking_over["fill_rate_pct"] == pytest.approx(100.00, abs=0.005)


class TestPlatformDurabilityWindows:
    """Two runs may touch at an instant but may not share one."""

    def test_a_window_starting_where_the_previous_one_ends_is_accepted(
        self, canonical_clock
    ):
        """PRD §3.2: "The window must not overlap any other run on the same platform whose status is `SCHEDULED` or `COMPLETED`; overlap is judged on the half-open interval, so two windows that merely touch at an endpoint — one ending exactly where the next begins — are both accepted, while any genuine overlap is refused with `ERR_PLATFORM_TEST_WINDOW_OVERLAP`."
        PRD §3.2: "A family may legitimately carry several scheduled runs at once, on different platforms or in non-overlapping windows on one platform."
        PRD §2.10: "Note that scheduling a run itself increments the family's `version` by 1, which is precisely why a client that schedules two runs back to back must re-read the family between them."

        Design: Difficulty/resource_temporal_overlap/platform_durability_windows_half_open_instants
        """
        family, platform, first_run = _platform_carrying_one_scheduled_run()
        assert first_run["scheduled_end_at"].startswith("2026-08-24T09:00:00")
        version_after_first = family_version(family["id"])

        second_run = schedule_durability_run(
            family["id"],
            platform["id"],
            scheduled_start_at=FIRST_WINDOW_END,
            scheduled_end_at=SECOND_WINDOW_END,
        )

        assert second_run["status"] == "SCHEDULED"
        assert read_durability_run(first_run["id"])["status"] == "SCHEDULED"
        assert family_version(family["id"]) == version_after_first + 1
        assert read_family(family["id"])["status"] == "DURABILITY_TESTING"

        listed = api_client.list_durability_tests(
            CERTIFICATION_ENGINEER, params={"engine_platform_id": platform["id"]}
        )
        assert listed.json()["meta"]["total_count"] == 2

    def test_a_window_intruding_by_a_day_is_refused_and_costs_no_version(
        self, canonical_clock
    ):
        """PRD §3.2: "A `CertificationEngineer` schedules one by naming the `certification_family_id` whose deterioration basis the run will establish, the `engine_platform_id` that will be occupied, a half-open window bounded by an inclusive `scheduled_start_at` and an exclusive `scheduled_end_at` strictly after it, the `target_hours` the run is planned to accumulate (between 1 and 2000), and the `initial_emission_g_per_kwh` measured at run start on a green engine, above zero at 2 decimal places."
        PRD §3.2: "Three things then happen to the surrounding graph: the family advances to `DURABILITY_TESTING` (from `DRAFT` or from `AUDIT_HOLD`; a family already in `DURABILITY_TESTING` stays there and simply carries an additional scheduled run), the family's `version` increments by 1, and every platform of the family has its `certification_posture` recomputed, landing on `RESTRICTED`."

        Design: Difficulty/resource_temporal_overlap/platform_durability_windows_half_open_instants
        """
        family, platform, _ = _platform_carrying_one_scheduled_run()
        schedule_durability_run(
            family["id"],
            platform["id"],
            scheduled_start_at=FIRST_WINDOW_END,
            scheduled_end_at=SECOND_WINDOW_END,
        )
        version_before = family_version(family["id"])

        # A day inside the first window and eight days inside the second.
        response = api_client.create_durability_test(
            create_durability_test_payload(
                family["id"],
                platform["id"],
                version_before,
                scheduled_start_at=INTRUDING_WINDOW_START,
                scheduled_end_at=INTRUDING_WINDOW_END,
            ),
            CERTIFICATION_ENGINEER,
        )

        validate_error(response, ApiErrorId.ERR_PLATFORM_TEST_WINDOW_OVERLAP.value)

        assert family_version(family["id"]) == version_before
        assert read_family(family["id"])["status"] == "DURABILITY_TESTING"
        assert read_platform(platform["id"])["certification_posture"] == "RESTRICTED"

        listed = api_client.list_durability_tests(
            CERTIFICATION_ENGINEER, params={"engine_platform_id": platform["id"]}
        )
        assert listed.json()["meta"]["total_count"] == 2


class TestAssemblyLineWeeklyCapacity:
    """Weeks are shared, not owned: the loads add up week by week."""

    def test_two_more_units_in_a_week_already_at_the_cap_are_refused(
        self, canonical_clock
    ):
        """PRD §3.6: "An order spreads its `planned_quantity` evenly across its span, contributing to each occupied week a load of `planned_quantity` divided by `week_span`, rounded **up** to a whole unit."
        PRD §3.6: "For every week this order would occupy, the sum of that per-week load over all orders on the same line and in the same week whose status is `PLANNED`, `RELEASED` or `IN_PRODUCTION` — this order included — must be at most the line's `weekly_capacity_units`."
        PRD §3.6: "Orders of the same product line never conflict on changeover, however tightly packed."

        Design: Difficulty/resource_temporal_overlap/assembly_line_week_capacity_inclusive_week_sets
        """
        model, line, first_order = _line_loaded_exactly_to_capacity_for_two_weeks()
        assert first_order["status"] == "PLANNED"
        assert first_order["week_span"] == 2
        assert first_order["planned_quantity"] == 1000

        # Week 2026-09-21 already carries 500 of the line's 500 units.
        response = api_client.create_build_order(
            create_build_order_payload(
                model["id"],
                line["id"],
                production_week="2026-09-21",
                week_span=1,
                planned_quantity=2,
            ),
            PRODUCTION_PLANNER,
        )

        validate_error(response, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value)
        assert read_build_order(first_order["id"])["status"] == "PLANNED"

    def test_a_full_week_of_units_lands_in_an_unoccupied_week(self, canonical_clock):
        """PRD §3.6: "A breach in even one occupied week refuses the whole plan with `ERR_LINE_CAPACITY_EXCEEDED`."
        PRD §3.6: "A successful plan opens the order in `status` `PLANNED` with `allocation_status` `UNALLOCATED`, all of `staged_quantity`, `built_quantity`, `allocated_dealer_units`, `allocated_mass_retail_units` and `unallocated_units` at 0, and `allocation_run_at`, `held_reason`, `status_before_hold` and `released_at` empty."
        PRD §3.6: "Capacity is checked last, and it is checked per week rather than in aggregate."

        Design: Difficulty/resource_temporal_overlap/assembly_line_week_capacity_inclusive_week_sets
        """
        model, line, first_order = _line_loaded_exactly_to_capacity_for_two_weeks()
        refused = api_client.create_build_order(
            create_build_order_payload(
                model["id"],
                line["id"],
                production_week="2026-09-21",
                week_span=1,
                planned_quantity=2,
            ),
            PRODUCTION_PLANNER,
        )
        validate_error(refused, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value)

        third_order = plan_build_order(
            model["id"],
            line["id"],
            production_week="2026-09-28",
            week_span=1,
            planned_quantity=500,
        )

        assert third_order["status"] == "PLANNED"
        assert third_order["allocation_status"] == "UNALLOCATED"
        assert third_order["staged_quantity"] == 0
        assert third_order["built_quantity"] == 0
        assert third_order["released_at"] is None

        listed = api_client.list_build_orders(
            PRODUCTION_PLANNER, params={"assembly_line_id": line["id"]}
        )
        assert listed.json()["meta"]["total_count"] == 2


class TestComponentPieceConservation:
    """Pieces drawn from a lot come back exactly once."""

    def test_staging_then_cancelling_leaves_every_lot_ledger_balanced(
        self, canonical_clock
    ):
        """PRD §2.11: "On a component lot, the pieces released to the line are conserved: `accepted_qty` always equals `consumed_qty` plus `remaining_qty`."
        PRD §2.11: "Cancelling that unit reverses exactly that charge, subtracting 1 from `consumed_qty` and adding 1 back to `remaining_qty` on each of the same two lots."
        PRD §3.7: "Each of the two consumed lots has 1 added to `consumed_qty` and 1 subtracted from `remaining_qty`, per §2.11 — note that the bound machining run and its casting lot are not charged in this way; only the carburetor and ignition lots are consumed piecewise."

        Design: Difficulty/compensating_invariant/component_lot_piece_conservation_across_stage_and_cancel
        """
        scenario = build_released_order_plant()
        staged = stage_engine_unit(scenario, "SN-0001")

        for lot_id in (scenario.carburetor_lot_id, scenario.ignition_lot_id):
            charged = read_lot(lot_id)
            assert charged["accepted_qty"] == 800
            assert charged["consumed_qty"] == 1
            assert charged["remaining_qty"] == 799
            assert_lot_piece_conservation(charged)

        cancel_engine_unit(staged["id"])

        for lot_id in (scenario.carburetor_lot_id, scenario.ignition_lot_id):
            refunded = read_lot(lot_id)
            assert refunded["accepted_qty"] == 800
            assert refunded["consumed_qty"] == 0
            assert refunded["remaining_qty"] == 800
            assert_lot_piece_conservation(refunded)

        # Casting pieces are drawn by the machining run, never by the engine.
        casting = read_lot(scenario.casting_lot_id)
        assert casting["consumed_qty"] == 0
        assert_lot_piece_conservation(casting)

    def test_the_scrapped_unit_leaves_the_order_counters_empty_but_in_production(
        self, canonical_clock
    ):
        """PRD §3.7: "Cancellation is the compensating action for staging."
        PRD §3.7: "The order's `staged_quantity` rises by 1, and the very first unit staged against a `RELEASED` order advances that order `RELEASED → IN_PRODUCTION`."
        PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."

        Design: Difficulty/compensating_invariant/component_lot_piece_conservation_across_stage_and_cancel
        """
        scenario = build_released_order_plant()
        staged = stage_engine_unit(scenario, "SN-0001")
        assert read_build_order(scenario.build_order_id)["status"] == "IN_PRODUCTION"

        cancelled = cancel_engine_unit(staged["id"])

        assert cancelled["build_state"] == "CANCELLED"
        assert cancelled["conformance_state"] == "PENDING"
        assert cancelled["rework_count"] == 0

        order = read_build_order(scenario.build_order_id)
        assert order["staged_quantity"] == 0
        assert order["built_quantity"] == 0
        # The order does not fall back to RELEASED.
        assert order["status"] == "IN_PRODUCTION"


class TestBuildOrderUnitConservation:
    """The buckets move; the released population does not."""

    def test_the_reset_collapses_the_split_back_into_the_slack_bucket(
        self, canonical_clock
    ):
        """PRD §2.11: "On a build order, the released population is conserved across channels: `built_quantity` always equals `allocated_dealer_units` plus `allocated_mass_retail_units` plus `unallocated_units`."
        PRD §3.8: "A compensating reset is also available to the planner: it sets `allocated_dealer_units` and `allocated_mass_retail_units` to 0, sets `unallocated_units` to the full `built_quantity`, returns `allocation_status` to `UNALLOCATED` and clears `allocation_run_at`, all without touching a single engine and while preserving the same invariant."

        Design: Difficulty/compensating_invariant/build_order_unit_conservation_across_allocation_and_reset
        """
        scenario = build_allocatable_plant(released_units=3)
        allocated = run_allocations(
            scenario.build_order_id, expected_version=build_order_version(
                scenario.build_order_id
            )
        )
        assert allocated["built_quantity"] == 3
        assert allocated["allocated_dealer_units"] == 2
        assert allocated["allocated_mass_retail_units"] == 1
        assert allocated["unallocated_units"] == 0
        assert allocated["allocation_status"] == "ALLOCATED"
        assert_build_order_unit_conservation(allocated)

        reset = reset_allocations(scenario.build_order_id)

        assert reset["built_quantity"] == 3
        assert reset["allocated_dealer_units"] == 0
        assert reset["allocated_mass_retail_units"] == 0
        assert reset["unallocated_units"] == 3
        assert reset["allocation_status"] == "UNALLOCATED"
        assert reset["allocation_run_at"] is None
        assert_build_order_unit_conservation(reset)

    def test_the_reset_moves_no_engine_and_leaves_the_order_in_production(
        self, canonical_clock
    ):
        """PRD §3.8: "The allocation pool is exactly the order's `built_quantity` — units whose `build_state` is `RELEASED`."
        PRD §2.11: "`unallocated_units` is the slack that absorbs whatever the channel caps refuse to take, and the compensating reset described in §3.8 restores the whole population to that slack bucket without touching a single engine."
        PRD §3.7: "When the release brings `built_quantity` up to the order's `planned_quantity`, the order transitions `IN_PRODUCTION → COMPLETED` in the same request; a `COMPLETED` order accepts no further units, though allocation runs remain permitted on it."

        Design: Difficulty/compensating_invariant/build_order_unit_conservation_across_allocation_and_reset
        """
        scenario = build_allocatable_plant(released_units=3)
        run_allocations(scenario.build_order_id)

        reset_allocations(scenario.build_order_id)

        for unit in scenario.units:
            assert read_engine_unit(unit["id"])["build_state"] == "RELEASED"

        order = read_build_order(scenario.build_order_id)
        assert order["status"] == "IN_PRODUCTION"
        assert order["planned_quantity"] == 6
        assert order["built_quantity"] == 3
