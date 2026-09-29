"""Refusals: uniqueness, capability, quantity and screening-order errors."""
import pytest

from test_helpers import (
    ADMIN,
    CONVERTER,
    ENGINEER,
    EXTRUDER,
    ISSUING_MANAGER,
    PLANT_ADMIN_USER,
    PRINTER,
    QUALITY,
    ApiErrorId,
    CLOCK_D1_0600,
    NON_EXISTENT_UUID,
    add_gauge_readings,
    create_blend_recipe_payload,
    create_component_payload,
    create_extrusion_line_payload,
    create_extrusion_run_payload,
    create_plate_set_payload,
    create_resin_grade_payload,
    get_success_data,
    narrow_line_payload,
    non_food_product_payload,
    set_logical_clock,
    setup_approved_non_food_recipe,
    setup_bag_lot_converting,
    setup_bag_lot_packed,
    setup_bag_lot_qualified,
    setup_bag_lot_testing,
    setup_draft_dossier,
    setup_food_contact_catalog,
    setup_food_run_completed,
    setup_issued_dossier,
    setup_mounted_plate,
    setup_pool_with_reincorporation,
    setup_print_job_completed,
    setup_print_job_printing,
    validate_error,
    validate_paginated,
    validate_success,
)

# A gauge panel wide enough to come out INCAPABLE on the food-contact product.
INCAPABLE_FOOD_PANEL = (46.0, 54.0, 50.0, 50.0, 50.0)

# Headers carrying an operator identity but no declared capacity at all.
NO_ROLE_HEADERS = {"X-User-ID": PLANT_ADMIN_USER,
                   "Content-Type": "application/json"}


def _running_run_without_any_pool(api):
    """A RUNNING non-food run, fully gauged, with no regrind pool in existence."""
    set_logical_clock(api, CLOCK_D1_0600)
    product = get_success_data(
        api.create_product(non_food_product_payload(), ADMIN))
    grade = get_success_data(
        api.create_resin_grade(create_resin_grade_payload(), ADMIN))
    line = get_success_data(
        api.create_extrusion_line(create_extrusion_line_payload(), ADMIN))
    recipe = get_success_data(api.create_blend_recipe(
        create_blend_recipe_payload(product["id"], recipe_code="R-NF-0",
                                    layer_count=1), ENGINEER))
    get_success_data(api.add_recipe_component(
        recipe["id"],
        create_component_payload(weight_pct=100.0, resin_grade_id=grade["id"]),
        ENGINEER))
    get_success_data(api.submit_blend_recipe(recipe["id"], ENGINEER))
    get_success_data(api.approve_blend_recipe(recipe["id"], QUALITY))
    run = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(line["id"], recipe["id"],
                                     run_code="RUN-NF-1"), EXTRUDER))
    get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
    add_gauge_readings(api, run["id"], (40.0,) * 5)
    return run


