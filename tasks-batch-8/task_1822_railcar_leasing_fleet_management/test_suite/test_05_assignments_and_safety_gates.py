"""Assignment placement: initial state and pins, state legality, the three
fleet-safety gates, inclusive-window overlap, and the turnaround buffer."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_repair,
    create_assignment,
    create_lease_assignment_payload,
    create_railcar,
    create_repair,
    create_lessee,
    create_active_lease,
    create_tariff_pair,
    deliver_assignment,
    get_assignment,
    get_railcar,
    get_success_data,
    make_lessee_rep_headers,
    return_assignment,
    set_clock,
    setup_active_lease_scenario,
    setup_provisional_statement,
    submit_mileage_report,
    validate_error,
    validate_report,
    validate_success,
    generate_statements,
    get_statement,
    get_lessee_balance,
    certify_cleaning_record,
    create_cleaning,
)

LEASE_ADMIN = TEST_USERS["lease_admin_headers"]
PLANNER = TEST_USERS["fleet_planner_headers"]
MAINT = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestAssignmentCreation:
    def test_assignment_created_in_initial_state_scheduled(self, api):
        """PRD §3.4: "A created assignment holds status `SCHEDULED`, with
        `actual_on_lease_date`, `actual_off_lease_date`, `billable_days`,
        `final_rent_cents`, `termination_fee_cents`, and
        `cancellation_reason` all null."
        PRD §3.4: "When coverage exists, the two rates effective at
        `scheduled_start` are snapshotted onto the assignment as
        `pinned_car_hire_daily_cents` and `pinned_mileage_credit_cents` —
        these pinned values, not the live grid, later price the final
        settlement variant."

        Design: Corner/state_machines/assignment_created_in_initial_state_scheduled
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1201", window_start="2026-09-01",
            window_end="2026-09-30",
        )
        assignment = scenario["assignment"]
        assert assignment["status"] == "SCHEDULED"
        assert assignment["actual_on_lease_date"] is None
        assert assignment["actual_off_lease_date"] is None
        assert assignment["cancellation_reason"] is None
        assert assignment["pinned_car_hire_daily_cents"] == 9000
        assert assignment["pinned_mileage_credit_cents"] == 55

    def test_mutation_visible_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.4: "Delivery moves the assignment `SCHEDULED → ON_LEASE`,
        stamps `actual_on_lease_date` with the current logical date, and moves
        the railcar to `ON_LEASE`; delivery requires the car to still be
        `AVAILABLE` (`ERR_RAILCAR_NOT_AVAILABLE`, 409)."
        PRD §2.5: "Before any client sets it, the logical clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Corner/consistency_model/mutation_visible_in_same_response
        """
        scenario = setup_active_lease_scenario(car_mark="GATX1901")
        delivered = validate_success(
            api.deliver_assignment(scenario["assignment"]["id"], PLANNER)
        )
        assert delivered["status"] == "ON_LEASE"
        assert delivered["actual_on_lease_date"] == "2026-08-01"
        car = get_railcar(scenario["railcar"]["id"])
        assert car["status"] == "ON_LEASE"

    def test_deliver_from_returned_rejected_invalid_state(self, api):
        """PRD §2.6: "6. **State-machine legality** — the target entity is in
        a state from which the requested transition exists; failure yields
        `ERR_INVALID_STATE` (409)."
        PRD §3.4: "Delivery moves the assignment `SCHEDULED → ON_LEASE`,
        stamps `actual_on_lease_date` with the current logical date, and
        moves the railcar to `ON_LEASE`" — no deliver transition exists from
        `RETURNED`.

        Design: Corner/state_machines/deliver_from_returned_rejected_invalid_state
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1202", window_start="2026-08-01",
            window_end="2026-08-31", deliver=True,
        )
        return_assignment(scenario["assignment"]["id"])
        resp = api.deliver_assignment(scenario["assignment"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_assignment(scenario["assignment"]["id"])
        assert after["status"] == "RETURNED"


class TestAgeBoundary:
    def test_car_age_49_is_assignable(self, api):
        """PRD §2.10: "First, age: a car whose `car_age_years` — the calendar
        year of the logical clock minus its `built_year` — is 50 or older is
        rejected with `ERR_AGE_LIMIT_EXCEEDED`; the limit triggers at exactly
        50."

        Design: Difficulty/boundary_precision_check/assignment_age_boundary_49_vs_50
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX9101", built_year=1977, with_assignment=False,
        )
        # 2026 - 1977 = 49: below the 50-year limit.
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=scenario["lease"]["id"],
                railcar_id=scenario["railcar"]["id"],
                planned_commodity="GRAIN",
                scheduled_start="2026-08-05",
                scheduled_end="2026-08-15",
            ),
            PLANNER,
        )
        assignment = validate_success(resp, 201)
        assert assignment["status"] == "SCHEDULED"

    def test_car_age_50_is_rejected(self, api):
        """PRD §2.10: "First, age: a car whose `car_age_years` — the calendar
        year of the logical clock minus its `built_year` — is 50 or older is
        rejected with `ERR_AGE_LIMIT_EXCEEDED`; the limit triggers at exactly
        50."

        Design: Difficulty/boundary_precision_check/assignment_age_boundary_49_vs_50
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX9102", built_year=1976, with_assignment=False,
        )
        # 2026 - 1976 = 50: the boundary value itself fails because the rule
        # is >= 50, not > 50.
        car = get_railcar(scenario["railcar"]["id"])
        assert car["car_age_years"] == 50
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=scenario["lease"]["id"],
                railcar_id=scenario["railcar"]["id"],
                planned_commodity="GRAIN",
                scheduled_start="2026-08-05",
                scheduled_end="2026-08-15",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_AGE_LIMIT_EXCEEDED, 422)


