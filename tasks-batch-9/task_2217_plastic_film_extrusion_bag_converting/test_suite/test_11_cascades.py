"""The two great cascade roots: run completion and dossier revocation."""
import pytest

from test_helpers import (
    ADMIN,
    CLOCK_D1_1500,
    CONVERTER,
    ENGINEER,
    EXTRUDER,
    PRINTER,
    QUALITY,
    ApiErrorId,
    ISSUING_MANAGER,
    add_gauge_readings,
    create_blend_recipe_payload,
    create_component_payload,
    create_extrusion_run_payload,
    create_film_roll_payload,
    create_print_job_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_blend_engineer_headers,
    make_quality_manager_headers,
    setup_incapable_non_food_run,
    setup_issued_dossier,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

INCAPABLE_PANEL = (37.0, 43.0, 40.0, 40.0, 40.0)
AUDIT_REASON = "customer audit rejected the food-contact declaration"
CLAIM_REASON = "recycled-content substantiation withdrawn by the supplier"


def _cascade_ready_line(api):
    """One INCAPABLE run behind us, a second gauged and ready to close."""
    world = setup_incapable_non_food_run(api)
    set_logical_clock(api, CLOCK_D1_1500)
    world["run_c"] = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code="RUN-NF-C",
                                     scheduled_start="2026-08-06T06:00:00Z",
                                     scheduled_end="2026-08-06T14:00:00Z"),
        EXTRUDER))
    run_b = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code="RUN-NF-B",
                                     scheduled_start="2026-08-05T15:00:00Z",
                                     scheduled_end="2026-08-05T20:00:00Z"),
        EXTRUDER))
    get_success_data(api.start_extrusion_run(run_b["id"], EXTRUDER))
    add_gauge_readings(api, run_b["id"], INCAPABLE_PANEL)
    world["rolls"][2] = get_success_data(api.create_film_roll(
        create_film_roll_payload(run_b["id"], 2, 100.0), EXTRUDER))
    world["run_b"] = run_b

    successor = get_success_data(api.create_blend_recipe(
        create_blend_recipe_payload(world["product"]["id"],
                                    recipe_code="R-NF-0B",
                                    layer_count=1,
                                    supersedes_recipe_id=world["recipe"]["id"]),
        ENGINEER))
    get_success_data(api.add_recipe_component(
        successor["id"],
        create_component_payload(layer_index=1, component_kind="VIRGIN",
                                 weight_pct=100.0,
                                 resin_grade_id=world["g_ll"]["id"]),
        ENGINEER))
    get_success_data(api.submit_blend_recipe(successor["id"],
                                             make_blend_engineer_headers("u-be-2")))
    world["r0b"] = get_success_data(api.approve_blend_recipe(
        successor["id"], make_quality_manager_headers("u-qm-2")))
    return world


def _close_run_b(api, world):
    return validate_success(
        api.complete_extrusion_run(world["run_b"]["id"], 500.0, 100.0, EXTRUDER), 200)