class TestDuplicateProductCode:
    """A product code is claimed by whichever row got there first."""

    def test_a_second_product_reusing_the_code_is_refused(self, api):
        """The retry is screened on uniqueness, and the first row survives it.

        PRD: "Each registry resource is addressed operationally by a
        human-readable code, and each such code is globally unique within its own
        collection". And: "A collision on any of these is rejected with
        `ERR_DUPLICATE_CODE` (HTTP 409)."

        Design: Corner/errors/reusing_a_product_code_is_rejected
        """
        set_logical_clock(api, CLOCK_D1_0600)
        first = validate_success(
            api.create_product(non_food_product_payload(), ADMIN), 201)

        validate_error(api.create_product(non_food_product_payload(), ADMIN),
                       ApiErrorId.ERR_DUPLICATE_CODE, 409)

        rows, meta = validate_paginated(
            api.list_products(ADMIN, params={"customer_code": "CUST-NF"}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]


class TestCompletionWithoutAnEligiblePool:
    """Scrap has to land somewhere, so closure needs a pool to book it into."""

    def test_closing_a_scrapping_run_with_no_pool_at_all_is_refused(self, api):
        """Five readings are on file and the arithmetic is fine; the pool is not.

        PRD: "it requires that an eligible regrind pool exist for the scrap
        — matching the recipe's `dominant_polymer_family` and the product's
        food-contact status — or `ERR_NO_ELIGIBLE_REGRIND_POOL`."

        Design: Corner/errors/completing_a_run_with_scrap_but_no_matching_pool_is_rejected
        """
        run = _running_run_without_any_pool(api)

        validate_error(api.complete_extrusion_run(run["id"], 500.0, 100.0, EXTRUDER),
                       ApiErrorId.ERR_NO_ELIGIBLE_REGRIND_POOL, 409)

        _rows, meta = validate_paginated(api.list_regrind_pools(EXTRUDER))
        assert meta["total_count"] == 0

    def test_the_refused_closure_leaves_the_run_running_and_unbalanced(self, api):
        """No mass balance is struck, so the as-built figures stay null.

        PRD: "Closure moves `RUNNING → COMPLETED` and takes two figures: a
        `gross_output_kg` of total extruded mass and a `scrap_kg` of scrap mass."
        And: "Both `regrind_actual_pct` and `actual_recycled_content_pct` are null
        before completion."

        Design: Corner/errors/completing_a_run_with_scrap_but_no_matching_pool_is_rejected
        """
        run = _running_run_without_any_pool(api)
        validate_error(api.complete_extrusion_run(run["id"], 500.0, 100.0, EXTRUDER),
                       ApiErrorId.ERR_NO_ELIGIBLE_REGRIND_POOL, 409)

        stored = get_success_data(api.get_extrusion_run(run["id"], EXTRUDER))
        assert stored["status"] == "RUNNING"
        assert stored["regrind_actual_pct"] is None
        assert stored["actual_recycled_content_pct"] is None


class TestPrintedMassCannotExceedTheRoll:
    """Printed mass is bounded above by the mass actually fed in."""

    def test_reporting_more_mass_than_the_roll_holds_is_refused(self, api):
        """700.0 kg of print off a 600.0 kg roll is physically impossible.

        PRD: "Completing the job advances `PRINTING → COMPLETED` and takes a
        `printed_kg` of printed mass, which must be strictly positive and no
        greater than the fed roll's `net_kg`; a violation is
        `ERR_PRINTED_KG_EXCEEDS_ROLL`."

        Design: Corner/errors/reporting_more_printed_mass_than_the_roll_holds_is_rejected
        """
        world = setup_print_job_printing(api)

        validate_error(
            api.complete_print_job(world["print_job"]["id"], 700.0, PRINTER),
            ApiErrorId.ERR_PRINTED_KG_EXCEEDS_ROLL, 422)

        job = get_success_data(api.get_print_job(world["print_job"]["id"], PRINTER))
        assert job["status"] == "PRINTING"
        assert job["printed_kg"] is None

    def test_the_plate_takes_no_impressions_from_a_refused_completion(self, api):
        """Impressions are charged by completion, and no completion happened.

        PRD: "Completion charges the plate set: `impressions_count` increases by
        `printed_kg` rounded **down** to a whole number".

        Design: Corner/errors/reporting_more_printed_mass_than_the_roll_holds_is_rejected
        """
        world = setup_print_job_printing(api)
        validate_error(
            api.complete_print_job(world["print_job"]["id"], 700.0, PRINTER),
            ApiErrorId.ERR_PRINTED_KG_EXCEEDS_ROLL, 422)

        plate = get_success_data(api.get_plate_set(world["plate"]["id"], PRINTER))
        assert plate["impressions_count"] == 0
        assert plate["status"] == "MOUNTED"


class TestLayflatToleranceOnRelease:
    """The run is beyond reproach; the roll itself is the wrong width."""

    @staticmethod
    def _run_with_a_wide_roll(api):
        return setup_food_run_completed(api, roll_specs=((1, 600.0),),
                                        roll_overrides={1: {"layflat_mm": 320.0}})

    def test_a_roll_twenty_millimetres_wide_is_not_released(self, api):
        """320.0 mm against a 300.0 mm specification is four times the tolerance.

        PRD: "the roll's `layflat_mm` must deviate from the product's
        `layflat_width_mm` by no more than 5.0 millimetres in absolute value, a
        wider deviation yielding `ERR_LAYFLAT_OUT_OF_TOLERANCE`".

        Design: Corner/errors/releasing_a_roll_whose_layflat_is_out_of_tolerance_is_rejected
        """
        world = self._run_with_a_wide_roll(api)
        roll_id = world["rolls"][1]["id"]

        error = validate_error(api.release_film_roll(roll_id, QUALITY),
                               ApiErrorId.ERR_LAYFLAT_OUT_OF_TOLERANCE, 422)
        assert error["error_id"] != ApiErrorId.ERR_GAUGE_CAPABILITY_INSUFFICIENT

        roll = get_success_data(api.get_film_roll(roll_id, QUALITY))
        assert roll["status"] == "WOUND"
        assert roll["layflat_mm"] == pytest.approx(320.0, abs=0.01)

    def test_the_producing_run_was_capable_all_along(self, api):
        """Five identical readings put the run at the capability ceiling.

        PRD: "that run's `gauge_capability_state` must be either `CAPABLE` or
        `MARGINAL`, an `INCAPABLE` or `INSUFFICIENT_DATA` run yielding
        `ERR_GAUGE_CAPABILITY_INSUFFICIENT`".

        Design: Corner/errors/releasing_a_roll_whose_layflat_is_out_of_tolerance_is_rejected
        """
        world = self._run_with_a_wide_roll(api)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["status"] == "COMPLETED"
        assert run["gauge_capability_state"] == "CAPABLE"
        assert run["gauge_capability_index"] == pytest.approx(4.000, abs=0.001)


class TestCountAccuracyGateOnRelease:
    """Everything paperwork-side is in order; the bag count is not."""

    @staticmethod
    def _packed_lot_behind_an_issued_dossier(api):
        world = setup_print_job_completed(api, printed_kg=600.0)
        world = setup_bag_lot_converting(api, world)
        world = setup_bag_lot_testing(api, world)
        world = setup_bag_lot_qualified(api, world)
        world = setup_bag_lot_packed(api, world, requested_bags=46000)
        world = setup_draft_dossier(api, world)
        return setup_issued_dossier(api, world)

    def test_the_count_block_marks_the_lot_out_of_specification(self, api):
        """46000 bags against a theoretical 47923 is 95.99 per cent.

        PRD: "`count_accuracy_pct` is `bag_count_produced` divided by
        `bag_count_theoretical`, multiplied by one hundred, rounded to two
        decimals, and is null when `bag_count_theoretical` is zero."

        Design: Corner/errors/releasing_a_lot_whose_count_accuracy_is_out_of_spec_is_rejected
        """
        world = self._packed_lot_behind_an_issued_dossier(api)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["bag_count_theoretical"] == 47923
        assert lot["count_accuracy_pct"] == pytest.approx(95.99, abs=0.01)
        assert lot["count_accuracy_conforming"] is False

        dossier = get_success_data(
            api.get_compliance_dossier(world["dossier"]["id"], QUALITY))
        assert dossier["status"] == "ISSUED"
        assert dossier["claim_conformance"] == "CONFORMING"

    def test_release_is_refused_on_the_count_and_not_on_the_dossier(self, api):
        """The dossier gate is satisfied, so only the count can be at fault.

        PRD: "Releasing a `PACKED` lot is a `QualityManager` action and it
        enforces four gates. `count_accuracy_conforming` must be true, or
        `ERR_COUNT_ACCURACY_OUT_OF_SPEC`."

        Design: Corner/errors/releasing_a_lot_whose_count_accuracy_is_out_of_spec_is_rejected
        """
        world = self._packed_lot_behind_an_issued_dossier(api)
        lot_id = world["bag_lot"]["id"]

        error = validate_error(api.release_bag_lot(lot_id, ISSUING_MANAGER),
                               ApiErrorId.ERR_COUNT_ACCURACY_OUT_OF_SPEC, 422)
        assert error["error_id"] != ApiErrorId.ERR_DOSSIER_NOT_ISSUED

        lot = get_success_data(api.get_bag_lot(lot_id, CONVERTER))
        assert lot["status"] == "PACKED"


class TestPlateColoursAgainstThePress:
    """Cylinder capacity is generous; the colour stations are the limit."""

    def test_an_eight_colour_plate_will_not_mount_on_six_stations(self, api):
        """Eight colours would need eight stations and the press offers six.

        PRD: "the plate's `color_count` may not exceed that press's
        `max_colors`, or the mount is refused with
        `ERR_PLATE_COLOR_EXCEEDS_PRESS`."

        Design: Corner/errors/mounting_a_plate_with_more_colours_than_the_press_supports_is_rejected
        """
        world = setup_food_contact_catalog(api)
        assert world["press"]["max_colors"] == 6
        assert world["press"]["cylinder_capacity"] == 8

        plate = get_success_data(api.create_plate_set(
            create_plate_set_payload(world["product"]["id"], plate_code="PL-8",
                                     color_count=8), PRINTER))

        validate_error(
            api.mount_plate_set(plate["id"], world["press"]["id"], PRINTER),
            ApiErrorId.ERR_PLATE_COLOR_EXCEEDS_PRESS, 422)

        stored = get_success_data(api.get_plate_set(plate["id"], PRINTER))
        assert stored["status"] == "NEW"
        assert stored["mounted_press_id"] is None


class TestLineWidthCapability:
    """A line can match on every axis but one and still be incapable."""

    def test_a_four_hundred_millimetre_product_will_not_fit_a_narrow_line(self, api):
        """L-SM tops out at 300.0 mm layflat and the product needs 400.0 mm.

        PRD: "and the product's `target_gauge_micron` and `layflat_width_mm` must
        sit inside the line's gauge range and at or below its `max_layflat_mm`; a
        violation of any of these is `ERR_LINE_CAPABILITY_MISMATCH`."

        Design: Corner/errors/scheduling_a_run_on_a_line_too_narrow_for_the_product_is_rejected
        """
        world = setup_approved_non_food_recipe(api)
        narrow = get_success_data(
            api.create_extrusion_line(narrow_line_payload(), ADMIN))
        assert narrow["max_layflat_mm"] == pytest.approx(300.0, abs=0.01)

        validate_error(api.create_extrusion_run(
            create_extrusion_run_payload(narrow["id"], world["recipe"]["id"],
                                         run_code="RUN-SM-1",
                                         scheduled_start="2026-08-05T07:00:00Z",
                                         scheduled_end="2026-08-05T15:00:00Z",
                                         target_output_kg=300.0),
            EXTRUDER), ApiErrorId.ERR_LINE_CAPABILITY_MISMATCH, 422)

        _rows, meta = validate_paginated(api.list_extrusion_runs(
            EXTRUDER, params={"line_id": narrow["id"]}))
        assert meta["total_count"] == 0

    def test_the_refused_schedule_pins_nothing(self, api):
        """No run row exists, so the recipe was never pinned by one.

        PRD: "The run enters `SCHEDULED` and the pinned recipe's
        `pinned_run_count` increments."

        Design: Corner/errors/scheduling_a_run_on_a_line_too_narrow_for_the_product_is_rejected
        """
        world = setup_approved_non_food_recipe(api)
        narrow = get_success_data(
            api.create_extrusion_line(narrow_line_payload(), ADMIN))
        validate_error(api.create_extrusion_run(
            create_extrusion_run_payload(narrow["id"], world["recipe"]["id"],
                                         run_code="RUN-SM-1",
                                         scheduled_start="2026-08-05T07:00:00Z",
                                         scheduled_end="2026-08-05T15:00:00Z",
                                         target_output_kg=300.0),
            EXTRUDER), ApiErrorId.ERR_LINE_CAPABILITY_MISMATCH, 422)

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["pinned_run_count"] == 0
        assert recipe["status"] == "APPROVED"


class TestReversalThatWouldOverdrawThePool:
    """Unwinding the generation would leave the pool sixty kilograms short."""

    @staticmethod
    def _pool_drawn_down_by_sixty(api):
        world = setup_pool_with_reincorporation(api, kg=60.0)
        rows, _meta = validate_paginated(api.list_regrind_transactions(
            EXTRUDER, params={"pool_id": world["pool"]["id"], "direction": "IN"}))
        world["in_transaction"] = rows[0]
        return world

    def test_the_pool_stands_at_forty_kilograms_before_the_attempt(self, api):
        """100.000 kg generated less 60.000 kg reincorporated.

        PRD: "`available_kg` is `cumulative_in_kg` minus `cumulative_out_kg`,
        rounded to three decimals — this is the pool's first invariant, and it
        must hold at every observable moment."

        Design: Corner/errors/reversing_a_generation_row_that_would_overdraw_the_pool_is_rejected
        """
        world = self._pool_drawn_down_by_sixty(api)

        balance = get_success_data(
            api.get_regrind_pool_balance(world["pool"]["id"], EXTRUDER))
        assert balance["cumulative_in_kg"] == pytest.approx(100.000, abs=0.001)
        assert balance["cumulative_out_kg"] == pytest.approx(60.000, abs=0.001)
        assert balance["available_kg"] == pytest.approx(40.000, abs=0.001)

    def test_reversing_the_generation_row_is_refused(self, api):
        """The row is neither a reversal nor already reversed; only the sum objects.

        PRD: "a target that is itself a reversal — or whose reversal would drive
        the pool's `available_kg` below zero — yields
        `ERR_TRANSACTION_NOT_REVERSIBLE`." And: "a target already referenced by an
        existing reversal yields `ERR_TRANSACTION_ALREADY_REVERSED`".

        Design: Corner/errors/reversing_a_generation_row_that_would_overdraw_the_pool_is_rejected
        """
        world = self._pool_drawn_down_by_sixty(api)

        error = validate_error(api.reverse_regrind_transaction(
            world["in_transaction"]["id"], "mis-booked generation", QUALITY),
            ApiErrorId.ERR_TRANSACTION_NOT_REVERSIBLE, 422)
        assert error["error_id"] != ApiErrorId.ERR_TRANSACTION_ALREADY_REVERSED

        balance = get_success_data(
            api.get_regrind_pool_balance(world["pool"]["id"], EXTRUDER))
        assert balance["available_kg"] == pytest.approx(40.000, abs=0.001)

        _rows, meta = validate_paginated(api.list_regrind_transactions(
            QUALITY, params={"pool_id": world["pool"]["id"],
                             "origin_kind": "REVERSAL"}))
        assert meta["total_count"] == 0


class TestRestrictedLineRefusesFoodWork:
    """One incapable run costs the line its food-contact work, not all work."""

    @staticmethod
    def _restricted_food_line(api):
        return setup_food_run_completed(api, thicknesses=INCAPABLE_FOOD_PANEL,
                                        roll_specs=((1, 600.0),))

    def test_scheduling_more_food_work_on_the_restricted_line_is_refused(self, api):
        """The posture is RESTRICTED, one step short of a freeze.

        PRD: "The line must not be `FROZEN`, or `ERR_LINE_POSTURE_FROZEN`; and
        when the recipe's product requires food contact, the line must not be
        `RESTRICTED` either, or `ERR_LINE_POSTURE_RESTRICTED`".

        Design: Corner/errors/scheduling_a_food_contact_run_on_a_restricted_line_is_rejected
        """
        world = self._restricted_food_line(api)
        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["posture"] == "RESTRICTED"
        assert line["incapable_run_count"] == 1

        error = validate_error(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                         run_code="RUN-FD-2",
                                         scheduled_start="2026-08-05T19:00:00Z",
                                         scheduled_end="2026-08-05T20:00:00Z",
                                         target_output_kg=200.0),
            EXTRUDER), ApiErrorId.ERR_LINE_POSTURE_RESTRICTED, 409)
        assert error["error_id"] != ApiErrorId.ERR_LINE_POSTURE_FROZEN

        _rows, meta = validate_paginated(api.list_extrusion_runs(
            EXTRUDER, params={"line_id": world["line"]["id"]}))
        assert meta["total_count"] == 1

    def test_the_restriction_follows_from_a_single_incapable_run(self, api):
        """A 46-to-54 micron spread cannot hold a 50 micron target.

        PRD: "Otherwise it is `RESTRICTED` when `incapable_run_count` is exactly
        one, or when `active_hold_count` has reached two or more."

        Design: Corner/errors/scheduling_a_food_contact_run_on_a_restricted_line_is_rejected
        """
        world = self._restricted_food_line(api)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["gauge_capability_state"] == "INCAPABLE"
        assert run["gauge_capability_index"] == pytest.approx(0.527, abs=0.001)


