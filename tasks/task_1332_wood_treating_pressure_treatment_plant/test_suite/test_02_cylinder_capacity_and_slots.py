"""Cylinder capacity checks, schedule-slot overlap, cylinder state branching,
and the loaded-volume invariant under scrap (PRD §3.2, §3.5, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_NOW,
    SCRAP_COMPLIANCE_PENALTY,
    SCRAP_DISPOSAL_PER_MBF_CENTS,
    TEST_USERS,
    book_treatment_slot,
    create_charge_payload,
    create_cylinder_payload,
    force_charge_state,
    get_charge,
    get_cylinder,
    get_plant,
    load_charge,
    record_assay_for_outcome,
    run_cycle_to_complete,
    set_clock,
    setup_cycle_complete_charge,
    setup_cylinder,
    setup_plant,
    setup_shop,
    validate_error,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]
CO = TEST_USERS["compliance_officer_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestCylinderCapacityBoundary:
    def test_cylinder_capacity_equality_allowed_boundary(self, api):
        """PRD §3.5: "the load is rejected with
        `ERR_CYLINDER_CAPACITY_EXCEEDED` (409) only when that current total
        plus the new charge's `volume_mbf` is strictly greater than
        `max_volume_mbf` — a total exactly equal to the maximum is permitted."

        Design: Difficulty/boundary_precision_check/cylinder_capacity_equality_allowed_boundary
        """
        shop = setup_shop(max_volume_mbf=10.0)
        resp = api.load_charge(
            shop["plant"]["id"], shop["cylinder"]["id"],
            create_charge_payload(volume_mbf=10.0), OP)
        charge = validate_success(resp, 201)
        assert charge["status"] == "IN_CYLINDER"

    def test_cylinder_capacity_one_over_rejected(self, api):
        """PRD §3.5: "the load is rejected with
        `ERR_CYLINDER_CAPACITY_EXCEEDED` (409) only when that current total
        plus the new charge's `volume_mbf` is strictly greater than
        `max_volume_mbf`".

        Design: Difficulty/boundary_precision_check/cylinder_capacity_equality_allowed_boundary
        """
        shop = setup_shop(max_volume_mbf=10.0)
        resp = api.load_charge(
            shop["plant"]["id"], shop["cylinder"]["id"],
            create_charge_payload(volume_mbf=10.1), OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_CAPACITY_EXCEEDED.value)


class TestCylinderCapacityAggregation:
    def test_capacity_counts_in_cylinder_and_cycle_complete_charges(self, api):
        """PRD §3.5: "the cylinder's current loaded volume is the sum of
        `volume_mbf` across the charges physically present in it, meaning
        those in `IN_CYLINDER` or `CYCLE_COMPLETE` status, summed oldest-first
        by creation for determinism, and the load is rejected with
        `ERR_CYLINDER_CAPACITY_EXCEEDED` (409) only when that current total
        plus the new charge's `volume_mbf` is strictly greater than
        `max_volume_mbf` — a total exactly equal to the maximum is permitted."

        Design: Difficulty/combinatorial_formula/cylinder_capacity_circular_dependency_capacity_vs_loaded_mbf
        """
        shop = setup_shop(max_volume_mbf=25.0)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]

        # Q1 (12 mbf) driven to CYCLE_COMPLETE: still physically present.
        q1, _cyc1 = setup_cycle_complete_charge(shop, volume_mbf=12.0)
        assert q1["status"] == "CYCLE_COMPLETE"
        # Cylinder is NEEDS_CLEANING after the cycle; clean it back to IDLE.
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))

        # Q2 (8 mbf) also driven to CYCLE_COMPLETE: 12 + 8 = 20 mbf present.
        q2 = load_charge(plant_id, cyl_id, volume_mbf=8.0)
        run_cycle_to_complete(plant_id, cyl_id, shop["preservative"]["id"], 0.5)
        assert get_charge(plant_id, q2["id"])["status"] == "CYCLE_COMPLETE"
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))

        # 20 + 6 = 26 > 25 -> rejected.
        resp = api.load_charge(plant_id, cyl_id, create_charge_payload(volume_mbf=6.0), OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_CAPACITY_EXCEEDED.value)

        # 20 + 5 = 25 == 25 -> boundary equality permitted.
        resp = api.load_charge(plant_id, cyl_id, create_charge_payload(volume_mbf=5.0), OP)
        q3 = validate_success(resp, 201)
        assert q3["status"] == "IN_CYLINDER"

    def test_capacity_rejects_any_overhang_after_exact_fill(self, api):
        """PRD §3.5: "the load is rejected with
        `ERR_CYLINDER_CAPACITY_EXCEEDED` (409) only when that current total
        plus the new charge's `volume_mbf` is strictly greater than
        `max_volume_mbf` — a total exactly equal to the maximum is permitted."

        Design: Difficulty/combinatorial_formula/cylinder_capacity_circular_dependency_capacity_vs_loaded_mbf
        """
        shop = setup_shop(max_volume_mbf=25.0)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]

        q1, _ = setup_cycle_complete_charge(shop, volume_mbf=12.0)
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))
        q2 = load_charge(plant_id, cyl_id, volume_mbf=8.0)
        run_cycle_to_complete(plant_id, cyl_id, shop["preservative"]["id"], 0.5)
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))
        validate_success(
            api.load_charge(plant_id, cyl_id, create_charge_payload(volume_mbf=5.0), OP),
            201,
        )
        # Cylinder is now LOADED with 25 mbf aboard; drive Q3 through its
        # cycle so the cylinder returns to IDLE at exactly full capacity.
        run_cycle_to_complete(plant_id, cyl_id, shop["preservative"]["id"], 0.5)
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))

        resp = api.load_charge(plant_id, cyl_id, create_charge_payload(volume_mbf=0.5), OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_CAPACITY_EXCEEDED.value)


class TestLoadedVolumeInvariantViaScrap:
    def test_scrap_restores_available_capacity(self, api):
        """PRD §3.5: "the cylinder's current loaded volume is the sum of
        `volume_mbf` across the charges physically present in it, meaning
        those in `IN_CYLINDER` or `CYCLE_COMPLETE` status".
        PRD §3.7: "a `QualityManager` scraps the charge: it moves to
        `SCRAPPED`".

        Design: Difficulty/compensating_invariant/cylinder_loaded_volume_invariant_via_charge_scrap
        """
        shop = setup_shop(max_volume_mbf=50.0)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]

        q1, _ = setup_cycle_complete_charge(shop, volume_mbf=20.0)
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))

        # Q2 (5 mbf) driven to CYCLE_COMPLETE: 20 + 5 = 25 mbf counted.
        q2 = load_charge(plant_id, cyl_id, volume_mbf=5.0)
        cyc2 = run_cycle_to_complete(plant_id, cyl_id, shop["preservative"]["id"], 0.5)
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))

        # Probe: 25 + 26 = 51 > 50 -> capacity rejection proves Q2 counted.
        resp = api.load_charge(plant_id, cyl_id, create_charge_payload(volume_mbf=26.0), OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_CAPACITY_EXCEEDED.value)

        # FAIL_GROSS assay, then scrap Q2 via the re-treat-pending state.
        assay = record_assay_for_outcome(plant_id, q2["id"], cyc2["id"], "FAIL_GROSS")
        assert assay["outcome"] == "FAIL_GROSS"
        force_charge_state(q2["id"], "RE_TREAT_PENDING")
        scrapped = validate_success(api.scrap_charge(plant_id, q2["id"], QM))
        assert scrapped["status"] == "SCRAPPED"

        # Invariant: scrapping removes Q2's volume from the loaded sum, so a
        # 30 mbf charge now fits exactly (20 + 30 = 50 <= 50).
        resp = api.load_charge(plant_id, cyl_id, create_charge_payload(volume_mbf=30.0), OP)
        charge = validate_success(resp, 201)
        assert charge["status"] == "IN_CYLINDER"

    def test_scrap_posts_liability_and_compliance_penalty(self, api):
        """PRD §3.7: "its `volume_mbf` times seventy-five thousand cents per
        mbf (a $750-per-mbf disposal cost) is added to the plant's
        `hazardous_waste_liability_cents`, and the plant's `compliance_score`
        drops by 100, clamped at zero."

        Design: Difficulty/compensating_invariant/cylinder_loaded_volume_invariant_via_charge_scrap
        """
        shop = setup_shop(max_volume_mbf=50.0)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]

        q1, cyc1 = setup_cycle_complete_charge(shop, volume_mbf=20.0)
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))
        q2 = load_charge(plant_id, cyl_id, volume_mbf=5.0)
        cyc2 = run_cycle_to_complete(plant_id, cyl_id, shop["preservative"]["id"], 0.5)

        # Scrap Q2 (5 mbf, FAIL_GROSS).
        record_assay_for_outcome(plant_id, q2["id"], cyc2["id"], "FAIL_GROSS")
        force_charge_state(q2["id"], "RE_TREAT_PENDING")
        validate_success(api.scrap_charge(plant_id, q2["id"], QM))

        # Scrap Q1 (20 mbf, FAIL_GROSS) as well: liabilities accumulate.
        record_assay_for_outcome(plant_id, q1["id"], cyc1["id"], "FAIL_GROSS")
        force_charge_state(q1["id"], "RE_TREAT_PENDING")
        validate_success(api.scrap_charge(plant_id, q1["id"], QM))

        plant = get_plant(plant_id)
        expected_liability = (5.0 + 20.0) * SCRAP_DISPOSAL_PER_MBF_CENTS
        assert plant["hazardous_waste_liability_cents"] == expected_liability
        assert plant["compliance_score"] == 1000 - 2 * SCRAP_COMPLIANCE_PENALTY


class TestCylinderSlotOverlap:
    def test_slot_adjacency_allowed_overlap_rejected(self, api):
        """PRD §3.2: "each slot effectively occupies the half-open interval
        from its `slot_start` to its `slot_end` plus its `buffer_minutes`."
        PRD §3.2: "a new slot whose start coincides exactly with an existing
        slot's effective end is merely adjacent, not overlapping, and is
        permitted."
        PRD §3.2: "A booking is rejected with `ERR_CYLINDER_SLOT_CONFLICT`
        (409) when its effective interval intersects the effective interval
        of any other slot on the same cylinder".

        Design: Difficulty/resource_temporal_overlap/cylinder_slot_half_open_interval_with_buffer
        """
        shop = setup_shop(with_slot=False)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]

        # S1 occupies effective [09:00, 10:30) (slot 09:00-10:00 + 30m buffer).
        book_treatment_slot(
            plant_id, cyl_id,
            slot_start="2026-08-10T09:00:00Z", slot_end="2026-08-10T10:00:00Z",
            buffer_minutes=30,
        )
        # Adjacent at exactly the effective end (10:30): permitted.
        resp = api.create_slot(
            plant_id, cyl_id,
            {"slot_start": "2026-08-10T10:30:00Z", "slot_end": "2026-08-10T12:00:00Z",
             "slot_kind": "TREATMENT", "buffer_minutes": 30}, OP)
        validate_success(resp, 201)
        # One minute inside the effective window (10:29 < 10:30): conflict.
        resp = api.create_slot(
            plant_id, cyl_id,
            {"slot_start": "2026-08-10T10:29:00Z", "slot_end": "2026-08-10T12:00:00Z",
             "slot_kind": "TREATMENT", "buffer_minutes": 30}, OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_SLOT_CONFLICT.value)

    def test_cleaning_slot_blocks_treatment_slot(self, api):
        """PRD §3.2: "`CLEANING` and `MAINTENANCE` slots block `TREATMENT`
        slots under the same rule, and two `TREATMENT` slots may never
        overlap each other on one cylinder."

        Design: Difficulty/resource_temporal_overlap/cylinder_slot_half_open_interval_with_buffer
        """
        shop = setup_shop(with_slot=False)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]

        book_treatment_slot(
            plant_id, cyl_id,
            slot_start="2026-08-10T09:00:00Z", slot_end="2026-08-10T10:00:00Z",
            buffer_minutes=30,
        )
        # CLEANING 10:15-11:00 intersects the TREATMENT slot's effective
        # window [09:00, 10:30) -> conflict.
        resp = api.create_slot(
            plant_id, cyl_id,
            {"slot_start": "2026-08-10T10:15:00Z", "slot_end": "2026-08-10T11:00:00Z",
             "slot_kind": "CLEANING", "buffer_minutes": 0}, OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_SLOT_CONFLICT.value)


class TestSlotCancellation:
    def test_delete_slot_in_past_rejected(self, api):
        """PRD §3.2: "A slot may be cancelled, but only while its `slot_start`
        still lies in the future; cancelling a slot whose start has passed is
        rejected with `ERR_SLOT_IN_PAST` (409), and a successful cancellation
        removes the slot and answers 204 No Content."

        Design: Corner/endpoints/delete_slot_in_past_rejected
        """
        shop = setup_shop(with_slot=False)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        # Logical clock is at 2026-08-10T08:00:00Z; the slot lies in the past.
        slot = book_treatment_slot(
            plant_id, cyl_id,
            slot_start="2026-08-09T09:00:00Z", slot_end="2026-08-09T17:00:00Z",
        )
        resp = api.delete_slot(plant_id, cyl_id, slot["id"], OP)
        validate_error(resp, ApiErrorId.ERR_SLOT_IN_PAST.value)


class TestCylinderStateBranching:
    def test_needs_cleaning_blocks_load_until_marked_cleaned(self, api):
        """PRD §3.5: "The cylinder must be `IDLE` — loading against a busy
        cylinder fails with `ERR_CYLINDER_NOT_IDLE` (409)."
        PRD §3.2: "Only after the operator marks the cylinder cleaned does it
        return to `IDLE` — an act that also closes the cylinder's `CLEANING`
        slot".

        Design: Difficulty/non_linear_state_machine/cylinder_state_machine_branching_cleaning_and_decommission
        """
        shop = setup_shop()
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        setup_cycle_complete_charge(shop, volume_mbf=5.0)
        assert get_cylinder(plant_id, cyl_id)["status"] == "NEEDS_CLEANING"

        # Load while NEEDS_CLEANING -> rejected.
        resp = api.load_charge(plant_id, cyl_id, create_charge_payload(volume_mbf=2.0), OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_NOT_IDLE.value)

        # Mark cleaned -> IDLE -> the same load succeeds.
        cleaned = validate_success(api.mark_cleaned(plant_id, cyl_id, OP))
        assert cleaned["status"] == "IDLE"
        resp = api.load_charge(plant_id, cyl_id, create_charge_payload(volume_mbf=2.0), OP)
        charge = validate_success(resp, 201)
        assert charge["status"] == "IN_CYLINDER"

    def test_decommission_only_from_idle(self, api):
        """PRD §3.2: "only an `IDLE` cylinder with no future slot (no slot
        whose `slot_end` lies beyond the present moment) may be decommissioned,
        which is terminal."
        PRD §2.9: "with `ERR_INVALID_STATE` (409) as the generic form when a
        resource is simply not in a valid from-state."

        Design: Difficulty/non_linear_state_machine/cylinder_state_machine_branching_cleaning_and_decommission
        """
        shop = setup_shop()
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        load_charge(plant_id, cyl_id, volume_mbf=2.0)
        assert get_cylinder(plant_id, cyl_id)["status"] == "LOADED"

        # Decommission from LOADED -> invalid from-state.
        resp = api.decommission_cylinder(plant_id, cyl_id, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        # A fresh IDLE cylinder with no slots decommissions cleanly.
        cyl2 = setup_cylinder(plant_id, cylinder_code="CYL-2")
        data = validate_success(api.decommission_cylinder(plant_id, cyl2["id"], OP))
        assert data["status"] == "DECOMMISSIONED"


class TestCylinderRegistration:
    def test_create_cylinder_invalid_enum_process_type_returns_400(self, api):
        """PRD §2.9: "a malformed body, a missing required field, or a value
        outside a declared enum set is rejected up front with
        `ERR_INVALID_REQUEST` (400) or `ERR_INVALID_ENUM` (400)."
        PRD §3.2: supported process types are "drawn from `FULL_CELL`,
        `LOWRY`, `RUEPING`, and `SAP_DISPLACEMENT`."

        Design: Corner/entities/create_cylinder_invalid_enum_process_type_returns_400
        """
        plant = setup_plant()
        resp = api.create_cylinder(
            plant["id"],
            create_cylinder_payload(supported_process_types=["INVALID_PROCESS"]),
            OP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)