class TestSafetyErrorBeatsTemporal:
    def _setup_aged_car_with_overlap(self, api):
        """At clock 2025-06-01 the car (built 1976) is 49 and takes a first
        assignment; at clock 2026-08-01 it is 50 and the new window also
        overlaps the first."""
        set_clock("2025-06-01T00:00:00Z")
        create_tariff_pair("COVERED_HOPPER", 9000, 55,
                           "2025-01-01", "2027-01-01")
        lessee = create_lessee(company_name="L")
        car = create_railcar(car_mark="GATX9002", built_year=1976)
        lease = create_active_lease(
            lessee["id"], start_date="2025-06-01", end_date="2027-05-31"
        )
        first = create_assignment(
            lease["id"], car["id"], planned_commodity="GRAIN",
            scheduled_start="2026-08-10", scheduled_end="2026-08-20",
        )
        set_clock("2026-08-01T00:00:00Z")
        return {"lessee": lessee, "car": car, "lease": lease, "first": first}

    def test_age_limit_fires_before_window_overlap(self, api):
        """PRD §2.6: "Within assignment creation, a car that is both too old
        and non-compliant surfaces `ERR_AGE_LIMIT_EXCEEDED` (priority 8)
        before tariff coverage (priority 9) is even consulted; and both
        surface before a date-range problem (priority 10), a duplicate
        (priority 11), or a credit-limit breach (priority 12)."
        PRD §2.10: "First, age: a car whose `car_age_years` — the calendar
        year of the logical clock minus its `built_year` — is 50 or older is
        rejected with `ERR_AGE_LIMIT_EXCEEDED`; the limit triggers at exactly
        50."

        Design: Difficulty/priority_pair_validation_conflict/assignment_safety_error_beats_temporal_error
        """
        env = self._setup_aged_car_with_overlap(api)
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=env["lease"]["id"],
                railcar_id=env["car"]["id"],
                planned_commodity="GRAIN",
                scheduled_start="2026-08-15",
                scheduled_end="2026-08-25",
            ),
            PLANNER,
        )
        # The window overlaps the first assignment (temporal, lower priority),
        # but the age gate must win.
        validate_error(resp, ApiErrorId.ERR_AGE_LIMIT_EXCEEDED, 422)

    def test_age_fifty_boundary_and_first_assignment_untouched(self, api):
        """PRD §2.10: "First, age: a car whose `car_age_years` — the calendar
        year of the logical clock minus its `built_year` — is 50 or older is
        rejected with `ERR_AGE_LIMIT_EXCEEDED`; the limit triggers at exactly
        50."

        Design: Difficulty/priority_pair_validation_conflict/assignment_safety_error_beats_temporal_error
        """
        env = self._setup_aged_car_with_overlap(api)
        car = get_railcar(env["car"]["id"])
        assert car["car_age_years"] == 50, (
            "2026 - 1976 = 50; the trigger is >=, so exactly 50 fails"
        )
        first = get_assignment(env["first"]["id"])
        assert first["status"] == "SCHEDULED", (
            "The rejected second creation leaves the first assignment in place"
        )