class TestIncapableRunFreezesTheLine:
    """One completion walks six hops with no intermediate call."""

    def test_the_deferred_supersede_is_pending_before_the_completion(self, api):
        """Two pinning runs keep the predecessor in APPROVED for now.

        PRD: "When a successor is approved and the predecessor's
        `pinned_run_count` is zero, the predecessor moves `APPROVED →
        SUPERSEDED` immediately."

        Design: Difficulty/transitive_cascade/cascade_incapable_run_freezes_line_blocks_run_and_supersedes_recipe
        """
        world = _cascade_ready_line(api)
        predecessor = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))

        assert predecessor["status"] == "APPROVED"
        assert predecessor["supersede_pending"] is True
        assert predecessor["pinned_run_count"] == 2
        assert world["r0b"]["status"] == "APPROVED"

    def test_the_closing_run_computes_an_incapable_index(self, api):
        """A 6-micron spread over a 40-micron target cannot be capable.

        PRD: "`gauge_capability_state` is then read **from that rounded value**:
        `CAPABLE` when the index is at least 1.330, `MARGINAL` when it is at
        least 1.000, and `INCAPABLE` otherwise."

        Design: Difficulty/transitive_cascade/cascade_incapable_run_freezes_line_blocks_run_and_supersedes_recipe
        """
        world = _cascade_ready_line(api)
        completed = _close_run_b(api, world)

        assert completed["gauge_mean_micron"] == pytest.approx(40.000, abs=0.01)
        assert completed["gauge_sd_micron"] == pytest.approx(1.8974, abs=0.01)
        assert completed["gauge_cv_pct"] == pytest.approx(4.743, abs=0.01)
        assert completed["gauge_capability_index"] == pytest.approx(0.703, abs=0.01)
        assert completed["gauge_capability_state"] == "INCAPABLE"
        assert completed["status"] == "COMPLETED"
        assert completed["net_good_kg"] == pytest.approx(400.000, abs=0.01)
        assert completed["actual_recycled_content_pct"] == pytest.approx(0.000,
                                                                        abs=0.01)

    def test_the_second_incapable_run_freezes_the_line(self, api):
        """Two incapable runs is the freeze threshold.

        PRD: "The line is `FROZEN` when `incapable_run_count` has reached two or
        more, or when `revoked_dossier_count` has reached one or more."

        Design: Difficulty/transitive_cascade/cascade_incapable_run_freezes_line_blocks_run_and_supersedes_recipe
        """
        world = _cascade_ready_line(api)
        _close_run_b(api, world)

        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["incapable_run_count"] == 2
        assert line["posture"] == "FROZEN"

    def test_the_freeze_blocks_the_scheduled_run_and_quarantines_both_rolls(self, api):
        """The posture change reaches every scheduled run and wound roll.

        PRD: "if it now reads `FROZEN`, every `SCHEDULED` run on that line moves
        to `BLOCKED` and every `WOUND` roll produced on that line moves to
        `QUARANTINED`."

        Design: Difficulty/transitive_cascade/cascade_incapable_run_freezes_line_blocks_run_and_supersedes_recipe
        """
        world = _cascade_ready_line(api)
        _close_run_b(api, world)

        run_c = get_success_data(api.get_extrusion_run(world["run_c"]["id"], EXTRUDER))
        assert run_c["status"] == "BLOCKED"

        roll_a = get_success_data(api.get_film_roll(world["rolls"][1]["id"], QUALITY))
        roll_b = get_success_data(api.get_film_roll(world["rolls"][2]["id"], QUALITY))
        assert roll_a["status"] == "QUARANTINED"
        assert roll_a["release_blocked_reason"] is not None
        assert roll_b["status"] == "QUARANTINED"

    def test_the_blocked_run_releases_its_pin_and_the_supersede_fires(self, api):
        """Hops five and six: the pin count reaches zero and the recipe retires.

        PRD: "A run driven to `BLOCKED` by a freeze likewise sets
        `recipe_pin_released` to true and decrements the recipe's
        `pinned_run_count`".

        Design: Difficulty/transitive_cascade/cascade_incapable_run_freezes_line_blocks_run_and_supersedes_recipe
        """
        world = _cascade_ready_line(api)
        _close_run_b(api, world)

        predecessor = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert predecessor["pinned_run_count"] == 0
        assert predecessor["status"] == "SUPERSEDED"
        assert predecessor["supersede_pending"] is False

        successor = get_success_data(api.get_blend_recipe(world["r0b"]["id"], ENGINEER))
        assert successor["status"] == "APPROVED"
        assert successor["pinned_run_count"] == 0

    def test_a_quarantined_roll_reports_its_own_state_not_the_posture(self, api):
        """The path entity's state is screened before the line posture gate.

        PRD: "Release attempted on a roll that is not `WOUND` is refused with
        `ERR_ROLL_STATE_INVALID`."

        Design: Difficulty/transitive_cascade/cascade_incapable_run_freezes_line_blocks_run_and_supersedes_recipe
        """
        world = _cascade_ready_line(api)
        _close_run_b(api, world)

        error = validate_error(
            api.release_film_roll(world["rolls"][2]["id"], QUALITY),
            ApiErrorId.ERR_ROLL_STATE_INVALID, 409)
        assert error["error_id"] != ApiErrorId.ERR_LINE_POSTURE_FROZEN

        rows, meta = validate_paginated(api.list_film_rolls(
            QUALITY, params={"extrusion_run_id": world["run_b"]["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "QUARANTINED"

    def test_both_scrap_generations_are_in_the_pool(self, api):
        """Each closure booked its own inbound scrap row.

        PRD: "A regrind transaction is booked into the eligible pool with
        `direction` `IN` and `origin_kind` `EXTRUSION_SCRAP`, carrying `kg`
        equal to `scrap_kg`".

        Design: Difficulty/transitive_cascade/cascade_incapable_run_freezes_line_blocks_run_and_supersedes_recipe
        """
        world = _cascade_ready_line(api)
        _close_run_b(api, world)

        pool = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["cumulative_in_kg"] == pytest.approx(200.000, abs=0.01)
        assert pool["available_kg"] == pytest.approx(200.000, abs=0.01)
        assert pool["generation_count"] == 2
        assert pool["embedded_pcr_pct"] == pytest.approx(0.000, abs=0.01)


def _revocation_ready_plant(api):
    """A packed, documented lot with a second job in SETUP and a run scheduled."""
    world = setup_issued_dossier(api)
    world["plate1"] = world["plate"]
    world["pj1"] = world["print_job"]
    world["pj2"] = get_success_data(api.create_print_job(
        create_print_job_payload(world["rolls"][2]["id"], world["plate1"]["id"],
                                 world["press"]["id"], job_code="PJ-2",
                                 window_start="2026-08-05T06:00:00Z",
                                 window_end="2026-08-05T18:00:00Z"),
        PRINTER))
    world["run_fd2"] = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code="RUN-FD-2",
                                     scheduled_start="2026-08-06T06:00:00Z",
                                     scheduled_end="2026-08-06T14:00:00Z",
                                     target_output_kg=1000.0),
        EXTRUDER))
    return world


class TestDossierRevocationCascade:
    """A compliance action walks a five-level chain of its own."""

    def test_revocation_stamps_the_dossier_and_quarantines_the_lot(self, api):
        """Hops one and two of the revocation chain.

        PRD: "At the first level, the dossier moves `ISSUED → REVOKED` and
        `revoked_at` is stamped from the logical clock."

        Design: Difficulty/transitive_cascade/cascade_dossier_revocation_quarantines_lot_wears_plate_and_freezes_line
        """
        world = _revocation_ready_plant(api)
        revoked = validate_success(api.revoke_compliance_dossier(
            world["dossier"]["id"], AUDIT_REASON, ISSUING_MANAGER), 200)

        assert revoked["status"] == "REVOKED"
        assert is_iso8601_timestamp(revoked["revoked_at"])
        assert revoked["revoked_at"].startswith("2026-08-05T06:00:00")

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["status"] == "QUARANTINED"
        assert lot["quarantine_reason"] is not None

    def test_the_packout_is_unwound_on_the_quarantined_lot(self, api):
        """Every packout counter resets and the unpacked count is restored.

        PRD: "`packed_bag_count`, `packed_case_count`, `partial_case_bag_count`
        and `pallet_count` all reset to zero and `bag_count_unpacked` is restored
        to `bag_count_produced` minus `bag_count_scrapped`".

        Design: Difficulty/transitive_cascade/cascade_dossier_revocation_quarantines_lot_wears_plate_and_freezes_line
        """
        world = _revocation_ready_plant(api)
        get_success_data(api.revoke_compliance_dossier(
            world["dossier"]["id"], AUDIT_REASON, ISSUING_MANAGER))

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["packed_bag_count"] == 0
        assert lot["packed_case_count"] == 0
        assert lot["partial_case_bag_count"] == 0
        assert lot["pallet_count"] == 0
        assert lot["bag_count_unpacked"] == 46000

    def test_the_plate_wears_out_and_its_setup_job_is_blocked(self, api):
        """Hops three and four reach the plate set and the jobs mounted on it.

        PRD: "if that increment brings `nonconformance_count` to one, the plate
        set moves to `WORN`, its `mounted_press_id` is cleared, and every print
        job on it whose `status` is `SETUP` moves to `BLOCKED`".

        Design: Difficulty/transitive_cascade/cascade_dossier_revocation_quarantines_lot_wears_plate_and_freezes_line
        """
        world = _revocation_ready_plant(api)
        get_success_data(api.revoke_compliance_dossier(
            world["dossier"]["id"], AUDIT_REASON, ISSUING_MANAGER))

        plate = get_success_data(api.get_plate_set(world["plate1"]["id"], PRINTER))
        assert plate["nonconformance_count"] == 1
        assert plate["status"] == "WORN"
        assert plate["mounted_press_id"] is None

        pj2 = get_success_data(api.get_print_job(world["pj2"]["id"], PRINTER))
        assert pj2["status"] == "BLOCKED"
        assert pj2["blocked_reason"] is not None

    def test_the_completed_job_is_untouched_by_the_cascade(self, api):
        """Only SETUP jobs are blocked; a finished job keeps its status.

        PRD: "Jobs in `COMPLETED` or `BLOCKED` status release their cylinders and
        are excluded from the sum."

        Design: Difficulty/transitive_cascade/cascade_dossier_revocation_quarantines_lot_wears_plate_and_freezes_line
        """
        world = _revocation_ready_plant(api)
        get_success_data(api.revoke_compliance_dossier(
            world["dossier"]["id"], AUDIT_REASON, ISSUING_MANAGER))

        pj1 = get_success_data(api.get_print_job(world["pj1"]["id"], PRINTER))
        assert pj1["status"] == "COMPLETED"

    def test_the_producing_line_freezes_on_a_single_revocation(self, api):
        """Hop five: one revoked dossier is enough to freeze the line.

        PRD: "the producing line — reached through the chain lot → print job →
        film roll → run — has its `revoked_dossier_count` incremented and its
        `posture` re-derived".

        Design: Difficulty/transitive_cascade/cascade_dossier_revocation_quarantines_lot_wears_plate_and_freezes_line
        """
        world = _revocation_ready_plant(api)
        get_success_data(api.revoke_compliance_dossier(
            world["dossier"]["id"], AUDIT_REASON, ISSUING_MANAGER))

        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["revoked_dossier_count"] == 1
        assert line["posture"] == "FROZEN"

    def test_the_freeze_reaches_the_scheduled_run_and_the_wound_roll_only(self, api):
        """Consumed rolls are left alone; only the WOUND roll is quarantined.

        PRD: "since a single revoked dossier is enough to freeze a line, the line
        typically moves to `FROZEN`, which in turn moves every `SCHEDULED` run on
        that line to `BLOCKED` and every `WOUND` roll produced on it to
        `QUARANTINED`."

        Design: Difficulty/transitive_cascade/cascade_dossier_revocation_quarantines_lot_wears_plate_and_freezes_line
        """
        world = _revocation_ready_plant(api)
        get_success_data(api.revoke_compliance_dossier(
            world["dossier"]["id"], AUDIT_REASON, ISSUING_MANAGER))

        run_fd2 = get_success_data(
            api.get_extrusion_run(world["run_fd2"]["id"], EXTRUDER))
        assert run_fd2["status"] == "BLOCKED"

        roll3 = get_success_data(api.get_film_roll(world["rolls"][3]["id"], QUALITY))
        assert roll3["status"] == "QUARANTINED"

        for roll_number in (1, 2):
            roll = get_success_data(
                api.get_film_roll(world["rolls"][roll_number]["id"], QUALITY))
            assert roll["status"] == "CONSUMED"

        recipe = get_success_data(api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["pinned_run_count"] == 0


class TestBagCountConservationAcrossTheUnwind:
    """The count invariant holds before and after the compensating cascade."""

    def test_conservation_holds_while_the_lot_is_packed(self, api):
        """22500 packed plus 23500 unpacked accounts for all 46000 bags.

        PRD: "A conservation invariant holds after every packout and every
        unwind: `bag_count_produced` always equals `bag_count_unpacked` plus
        `packed_bag_count` plus `bag_count_scrapped`."

        Design: Difficulty/compensating_invariant/bag_count_conservation_holds_across_packout_and_revocation_unwind
        """
        world = setup_issued_dossier(api)
        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))

        assert lot["bag_count_produced"] == 46000
        assert lot["bag_count_unpacked"] == 23500
        assert lot["packed_bag_count"] == 22500
        assert lot["bag_count_scrapped"] == 0
        assert (lot["bag_count_unpacked"] + lot["packed_bag_count"]
                + lot["bag_count_scrapped"]) == lot["bag_count_produced"]
        assert lot["packed_case_count"] == 45
        assert lot["partial_case_bag_count"] == 0
        assert lot["pallet_count"] == 2

    def test_conservation_survives_the_revocation_unwind(self, api):
        """With the packout unwound, every bag is unpacked again.

        PRD: "`packed_bag_count`, `packed_case_count`, `partial_case_bag_count` and
        `pallet_count` all reset to zero and `bag_count_unpacked` is restored to
        `bag_count_produced` minus `bag_count_scrapped`, which re-establishes the
        conservation invariant of §3.9."

        Design: Difficulty/compensating_invariant/bag_count_conservation_holds_across_packout_and_revocation_unwind
        """
        world = setup_issued_dossier(api)
        get_success_data(api.revoke_compliance_dossier(
            world["dossier"]["id"], CLAIM_REASON, ISSUING_MANAGER))

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["bag_count_unpacked"] == 46000
        assert lot["packed_bag_count"] == 0
        assert lot["bag_count_scrapped"] == 0
        assert (lot["bag_count_unpacked"] + lot["packed_bag_count"]
                + lot["bag_count_scrapped"]) == lot["bag_count_produced"]
        assert lot["status"] == "QUARANTINED"
        assert lot["quarantine_reason"] is not None

    def test_the_measured_count_accuracy_block_is_not_recomputed(self, api):
        """The unwind touches allocation counters, not the measured figures.

        PRD: "`bag_count_theoretical` is the print job's `printed_kg` divided by
        `bag_unit_weight_kg`, rounded **down** to a whole number."

        Design: Difficulty/compensating_invariant/bag_count_conservation_holds_across_packout_and_revocation_unwind
        """
        world = setup_issued_dossier(api)
        before = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        get_success_data(api.revoke_compliance_dossier(
            world["dossier"]["id"], CLAIM_REASON, ISSUING_MANAGER))
        after = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))

        assert after["bag_unit_weight_kg"] == pytest.approx(0.012520, abs=0.01)
        assert after["bag_count_theoretical"] == 46006
        assert after["count_accuracy_pct"] == pytest.approx(99.99, abs=0.01)
        assert after["bag_count_theoretical"] == before["bag_count_theoretical"]
        assert after["count_accuracy_pct"] == pytest.approx(
            before["count_accuracy_pct"], abs=0.01)

    def test_the_compensation_is_recorded_on_the_neighbouring_entities(self, api):
        """The unwind is a cascade, so the plate and the line record it too.

        PRD: "At the third level, the lot's print job's plate set has its
        `nonconformance_count` incremented."

        Design: Difficulty/compensating_invariant/bag_count_conservation_holds_across_packout_and_revocation_unwind
        """
        world = setup_issued_dossier(api)
        get_success_data(api.revoke_compliance_dossier(
            world["dossier"]["id"], CLAIM_REASON, ISSUING_MANAGER))

        plate = get_success_data(api.get_plate_set(world["plate"]["id"], PRINTER))
        assert plate["nonconformance_count"] == 1

        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["revoked_dossier_count"] == 1

        dossier = get_success_data(
            api.get_compliance_dossier(world["dossier"]["id"], ISSUING_MANAGER))
        assert dossier["status"] == "REVOKED"
        assert dossier["revocation_reason"] is not None
