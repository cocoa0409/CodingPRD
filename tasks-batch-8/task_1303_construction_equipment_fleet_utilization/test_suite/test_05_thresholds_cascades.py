"""Service thresholds, cascades, priority pairs, temporal overlap, OCC, and
compensating invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    assess_damage,
    close_assignment,
    complete_work_order_as_mechanic,
    confirm_damage,
    dispatch_work_order,
    dispute_damage,
    get_success_data,
    make_active_assignment,
    make_class,
    make_damage_report,
    make_equipment,
    make_fleet_bundle,
    make_lowboy,
    make_mechanic,
    make_project,
    make_reading,
    make_reserved_assignment,
    make_transport_job,
    make_work_order,
    reassess_damage,
    run_repair_to_completion,
    set_clock,
    start_work_order_as_mechanic,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, make_mechanic_headers

_ADMIN = TEST_USERS["fleet_admin_headers"]
_DISP = TEST_USERS["dispatcher_headers"]
_PM = TEST_USERS["project_manager_headers"]


# ============================================================================
# Difficulty / non_linear_state_machine
# ============================================================================

class TestParallelEquipmentDimensions:
    def test_maintenance_flips_alone_under_on_rent(self, api):
        """PRD section 2.5: "Every equipment unit's condition is described by
        two parallel and independent status dimensions, not one. ... a unit
        can legitimately be `ON_RENT` with `SERVICE_DUE` (its interval lapsed
        mid-job)". PRD section 3.3: "If `hours_since_service_milli` has
        reached the class threshold ... while the unit is `SERVICE_OK`, the
        unit flips `SERVICE_OK` → `SERVICE_DUE` and the system auto-creates a
        `PREVENTIVE` work order in `OPEN` with `trigger_hours_milli` set to
        the current meter reading".

        Design: Difficulty/non_linear_state_machine/equipment_parallel_availability_and_maintenance_evolve_independently
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-370", service_interval_hours=50,
                         daily_rate_cents=10000)
        project = make_project(project_code="PRJ-G")
        equip = make_equipment(cls["id"], unit_tag="UNIT-7")
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-14")

        for d in ("2026-08-03", "2026-08-04", "2026-08-05"):
            make_reading(equip["id"], recorded_date=d,
                         engine_hours_delta_milli=24000, fuel_used_milliliters=12000)

        mid = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert mid["availability_status"] == "ON_RENT"
        assert mid["maintenance_status"] == "SERVICE_DUE"

        wos, _ = validate_paginated(api.list_equipment_work_orders(equip["id"], _ADMIN))
        assert len(wos) == 1
        assert wos[0]["kind"] == "PREVENTIVE"
        assert wos[0]["status"] == "OPEN"

    def test_markdown_moves_availability_alone(self, api):
        """PRD section 3.4: "Marking down an `ON_RENT` unit moves it `ON_RENT`
        → `DOWN` and suspends every `ACTIVE` assignment on it (`ACTIVE` →
        `SUSPENDED`); suspension pauses the billing window". Combined with
        the parallel dimension rule of section 2.5, after mark-down on a
        SERVICE_DUE unit the combined state is (DOWN, SERVICE_DUE).

        Design: Difficulty/non_linear_state_machine/equipment_parallel_availability_and_maintenance_evolve_independently
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-370", service_interval_hours=50,
                         daily_rate_cents=10000)
        project = make_project(project_code="PRJ-G")
        equip = make_equipment(cls["id"], unit_tag="UNIT-7")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-14")

        for d in ("2026-08-03", "2026-08-04", "2026-08-05"):
            make_reading(equip["id"], recorded_date=d,
                         engine_hours_delta_milli=24000, fuel_used_milliliters=12000)

        validate_success(api.mark_down_equipment(equip["id"], _ADMIN))
        end = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert end["availability_status"] == "DOWN"
        assert end["maintenance_status"] == "SERVICE_DUE"
        asg_after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert asg_after["status"] == "SUSPENDED"


class TestDamageCyclicLoop:
    def _setup_disputed_report(self, api):
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        d = make_damage_report(equip["id"], project["id"],
                               description="cracked panel",
                               line_items=[{"description": "panel", "amount_cents": 10000}])
        assess_damage(d["id"])
        return d, project

    def test_two_full_dispute_reassess_rounds_succeed(self, api):
        """PRD section 3.8: "A `FleetAdmin` answers a dispute by reassessing
        with replacement `line_items`: the lines are replaced wholesale, the
        charge is recomputed from scratch under the same per-line rule, the
        report's `version` increments for each reassessment round, and the
        report returns to `ASSESSED` — the dispute-and-reassess loop is
        unbounded."

        Design: Difficulty/non_linear_state_machine/damage_report_cyclic_dispute_reassess_loop_multiple_rounds
        """
        d, project = self._setup_disputed_report(api)
        # Round 1
        disp1 = dispute_damage(d["id"], "panel was pre-cracked")
        r1 = reassess_damage(d["id"], [{"description": "panel (used part)", "amount_cents": 7000}],
                             disp1["version"])
        assert r1["status"] == "ASSESSED"
        assert r1["assessed_charge_cents"] == 7000
        # Round 2
        disp2 = dispute_damage(d["id"], "still too high")
        r2 = reassess_damage(
            d["id"],
            [{"description": "panel (used part)", "amount_cents": 4000},
             {"description": "paint", "amount_cents": 1000}],
            disp2["version"],
        )
        assert r2["status"] == "ASSESSED"
        assert r2["assessed_charge_cents"] == 5000

    def test_version_increments_each_mutation(self, api):
        """PRD section 2.4: "`version` (integer): a system-managed counter
        that increments by exactly 1 on every mutation of the resource." For
        a DamageReport: create(1) -> assess(2) -> dispute(3) -> reassess(4)
        -> dispute(5) -> reassess(6). PRD section 2.9: "Voided readings never
        touch the ledger, and neither do assessed-but-unconfirmed damage
        charges".

        Design: Difficulty/non_linear_state_machine/damage_report_cyclic_dispute_reassess_loop_multiple_rounds
        """
        d, project = self._setup_disputed_report(api)
        disp1 = dispute_damage(d["id"], "panel was pre-cracked")
        r1 = reassess_damage(d["id"], [{"description": "panel (used part)", "amount_cents": 7000}],
                             disp1["version"])
        disp2 = dispute_damage(d["id"], "still too high")
        r2 = reassess_damage(
            d["id"],
            [{"description": "panel (used part)", "amount_cents": 4000},
             {"description": "paint", "amount_cents": 1000}],
            disp2["version"],
        )
        final = validate_success(api.get_damage_report(d["id"], _ADMIN))
        assert final["version"] == 6
        assert final["status"] == "ASSESSED"
        proj = validate_success(api.get_project(project["id"], _ADMIN))
        assert proj["billed_total_cents"] == 0


# ============================================================================
# Difficulty / transitive_cascade
# ============================================================================

class TestRepairCascade:
    def _setup_suspended_via_down(self, api):
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-390", service_interval_hours=10000,
                         daily_rate_cents=10000)
        project = make_project(project_code="PRJ-I")
        equip = make_equipment(cls["id"], unit_tag="UNIT-9")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        set_clock("2026-08-04T12:00:00Z")
        validate_success(api.mark_down_equipment(equip["id"], _ADMIN))
        mech = make_mechanic(project["id"], mechanic_code="MECH-9", name="Mac Nine")
        wo = make_work_order(equip["id"], kind="REPAIR", notes="track tension")
        dispatch_work_order(wo["id"], mech["id"])
        set_clock("2026-08-06T09:00:00Z")
        start_work_order_as_mechanic(wo["id"], mech["id"])
        return cls, project, equip, asg, mech, wo

    def test_repair_completion_cascade_links(self, api):
        """PRD section 3.4: "When the completed order is a `REPAIR` and the
        unit's availability is `DOWN`, the repair cascade also fires: the
        unit's availability returns `DOWN` → `IDLE`, and the unit's
        `SUSPENDED` assignments are then walked in `created_at` ascending
        order — the first one whose project is `OPEN` is reactivated
        `SUSPENDED` → `ACTIVE` and the unit goes back `ON_RENT` for that
        assignment".

        Design: Difficulty/transitive_cascade/repair_completion_cascades_through_equipment_assignment_project
        """
        _, project, equip, asg, mech, wo = self._setup_suspended_via_down(api)
        completed = complete_work_order_as_mechanic(wo["id"], mech["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None

        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "ON_RENT"
        assert e_after["maintenance_status"] == "SERVICE_OK"
        assert e_after["hours_at_last_service_milli"] == 8000
        assert e_after["engine_hours_milli"] == 8000

        a_after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert a_after["status"] == "ACTIVE"

    def test_cascade_updates_project_count_and_mechanic_count(self, api):
        """PRD section 3.4: "the mechanic's count decrements and their status
        recomputes (falling back below 2 returns an `ON_JOB` mechanic to
        `AVAILABLE`)". PRD section 3.2: "the project's
        `active_assignment_count` is recomputed."

        Design: Difficulty/transitive_cascade/repair_completion_cascades_through_equipment_assignment_project
        """
        _, project, equip, asg, mech, wo = self._setup_suspended_via_down(api)
        # Sanity: mark-down dropped the count to 0
        mid_proj = validate_success(api.get_project(project["id"], _ADMIN))
        assert mid_proj["active_assignment_count"] == 0

        complete_work_order_as_mechanic(wo["id"], mech["id"])

        p_after = validate_success(api.get_project(project["id"], _ADMIN))
        assert p_after["active_assignment_count"] == 1

        m_after = validate_success(api.get_mechanic(mech["id"], _ADMIN))
        assert m_after["active_work_order_count"] == 0
        assert m_after["status"] == "AVAILABLE"


class TestVoidUnCrossCascade:
    def _setup_auto_work_order(self, api):
        set_clock("2026-08-05T09:00:00Z")
        cls = make_class(class_code="EXC-400", service_interval_hours=50)
        equip = make_equipment(cls["id"], unit_tag="UNIT-10")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        r_third = make_reading(equip["id"], recorded_date="2026-08-05",
                               engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        wos, _ = validate_paginated(api.list_equipment_work_orders(equip["id"], _ADMIN))
        assert len(wos) == 1
        return equip, r_third, wos[0]

    def test_void_brings_meter_below_threshold(self, api):
        """PRD section 3.3: "voiding flips the reading to `VOIDED`, subtracts
        its delta back out of the meter, and re-evaluates the threshold. If
        the corrected `hours_since_service_milli` now falls below the
        threshold while the unit is `SERVICE_DUE` and the auto-created work
        order is still sitting `OPEN` (never dispatched), the unit returns to
        `SERVICE_OK`".

        Design: Difficulty/transitive_cascade/reading_void_uncrosses_threshold_and_cancels_auto_work_order
        """
        equip, r_third, wo = self._setup_auto_work_order(api)
        validate_success(api.void_reading(r_third["id"], {"void_reason": "meter rollover misread"}, _ADMIN))
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["engine_hours_milli"] == 48000
        assert e_after["maintenance_status"] == "SERVICE_OK"

    def test_void_cancels_open_auto_work_order(self, api):
        """PRD section 3.3: "and that work order is cancelled automatically.
        Once a mechanic has been dispatched, voiding no longer un-crosses the
        threshold in this way."

        Design: Difficulty/transitive_cascade/reading_void_uncrosses_threshold_and_cancels_auto_work_order
        """
        equip, r_third, wo = self._setup_auto_work_order(api)
        validate_success(api.void_reading(r_third["id"], {"void_reason": "meter rollover misread"}, _ADMIN))
        r_after = validate_success(api.get_work_order(wo["id"], _ADMIN))
        assert r_after["status"] == "CANCELLED"
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "IDLE"


# ============================================================================
# Difficulty / priority_pair_validation_conflict
# ============================================================================

class TestAvailabilityBeatsService:
    def test_state_error_wins_over_service_error(self, api):
        """PRD section 2.7: "When a request fails more than one rule, the error
        returned is determined by a fixed priority order, evaluated
        first-match-wins"; priority 8 is "Equipment availability gate for the
        operation — else `ERR_EQUIPMENT_NOT_AVAILABLE`" and priority 9 is
        "Maintenance gate on project commitment — else `ERR_SERVICE_DUE`".

        Design: Difficulty/priority_pair_validation_conflict/availability_state_check_beats_service_safety_check
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-410", service_interval_hours=50,
                         daily_rate_cents=10000)
        project = make_project(project_code="PRJ-K")
        equip = make_equipment(cls["id"], unit_tag="UNIT-11")
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-14")
        for d in ("2026-08-03", "2026-08-04", "2026-08-05"):
            make_reading(equip["id"], recorded_date=d,
                         engine_hours_delta_milli=24000, fuel_used_milliliters=12000)

        e_now = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_now["availability_status"] == "ON_RENT"
        assert e_now["maintenance_status"] == "SERVICE_DUE"

        err = api.create_assignment(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "start_date": "2026-08-15",
                "end_date": "2026-08-20",
                "expected_equipment_version": e_now["version"],
            },
            _ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_EQUIPMENT_NOT_AVAILABLE)
        assert err.status_code == 409

    def test_no_new_assignment_created_on_priority_error(self, api):
        """PRD section 2.7: "When a request fails more than one rule, the error
        returned is determined by a fixed priority order, evaluated
        first-match-wins" — a rejected create mutates nothing, so the
        unit still carries exactly the one pre-existing assignment.

        Design: Difficulty/priority_pair_validation_conflict/availability_state_check_beats_service_safety_check
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-410", service_interval_hours=50,
                         daily_rate_cents=10000)
        project = make_project(project_code="PRJ-K")
        equip = make_equipment(cls["id"], unit_tag="UNIT-11")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-14")
        for d in ("2026-08-03", "2026-08-04", "2026-08-05"):
            make_reading(equip["id"], recorded_date=d,
                         engine_hours_delta_milli=24000, fuel_used_milliliters=12000)

        e_now = validate_success(api.get_equipment(equip["id"], _ADMIN))
        api.create_assignment(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "start_date": "2026-08-15",
                "end_date": "2026-08-20",
                "expected_equipment_version": e_now["version"],
            },
            _ADMIN,
        )
        rows, meta = validate_paginated(api.list_equipment_assignments(equip["id"], _ADMIN))
        assert len(rows) == 1
        assert rows[0]["id"] == asg["id"]


class TestBudgetBeatsProjectState:
    def test_fiscal_error_wins_over_project_state_error(self, api):
        """PRD section 3.2: "then the budget guard and the project-state
        gate, in that order". PRD section 2.7 priority 18 (budget guard) is
        evaluated before priority 19 (project must be OPEN). On activate with
        project SUSPENDED and budget insufficient, the priority-18
        `ERR_BUDGET_EXCEEDED` is returned, not `ERR_PROJECT_NOT_OPEN`.

        Design: Difficulty/priority_pair_validation_conflict/budget_fiscal_check_beats_project_state_check
        """
        cls = make_class(class_code="EXC-420", daily_rate_cents=10000,
                         service_interval_hours=10000)
        project = make_project(project_code="PRJ-L", equipment_budget_cents=5000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-12")
        asg = make_reserved_assignment(equip, project,
                                       start_date="2026-08-20", end_date="2026-08-25")
        validate_success(api.suspend_project(project["id"], _ADMIN))

        err = api.activate_assignment(asg["id"], _ADMIN)
        validate_error(err, ApiErrorId.ERR_BUDGET_EXCEEDED)
        assert err.status_code == 422

    def test_assignment_unchanged_after_fiscal_rejection(self, api):
        """PRD section 2.7: "When a request fails more than one rule, the error
        returned is determined by a fixed priority order, evaluated
        first-match-wins". Because the activation attempt is rejected at the
        budget guard, the assignment's RESERVED state and the unit's RESERVED
        availability are preserved.

        Design: Difficulty/priority_pair_validation_conflict/budget_fiscal_check_beats_project_state_check
        """
        cls = make_class(class_code="EXC-420", daily_rate_cents=10000,
                         service_interval_hours=10000)
        project = make_project(project_code="PRJ-L", equipment_budget_cents=5000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-12")
        asg = make_reserved_assignment(equip, project,
                                       start_date="2026-08-20", end_date="2026-08-25")
        validate_success(api.suspend_project(project["id"], _ADMIN))
        api.activate_assignment(asg["id"], _ADMIN)
        a_after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert a_after["status"] == "RESERVED"
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "RESERVED"


# ============================================================================
# Difficulty / boundary_precision_check
# ============================================================================

class TestServiceThresholdBoundary:
    def test_threshold_minus_one_does_not_fire(self, api):
        """PRD section 3.3: "If `hours_since_service_milli` has reached the
        class threshold — the class `service_interval_hours` expressed in
        milli-hours — while the unit is `SERVICE_OK`, the unit flips
        `SERVICE_OK` → `SERVICE_DUE`". At 49999 milli (threshold-1), no flip.

        Design: Difficulty/boundary_precision_check/service_threshold_inclusive_at_exact_interval
        """
        cls = make_class(class_code="EXC-430", service_interval_hours=50)
        equip = make_equipment(cls["id"], unit_tag="UNIT-13")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        at_48000 = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert at_48000["maintenance_status"] == "SERVICE_OK"

        make_reading(equip["id"], recorded_date="2026-08-05",
                     engine_hours_delta_milli=1999, fuel_used_milliliters=1000)
        at_49999 = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert at_49999["maintenance_status"] == "SERVICE_OK"

    def test_threshold_exact_fires_and_creates_preventive_work_order(self, api):
        """PRD section 3.3: "The boundary is inclusive: a meter sitting
        exactly at the threshold triggers. ... the system auto-creates a
        `PREVENTIVE` work order in `OPEN` with `trigger_hours_milli` set to
        the current meter reading".

        Design: Difficulty/boundary_precision_check/service_threshold_inclusive_at_exact_interval
        """
        cls = make_class(class_code="EXC-430", service_interval_hours=50)
        equip = make_equipment(cls["id"], unit_tag="UNIT-13")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        make_reading(equip["id"], recorded_date="2026-08-05",
                     engine_hours_delta_milli=1999, fuel_used_milliliters=1000)
        make_reading(equip["id"], recorded_date="2026-08-06",
                     engine_hours_delta_milli=1, fuel_used_milliliters=1)
        at_50000 = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert at_50000["maintenance_status"] == "SERVICE_DUE"

        wos, _ = validate_paginated(api.list_equipment_work_orders(equip["id"], _ADMIN))
        assert len(wos) == 1
        assert wos[0]["kind"] == "PREVENTIVE"
        assert wos[0]["status"] == "OPEN"
        assert wos[0]["trigger_hours_milli"] == 50000


class TestBudgetCapBoundary:
    def test_equality_at_cap_is_allowed(self, api):
        """PRD section 3.2: "The guard is inclusive: a charge that would land
        `billed_total_cents` exactly on `equipment_budget_cents` is
        permitted, and only a strictly-over-cap result is rejected with
        `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/budget_cap_inclusive_at_exact_equality
        """
        cls = make_class(class_code="EXC-440", daily_rate_cents=10000,
                         service_interval_hours=10000)
        p_ok = make_project(project_code="PRJ-OK", equipment_budget_cents=10000)
        e_ok = make_equipment(cls["id"], unit_tag="UNIT-OK")
        a_ok = make_reserved_assignment(e_ok, p_ok, start_date="2026-08-03", end_date="2026-08-05")
        activated = validate_success(api.activate_assignment(a_ok["id"], _ADMIN))
        assert activated["status"] == "ACTIVE"

    def test_one_cent_over_cap_rejected(self, api):
        """PRD section 3.2: "only a strictly-over-cap result is rejected with
        `ERR_BUDGET_EXCEEDED`." budget 9999 vs projected 10000 is one cent
        over.

        Design: Difficulty/boundary_precision_check/budget_cap_inclusive_at_exact_equality
        """
        cls = make_class(class_code="EXC-440", daily_rate_cents=10000,
                         service_interval_hours=10000)
        p_bad = make_project(project_code="PRJ-BAD", equipment_budget_cents=9999)
        e_bad = make_equipment(cls["id"], unit_tag="UNIT-BAD")
        a_bad = make_reserved_assignment(e_bad, p_bad,
                                         start_date="2026-08-03", end_date="2026-08-05")
        err = api.activate_assignment(a_bad["id"], _ADMIN)
        validate_error(err, ApiErrorId.ERR_BUDGET_EXCEEDED)
        assert err.status_code == 422
        a_after = validate_success(api.get_assignment(a_bad["id"], _ADMIN))
        assert a_after["status"] == "RESERVED"
        e_after = validate_success(api.get_equipment(e_bad["id"], _ADMIN))
        assert e_after["availability_status"] == "RESERVED"


class TestMechanicCapacityBoundary:
    def _setup_three_work_orders(self, api):
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-15", name="Mac Fifteen")
        w1 = make_work_order(equip["id"], kind="REPAIR", notes="w1")
        w2 = make_work_order(equip["id"], kind="REPAIR", notes="w2")
        w3 = make_work_order(equip["id"], kind="REPAIR", notes="w3")
        return mech, w1, w2, w3

    def test_first_two_dispatches_allowed_second_flips_on_job(self, api):
        """PRD section 3.4: "Dispatch assigns an `OPEN` order to a mechanic
        by `mechanic_id`, but only when that mechanic's `status` is
        `AVAILABLE` and their `active_work_order_count` is below 2 ... a
        count that has reached 2 flips the mechanic `AVAILABLE` → `ON_JOB`,
        while a count below 2 keeps them `AVAILABLE`."

        Design: Difficulty/boundary_precision_check/mechanic_capacity_boundary_at_two_active_orders
        """
        mech, w1, w2, _ = self._setup_three_work_orders(api)
        dispatch_work_order(w1["id"], mech["id"])
        m1 = validate_success(api.get_mechanic(mech["id"], _ADMIN))
        assert m1["active_work_order_count"] == 1
        assert m1["status"] == "AVAILABLE"

        dispatch_work_order(w2["id"], mech["id"])
        m2 = validate_success(api.get_mechanic(mech["id"], _ADMIN))
        assert m2["active_work_order_count"] == 2
        assert m2["status"] == "ON_JOB"

    def test_third_dispatch_rejected_at_capacity(self, api):
        """PRD section 3.4: "a mechanic who is `ON_JOB`, `OFF_DUTY`, or
        already carrying two active orders is refused with
        `ERR_MECHANIC_UNAVAILABLE`."

        Design: Difficulty/boundary_precision_check/mechanic_capacity_boundary_at_two_active_orders
        """
        mech, w1, w2, w3 = self._setup_three_work_orders(api)
        dispatch_work_order(w1["id"], mech["id"])
        dispatch_work_order(w2["id"], mech["id"])
        err = api.dispatch_work_order(w3["id"], {"mechanic_id": mech["id"]}, _ADMIN)
        validate_error(err, ApiErrorId.ERR_MECHANIC_UNAVAILABLE)
        assert err.status_code == 409
        w3_after = validate_success(api.get_work_order(w3["id"], _ADMIN))
        assert w3_after["status"] == "OPEN"


# ============================================================================
# Difficulty / cross_entity_state_dependency
# ============================================================================

class TestAssignmentActivationProjectGate:
    def test_suspended_project_blocks_activation(self, api):
        """PRD section 3.2: "Finally the project must be `OPEN`, else
        `ERR_PROJECT_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/assignment_activation_depends_on_project_open
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        asg = make_reserved_assignment(equip, project,
                                       start_date="2026-08-03", end_date="2026-08-07")
        validate_success(api.suspend_project(project["id"], _ADMIN))
        err = api.activate_assignment(asg["id"], _ADMIN)
        validate_error(err, ApiErrorId.ERR_PROJECT_NOT_OPEN)
        assert err.status_code == 409

    def test_resume_makes_same_activate_succeed(self, api):
        """PRD section 3.1: "a suspended one resumed (`SUSPENDED` → `OPEN`)"
        and section 3.2: "When all gates pass, the assignment becomes
        `ACTIVE` with `activated_at` stamped, the unit moves `RESERVED` →
        `ON_RENT`, both `current_project_id` and `current_site_id` are set to
        the assignment's project".

        Design: Difficulty/cross_entity_state_dependency/assignment_activation_depends_on_project_open
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        asg = make_reserved_assignment(equip, project,
                                       start_date="2026-08-03", end_date="2026-08-07")
        validate_success(api.suspend_project(project["id"], _ADMIN))
        validate_success(api.resume_project(project["id"], _ADMIN))
        activated = validate_success(api.activate_assignment(asg["id"], _ADMIN))
        assert activated["status"] == "ACTIVE"
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "ON_RENT"
        assert e_after["current_project_id"] == project["id"]


class TestWorkOrderMechanicIdentity:
    def test_wrong_mechanic_cannot_start(self, api):
        """PRD section 3.4: "Starting a `DISPATCHED` order requires the
        acting header identity to equal the order's `mechanic_id`; anyone
        else is refused with `ERR_NOT_ASSIGNED_MECHANIC`."

        Design: Difficulty/cross_entity_state_dependency/work_order_start_depends_on_dispatched_mechanic_identity
        """
        cls, project, equip = make_fleet_bundle()
        m_a = make_mechanic(project["id"], mechanic_code="MECH-A", name="Mac A")
        m_b = make_mechanic(project["id"], mechanic_code="MECH-B", name="Mac B")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], m_a["id"])
        err = api.start_work_order(wo["id"], make_mechanic_headers(m_b["id"]))
        validate_error(err, ApiErrorId.ERR_NOT_ASSIGNED_MECHANIC)
        assert err.status_code == 403

    def test_dispatched_mechanic_can_start_and_flips_maintenance(self, api):
        """PRD section 3.4: "Starting flips the order `DISPATCHED` →
        `IN_PROGRESS` and the unit's maintenance dimension to `IN_SERVICE`".

        Design: Difficulty/cross_entity_state_dependency/work_order_start_depends_on_dispatched_mechanic_identity
        """
        cls, project, equip = make_fleet_bundle()
        m_a = make_mechanic(project["id"], mechanic_code="MECH-A", name="Mac A")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], m_a["id"])
        started = start_work_order_as_mechanic(wo["id"], m_a["id"])
        assert started["status"] == "IN_PROGRESS"
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["maintenance_status"] == "IN_SERVICE"


class TestTransportOriginGate:
    def _setup_idle_at_origin(self, api):
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-480", service_interval_hours=10000)
        p_org = make_project(project_code="PRJ-ORG", name="Origin Yard")
        p_dst = make_project(project_code="PRJ-DST", name="Destination")
        p_else = make_project(project_code="PRJ-ELS", name="Elsewhere")
        lb = make_lowboy(lowboy_code="LB-18")
        equip = make_equipment(cls["id"], unit_tag="UNIT-18")
        asg = make_active_assignment(equip, p_org,
                                     start_date="2026-08-03", end_date="2026-08-10")
        set_clock("2026-08-05T09:00:00Z")
        close_assignment(asg["id"])
        return p_org, p_dst, p_else, lb, equip

    def test_wrong_origin_rejected(self, api):
        """PRD section 3.5: "First, the unit must be physically present: its
        `availability_status` must be `IDLE` and its `current_site_id` must
        equal `from_project_id`. ... A violation of either gate is rejected
        with `ERR_TRANSPORT_CONFLICT`."

        Design: Difficulty/cross_entity_state_dependency/transport_creation_depends_on_equipment_physical_site
        """
        p_org, p_dst, p_else, lb, equip = self._setup_idle_at_origin(api)
        err = api.create_transport_job(
            {
                "equipment_id": equip["id"],
                "from_project_id": p_else["id"],
                "to_project_id": p_dst["id"],
                "lowboy_id": lb["id"],
                "depart_at": "2026-08-12T08:00:00Z",
                "arrive_at": "2026-08-12T12:00:00Z",
            },
            _DISP,
        )
        validate_error(err, ApiErrorId.ERR_TRANSPORT_CONFLICT)
        assert err.status_code == 409

    def test_correct_origin_succeeds(self, api):
        """PRD section 3.5: "A planned haul is created in `PLANNED` and moves
        the unit `IDLE` → `IN_TRANSIT`."

        Design: Difficulty/cross_entity_state_dependency/transport_creation_depends_on_equipment_physical_site
        """
        p_org, p_dst, _, lb, equip = self._setup_idle_at_origin(api)
        tj = validate_success(api.create_transport_job(
            {
                "equipment_id": equip["id"],
                "from_project_id": p_org["id"],
                "to_project_id": p_dst["id"],
                "lowboy_id": lb["id"],
                "depart_at": "2026-08-12T08:00:00Z",
                "arrive_at": "2026-08-12T12:00:00Z",
            },
            _DISP,
        ), expected_status=201)
        assert tj["status"] == "PLANNED"
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "IN_TRANSIT"


# ============================================================================
# Difficulty / resource_temporal_overlap
# ============================================================================

class TestAssignmentHalfOpenSemantics:
    def _setup_idle_with_suspended_assignment(self, api):
        """Build the only state where IDLE equipment coexists with a
        non-terminal assignment: assignment SUSPENDED via project-suspended
        mark-down + repair that could not reactivate (project not OPEN)."""
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-490", service_interval_hours=10000,
                         daily_rate_cents=10000)
        project = make_project(project_code="PRJ-P")
        equip = make_equipment(cls["id"], unit_tag="UNIT-19")
        asg = make_active_assignment(equip, project,
                                     start_date="2026-08-03", end_date="2026-08-10")
        validate_success(api.suspend_project(project["id"], _ADMIN))
        validate_success(api.mark_down_equipment(equip["id"], _ADMIN))
        mech = make_mechanic(project["id"], mechanic_code="MECH-19")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], mech["id"])
        start_work_order_as_mechanic(wo["id"], mech["id"])
        complete_work_order_as_mechanic(wo["id"], mech["id"])
        e_now = validate_success(api.get_equipment(equip["id"], _ADMIN))
        return project, equip, asg, e_now

    def test_overlapping_window_rejected(self, api):
        """PRD section 3.2: "Two windows overlap exactly when the new
        `start_date` falls before the existing window's `end_date` and the
        existing window's `start_date` falls before the new `end_date` ... A
        true collision is rejected with `ERR_ASSIGNMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_overlap_rejected
        """
        project, equip, asg, e_now = self._setup_idle_with_suspended_assignment(api)
        err = api.create_assignment(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "start_date": "2026-08-05",
                "end_date": "2026-08-12",
                "expected_equipment_version": e_now["version"],
            },
            _ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)
        assert err.status_code == 409

    def test_adjacent_window_allowed(self, api):
        """PRD section 3.2: "adjacent windows, where one's `end_date` equals
        the other's `start_date`, do not overlap and are always allowed."

        Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_overlap_rejected
        """
        project, equip, asg, e_now = self._setup_idle_with_suspended_assignment(api)
        resp = api.create_assignment(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "start_date": "2026-08-10",
                "end_date": "2026-08-15",
                "expected_equipment_version": e_now["version"],
            },
            _ADMIN,
        )
        new_asg = validate_success(resp, expected_status=201)
        assert new_asg["status"] == "RESERVED"
        asg_orig = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert asg_orig["status"] == "SUSPENDED"


class TestLowboyBufferedInterval:
    def _setup_lowboy_with_morning_job(self, api):
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-500", service_interval_hours=10000)
        p_src = make_project(project_code="PRJ-SRC", name="Source Yard")
        p_dst = make_project(project_code="PRJ-D2", name="Dest Two")
        lb = make_lowboy(lowboy_code="LB-20")

        e_a = make_equipment(cls["id"], unit_tag="UNIT-20A")
        a_a = make_active_assignment(e_a, p_src, start_date="2026-08-03", end_date="2026-08-10")
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(a_a["id"])

        e_b = make_equipment(cls["id"], unit_tag="UNIT-20B")
        a_b = make_active_assignment(e_b, p_src, start_date="2026-08-03", end_date="2026-08-10")
        close_assignment(a_b["id"])

        t1 = make_transport_job(
            e_a["id"], p_src["id"], p_dst["id"], lb["id"],
            depart_at="2026-08-10T08:00:00Z", arrive_at="2026-08-10T12:00:00Z",
        )
        return p_src, p_dst, lb, e_b, t1

    def test_departure_inside_buffer_rejected(self, api):
        """PRD section 3.5: "two jobs on the same lowboy conflict when the
        new job's departure falls before the existing job's buffered end and
        the existing job's departure falls before the new job's buffered end.
        ... A violation of either gate is rejected with
        `ERR_TRANSPORT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/lowboy_buffered_interval_exact_departure_allowed
        """
        p_src, p_dst, lb, e_b, _t1 = self._setup_lowboy_with_morning_job(api)
        err = api.create_transport_job(
            {
                "equipment_id": e_b["id"],
                "from_project_id": p_src["id"],
                "to_project_id": p_dst["id"],
                "lowboy_id": lb["id"],
                "depart_at": "2026-08-10T15:59:00Z",
                "arrive_at": "2026-08-10T18:00:00Z",
            },
            _DISP,
        )
        validate_error(err, ApiErrorId.ERR_TRANSPORT_CONFLICT)
        assert err.status_code == 409

    def test_departure_exactly_at_buffer_end_allowed(self, api):
        """PRD section 3.5: "The buffered end is exclusive — a job departing
        exactly four hours after the previous job's arrival is allowed."

        Design: Difficulty/resource_temporal_overlap/lowboy_buffered_interval_exact_departure_allowed
        """
        p_src, p_dst, lb, e_b, _t1 = self._setup_lowboy_with_morning_job(api)
        t3 = validate_success(api.create_transport_job(
            {
                "equipment_id": e_b["id"],
                "from_project_id": p_src["id"],
                "to_project_id": p_dst["id"],
                "lowboy_id": lb["id"],
                "depart_at": "2026-08-10T16:00:00Z",
                "arrive_at": "2026-08-10T20:00:00Z",
            },
            _DISP,
        ), expected_status=201)
        assert t3["status"] == "PLANNED"
        e_after = validate_success(api.get_equipment(e_b["id"], _ADMIN))
        assert e_after["availability_status"] == "IN_TRANSIT"


# ============================================================================
# Difficulty / compensating_invariant
# ============================================================================

class TestReadingAcceptVoidInvariant:
    def test_accept_then_void_conserves_meter(self, api):
        """PRD section 2.4: "Accepted telematics readings add their delta to
        `equipment.engine_hours_milli`; voiding a reading subtracts that
        reading's delta back out, so the meter equals the sum of accepted
        deltas minus voided ones."

        Design: Difficulty/compensating_invariant/reading_accept_void_pair_conserves_engine_meter
        """
        cls = make_class(class_code="EXC-510", service_interval_hours=10000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-21")
        assert equip["engine_hours_milli"] == 0

        r = make_reading(equip["id"], recorded_date="2026-08-03",
                         engine_hours_delta_milli=12345, fuel_used_milliliters=6000)
        mid = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert mid["engine_hours_milli"] == 12345

        validate_success(api.void_reading(r["id"], {"void_reason": "duplicate feed"}, _ADMIN))
        end = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert end["engine_hours_milli"] == 0

    def test_void_marks_reading_voided_and_stores_reason(self, api):
        """PRD section 3.3: "voiding flips the reading to `VOIDED`". PRD
        section 3.3 also says the reading is voided "with a `void_reason`".

        Design: Difficulty/compensating_invariant/reading_accept_void_pair_conserves_engine_meter
        """
        cls = make_class(class_code="EXC-510", service_interval_hours=10000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-21")
        r = make_reading(equip["id"], recorded_date="2026-08-03",
                         engine_hours_delta_milli=12345, fuel_used_milliliters=6000)
        voided = validate_success(
            api.void_reading(r["id"], {"void_reason": "duplicate feed"}, _ADMIN)
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "duplicate feed"
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["maintenance_status"] == "SERVICE_OK"


class TestDispatchCancelInvariant:
    def test_dispatch_then_cancel_conserves_mechanic_capacity(self, api):
        """PRD section 3.4: "Dispatch ... increments the mechanic's
        `active_work_order_count`"; and "Cancelling a `DISPATCHED` order
        clears its `mechanic_id`, decrements the mechanic's count and
        recomputes their status".

        Design: Difficulty/compensating_invariant/dispatch_cancel_pair_conserves_mechanic_capacity
        """
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-22", name="Mac 22")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], mech["id"])
        mid = validate_success(api.get_mechanic(mech["id"], _ADMIN))
        assert mid["active_work_order_count"] == 1

        cancelled = validate_success(api.cancel_work_order(wo["id"], _ADMIN))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["mechanic_id"] is None
        end = validate_success(api.get_mechanic(mech["id"], _ADMIN))
        assert end["active_work_order_count"] == 0
        assert end["status"] == "AVAILABLE"

    def test_cancel_dispatch_leaves_maintenance_untouched(self, api):
        """PRD section 3.4: "Cancelling an `OPEN` order is bookkeeping only.
        Cancelling a `DISPATCHED` order clears its `mechanic_id` ... and
        restores the unit's maintenance dimension to what the meter says:
        back to `SERVICE_DUE` if `hours_since_service_milli` still sits at or
        above the class threshold, otherwise `SERVICE_OK`." Below threshold,
        the post-cancel state is SERVICE_OK.

        Design: Difficulty/compensating_invariant/dispatch_cancel_pair_conserves_mechanic_capacity
        """
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-22", name="Mac 22")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], mech["id"])
        validate_success(api.cancel_work_order(wo["id"], _ADMIN))
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["maintenance_status"] == "SERVICE_OK"


class TestReserveCancelInvariant:
    def test_reserve_then_cancel_posts_no_charge(self, api):
        """PRD section 2.9: "Only two events post to it: the closure of an
        assignment, which posts that assignment's rental allocation, and the
        confirmation of a damage report, which posts the confirmed
        chargeback. Voided readings never touch the ledger, and neither do
        assessed-but-unconfirmed damage charges, cancelled assignments, or
        reserved ones."

        Design: Difficulty/compensating_invariant/reserve_cancel_pair_conserves_project_ledger
        """
        cls, project, equip = make_fleet_bundle()
        asg = make_reserved_assignment(equip, project,
                                       start_date="2026-08-03", end_date="2026-08-10")
        cancelled = validate_success(api.cancel_assignment(asg["id"], _ADMIN))
        assert cancelled["status"] == "CANCELLED"
        proj_after = validate_success(api.get_project(project["id"], _ADMIN))
        assert proj_after["billed_total_cents"] == 0

    def test_reserve_then_cancel_returns_equipment_idle_and_no_charge_rows(self, api):
        """PRD section 3.2: "A reservation that is no longer wanted can be
        cancelled while still `RESERVED` (`RESERVED` → `CANCELLED`), which
        returns the unit to `IDLE`." Section 3.6: an AssignmentCharge row is
        created on close, so a cancelled assignment has none.

        Design: Difficulty/compensating_invariant/reserve_cancel_pair_conserves_project_ledger
        """
        cls, project, equip = make_fleet_bundle()
        asg = make_reserved_assignment(equip, project,
                                       start_date="2026-08-03", end_date="2026-08-10")
        validate_success(api.cancel_assignment(asg["id"], _ADMIN))
        rows, _ = validate_paginated(api.list_assignment_charges(asg["id"], _ADMIN))
        assert rows == []
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "IDLE"


# ============================================================================
# Corner / validations (multi-condition validation paths)
# ============================================================================

class TestServiceDueGate:
    def test_service_due_blocks_assignment_create_with_idle_equipment(self, api):
        """PRD section 2.5: "Committing a unit to a project — reserving it or
        activating a reservation — requires `SERVICE_OK` on the maintenance
        dimension; a unit in `SERVICE_DUE` or `IN_SERVICE` cannot be
        committed, and the attempt is rejected with `ERR_SERVICE_DUE`."

        Design: Corner/validations/service_due_blocks_assignment_create_with_idle_equipment
        """
        cls = make_class(class_code="EXC-401", service_interval_hours=50)
        project = make_project(project_code="PRJ-401")
        equip = make_equipment(cls["id"], unit_tag="UNIT-401")
        for d in ("2026-08-03", "2026-08-04", "2026-08-05"):
            make_reading(equip["id"], recorded_date=d,
                         engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        e_now = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_now["availability_status"] == "IDLE"
        assert e_now["maintenance_status"] == "SERVICE_DUE"

        err = api.create_assignment(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "start_date": "2026-08-06",
                "end_date": "2026-08-10",
                "expected_equipment_version": e_now["version"],
            },
            _ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_SERVICE_DUE)
        assert err.status_code == 409


class TestDamageProjectMismatch:
    def test_file_against_wrong_project_rejected(self, api):
        """PRD section 3.8: "Filing requires the charged project to be where
        the unit actually is: `project_id` must equal the unit's
        `current_project_id` at filing time — meaning the unit is `ON_RENT`
        at that project — or the filing is rejected with
        `ERR_PROJECT_MISMATCH`."

        Design: Corner/validations/damage_file_project_mismatch_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, p_a, equip = make_fleet_bundle()
        p_b = make_project(project_code="PRJ-402B")
        make_active_assignment(equip, p_a, start_date="2026-08-03", end_date="2026-08-10")
        err = api.create_damage_report(
            {
                "equipment_id": equip["id"],
                "project_id": p_b["id"],
                "description": "wrong project",
                "abuse_flag": False,
                "line_items": [{"description": "x", "amount_cents": 1000}],
            },
            _ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_PROJECT_MISMATCH)
        assert err.status_code == 422
        rows, _ = validate_paginated(api.list_equipment_damage_reports(equip["id"], _ADMIN))
        assert rows == []