class TestDossierIssueIsNotIdempotent:
    """Issue is declared from DRAFT only, so the replay must not re-stamp it."""

    def test_replaying_issue_on_an_issued_dossier_is_refused(self, api):
        """The second call finds the dossier already frozen.

        PRD: "Issuing a dossier that is not in `DRAFT` is refused with
        `ERR_DOSSIER_STATE_INVALID`."

        Design: Corner/errors/issuing_an_already_issued_dossier_is_rejected
        """
        world = setup_issued_dossier(api)
        dossier_id = world["dossier"]["id"]
        first_issued_at = world["dossier"]["issued_at"]
        assert first_issued_at is not None

        validate_error(api.issue_compliance_dossier(dossier_id, ISSUING_MANAGER),
                       ApiErrorId.ERR_DOSSIER_STATE_INVALID, 409)

        stored = get_success_data(api.get_compliance_dossier(dossier_id, QUALITY))
        assert stored["status"] == "ISSUED"
        assert stored["issued_at"] == first_issued_at

    def test_the_claim_comparison_is_not_re_run_by_the_replay(self, api):
        """A zero claim against a zero as-built figure stays exactly conforming.

        PRD: "and sets `claim_conformance` to `CONFORMING` when the absolute
        value of that variance is no greater than 0.500 percentage points".

        Design: Corner/errors/issuing_an_already_issued_dossier_is_rejected
        """
        world = setup_issued_dossier(api)
        dossier_id = world["dossier"]["id"]
        validate_error(api.issue_compliance_dossier(dossier_id, ISSUING_MANAGER),
                       ApiErrorId.ERR_DOSSIER_STATE_INVALID, 409)

        stored = get_success_data(api.get_compliance_dossier(dossier_id, QUALITY))
        assert stored["claim_conformance"] == "CONFORMING"
        assert stored["claim_variance_pct"] == pytest.approx(0.000, abs=0.001)
        assert stored["as_built_recycled_content_pct"] == pytest.approx(0.000,
                                                                       abs=0.001)


