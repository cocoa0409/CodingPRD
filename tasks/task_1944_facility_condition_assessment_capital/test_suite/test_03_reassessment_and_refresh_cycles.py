"""Reassessment workflow, remaining-useful-life variants, and refresh-cycle
occupancy / close-out."""
from test_helpers import (
    ApiErrorId,
    accept_assessment,
    assert_refresh_cycle,
    assert_refresh_health,
    assess_system,
    create_asset_system,
    create_deficiency,
    create_facility,
    get_asset_system,
    get_facility,
    list_facility_cycles,
    list_system_snapshots,
    open_cycle,
    reject_assessment,
    setup_assessed_system,
    setup_facility_with_system,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CONSULTANT, MANAGER


def create_facility_once():
    return create_facility()


def create_system_on(facility_id, name, design_life_years):
    return create_asset_system(
        facility_id, system_category="HVAC", name=name, install_year=2010,
        design_life_years=design_life_years, replacement_cost_cents=50000000,
        condition_rating=4)


class TestRemainingUsefulLifeVariants:
    def test_displayed_rul_uses_base_variant(self, api):
        """PRD §3.2: "The base variant works from raw age: the age in years is
        the current calendar year from the server logical clock minus the
        `install_year`; the remaining life is the `design_life_years` minus
        that age, floored at zero."
        PRD §3.2: "This variant never appears on the AssetSystem itself —
        `remaining_useful_life_years` always shows the base variant — but it
        drives the stressed-backlog figure in the refresh-health read (§3.9)."
        PRD §2.8: "At startup it reads exactly 2026-08-01T00:00:00Z — that is,
        the base year 2026"

        Design: Difficulty/dual_variant_calc/rul_optimistic_vs_pessimistic_refresh_health
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "ROOF", "name": "Membrane Roof",
             "install_year": 2010, "design_life_years": 25,
             "replacement_cost_cents": 50000000, "condition_rating": 4})
        # Base variant: max(0, 25 - (2026 - 2010)) = 9.
        assert system["remaining_useful_life_years"] == 9, (
            "display RUL uses the optimistic base variant over raw age")
        fetched = get_asset_system(system["id"])
        assert fetched["remaining_useful_life_years"] == 9

        # The pessimistic variant (9 - 2 = 7) stays internal: refresh-health
        # over this deficiency-free facility reports nothing stressed.
        health = validate_success(api.get_refresh_health(_facility["id"],
                                                         CONSULTANT))
        assert_refresh_health(health)
        assert health["stressed_backlog_cents"] == 0
        assert health["health"] == "GOOD"
        assert health["stale_systems"] == 0
        assert health["total_systems"] == 1

    def test_pessimistic_variant_drives_stressed_backlog_only(self, api):
        """PRD §3.2: "the **pessimistic** remaining useful life subtracts a
        further 2 years after all other adjustments, floored at zero."
        PRD §3.9: "It also computes `stressed_backlog_cents`: the sum of
        `cost_estimate_cents` over the facility's open or in-progress
        deficiencies whose owning system's pessimistic remaining useful life
        (the stress-test variant of §3.2) has reached zero"

        Design: Difficulty/dual_variant_calc/rul_optimistic_vs_pessimistic_refresh_health
        """
        facility = create_facility_once()
        # System A: base RUL = max(0, 18 - 16) = 2 -> pessimistic 0 (stressed).
        sys_stressed = create_system_on(
            facility["id"], name="Stressed", design_life_years=18)
        # System B: base RUL = max(0, 19 - 16) = 3 -> pessimistic 1 (not stressed).
        sys_safe = create_system_on(
            facility["id"], name="Safe", design_life_years=19)
        create_deficiency(sys_stressed["id"], description="on dying system",
                          cost_estimate_cents=1000000, severity=3, urgency=3,
                          recommended_year=2027)
        create_deficiency(sys_safe["id"], description="on viable system",
                          cost_estimate_cents=2000000, severity=3, urgency=3,
                          recommended_year=2027)

        health = validate_success(api.get_refresh_health(facility["id"],
                                                         CONSULTANT))
        assert_refresh_health(health)
        assert health["stressed_backlog_cents"] == 1000000, (
            "only the deficiency on the pessimistic-RUL-0 system is stressed; "
            "the base variant would show both systems alive (2 and 3 years)")
        assert health["stale_systems"] == 0
        assert health["total_systems"] == 2
        # Displayed values still carry the base variant.
        assert get_asset_system(sys_stressed["id"])["remaining_useful_life_years"] == 2
        assert get_asset_system(sys_safe["id"])["remaining_useful_life_years"] == 3


class TestAssessRequiresOpenCycle:
    def test_assess_without_open_refresh_cycle_rejected(self, api):
        """PRD §3.3: "This requires the system to be `ACTIVE` and an `OPEN`
        refresh cycle to exist for the owning facility; attempting to assess
        without an open cycle, or on a system that is not `ACTIVE`, is
        rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/assess_requires_open_refresh_cycle_of_facility
        """
        facility, system = setup_facility_with_system(
            {"system_category": "HVAC", "name": "AHU-2", "install_year": 2014,
             "design_life_years": 20, "replacement_cost_cents": 70000000,
             "condition_rating": 3})

        blocked = api.assess_asset_system(
            system["id"], {"condition_rating": 2}, CONSULTANT)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
        assert get_asset_system(system["id"])["status"] == "ACTIVE"

        cycle = open_cycle(facility["id"])
        assert_refresh_cycle(cycle)
        assert cycle["epoch"] == 1
        reassessed = validate_success(api.assess_asset_system(
            system["id"], {"condition_rating": 2}, CONSULTANT))
        assert reassessed["status"] == "REASSESSED"
        assert reassessed["last_assessed_epoch"] == 1, (
            "assessment stamps the facility's current (open) cycle epoch")

    def test_assess_on_non_active_system_rejected(self, api):
        """PRD §3.3: "This requires the system to be `ACTIVE` and an `OPEN`
        refresh cycle to exist for the owning facility; attempting to assess
        without an open cycle, or on a system that is not `ACTIVE`, is
        rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/assess_requires_open_refresh_cycle_of_facility
        """
        facility, system = setup_facility_with_system()
        open_cycle(facility["id"])
        first = validate_success(api.assess_asset_system(
            system["id"], {"condition_rating": 2}, CONSULTANT))
        assert first["status"] == "REASSESSED"

        second = api.assess_asset_system(
            system["id"], {"condition_rating": 4}, CONSULTANT)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)
        assert get_asset_system(system["id"])["status"] == "REASSESSED"


class TestReassessmentVerdict:
    def test_reject_assessment_restores_prior_values(self, api):
        """PRD §3.3: "the manager may reject the reassessment: the system
        likewise returns from `REASSESSED` to `ACTIVE`, but as compensation its
        `condition_rating` and `remaining_useful_life_years` revert to the
        values stored on the most recent prior ConditionSnapshot, and the
        version increments."
        PRD §3.2: "a `condition_rating` of 1 forces remaining life to 0
        outright"

        Design: Difficulty/compensating_invariant/reject_assessment_restores_prior_snapshot_values
        """
        facility, system = setup_facility_with_system(
            {"system_category": "PLUMBING", "name": "Process Water",
             "install_year": 2010, "design_life_years": 25,
             "replacement_cost_cents": 60000000, "condition_rating": 4})
        open_cycle(facility["id"])
        # Pre-assess pair: rating 4, base RUL = max(0, 25 - 16) = 9.
        assert system["remaining_useful_life_years"] == 9

        mid = assess_system(system["id"], 1,
                            note="catastrophic corrosion observed")
        assert mid["status"] == "REASSESSED"
        assert mid["condition_rating"] == 1
        assert mid["remaining_useful_life_years"] == 0, (
            "rating 1 forces remaining life to 0 mid-flight")

        restored = reject_assessment(system["id"])
        assert restored["status"] == "ACTIVE"
        assert restored["condition_rating"] == 4, (
            "reject restores the pre-assess rating")
        assert restored["remaining_useful_life_years"] == 9, (
            "reject restores the pre-assess RUL — compensating invariant")

        snapshots = list_system_snapshots(system["id"])
        assert any(s["condition_rating"] == 1 and s["epoch"] == 1
                   for s in snapshots), (
            "the assess-time snapshot remains in the append-only audit log "
            "even though the live values reverted")

    def test_accept_assessment_retains_new_values(self, api):
        """PRD §3.3: "A `FacilityManager` reviewing a `REASSESSED` system may
        accept the reassessment, returning the system to `ACTIVE` with the new
        values retained and the version incremented."
        PRD §3.3: "Either branch requires the system to currently be
        `REASSESSED`; acting on a system in any other state is
        `ERR_INVALID_STATE`."
        PRD §3.2: "a `condition_rating` of 2 caps remaining life at no more
        than 2 years even if the raw arithmetic would allow more."

        Design: Difficulty/compensating_invariant/reject_assessment_restores_prior_snapshot_values
        """
        facility, system = setup_facility_with_system(
            {"system_category": "PLUMBING", "name": "Process Water",
             "install_year": 2010, "design_life_years": 25,
             "replacement_cost_cents": 60000000, "condition_rating": 4})
        open_cycle(facility["id"])

        # Accepting a system that was never reassessed is illegal.
        premature = api.accept_assessment(system["id"], MANAGER)
        validate_error(premature, ApiErrorId.ERR_INVALID_STATE)

        reassessed = assess_system(system["id"], 2)
        # Raw RUL 9, rating-2 cap -> 2.
        assert reassessed["remaining_useful_life_years"] == 2

        accepted = accept_assessment(system["id"])
        assert accepted["status"] == "ACTIVE"
        assert accepted["condition_rating"] == 2, "accepted values retained"
        assert accepted["remaining_useful_life_years"] == 2
        assert accepted["version"] == reassessed["version"] + 1


class TestRefreshCycleOccupancy:
    def test_second_open_cycle_rejected(self, api):
        """PRD §3.9: "Only one cycle per facility may be `OPEN` at a time —
        opening a second is `ERR_DUPLICATE`."
        PRD §3.9: "A `Consultant` opens the first cycle for a facility, and
        the server assigns it `epoch` 1"

        Design: Difficulty/resource_temporal_overlap/refresh_cycle_single_open_interval_per_facility
        """
        facility = create_facility_once()
        first = open_cycle(facility["id"])
        assert first["epoch"] == 1
        assert first["status"] == "OPEN"

        duplicate = api.open_refresh_cycle(facility["id"], CONSULTANT)
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE)

        cycles = list_facility_cycles(facility["id"])
        assert len(cycles) == 1, "the failed open leaves no row behind"
        assert cycles[0]["id"] == first["id"]
        assert cycles[0]["status"] == "OPEN"

    def test_open_after_close_targets_the_auto_opened_successor(self, api):
        """PRD §3.9: "A successful close moves the cycle to the terminal
        `CLOSED` state, sets the facility's `assessment_epoch` to the closed
        cycle's epoch, and automatically opens the next cycle for the same
        facility with the following epoch."
        PRD §3.9: "Only one cycle per facility may be `OPEN` at a time —
        opening a second is `ERR_DUPLICATE`."

        Design: Difficulty/resource_temporal_overlap/refresh_cycle_single_open_interval_per_facility
        """
        facility, system, cycle1 = setup_assessed_system(
            {"system_category": "ROOF", "name": "R", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 5000000,
             "condition_rating": 3}, assess_rating=3)
        closed = validate_success(api.close_refresh_cycle(cycle1["id"],
                                                          CONSULTANT))
        assert closed["status"] == "CLOSED"
        assert get_facility(facility["id"])["assessment_epoch"] == 1

        # The auto-opened epoch-2 cycle holds the single-OPEN slot.
        duplicate = api.open_refresh_cycle(facility["id"], CONSULTANT)
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE)

        epochs = {(c["epoch"], c["status"]) for c in
                  list_facility_cycles(facility["id"])}
        assert epochs == {(1, "CLOSED"), (2, "OPEN")}


class TestRefreshCycleClose:
    def test_close_with_unassessed_system_rejected(self, api):
        """PRD §3.9: "every non-`RETIRED` system of the facility must have its
        `last_assessed_epoch` equal to the closing cycle's epoch — any system
        not re-rated during this cycle leaves the close rejected with
        `ERR_PRECONDITION_UNMET`, and acting on a cycle not `OPEN` is
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/refresh_cycle_close_with_unassessed_system_rejected
        """
        facility, system = setup_facility_with_system(
            {"system_category": "ROOF", "name": "R", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 5000000,
             "condition_rating": 3})
        cycle = open_cycle(facility["id"])
        # The system was never assessed in epoch 1 (last_assessed_epoch 0).
        resp = api.close_refresh_cycle(cycle["id"], CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_PRECONDITION_UNMET)
        still_open = [c for c in list_facility_cycles(facility["id"])]
        assert len(still_open) == 1 and still_open[0]["status"] == "OPEN"

    def test_close_success_advances_epoch_and_opens_next(self, api):
        """PRD §3.9: "A successful close moves the cycle to the terminal
        `CLOSED` state, sets the facility's `assessment_epoch` to the closed
        cycle's epoch, and automatically opens the next cycle for the same
        facility with the following epoch."
        PRD §3.9: "each subsequent cycle takes the highest prior epoch for
        that facility plus one."

        Design: Corner/state_machines/refresh_cycle_close_success_advances_epoch_and_opens_next
        """
        facility, system, cycle = setup_assessed_system(
            {"system_category": "ROOF", "name": "R", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 5000000,
             "condition_rating": 3}, assess_rating=3)
        resp = api.close_refresh_cycle(cycle["id"], CONSULTANT)
        closed = validate_success(resp, 200)
        assert_refresh_cycle(closed)
        assert closed["status"] == "CLOSED"
        assert closed["epoch"] == 1

        facility_after = get_facility(facility["id"])
        assert facility_after["assessment_epoch"] == 1

        cycles = list_facility_cycles(facility["id"])
        assert len(cycles) == 2, "close auto-opens the successor cycle"
        by_epoch = {c["epoch"]: c for c in cycles}
        assert by_epoch[1]["status"] == "CLOSED"
        assert by_epoch[2]["status"] == "OPEN", (
            "the epoch-2 OPEN row is the auto-opened successor")