class TestDuplicateReading:
    def test_second_reading_same_date_rejected_then_allowed_after_void(self, api):
        """PRD section 3.3: "A unit accepts at most one `ACCEPTED` reading
        per calendar day: a second reading for the same unit and
        `recorded_date` while the first still stands `ACCEPTED` is rejected
        with `ERR_DUPLICATE_READING`."

        Design: Corner/validations/duplicate_reading_same_date_rejected_then_accepted_after_void
        """
        cls = make_class(class_code="EXC-403", service_interval_hours=10000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-403")
        r1 = make_reading(equip["id"], recorded_date="2026-08-03",
                          engine_hours_delta_milli=5000, fuel_used_milliliters=2500)
        err = api.create_reading(
            equip["id"],
            {"recorded_date": "2026-08-03", "engine_hours_delta_milli": 7000,
             "fuel_used_milliliters": 3500},
            _ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_DUPLICATE_READING)
        assert err.status_code == 409

        validate_success(api.void_reading(r1["id"], {"void_reason": "bad meter"}, _ADMIN))
        r2 = validate_success(api.create_reading(
            equip["id"],
            {"recorded_date": "2026-08-03", "engine_hours_delta_milli": 7000,
             "fuel_used_milliliters": 3500},
            _ADMIN,
        ), expected_status=201)
        assert r2["status"] == "ACCEPTED"
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["engine_hours_milli"] == 7000


class TestRentedDispose:
    def test_rented_unit_dispose_rejected(self, api):
        """PRD section 3.9: "its `ownership` must be `OWNED` — disposing a
        rented unit is rejected with `ERR_RENTED_UNIT`".

        Design: Corner/validations/rented_unit_dispose_rejected
        """
        cls = make_class(class_code="EXC-404")
        equip = make_equipment(cls["id"], unit_tag="UNIT-404",
                               ownership="RENTED", acquisition_cost_cents=0)
        err = api.dispose_equipment(equip["id"], {"disposal_method": "SALE"}, _ADMIN)
        validate_error(err, ApiErrorId.ERR_RENTED_UNIT)
        assert err.status_code == 422
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "IDLE"


class TestOpenWorkBlocksDispose:
    def test_open_work_order_blocks_dispose(self, api):
        """PRD section 3.9: "the unit must carry no open work — no work order
        in `OPEN`, `DISPATCHED`, or `IN_PROGRESS`, no transport job in
        `PLANNED` or `EN_ROUTE`, and no damage report in `FILED`,
        `ASSESSED`, or `DISPUTED` — else `ERR_OPEN_WORK`."

        Design: Corner/validations/open_work_blocks_dispose_work_order_and_damage_variants
        """
        cls, project, equip_a = make_fleet_bundle()
        make_work_order(equip_a["id"], kind="REPAIR")
        err = api.dispose_equipment(equip_a["id"], {"disposal_method": "SALE"}, _ADMIN)
        validate_error(err, ApiErrorId.ERR_OPEN_WORK)
        assert err.status_code == 409

    def test_filed_damage_report_blocks_dispose(self, api):
        """PRD section 3.9: "no damage report in `FILED`, `ASSESSED`, or
        `DISPUTED` — else `ERR_OPEN_WORK`."

        Design: Corner/validations/open_work_blocks_dispose_work_order_and_damage_variants
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        asg = make_active_assignment(equip, project,
                                     start_date="2026-08-03", end_date="2026-08-06")
        make_damage_report(equip["id"], project["id"], description="dent",
                           line_items=[{"description": "panel", "amount_cents": 3000}])
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(asg["id"])
        err = api.dispose_equipment(equip["id"], {"disposal_method": "SCRAP"}, _ADMIN)
        validate_error(err, ApiErrorId.ERR_OPEN_WORK)
        assert err.status_code == 409
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "IDLE"


class TestTransportPendingBlocksClose:
    def _setup_suspended_with_pending_transport(self, api):
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-406", service_interval_hours=10000,
                         daily_rate_cents=10000)
        p_a = make_project(project_code="PRJ-406A")
        p_b = make_project(project_code="PRJ-406B")
        lb = make_lowboy(lowboy_code="LB-406")
        equip = make_equipment(cls["id"], unit_tag="UNIT-406")
        asg = make_active_assignment(equip, p_a, start_date="2026-08-03", end_date="2026-08-10")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        # Advance the clock so the assignment is genuinely ACTIVE through
        # 2026-08-04 before the mark-down suspends it: PRD 3.6 makes a day
        # chargeable only when the assignment was ACTIVE for part of it, so
        # 08-03 and 08-04 both qualify only if suspension lands on 08-04.
        set_clock("2026-08-04T09:00:00Z")
        validate_success(api.suspend_project(p_a["id"], _ADMIN))
        validate_success(api.mark_down_equipment(equip["id"], _ADMIN))
        mech = make_mechanic(p_a["id"], mechanic_code="MECH-406")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], mech["id"])
        start_work_order_as_mechanic(wo["id"], mech["id"])
        complete_work_order_as_mechanic(wo["id"], mech["id"])
        # equipment now IDLE with assignment still SUSPENDED (project not OPEN)
        tj = make_transport_job(
            equip["id"], p_a["id"], p_b["id"], lb["id"],
            depart_at="2026-08-12T08:00:00Z", arrive_at="2026-08-12T12:00:00Z",
            assignment_id=asg["id"],
        )
        set_clock("2026-08-13T09:00:00Z")
        return p_a, p_b, equip, asg, tj

    def test_close_blocked_while_transport_pending(self, api):
        """PRD section 3.6: "no `PLANNED` or `EN_ROUTE` transport job may
        reference the assignment — closing while a haul is pending is
        rejected with `ERR_TRANSPORT_PENDING`."

        Design: Corner/validations/transport_pending_blocks_assignment_close_then_allows_after_cancel
        """
        _, _, _, asg, _tj = self._setup_suspended_with_pending_transport(api)
        err = api.close_assignment(asg["id"], {"close_reason": "EQUIPMENT_DOWN"}, _ADMIN)
        validate_error(err, ApiErrorId.ERR_TRANSPORT_PENDING)
        assert err.status_code == 409

    def test_close_succeeds_after_transport_cancelled(self, api):
        """PRD section 3.6: "when closing from `SUSPENDED` the reason must be
        `EQUIPMENT_DOWN` or `PROJECT_CLOSED`" and the close "computes
        allocation ... over the chargeable (non-suspended) days" (section
        3.6: "days spent `SUSPENDED` drop out"). With both chargeable days
        idle at multiplier 5000 over daily 10000, allocated == 10000.

        Design: Corner/validations/transport_pending_blocks_assignment_close_then_allows_after_cancel
        """
        p_a, _, equip, asg, tj = self._setup_suspended_with_pending_transport(api)
        validate_success(api.cancel_transport_job(tj["id"], _DISP))
        closed = validate_success(
            api.close_assignment(asg["id"], {"close_reason": "EQUIPMENT_DOWN"}, _ADMIN)
        )
        assert closed["status"] == "CLOSED"
        assert closed["close_reason"] == "EQUIPMENT_DOWN"
        proj = validate_success(api.get_project(p_a["id"], _ADMIN))
        assert proj["billed_total_cents"] == 10000
        e_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert e_after["availability_status"] == "IDLE"