class TestInShopCarBlocked:
    def _setup_in_shop_car(self, api):
        car = create_railcar(car_mark="GATX9201", car_type="BOX", built_year=2018)
        repair = create_repair(car["id"], defect_cause="PRE_EXISTING",
                               estimate_cents=80000, requires_shop=True,
                               defect_description="floor")
        approve_repair(repair["id"], 80000)
        get_success_data(api.start_repair_work(repair["id"], MAINT))
        create_tariff_pair("BOX", 9000, 55)
        lessee = create_lessee(company_name="L")
        lease = create_active_lease(lessee["id"])
        return {"car": car, "repair": repair, "lease": lease}

    def test_assignment_on_in_shop_car_rejected(self, api):
        """PRD §2.7: "Creating an assignment requires the lease to be
        `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`), the lessee to be `ACTIVE`
        (`ERR_LESSEE_NOT_ACTIVE`), and the railcar to be `AVAILABLE`
        (`ERR_RAILCAR_NOT_AVAILABLE`)."
        PRD §3.2: "From either `AVAILABLE` or `ON_LEASE`, starting work on an
        approved shop repair moves the car to `IN_SHOP`".

        Design: Difficulty/cross_entity_state_dependency/railcar_in_shop_blocks_assignment
        """
        env = self._setup_in_shop_car(api)
        car = get_railcar(env["car"]["id"])
        assert car["status"] == "IN_SHOP"
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=env["lease"]["id"],
                railcar_id=env["car"]["id"],
                planned_commodity="LUMBER",
                scheduled_start="2026-08-10",
                scheduled_end="2026-09-10",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_RAILCAR_NOT_AVAILABLE, 409)

    def test_rejected_assignment_leaves_shop_state_untouched(self, api):
        """PRD §3.2: "When a shop repair completes, the count decrements by
        one, and only when it reaches zero does the car leave the shop —
        restored to whatever `status_before_shop` held (`AVAILABLE` or
        `ON_LEASE`), with `status_before_shop` cleared to null."

        Design: Difficulty/cross_entity_state_dependency/railcar_in_shop_blocks_assignment
        """
        env = self._setup_in_shop_car(api)
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=env["lease"]["id"],
                railcar_id=env["car"]["id"],
                planned_commodity="LUMBER",
                scheduled_start="2026-08-10",
                scheduled_end="2026-09-10",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_RAILCAR_NOT_AVAILABLE, 409)
        car = get_railcar(env["car"]["id"])
        assert car["status"] == "IN_SHOP"
        assert car["open_shop_repair_count"] == 1