class TestPlateMountIsNotIdempotent:
    """Re-mounting a mounted plate is an undeclared transition, colours aside."""

    def test_a_second_mount_of_the_same_plate_is_refused(self, api):
        """Naming the very same press does not make the replay legal.

        PRD: "Mounting anything that is not `NEW` — including the terminal
        `WORN` state — is refused with `ERR_PLATE_STATE_INVALID`".

        Design: Corner/errors/mounting_an_already_mounted_plate_set_is_rejected
        """
        world = setup_mounted_plate(api)
        plate_id = world["plate"]["id"]
        assert world["plate"]["status"] == "MOUNTED"

        error = validate_error(
            api.mount_plate_set(plate_id, world["press"]["id"], PRINTER),
            ApiErrorId.ERR_PLATE_STATE_INVALID, 409)
        assert error["error_id"] != ApiErrorId.ERR_PLATE_COLOR_EXCEEDS_PRESS

        stored = get_success_data(api.get_plate_set(plate_id, PRINTER))
        assert stored["status"] == "MOUNTED"
        assert stored["mounted_press_id"] == world["press"]["id"]


NOT_FOUND_SWEEP = (
    ("get_product", ADMIN, ApiErrorId.ERR_PRODUCT_NOT_FOUND),
    ("get_extrusion_line", ADMIN, ApiErrorId.ERR_EXTRUSION_LINE_NOT_FOUND),
    ("get_extrusion_run", EXTRUDER, ApiErrorId.ERR_EXTRUSION_RUN_NOT_FOUND),
    ("get_film_roll", EXTRUDER, ApiErrorId.ERR_FILM_ROLL_NOT_FOUND),
    ("get_regrind_pool", EXTRUDER, ApiErrorId.ERR_REGRIND_POOL_NOT_FOUND),
    ("get_regrind_transaction", QUALITY,
     ApiErrorId.ERR_REGRIND_TRANSACTION_NOT_FOUND),
    ("get_print_press", PRINTER, ApiErrorId.ERR_PRINT_PRESS_NOT_FOUND),
    ("get_plate_set", PRINTER, ApiErrorId.ERR_PLATE_SET_NOT_FOUND),
    ("get_print_job", PRINTER, ApiErrorId.ERR_PRINT_JOB_NOT_FOUND),
    ("get_compliance_dossier", QUALITY, ApiErrorId.ERR_DOSSIER_NOT_FOUND),
    ("get_resin_grade", ENGINEER, ApiErrorId.ERR_RESIN_GRADE_NOT_FOUND),
    ("get_blend_recipe", ENGINEER, ApiErrorId.ERR_BLEND_RECIPE_NOT_FOUND),
)


