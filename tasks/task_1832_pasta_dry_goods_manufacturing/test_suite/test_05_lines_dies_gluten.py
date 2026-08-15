"""Production lines and dies: posture cycle with swab fail loop, GF mixing
gate, die lifecycle and extrusion gates, line version accounting."""
from test_helpers import (
    ApiErrorId,
    abort_run,
    advance_run,
    complete_line_cleaning,
    create_accepted_lot,
    create_active_contract,
    create_approved_recipe,
    create_die,
    create_gf_validated_line,
    create_line,
    create_mounted_die,
    get_die,
    get_line,
    get_run,
    mount_die,
    record_and_verify_line_swab,
    record_gluten_test,
    schedule_run,
    set_clock,
    setup_scheduled_run,
    start_line_cleaning,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
TECH = TEST_USERS["qa_technician_headers"]
QAM = TEST_USERS["qa_manager_headers"]
OP = TEST_USERS["production_operator_headers"]


class TestLineGlutenPostureCycle:
    def test_swab_fail_loops_back_to_cleaning_then_pass_validates(self, api):
        """PRD: "a `PASS` moves the line to `GF_VALIDATED`, while a `FAIL`
        loops it back to `CLEANING_IN_PROGRESS`"

        Design: Difficulty/non_linear_state_machine/line_gluten_posture_cycle_with_swab_fail_loop
        """
        line = create_line("L-CYC")
        start_line_cleaning(line["id"])
        complete_line_cleaning(line["id"])

        record_and_verify_line_swab(line["id"], "FAIL")
        after_fail = get_line(line["id"])
        assert after_fail["gluten_posture"] == "CLEANING_IN_PROGRESS", "fail loop"

        complete_line_cleaning(line["id"])
        record_and_verify_line_swab(line["id"], "PASS")
        after_pass = get_line(line["id"])
        assert after_pass["gluten_posture"] == "GF_VALIDATED"

    def test_non_gf_extrusion_returns_line_to_gluten_exposed(self, api):
        """PRD: "A line loses `GF_VALIDATED` the moment a run whose recipe is
        not gluten-free advances from `MIXING` to `EXTRUDING` on it — the
        posture flips to `GLUTEN_EXPOSED` and `version` increments"

        Design: Difficulty/non_linear_state_machine/line_gluten_posture_cycle_with_swab_fail_loop
        """
        line = create_gf_validated_line("L-CYC2")
        assert line["gluten_posture"] == "GF_VALIDATED"

        contract = create_active_contract(contract_code="C-CYC")
        lot = create_accepted_lot(contract["id"], 1000.0)
        recipe = create_approved_recipe(recipe_name="Spaghetti CYC")  # non-GF LONG_CUT
        die = create_die("D-CYC", "LONG_CUT", 100000.0)
        mount_die(die["id"], line["id"])
        run = schedule_run(recipe["id"], line["id"], lot["id"], 500.0)

        set_clock("2026-08-10T00:00:00Z")
        advance_run(run["id"])
        run = advance_run(run["id"])
        assert run["production_status"] == "EXTRUDING"

        after = get_line(line["id"])
        assert after["gluten_posture"] == "GLUTEN_EXPOSED", (
            "cycle closed back to the initial state"
        )


class TestGfRunMixingRequiresLineGfValidated:
    def test_blocked_until_cleaning_and_verified_swab(self, api):
        """PRD: "If the run is gluten-free, the line's `gluten_posture` must be
        `GF_VALIDATED` (`ERR_GF_SEGREGATION_VIOLATION`)."

        Design: Difficulty/cross_entity_state_dependency/gf_run_mixing_requires_line_gf_validated
        """
        sc = setup_scheduled_run(
            contract_code="C-XG",
            recipe_overrides={"recipe_name": "GF Penne XG", "gluten_free": True,
                              "shape_family": "SHORT_CUT"},
            planned_input_kg=100.0, with_die=False,
        )
        set_clock("2026-08-10T00:00:00Z")
        resp = api.advance_run(sc["run"]["id"], {}, OP)
        validate_error(resp, ApiErrorId.ERR_GF_SEGREGATION_VIOLATION)

        start_line_cleaning(sc["line"]["id"])
        complete_line_cleaning(sc["line"]["id"])
        record_and_verify_line_swab(sc["line"]["id"], "PASS")
        line = get_line(sc["line"]["id"])
        assert line["gluten_posture"] == "GF_VALIDATED"

        run = advance_run(sc["run"]["id"])
        assert run["production_status"] == "MIXING"

    def test_mid_cycle_posture_also_blocks(self, api):
        """PRD: "If the run is gluten-free, the line's `gluten_posture` must be
        `GF_VALIDATED` (`ERR_GF_SEGREGATION_VIOLATION`)."

        Design: Difficulty/cross_entity_state_dependency/gf_run_mixing_requires_line_gf_validated
        """
        sc = setup_scheduled_run(
            contract_code="C-XG2",
            recipe_overrides={"recipe_name": "GF Penne XG2", "gluten_free": True,
                              "shape_family": "SHORT_CUT"},
            planned_input_kg=100.0, with_die=False,
        )
        # CLEANING_IN_PROGRESS is not GF_VALIDATED either.
        start_line_cleaning(sc["line"]["id"])
        set_clock("2026-08-10T00:00:00Z")
        resp = api.advance_run(sc["run"]["id"], {}, OP)
        validate_error(resp, ApiErrorId.ERR_GF_SEGREGATION_VIOLATION)


def test_die_lifecycle_wear_reset_and_auto_retire(api):
    """PRD: "The die accrues the run's full `planned_input_kg` onto its
    `extruded_kg`"
    PRD: "when `refurbish` is true the die returns to `AVAILABLE` with
    `extruded_kg` reset to zero; when `refurbish` is false the die returns to
    `AVAILABLE` only if `extruded_kg` is still below `rated_capacity_kg` —
    otherwise the wear limit forces an automatic retirement to `RETIRED`,
    terminal."

    Design: Corner/state_machines/die_lifecycle_wear_reset_and_auto_retire
    """
    sc = setup_scheduled_run(
        contract_code="C-DIE", lot_weight_kg=1000.0, die_code="D-WORN",
        die_rated_kg=100.0, planned_input_kg=150.0,
    )
    die1 = sc["die"]
    run1 = sc["run"]

    set_clock("2026-08-10T00:00:00Z")
    advance_run(run1["id"])
    advance_run(run1["id"])  # EXTRUDING: die1 accrues 150 kg
    abort_run(run1["id"])
    get_success = get_die(die1["id"])
    assert get_success["extruded_kg"] == 150.0

    get_success_data_unmount = api.unmount_die(die1["id"], OP)
    assert get_success_data_unmount.status_code == 200
    retired = validate_success(api.complete_die_cleaning(die1["id"], {"refurbish": False}, OP))
    assert retired["status"] == "RETIRED", "150.0 >= 100.0 rated capacity, no refurbish"
    assert retired["extruded_kg"] == 150.0, "wear retained at retirement"

    die2 = create_mounted_die(sc["line"]["id"], "D-FRESH", "LONG_CUT", 100000.0)
    run2 = schedule_run(sc["recipe"]["id"], sc["line"]["id"], sc["lot"]["id"],
                        planned_input_kg=100.0,
                        scheduled_start="2026-08-12T00:00:00Z",
                        scheduled_end="2026-08-13T00:00:00Z")
    set_clock("2026-08-12T00:00:00Z")
    advance_run(run2["id"])
    advance_run(run2["id"])
    abort_run(run2["id"])
    get_success_data_unmount2 = api.unmount_die(die2["id"], OP)
    assert get_success_data_unmount2.status_code == 200
    refurbished = validate_success(api.complete_die_cleaning(die2["id"], {"refurbish": True}, OP))
    assert refurbished["status"] == "AVAILABLE"
    assert refurbished["extruded_kg"] == 0, "refurbish resets wear"


def test_stale_swab_rejected_at_verify(api):
    """PRD: "verification additionally requires the swab's `created_at` to be
    at or after the line's `cleaning_completed_at` and the line to be sitting
    in `AWAITING_SWAB` (`ERR_STALE_SWAB`)"

    Design: Corner/validations/stale_swab_rejected_at_verify
    """
    line = create_line("L-SSW")
    start_line_cleaning(line["id"])
    swab = record_gluten_test(result="PASS", line_id=line["id"])

    set_clock("2026-08-01T06:00:00Z")
    complete_line_cleaning(line["id"])

    resp = api.verify_gluten_test(swab["id"], QAM)
    validate_error(resp, ApiErrorId.ERR_STALE_SWAB)

    after = get_line(line["id"])
    assert after["gluten_posture"] == "AWAITING_SWAB", "posture unchanged"


def test_die_not_mounted_then_shape_mismatch(api):
    """PRD: "The hop from `MIXING` to `EXTRUDING` requires a die currently
    `MOUNTED` on the run's line (`ERR_DIE_NOT_MOUNTED`) whose `shape_family`
    equals the recipe's (`ERR_DIE_SHAPE_MISMATCH`)."

    Design: Corner/errors/die_not_mounted_then_shape_mismatch
    """
    sc = setup_scheduled_run(contract_code="C-DG", lot_weight_kg=1000.0,
                             planned_input_kg=100.0, with_die=False)
    run1 = sc["run"]
    set_clock("2026-08-10T00:00:00Z")
    advance_run(run1["id"])  # MIXING

    resp1 = api.advance_run(run1["id"], {}, OP)
    validate_error(resp1, ApiErrorId.ERR_DIE_NOT_MOUNTED)

    abort_run(run1["id"])  # MIXING refund restores the lot to 1000.0
    lot = validate_success(api.get_semolina_lot(sc["lot"]["id"], PM))
    assert lot["remaining_weight_kg"] == 1000.0

    wrong = create_die("D-WRONG", "SHORT_CUT", 100000.0)
    mount_die(wrong["id"], sc["line"]["id"])
    run2 = schedule_run(sc["recipe"]["id"], sc["line"]["id"], sc["lot"]["id"],
                        planned_input_kg=100.0,
                        scheduled_start="2026-08-12T00:00:00Z",
                        scheduled_end="2026-08-13T00:00:00Z")
    set_clock("2026-08-12T00:00:00Z")
    advance_run(run2["id"])
    resp2 = api.advance_run(run2["id"], {}, OP)
    validate_error(resp2, ApiErrorId.ERR_DIE_SHAPE_MISMATCH)

    run2_after = get_run(run2["id"])
    assert run2_after["production_status"] == "MIXING"


def test_line_version_increments_on_every_mutation(api):
    """PRD: "A `ProductionOperator` starts cleaning from either
    `GLUTEN_EXPOSED` or `GF_VALIDATED`, moving the line to
    `CLEANING_IN_PROGRESS` and bumping its `version`"
    PRD: "Completing cleaning moves the line to `AWAITING_SWAB`, stamps
    `cleaning_completed_at` with the current clock, and bumps `version` again."
    PRD: "Because scheduling a run consumes line capacity, it also increments
    the line's `version`"

    Design: Corner/cross_cutting_layers/line_version_increments_on_every_mutation
    """
    line = create_line("L-VRM")
    assert line["version"] == 1
    line = start_line_cleaning(line["id"])
    assert line["version"] == 2
    line = complete_line_cleaning(line["id"])
    assert line["version"] == 3

    contract = create_active_contract(contract_code="C-VRM")
    lot = create_accepted_lot(contract["id"], 100.0)
    recipe = create_approved_recipe(recipe_name="Penne VRM")

    resp = api.create_production_run(
        {
            "recipe_id": recipe["id"],
            "line_id": line["id"],
            "semolina_lot_id": lot["id"],
            "planned_input_kg": 50.0,
            "scheduled_start": "2026-08-10T00:00:00Z",
            "scheduled_end": "2026-08-11T00:00:00Z",
            "expected_line_version": 3,
        },
        OP,
    )
    validate_success(resp, 201)
    after = get_line(line["id"])
    assert after["version"] == 4, "run creation increments line.version"