class TestInclusiveOverlapAndBuffer:
    def _setup_returned_grain_car(self, api):
        """Car returned 2026-08-15 from a GRAIN assignment, followed by a
        CERTIFIED GRAIN->COAL cleaning."""
        scenario = setup_active_lease_scenario(
            car_mark="GATX9301", window_start="2026-08-05",
            window_end="2026-08-15",
        )
        set_clock("2026-08-05T00:00:00Z")
        deliver_assignment(scenario["assignment"]["id"])
        set_clock("2026-08-15T00:00:00Z")
        return_assignment(scenario["assignment"]["id"])
        # The cleaning must be created strictly after the car's last return
        # (§2.10) to count as the commodity bridge.
        set_clock("2026-08-16T00:00:00Z")
        cleaning = create_cleaning(
            scenario["railcar"]["id"], prior_commodity="GRAIN",
            next_commodity="COAL", planned_date="2026-08-16",
        )
        certify_cleaning_record(cleaning["id"], grade="WASH", cost_cents=50000,
                                certificate_ref="CLN-1")
        return scenario

    def test_window_starting_on_prior_end_date_overlaps(self, api):
        """PRD §3.4: "The window must not overlap any other `SCHEDULED`,
        `ON_LEASE`, or `RETURNED` assignment on the same railcar, comparing
        inclusive windows (`ERR_ASSIGNMENT_OVERLAP`, 422)."

        Design: Difficulty/resource_temporal_overlap/assignment_inclusive_overlap_and_turnaround_buffer
        """
        scenario = self._setup_returned_grain_car(api)
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=scenario["lease"]["id"],
                railcar_id=scenario["railcar"]["id"],
                planned_commodity="GRAIN",
                scheduled_start="2026-08-15",
                scheduled_end="2026-08-25",
            ),
            PLANNER,
        )
        # Inclusive ends: 08-15 belongs to both windows.
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP, 422)

    def test_commodity_change_enforces_three_day_buffer(self, api):
        """PRD §3.4: "And on a commodity change — `planned_commodity`
        differing from the car's `last_commodity` when the latter is not
        `NONE` — a turnaround buffer applies on top of the cleaning
        requirement: `scheduled_start` must be at least 3 days after the
        previous assignment's `scheduled_end`, even when the cleaning is
        already certified; violating the buffer fails with
        `ERR_CLEANING_BUFFER_VIOLATION` (422)."

        Design: Difficulty/resource_temporal_overlap/assignment_inclusive_overlap_and_turnaround_buffer
        """
        scenario = self._setup_returned_grain_car(api)
        # Certified cleaning bridges GRAIN -> COAL, but 08-16 is less than
        # 3 days after the previous scheduled_end 08-15.
        too_early = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=scenario["lease"]["id"],
                railcar_id=scenario["railcar"]["id"],
                planned_commodity="COAL",
                scheduled_start="2026-08-16",
                scheduled_end="2026-08-25",
            ),
            PLANNER,
        )
        validate_error(too_early, ApiErrorId.ERR_CLEANING_BUFFER_VIOLATION, 422)

        # 2026-08-18 == scheduled_end 2026-08-15 + 3 days: the buffer is met.
        ok = validate_success(
            api.create_lease_assignment(
                create_lease_assignment_payload(
                    lease_id=scenario["lease"]["id"],
                    railcar_id=scenario["railcar"]["id"],
                    planned_commodity="COAL",
                    scheduled_start="2026-08-18",
                    scheduled_end="2026-08-25",
                ),
                PLANNER,
            ),
            201,
        )
        assert ok["status"] == "SCHEDULED"

    def test_commodity_change_without_certified_cleaning_rejected(self, api):
        """PRD §2.10: "Third, commodity compatibility: if the assignment's
        `planned_commodity` differs from the car's `last_commodity` and that
        last commodity is not `NONE`, the assignment is rejected with
        `ERR_COMMODITY_INCOMPATIBLE` unless a `CERTIFIED` cleaning record for
        the car, created after the car's last return, bridges the two
        commodities."
        PRD §3.4: "Return moves the assignment `ON_LEASE → RETURNED`, stamps
        `actual_off_lease_date`, moves the railcar back to `AVAILABLE`, and
        copies `planned_commodity` onto the car's `last_commodity`".

        Design: Corner/validations/commodity_change_without_certified_cleaning_rejected
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1407", window_start="2026-08-01",
            window_end="2026-08-15", deliver=True,
        )
        set_clock("2026-08-15T00:00:00Z")
        return_assignment(scenario["assignment"]["id"])
        car = get_railcar(scenario["railcar"]["id"])
        assert car["last_commodity"] == "GRAIN", (
            "The return copies planned_commodity onto last_commodity"
        )
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=scenario["lease"]["id"],
                railcar_id=scenario["railcar"]["id"],
                planned_commodity="COAL",
                scheduled_start="2026-09-01",
                scheduled_end="2026-09-30",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_COMMODITY_INCOMPATIBLE, 422)


class TestSuspendedLesseeGate:
    def test_suspended_lessee_state_error_beats_fiscal_error(self, api):
        """PRD §3.1: "if the balance now exceeds the lessee's
        `credit_limit_cents`, the lessee is automatically transitioned from
        `ACTIVE` to `SUSPENDED`, and while suspended, new lease submissions
        and new assignment creations for that lessee are blocked (surfacing
        `ERR_LESSEE_NOT_ACTIVE` per §2.7)."
        PRD §2.6: "When several validation rules could reject the same
        request, the server evaluates them in a fixed priority order, and the
        first failing check determines the error returned — lower priority
        number wins on dual failure." — cross-entity state gates (7) precede
        fiscal gates (12).

        Design: Corner/validations/suspended_lessee_blocked_state_beats_fiscal
        """
        scenario = setup_provisional_statement(
            car_mark="GATX1403", credit_limit_cents=200000,
            credit_tier="TIER_C",
        )
        lessee = scenario["lessee"]
        # Finalize the 224000 statement: balance 224000 > limit 200000.
        get_success_data(api.finalize_statement(scenario["statement"]["id"],
                                                BILLING))
        after = get_success_data(api.get_lessee(lessee["id"], BILLING))
        assert after["status"] == "SUSPENDED"
        assert after["outstanding_balance_cents"] == 224000

        car2 = create_railcar(car_mark="GATX1402", built_year=2016)
        # The suspended-lessee state gate must win over the credit-limit
        # fiscal gate that the same balance also trips.
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=scenario["lease"]["id"],
                railcar_id=car2["id"],
                planned_commodity="GRAIN",
                scheduled_start="2026-09-01",
                scheduled_end="2026-09-30",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LESSEE_NOT_ACTIVE, 409)
