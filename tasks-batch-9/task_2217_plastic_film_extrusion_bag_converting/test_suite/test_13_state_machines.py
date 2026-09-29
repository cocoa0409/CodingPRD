"""State machines: initial states, guarded transitions and terminal lockdown."""
import pytest

from test_helpers import (
    ADMIN,
    CONVERTER,
    ENGINEER,
    EXTRUDER,
    PRINTER,
    QUALITY,
    ApiErrorId,
    build_non_food_recipe_draft,
    create_blend_recipe_payload,
    create_extrusion_run_payload,
    create_plate_set_payload,
    get_success_data,
    non_food_product_payload,
    read_bag_lot_version,
    setup_food_contact_catalog,
    setup_food_run_completed,
    setup_frozen_line_by_two_incapable_runs,
    setup_approved_non_food_recipe,
    setup_mounted_plate,
    setup_non_food_catalog,
    setup_print_job_in_setup,
    setup_shipped_bag_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

INCAPABLE_FOOD_PANEL = (46.0, 54.0, 50.0, 50.0, 50.0)


class TestBlendRecipeInitialState:
    """DRAFT is the declared entry point and nothing derived is written yet."""

    def test_a_new_recipe_opens_in_draft_with_zeroed_composition(self, api):
        """An empty component list leaves every composition total at zero.

        PRD: "At creation the recipe's `components` list is empty and every
        derived index sits at its default."

        Design: Corner/state_machines/blend_recipe_is_created_in_draft_with_zeroed_derived_fields
        """
        product = get_success_data(
            api.create_product(non_food_product_payload(), ADMIN))

        recipe = validate_success(api.create_blend_recipe(
            create_blend_recipe_payload(product["id"], recipe_code="R-NF-0"),
            ENGINEER), 201)

        assert recipe["status"] == "DRAFT"
        assert recipe["total_weight_pct"] == pytest.approx(0.000, abs=0.001)
        assert recipe["regrind_pct"] == pytest.approx(0.000, abs=0.001)
        assert recipe["additive_pct"] == pytest.approx(0.000, abs=0.001)
        assert recipe["barrier_layer_present"] is False

    def test_a_new_recipe_carries_no_stamps_and_no_predecessor(self, api):
        """The review stamps are written by later transitions, not by creation.

        PRD: "A successful submit stamps `submitted_by_user_id` with the acting
        `X-User-ID` and clears any previous `rejection_reason`." And: "An
        optional `supersedes_recipe_id` names the approved predecessor this
        recipe is intended to replace."

        Design: Corner/state_machines/blend_recipe_is_created_in_draft_with_zeroed_derived_fields
        """
        product = get_success_data(
            api.create_product(non_food_product_payload(), ADMIN))

        recipe = validate_success(api.create_blend_recipe(
            create_blend_recipe_payload(product["id"], recipe_code="R-NF-0"),
            ENGINEER), 201)

        assert recipe["submitted_by_user_id"] is None
        assert recipe["approved_by_user_id"] is None
        assert recipe["rejection_reason"] is None
        assert recipe["supersedes_recipe_id"] is None
        assert recipe["pinned_run_count"] == 0
        assert recipe["supersede_pending"] is False


class TestPlateSetMount:
    """Mounting is guarded only by colour count and only stamps the press."""

    def test_mount_moves_new_to_mounted_and_stamps_the_press(self, api):
        """Four colours fit a six-colour press, so the mount is accepted.

        PRD: "A `PrintOperator` mounts a `NEW` plate set onto a press by naming
        the `press_id`, moving it `NEW → MOUNTED` and setting
        `mounted_press_id`".

        Design: Corner/state_machines/plate_mount_moves_new_to_mounted_and_stamps_the_press
        """
        world = setup_food_contact_catalog(api)
        plate = get_success_data(api.create_plate_set(
            create_plate_set_payload(world["product"]["id"]), PRINTER))
        assert plate["status"] == "NEW"

        mounted = validate_success(
            api.mount_plate_set(plate["id"], world["press"]["id"], PRINTER), 200)
        assert mounted["status"] == "MOUNTED"
        assert mounted["mounted_press_id"] == world["press"]["id"]

    def test_the_mount_leaves_the_wear_counters_at_their_defaults(self, api):
        """Nothing has been printed, so both counters are still zero.

        PRD: "and a `wear_limit_impressions` defaulting to 500000. A plate set
        begins in `NEW` with `impressions_count` and `nonconformance_count` at
        zero and `mounted_press_id` null."

        Design: Corner/state_machines/plate_mount_moves_new_to_mounted_and_stamps_the_press
        """
        world = setup_food_contact_catalog(api)
        plate = get_success_data(api.create_plate_set(
            create_plate_set_payload(world["product"]["id"]), PRINTER))
        mounted = get_success_data(
            api.mount_plate_set(plate["id"], world["press"]["id"], PRINTER))

        assert mounted["impressions_count"] == 0
        assert mounted["nonconformance_count"] == 0
        assert mounted["wear_limit_impressions"] == 500000

        rows, meta = validate_paginated(api.list_plate_sets(
            PRINTER, params={"mounted_press_id": world["press"]["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["plate_code"] == "PL-1"


class TestRunStartWindowPrecondition:
    """A run booked for tomorrow cannot be started today."""

    @staticmethod
    def _run_scheduled_for_the_next_day(api):
        world = setup_approved_non_food_recipe(api)
        world["run"] = get_success_data(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                         run_code="RUN-NF-D",
                                         scheduled_start="2026-08-06T06:00:00Z",
                                         scheduled_end="2026-08-06T14:00:00Z"),
            EXTRUDER))
        return world

    def test_starting_before_the_scheduled_start_is_refused(self, api):
        """The logical clock still reads the previous day.

        PRD: "the current logical clock must have reached `scheduled_start`, an
        earlier clock yielding `ERR_RUN_NOT_YET_STARTABLE`."

        Design: Corner/state_machines/starting_a_run_before_its_scheduled_start_is_rejected
        """
        world = self._run_scheduled_for_the_next_day(api)

        validate_error(api.start_extrusion_run(world["run"]["id"], EXTRUDER),
                       ApiErrorId.ERR_RUN_NOT_YET_STARTABLE, 409)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["status"] == "SCHEDULED"
        assert run["gauge_sample_count"] == 0

    def test_the_refused_start_does_not_unpin_the_recipe(self, api):
        """Scheduling pinned the recipe and the refusal changes nothing.

        PRD: "The run enters `SCHEDULED` and the pinned recipe's
        `pinned_run_count` increments."

        Design: Corner/state_machines/starting_a_run_before_its_scheduled_start_is_rejected
        """
        world = self._run_scheduled_for_the_next_day(api)
        validate_error(api.start_extrusion_run(world["run"]["id"], EXTRUDER),
                       ApiErrorId.ERR_RUN_NOT_YET_STARTABLE, 409)

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["pinned_run_count"] == 1
        assert recipe["status"] == "APPROVED"


class TestInvalidRecipeTransitions:
    """APPROVED is reachable only from SUBMITTED, and submit is not idempotent."""

    @staticmethod
    def _draft_recipe(api):
        world = setup_non_food_catalog(api)
        world["recipe"] = build_non_food_recipe_draft(api, world)
        return world

    def test_approving_a_draft_recipe_is_an_invalid_transition(self, api):
        """The state check fires before the duty-separation check.

        PRD: "Either action attempted on a recipe that is not in `SUBMITTED` is
        refused with `ERR_RECIPE_STATE_INVALID`."

        Design: Corner/state_machines/approving_a_draft_recipe_is_rejected_as_an_invalid_transition
        """
        world = self._draft_recipe(api)

        error = validate_error(
            api.approve_blend_recipe(world["recipe"]["id"], QUALITY),
            ApiErrorId.ERR_RECIPE_STATE_INVALID, 409)
        assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["status"] == "DRAFT"
        assert recipe["approved_by_user_id"] is None

    def test_resubmitting_a_submitted_recipe_is_refused(self, api):
        """Replaying submit must not re-stamp the recipe with a second caller.

        PRD: "A `BlendEngineer` submits a `DRAFT` recipe for quality review,
        moving `status` along `DRAFT → SUBMITTED`."

        Design: Corner/state_machines/submitting_an_already_submitted_recipe_is_rejected
        """
        world = self._draft_recipe(api)
        get_success_data(api.submit_blend_recipe(world["recipe"]["id"], ENGINEER))

        validate_error(api.submit_blend_recipe(world["recipe"]["id"], ENGINEER),
                       ApiErrorId.ERR_RECIPE_STATE_INVALID, 409)

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["status"] == "SUBMITTED"
        assert recipe["submitted_by_user_id"] == "u-be-1"

    def test_the_first_submissions_derived_block_survives_the_replay(self, api):
        """A single 100 % LLDPE line scores 42.00 and stays food-eligible.

        PRD: "`strength_index` is then the dart base multiplied by the binding
        penalty factor multiplied by the additive boost, rounded to two
        decimals".

        Design: Corner/state_machines/submitting_an_already_submitted_recipe_is_rejected
        """
        world = self._draft_recipe(api)
        get_success_data(api.submit_blend_recipe(world["recipe"]["id"], ENGINEER))
        validate_error(api.submit_blend_recipe(world["recipe"]["id"], ENGINEER),
                       ApiErrorId.ERR_RECIPE_STATE_INVALID, 409)

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["strength_index"] == pytest.approx(42.00, abs=0.01)
        assert recipe["food_contact_eligible"] is True


class TestShippedBagLotIsLockedDown:
    """SHIPPED is terminal: neither release nor packout is accepted afterwards."""

    def test_release_after_shipment_is_refused(self, api):
        """The lot has already left the plant.

        PRD: "Releasing a lot that is not `PACKED`, or shipping one that is not
        `RELEASED`, is refused with `ERR_BAG_LOT_STATE_INVALID`."

        Design: Corner/state_machines/a_shipped_bag_lot_accepts_no_further_transitions
        """
        world = setup_shipped_bag_lot(api)
        assert world["bag_lot"]["status"] == "SHIPPED"

        validate_error(api.release_bag_lot(world["bag_lot"]["id"], QUALITY),
                       ApiErrorId.ERR_BAG_LOT_STATE_INVALID, 409)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["status"] == "SHIPPED"

    def test_packout_after_shipment_leaves_the_shipped_quantities_alone(self, api):
        """A fresh version does not make the allocation legal again.

        PRD: "the lot must be `QUALIFIED`, `CONDITIONAL` or already `PACKED`,
        and any other status is refused with `ERR_BAG_LOT_STATE_INVALID`."

        Design: Corner/state_machines/a_shipped_bag_lot_accepts_no_further_transitions
        """
        world = setup_shipped_bag_lot(api)
        lot_id = world["bag_lot"]["id"]
        version = read_bag_lot_version(api, lot_id)

        validate_error(api.packout_bag_lot(lot_id, 100, version, CONVERTER),
                       ApiErrorId.ERR_BAG_LOT_STATE_INVALID, 409)

        lot = get_success_data(api.get_bag_lot(lot_id, CONVERTER))
        assert lot["packed_bag_count"] == 22500
        assert lot["packed_case_count"] == 45
        assert lot["pallet_count"] == 2
        assert lot["bag_count_unpacked"] == 23500


class TestPrintJobCompletionWearsThePlate:
    """One completion can both close the job and retire the plate."""

    @staticmethod
    def _two_jobs_on_a_nearly_worn_plate(api):
        world = setup_mounted_plate(api, plate_code="PL-W",
                                   wear_limit_impressions=500)
        world = setup_print_job_in_setup(api, world, job_code="PJ-W1",
                                        roll_number=1)
        world["job1"] = world["print_job"]
        get_success_data(api.registration_check(world["job1"]["id"], 40.0, PRINTER))
        get_success_data(api.color_proof(world["job1"]["id"], 1.2, PRINTER))
        world["job1"] = get_success_data(api.start_print(world["job1"]["id"], PRINTER))
        world = setup_print_job_in_setup(api, world, job_code="PJ-W2",
                                        roll_number=2)
        world["job2"] = world["print_job"]
        return world

    def test_completion_charges_the_plate_and_wears_it_out(self, api):
        """576 impressions blow straight past a 500-impression limit.

        PRD: "Completion charges the plate set: `impressions_count` increases by
        `printed_kg` rounded **down** to a whole number, and when
        `impressions_count` then stands at or above `wear_limit_impressions` the
        plate set moves to `WORN`".

        Design: Corner/state_machines/print_job_completion_advances_plate_impressions_and_wears_the_plate_out
        """
        world = self._two_jobs_on_a_nearly_worn_plate(api)

        completed = validate_success(
            api.complete_print_job(world["job1"]["id"], 576.0, PRINTER), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["printed_kg"] == pytest.approx(576.0, abs=0.01)

        plate = get_success_data(api.get_plate_set(world["plate"]["id"], PRINTER))
        assert plate["impressions_count"] == 576
        assert plate["status"] == "WORN"
        assert plate["mounted_press_id"] is None

    def test_wearing_out_blocks_the_other_setup_job_on_that_plate(self, api):
        """The sibling job never printed and is now unreachable.

        PRD: "Wearing out clears `mounted_press_id` and moves every print job on
        that plate set whose `status` is `SETUP` to `BLOCKED`, releasing each of
        those jobs' press cylinder windows."

        Design: Corner/state_machines/print_job_completion_advances_plate_impressions_and_wears_the_plate_out
        """
        world = self._two_jobs_on_a_nearly_worn_plate(api)
        get_success_data(api.complete_print_job(world["job1"]["id"], 576.0, PRINTER))

        job2 = get_success_data(api.get_print_job(world["job2"]["id"], PRINTER))
        assert job2["status"] == "BLOCKED"
        assert job2["blocked_reason"] is not None

        _rows, meta = validate_paginated(api.list_print_jobs(
            PRINTER, params={"plate_set_id": world["plate"]["id"]}))
        assert meta["total_count"] == 2


class TestRollReleaseBlockedByAnIncapableRun:
    """The roll's own state is fine; the blocker sits on its producing run."""

    @staticmethod
    def _incapable_food_run(api):
        return setup_food_run_completed(api, thicknesses=INCAPABLE_FOOD_PANEL,
                                        roll_specs=((1, 600.0),))

    def test_the_capability_block_comes_out_incapable(self, api):
        """A 46/54 spread against a 46-to-54 tolerance band gives Cpk 0.527.

        PRD: "`gauge_capability_state` is then read **from that rounded value**:
        `CAPABLE` when the index is at least 1.330, `MARGINAL` when it is at
        least 1.000, and `INCAPABLE` otherwise."

        Design: Corner/state_machines/releasing_a_roll_from_an_incapable_run_is_refused
        """
        world = self._incapable_food_run(api)
        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))

        assert run["gauge_sd_micron"] == pytest.approx(2.5298, abs=0.0001)
        assert run["gauge_cv_pct"] == pytest.approx(5.060, abs=0.001)
        assert run["gauge_capability_index"] == pytest.approx(0.527, abs=0.001)
        assert run["gauge_capability_state"] == "INCAPABLE"

    def test_one_incapable_run_only_restricts_the_line(self, api):
        """A single incapable run is short of the freeze threshold.

        PRD: "Otherwise it is `RESTRICTED` when `incapable_run_count` is exactly
        one, or when `active_hold_count` has reached two or more."

        Design: Corner/state_machines/releasing_a_roll_from_an_incapable_run_is_refused
        """
        world = self._incapable_food_run(api)
        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))

        assert line["incapable_run_count"] == 1
        assert line["posture"] == "RESTRICTED"

    def test_release_is_refused_while_the_roll_itself_stays_wound(self, api):
        """The line is RESTRICTED, not FROZEN, so no quarantine happened.

        PRD: "that run's `gauge_capability_state` must be either `CAPABLE` or
        `MARGINAL`, an `INCAPABLE` or `INSUFFICIENT_DATA` run yielding
        `ERR_GAUGE_CAPABILITY_INSUFFICIENT`".

        Design: Corner/state_machines/releasing_a_roll_from_an_incapable_run_is_refused
        """
        world = self._incapable_food_run(api)
        roll_id = world["rolls"][1]["id"]

        validate_error(api.release_film_roll(roll_id, QUALITY),
                       ApiErrorId.ERR_GAUGE_CAPABILITY_INSUFFICIENT, 422)

        roll = get_success_data(api.get_film_roll(roll_id, QUALITY))
        assert roll["status"] == "WOUND"