class TestUnknownPathIdentifiers:
    """Every collection answers with its own 404 identifier."""

    @pytest.mark.parametrize("reader,headers,expected", NOT_FOUND_SWEEP,
                             ids=[case[0] for case in NOT_FOUND_SWEEP])
    def test_each_read_names_the_entity_that_failed(self, api, reader, headers,
                                                    expected):
        """A well-formed but unknown identifier is a 404, never a server error.

        PRD: "Path identifier resolution, evaluated left to right (a 404 naming
        the entity that failed)." And: "When a path names an identifier, that
        identifier is resolved before anything to its right and before any body
        field is examined."

        Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_error
        """
        set_logical_clock(api, CLOCK_D1_0600)

        response = getattr(api, reader)(NON_EXISTENT_UUID, headers)
        validate_error(response, expected, 404)


class TestMissingRoleHeader:
    """Authentication is screened first, ahead of authorization and uniqueness."""

    def test_a_read_without_a_declared_role_is_unauthenticated(self, api):
        """The operator identity alone does not authenticate the call.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the
        six recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/a_request_with_no_role_header_returns_unauthenticated
        """
        set_logical_clock(api, CLOCK_D1_0600)
        product = get_success_data(
            api.create_product(non_food_product_payload(), ADMIN))

        validate_error(api.get_product(product["id"], NO_ROLE_HEADERS),
                       ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_a_write_without_a_declared_role_never_reaches_the_later_rungs(self, api):
        """The duplicate code behind this write is never even looked at.

        PRD: "If the headers are well-formed but the declared role is not among
        the roles authorized for the endpoint being called, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/errors/a_request_with_no_role_header_returns_unauthenticated
        """
        set_logical_clock(api, CLOCK_D1_0600)
        get_success_data(api.create_product(non_food_product_payload(), ADMIN))

        error = validate_error(
            api.create_product(non_food_product_payload(), NO_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_CODE
        assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE

        _rows, meta = validate_paginated(
            api.list_products(ADMIN, params={"customer_code": "CUST-NF"}))
        assert meta["total_count"] == 1