class TestClearingCapabilityFlagsIsPartial:
    """Reopening a line does not resurrect what the freeze already condemned."""

    def test_clearing_the_flags_returns_the_line_to_open(self, api):
        """Zeroing the counters re-derives the posture from scratch.

        PRD: "A `QualityManager` or `PlantAdmin` may clear a line's capability
        flags, which zeroes both `incapable_run_count` and
        `revoked_dossier_count` and re-derives `posture`."

        Design: Corner/state_machines/clearing_capability_flags_reopens_the_line_without_unblocking_the_cascade
        """
        world = setup_frozen_line_by_two_incapable_runs(api)
        before = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert before["posture"] == "FROZEN"
        assert before["incapable_run_count"] == 2

        cleared = validate_success(
            api.clear_capability_flags(world["line"]["id"], QUALITY), 200)
        assert cleared["incapable_run_count"] == 0
        assert cleared["active_hold_count"] == 0
        assert cleared["revoked_dossier_count"] == 0
        assert cleared["posture"] == "OPEN"

    def test_the_blocked_run_and_quarantined_rolls_are_not_restored(self, api):
        """The freeze cascade is forward-only.

        PRD: "runs already driven to `BLOCKED` and rolls already driven to
        `QUARANTINED` are not restored" by clearing the flags.

        Design: Corner/state_machines/clearing_capability_flags_reopens_the_line_without_unblocking_the_cascade
        """
        world = setup_frozen_line_by_two_incapable_runs(api)
        get_success_data(api.clear_capability_flags(world["line"]["id"], QUALITY))

        blocked = get_success_data(
            api.get_extrusion_run(world["blocked_run"]["id"], EXTRUDER))
        assert blocked["status"] == "BLOCKED"

        for roll_number in (1, 2):
            roll = get_success_data(
                api.get_film_roll(world["rolls"][roll_number]["id"], QUALITY))
            assert roll["status"] == "QUARANTINED"
