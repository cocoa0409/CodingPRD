"""Tufting: machine registration, run scheduling, setup gates, face weight,
backing / recoat and doffing roll goods."""

import pytest

from test_helpers import (
    TEST_USERS,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["mill_planner_headers"]
DYER = TEST_USERS["dye_house_operator_headers"]
QA = TEST_USERS["qa_lab_technician_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]

# A syntactically valid UUID that no row in a freshly restarted database owns.
UNKNOWN_RUN_ID = "00000000-0000-4000-8000-000000000404"


# ---------------------------------------------------------------------------
# Local composites. test_helpers/fixtures.py stops at SCHEDULED, TUFTING or
# BACKED; the greige and backing-failure states in this file sit between those
# rungs, so the two helpers below assemble exactly those.
# ---------------------------------------------------------------------------


def _scheduled_run(
    polymer_overrides=None,
    fiber_overrides=None,
    style_overrides=None,
    machine_overrides=None,
    run_overrides=None,
):
    """Polymer -> released creel -> active style -> tufter -> SCHEDULED run."""
    lot = fixtures.create_polymer_lot(**(polymer_overrides or {}))
    batch = fixtures.create_released_fiber_batch(lot["id"], **(fiber_overrides or {}))
    style = fixtures.create_active_style(**(style_overrides or {}))
    machine = fixtures.create_tufting_machine(**(machine_overrides or {}))
    run = fixtures.create_scheduled_run(
        style["id"], machine["id"], batch["id"], **(run_overrides or {})
    )
    return {
        "polymer_lot": lot,
        "fiber_batch": batch,
        "style": style,
        "machine": machine,
        "run": run,
    }


def _greige_run(load_setup_overrides=None, greige_overrides=None, **kwargs):
    """Take the chain above through load-setup and complete-greige to GREIGE."""
    ctx = _scheduled_run(**kwargs)
    ctx["run"] = fixtures.advance_run_to_greige(
        ctx["run"]["id"],
        load_setup_overrides=load_setup_overrides,
        **(greige_overrides or {}),
    )
    return ctx


class TestFaceWeightAtGreigeCompletion:
    def test_cut_pile_product_chain_yields_32_04_oz_per_sy(self, api):
        """A G_1_10 CUT style at 10.0 stitches/in, 8.0 mm pile, 3 plies and 1200.0
        denier closes greige at exactly 32.04 oz/sy.

        PRD: "Begin with needles per inch, looked up from the style's `gauge_code`:
        8.0 needles per inch for `G_1_8`, 10.0 for `G_1_10` and 12.8 for `G_5_64`."
        PRD: "Finally divide by 28.349523 grams per ounce and round half-up to 2
        decimal places; that single rounding, applied only at the very end,
        produces `face_weight_oz_per_sy`."

        Design: Difficulty/combinatorial_formula/face_weight_gauge_lookup_pile_branch_product_chain
        """
        ctx = _scheduled_run(machine_overrides={"changeover_minutes": 60})
        fixtures.advance_run_to_tufting(ctx["run"]["id"])

        data = validate_success(
            api.complete_greige_production_run(
                ctx["run"]["id"], {"greige_yards": 400.0}, PLANNER
            )
        )

        assert data["face_weight_oz_per_sy"] == pytest.approx(32.04, abs=0.01), (
            "the CUT-pile product chain must land on 32.04 oz/sy, got "
            f"{data['face_weight_oz_per_sy']}"
        )
        assert data["status"] == "GREIGE", (
            f"an in-tolerance face weight closes tufting out to GREIGE, got {data['status']}"
        )
        assert data["greige_yards"] == pytest.approx(400.0, abs=0.01), (
            f"greige_yards must record the 400.0 yards produced, got {data['greige_yards']}"
        )

    def test_greige_completion_consumes_the_creel_and_leaves_the_polymer_ledger_balanced(
        self, api
    ):
        """Closing greige moves the creeled batch ALLOCATED -> CONSUMED while the
        4000.000 kg drawn off the 5000.000 kg lot sits in consumed_kg.

        PRD: "On success the run's `status` becomes `GREIGE`, and one cascade fires:
        the creeled fiber batch transitions `ALLOCATED` to `CONSUMED`."
        PRD: "Spinning also moves mass one bucket to the right on each source lot:
        the drawn mass is subtracted from that lot's `reserved_kg` and added to its
        `consumed_kg`, after which each lot's `available_kg` and `status` are
        recomputed."

        Design: Difficulty/combinatorial_formula/face_weight_gauge_lookup_pile_branch_product_chain
        """
        ctx = _scheduled_run(machine_overrides={"changeover_minutes": 60})
        fixtures.advance_run_to_tufting(ctx["run"]["id"])

        validate_success(
            api.complete_greige_production_run(
                ctx["run"]["id"], {"greige_yards": 400.0}, PLANNER
            )
        )

        batch = validate_success(
            api.get_fiber_batch(ctx["fiber_batch"]["id"], PLANNER)
        )
        assert batch["status"] == "CONSUMED", (
            f"the creel is consumed by greige completion, got {batch['status']}"
        )

        lot = validate_success(
            api.get_polymer_lot(ctx["polymer_lot"]["id"], PLANNER)
        )
        assert lot["consumed_kg"] == pytest.approx(4000.000, abs=0.001), (
            f"consumed_kg must be 4000.000 after spinning, got {lot['consumed_kg']}"
        )
        assert lot["available_kg"] == pytest.approx(1000.000, abs=0.001), (
            f"available_kg must be 1000.000 of the 5000.000 received, got {lot['available_kg']}"
        )

    def test_loop_pile_allowance_moves_face_weight_to_34_83(self, api):
        """The same gauge, stitch rate, pile height, denier and plies on a LOOP
        style yields 34.83 oz/sy instead of the CUT branch's 32.04.

        PRD: "Next determine the yarn allowance per tuft, which depends on the
        style's `pile_construction`: 0.0600 inches when the construction is `CUT`
        and 0.1200 inches when it is `LOOP`."

        Design: Corner/calculations/loop_pile_face_weight_uses_the_loop_pile_allowance
        """
        ctx = _scheduled_run(
            style_overrides={
                "style_code": "ST-LP-01",
                "pile_construction": "LOOP",
                "target_face_weight_oz": 35.00,
            },
            machine_overrides={"changeover_minutes": 0},
        )
        fixtures.advance_run_to_tufting(ctx["run"]["id"])

        data = validate_success(
            api.complete_greige_production_run(
                ctx["run"]["id"], {"greige_yards": 400.0}, PLANNER
            )
        )

        assert data["face_weight_oz_per_sy"] == pytest.approx(34.83, abs=0.01), (
            "the LOOP allowance of 0.1200 in must give 34.83 oz/sy, got "
            f"{data['face_weight_oz_per_sy']}"
        )
        assert data["status"] == "GREIGE", (
            f"34.83 against a 35.00 target is in tolerance, got {data['status']}"
        )
        assert data["greige_yards"] == pytest.approx(400.0, abs=0.01), (
            f"greige_yards must be 400.0, got {data['greige_yards']}"
        )

        batch = validate_success(api.get_fiber_batch(ctx["fiber_batch"]["id"], PLANNER))
        assert batch["status"] == "CONSUMED", (
            f"the creel is consumed by greige completion, got {batch['status']}"
        )
        assert batch["denier_actual"] == pytest.approx(1200.0, abs=0.1), (
            f"the creel spun at 1200.0 denier, got {batch['denier_actual']}"
        )

    def test_face_weight_out_of_tolerance_leaves_the_run_in_tufting(self, api):
        """The setup that yields 32.04 oz/sy is refused against a 25.00 target and
        the run stays TUFTING with nothing written.

        PRD: "The tolerance gate is evaluated on the rounded
        `face_weight_oz_per_sy`: the absolute difference between it and the style's
        `target_face_weight_oz` may be at most 1.60 ounces per square yard. Goods
        outside that band are refused with `ERR_FACE_WEIGHT_OUT_OF_TOLERANCE` and
        the run stays in `TUFTING`."

        Design: Corner/validations/face_weight_out_of_tolerance_leaves_the_run_in_tufting
        """
        ctx = _scheduled_run(
            style_overrides={
                "style_code": "ST-LIGHT",
                "target_face_weight_oz": 25.00,
            },
            machine_overrides={"changeover_minutes": 0},
        )
        fixtures.advance_run_to_tufting(ctx["run"]["id"])

        validate_error(
            api.complete_greige_production_run(
                ctx["run"]["id"], {"greige_yards": 400.0}, PLANNER
            ),
            "ERR_FACE_WEIGHT_OUT_OF_TOLERANCE",
        )

        run = validate_success(api.get_production_run(ctx["run"]["id"], PLANNER))
        assert run["status"] == "TUFTING", (
            f"a refused greige close-out leaves the run TUFTING, got {run['status']}"
        )
        assert run["greige_yards"] is None, (
            f"greige_yards must stay null on refusal, got {run['greige_yards']}"
        )
        assert run["face_weight_oz_per_sy"] is None, (
            "face_weight_oz_per_sy must stay null on refusal, got "
            f"{run['face_weight_oz_per_sy']}"
        )

        batch = validate_success(api.get_fiber_batch(ctx["fiber_batch"]["id"], PLANNER))
        assert batch["status"] == "ALLOCATED", (
            f"the creel is not consumed by a refused close-out, got {batch['status']}"
        )


class TestBackingRecoatLoop:
    def test_failed_backing_recoats_back_into_greige_clearing_the_formulation(self, api):
        """A 60-second cure gives 1.55 lbf and BACKING_FAILED; the recoat returns
        the run to GREIGE at recoat_count 1 with the formulation nulled, and the
        second formulation fails again at 1.82 lbf.

        PRD: "Multiply the base strength by the cure index, by the temperature
        factor and by the backing factor, carrying full precision throughout, and
        round the product half-up to 2 decimal places exactly once; that figure is
        `delamination_strength_lbf`."
        PRD: "A permitted recoat increments `recoat_count` by 1, clears `sbr_pct`,
        `filler_load_pct`, `cure_temp_c`, `cure_seconds`, `secondary_backing_type`
        and `delamination_strength_lbf` all back to null, and returns the run's
        `status` to `GREIGE`, from which backing may be applied afresh with a
        different formulation."

        Design: Difficulty/non_linear_state_machine/backing_recoat_loop_reenters_greige_and_stalls_at_recoat_limit
        """
        ctx = _greige_run(machine_overrides={"changeover_minutes": 60})
        run_id = ctx["run"]["id"]

        first = validate_success(
            api.apply_backing_production_run(
                run_id,
                {
                    "sbr_pct": 70.0,
                    "filler_load_pct": 20.0,
                    "cure_temp_c": 150,
                    "cure_seconds": 60,
                    "secondary_backing_type": "ACTION_BAC",
                },
                PLANNER,
            )
        )
        assert first["delamination_strength_lbf"] == pytest.approx(1.55, abs=0.01), (
            "a 60-second cure halves the 3.10 lbf base to 1.55, got "
            f"{first['delamination_strength_lbf']}"
        )
        assert first["status"] == "BACKING_FAILED", (
            f"1.55 lbf is below 2.50 so the run fails backing, got {first['status']}"
        )
        assert first["recoat_count"] == 0, (
            f"the first failure has not consumed a recoat, got {first['recoat_count']}"
        )

        recoated = validate_success(api.recoat_production_run(run_id, PLANNER))
        assert recoated["status"] == "GREIGE", (
            f"a recoat returns the run to GREIGE, got {recoated['status']}"
        )
        assert recoated["recoat_count"] == 1, (
            f"a recoat increments recoat_count to 1, got {recoated['recoat_count']}"
        )
        assert recoated["delamination_strength_lbf"] is None, (
            "the recoat clears delamination_strength_lbf, got "
            f"{recoated['delamination_strength_lbf']}"
        )
        for field in (
            "sbr_pct",
            "filler_load_pct",
            "cure_temp_c",
            "cure_seconds",
            "secondary_backing_type",
        ):
            assert recoated[field] is None, (
                f"the recoat clears {field}, got {recoated[field]}"
            )
        assert recoated["greige_yards"] == pytest.approx(400.0, abs=0.01), (
            f"the greige result survives the loop, got {recoated['greige_yards']}"
        )
        assert recoated["face_weight_oz_per_sy"] == pytest.approx(32.04, abs=0.01), (
            "face_weight_oz_per_sy survives the loop, got "
            f"{recoated['face_weight_oz_per_sy']}"
        )

        second = validate_success(
            api.apply_backing_production_run(
                run_id,
                {
                    "sbr_pct": 60.0,
                    "filler_load_pct": 20.0,
                    "cure_temp_c": 130,
                    "cure_seconds": 120,
                    "secondary_backing_type": "ACTION_BAC",
                },
                PLANNER,
            )
        )
        assert second["delamination_strength_lbf"] == pytest.approx(1.82, abs=0.01), (
            "a 130 C cure applies the 0.88 factor to 2.60 lbf giving 1.82, got "
            f"{second['delamination_strength_lbf']}"
        )
        assert second["status"] == "BACKING_FAILED", (
            f"1.82 lbf fails backing a second time, got {second['status']}"
        )

    def test_second_recoat_is_refused_and_the_parked_run_cannot_be_doffed(self, api):
        """After one recoat the run is stuck in BACKING_FAILED: a second recoat is
        ERR_RECOAT_LIMIT_REACHED and doffing a roll is ERR_RUN_NOT_BACKED.

        PRD: "Recoating requires the run to be in `BACKING_FAILED` and requires its
        `recoat_count` to be strictly less than the recoat limit of 1 — a run that
        has already been recoated once is refused with
        `ERR_RECOAT_LIMIT_REACHED`."
        PRD: "The run must be in `BACKED` or `RELEASED`; doffing off a run in any
        other status is refused with `ERR_RUN_NOT_BACKED`."

        Design: Difficulty/non_linear_state_machine/backing_recoat_loop_reenters_greige_and_stalls_at_recoat_limit
        """
        ctx = _greige_run(machine_overrides={"changeover_minutes": 60})
        run_id = ctx["run"]["id"]

        fixtures.apply_backing(run_id, cure_seconds=60)
        get_success_data(api.recoat_production_run(run_id, PLANNER))
        fixtures.apply_backing(
            run_id, sbr_pct=60.0, cure_temp_c=130, cure_seconds=120
        )

        validate_error(
            api.recoat_production_run(run_id, PLANNER), "ERR_RECOAT_LIMIT_REACHED"
        )

        run = validate_success(api.get_production_run(run_id, PLANNER))
        assert run["status"] == "BACKING_FAILED", (
            f"the refused recoat leaves the run parked in BACKING_FAILED, got {run['status']}"
        )
        assert run["recoat_count"] == 1, (
            f"the refused recoat does not move recoat_count, got {run['recoat_count']}"
        )

        validate_error(
            api.doff_roll_good(
                run_id,
                {"roll_number": "RG-01", "width_ft": 12.0, "initial_yards": 200.0},
                PLANNER,
            ),
            "ERR_RUN_NOT_BACKED",
        )

        rolls, meta = validate_paginated(
            api.list_roll_goods(PLANNER, params={"limit": 100, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"the refused doff creates no RollGood, got total_count {meta['total_count']}"
        )
        assert not [r for r in rolls if r["roll_number"] == "RG-01"], (
            "no roll numbered RG-01 may exist after the refused doff"
        )

    def test_delamination_of_2_48_is_strictly_below_the_floor_and_fails_backing(
        self, api
    ):
        """51 points of filler give 2.48 lbf, strictly below 2.50, so the run goes
        GREIGE -> BACKING_FAILED.

        PRD: "When it is strictly below 2.50, the run transitions `GREIGE` to
        `BACKING_FAILED` instead; the formulation inputs and the computed strength
        are still persisted, so the operator can see exactly which lever was
        short."

        Design: Difficulty/boundary_precision_check/delamination_min_lbf_boundary_inclusive_at_two_point_five_zero
        """
        ctx = _greige_run(machine_overrides={"changeover_minutes": 60})

        data = validate_success(
            api.apply_backing_production_run(
                ctx["run"]["id"],
                {
                    "sbr_pct": 70.0,
                    "filler_load_pct": 51.0,
                    "cure_temp_c": 150,
                    "cure_seconds": 120,
                    "secondary_backing_type": "ACTION_BAC",
                },
                PLANNER,
            )
        )

        assert data["delamination_strength_lbf"] == pytest.approx(2.48, abs=0.01), (
            "3.50 lbf less 1.02 lbf of filler penalty is 2.48, got "
            f"{data['delamination_strength_lbf']}"
        )
        assert data["status"] == "BACKING_FAILED", (
            f"2.48 lbf is strictly below the 2.50 floor, got {data['status']}"
        )
        assert data["filler_load_pct"] == pytest.approx(51.0, abs=0.1), (
            f"the formulation inputs are persisted anyway, got {data['filler_load_pct']}"
        )

    def test_delamination_of_exactly_2_50_is_admitted_and_backs_the_run(self, api):
        """One point less filler gives exactly 2.50 lbf, which the "at least"
        comparison admits, so the same run backs after its recoat.

        PRD: "When `delamination_strength_lbf` is at least 2.50, the run
        transitions `GREIGE` to `BACKED`, which makes it eligible for roll-good
        creation."

        Design: Difficulty/boundary_precision_check/delamination_min_lbf_boundary_inclusive_at_two_point_five_zero
        """
        ctx = _greige_run(machine_overrides={"changeover_minutes": 60})
        run_id = ctx["run"]["id"]

        failed = fixtures.apply_backing(run_id, sbr_pct=70.0, filler_load_pct=51.0)
        assert failed["delamination_strength_lbf"] == pytest.approx(2.48, abs=0.01), (
            f"the 51-point run must be 2.48 lbf, got {failed['delamination_strength_lbf']}"
        )

        recoated = validate_success(api.recoat_production_run(run_id, PLANNER))
        assert recoated["status"] == "GREIGE", (
            f"the recoat reopens backing from GREIGE, got {recoated['status']}"
        )
        assert recoated["recoat_count"] == 1, (
            f"the recoat increments recoat_count to 1, got {recoated['recoat_count']}"
        )

        data = validate_success(
            api.apply_backing_production_run(
                run_id,
                {
                    "sbr_pct": 70.0,
                    "filler_load_pct": 50.0,
                    "cure_temp_c": 150,
                    "cure_seconds": 120,
                    "secondary_backing_type": "ACTION_BAC",
                },
                PLANNER,
            )
        )
        assert data["delamination_strength_lbf"] == pytest.approx(2.50, abs=0.01), (
            "3.50 lbf less 1.00 lbf of filler penalty is exactly 2.50, got "
            f"{data['delamination_strength_lbf']}"
        )
        assert data["status"] == "BACKED", (
            f"exactly 2.50 lbf is admitted by the at-least comparison, got {data['status']}"
        )


class TestRunSchedulingWindow:
    def test_leading_changeover_buffer_makes_a_1659_start_conflict(self, api):
        """PR-01 occupies 07:00..16:00 on a 60-minute-changeover tufter, so a run
        starting 16:59 has an effective start of 15:59 and is refused.

        PRD: "A run's occupancy window begins at its `scheduled_start_utc` minus
        the tufter's `changeover_minutes` and ends at its `scheduled_end_utc`"
        PRD: "falls exactly on an existing run's `scheduled_end_utc` is admissible,
        while one minute earlier is a conflict. A conflict is refused with
        `ERR_MACHINE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tufter_window_exclusive_with_leading_changeover_and_half_open_end
        """
        lot = fixtures.create_polymer_lot(received_kg=9000.0)
        fb1 = fixtures.create_released_fiber_batch(lot["id"], batch_code="FB-01")
        fb2 = fixtures.create_released_fiber_batch(lot["id"], batch_code="FB-02")
        style = fixtures.create_active_style()
        machine = fixtures.create_tufting_machine(changeover_minutes=60)
        fixtures.create_scheduled_run(
            style["id"], machine["id"], fb1["id"], run_code="PR-01"
        )

        validate_error(
            api.create_production_run(
                factories.create_production_run_payload(
                    style["id"],
                    machine["id"],
                    fb2["id"],
                    run_code="PR-02",
                    scheduled_start_utc="2026-08-05T16:59:00Z",
                    scheduled_end_utc="2026-08-06T00:59:00Z",
                ),
                PLANNER,
            ),
            "ERR_MACHINE_WINDOW_CONFLICT",
        )

        runs, meta = validate_paginated(
            api.list_production_runs(PLANNER, params={"limit": 100, "offset": 0})
        )
        assert not [r for r in runs if r["run_code"] == "PR-02"], (
            "the refused scheduling must not persist a run coded PR-02"
        )
        assert meta["total_count"] == 1, (
            f"only PR-01 should exist, got total_count {meta['total_count']}"
        )

        batch = validate_success(api.get_fiber_batch(fb2["id"], PLANNER))
        assert batch["status"] == "RELEASED", (
            f"a refused scheduling does not reserve the creel, got {batch['status']}"
        )

    def test_effective_start_landing_on_the_existing_end_is_admitted(self, api):
        """A run starting 17:00 has an effective start of exactly 16:00, which the
        exclusive end of PR-01's window admits, and the creel is reserved.

        PRD: "Because the end of the window is exclusive, a new run whose effective
        start — that is, its `scheduled_start_utc` less the changeover buffer —
        falls exactly on an existing run's `scheduled_end_utc` is admissible, while
        one minute earlier is a conflict."
        PRD: "The style must be in `ACTIVE`; the fiber batch must be in `RELEASED`
        and is moved to `ALLOCATED` by the scheduling itself."

        Design: Difficulty/resource_temporal_overlap/tufter_window_exclusive_with_leading_changeover_and_half_open_end
        """
        lot = fixtures.create_polymer_lot(received_kg=9000.0)
        fb1 = fixtures.create_released_fiber_batch(lot["id"], batch_code="FB-01")
        fb2 = fixtures.create_released_fiber_batch(lot["id"], batch_code="FB-02")
        style = fixtures.create_active_style()
        machine = fixtures.create_tufting_machine(changeover_minutes=60)
        pr1 = fixtures.create_scheduled_run(
            style["id"], machine["id"], fb1["id"], run_code="PR-01"
        )

        data = validate_success(
            api.create_production_run(
                factories.create_production_run_payload(
                    style["id"],
                    machine["id"],
                    fb2["id"],
                    run_code="PR-03",
                    scheduled_start_utc="2026-08-05T17:00:00Z",
                    scheduled_end_utc="2026-08-06T01:00:00Z",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        assert data["status"] == "SCHEDULED", (
            f"the admitted run starts SCHEDULED, got {data['status']}"
        )

        batch = validate_success(api.get_fiber_batch(fb2["id"], PLANNER))
        assert batch["status"] == "ALLOCATED", (
            f"scheduling reserves the creel as ALLOCATED, got {batch['status']}"
        )

        existing = validate_success(api.get_production_run(pr1["id"], PLANNER))
        assert existing["status"] == "SCHEDULED", (
            f"PR-01 is untouched by the second booking, got {existing['status']}"
        )
        assert existing["scheduled_end_utc"].startswith("2026-08-05T16:00:00"), (
            "PR-01's window still ends at 2026-08-05T16:00:00Z, got "
            f"{existing['scheduled_end_utc']}"
        )

    def test_new_run_starts_scheduled_with_zero_recoat_count_and_null_setup(self, api):
        """The creation response itself shows SCHEDULED, recoat_count 0, version 1
        and null setup / greige / backing fields, with the creel already reserved.

        PRD: "A newly scheduled run has a `status` of `SCHEDULED` and a
        `recoat_count` of 0, and its setup, greige, backing and computed fields are
        all null."
        PRD: "`version` — an integer that starts at 1 on creation and increases by
        exactly 1 on every mutation of the record."

        Design: Corner/state_machines/new_production_run_starts_scheduled_with_zero_recoat_count
        """
        lot = fixtures.create_polymer_lot()
        batch = fixtures.create_released_fiber_batch(lot["id"])
        style = fixtures.create_active_style()
        machine = fixtures.create_tufting_machine(changeover_minutes=0)

        data = validate_success(
            api.create_production_run(
                factories.create_production_run_payload(
                    style["id"], machine["id"], batch["id"]
                ),
                PLANNER,
            ),
            expected_status=201,
        )

        assert data["status"] == "SCHEDULED", (
            f"a new run starts SCHEDULED, got {data['status']}"
        )
        assert data["recoat_count"] == 0, (
            f"a new run starts at recoat_count 0, got {data['recoat_count']}"
        )
        assert data["gauge_loaded_code"] is None, (
            f"setup fields start null, got gauge_loaded_code {data['gauge_loaded_code']}"
        )
        assert data["greige_yards"] is None, (
            f"greige fields start null, got greige_yards {data['greige_yards']}"
        )
        assert data["face_weight_oz_per_sy"] is None, (
            "computed fields start null, got face_weight_oz_per_sy "
            f"{data['face_weight_oz_per_sy']}"
        )
        assert data["delamination_strength_lbf"] is None, (
            "backing fields start null, got delamination_strength_lbf "
            f"{data['delamination_strength_lbf']}"
        )
        assert data["version"] == 1, f"version starts at 1, got {data['version']}"

        refreshed = validate_success(api.get_fiber_batch(batch["id"], PLANNER))
        assert refreshed["status"] == "ALLOCATED", (
            f"the creel reservation already happened, got {refreshed['status']}"
        )

    def test_scheduled_end_before_start_is_a_malformed_request(self, api):
        """An inverted booking window is rejected as malformed and reserves nothing.

        PRD: "every datetime is ISO 8601 UTC, `limit` lies in the inclusive range 1
        through 100 and `offset` is not negative, `scheduled_end_utc` is strictly
        later than `scheduled_start_utc`"
        PRD: "and `accounting_basis` is either `MASS_BALANCE` or
        `PHYSICAL_SEGREGATION` exactly when `cert_type` is `NSF_140`. Failures here
        are `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/production_run_scheduled_end_before_start_returns_invalid_request
        """
        lot = fixtures.create_polymer_lot()
        batch = fixtures.create_released_fiber_batch(lot["id"])
        style = fixtures.create_active_style()
        machine = fixtures.create_tufting_machine(changeover_minutes=0)

        validate_error(
            api.create_production_run(
                factories.create_production_run_payload(
                    style["id"],
                    machine["id"],
                    batch["id"],
                    scheduled_start_utc="2026-08-05T16:00:00Z",
                    scheduled_end_utc="2026-08-05T08:00:00Z",
                ),
                PLANNER,
            ),
            "ERR_INVALID_REQUEST",
        )

        refreshed = validate_success(api.get_fiber_batch(batch["id"], PLANNER))
        assert refreshed["status"] == "RELEASED", (
            f"a malformed booking leaves the creel RELEASED, got {refreshed['status']}"
        )
        refreshed_style = validate_success(api.get_style(style["id"], PLANNER))
        assert refreshed_style["status"] == "ACTIVE", (
            f"the style is untouched by the malformed booking, got {refreshed_style['status']}"
        )


class TestEquipmentRegistrationDefaults:
    def test_tufter_defaults_to_idle_and_vessel_defaults_to_available(self, api):
        """Omitting status yields IDLE on a tufter and AVAILABLE on a vessel, while
        an explicit MAINTENANCE is honoured on both.

        PRD: "A machine's `status` is an operator-maintained availability posture of
        either `IDLE` or `MAINTENANCE`, defaulting to `IDLE`"
        PRD: "a `status` of either `AVAILABLE` or `MAINTENANCE`, defaulting to
        `AVAILABLE`"

        Design: Corner/entities/tufting_machine_and_dye_vessel_status_default_to_idle_and_available
        """
        tm1 = validate_success(
            api.create_tufting_machine(
                factories.create_tufting_machine_payload(machine_code="TM-01"),
                PLANNER,
            ),
            expected_status=201,
        )
        tm2 = validate_success(
            api.create_tufting_machine(
                factories.create_tufting_machine_payload(
                    machine_code="TM-02",
                    native_gauge_code="G_1_8",
                    changeover_minutes=0,
                    status="MAINTENANCE",
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        dv1 = validate_success(
            api.create_dye_vessel(
                factories.create_dye_vessel_payload(vessel_code="DV-01"), DYER
            ),
            expected_status=201,
        )
        dv2 = validate_success(
            api.create_dye_vessel(
                factories.create_dye_vessel_payload(
                    vessel_code="DV-02",
                    vessel_type="JET",
                    capacity_kg=900.0,
                    status="MAINTENANCE",
                ),
                DYER,
            ),
            expected_status=201,
        )

        assert tm1["status"] == "IDLE", (
            f"an omitted machine status defaults to IDLE, got {tm1['status']}"
        )
        assert tm2["status"] == "MAINTENANCE", (
            f"an explicit MAINTENANCE posture is honoured, got {tm2['status']}"
        )
        assert dv1["status"] == "AVAILABLE", (
            f"an omitted vessel status defaults to AVAILABLE, got {dv1['status']}"
        )
        assert dv2["status"] == "MAINTENANCE", (
            f"an explicit MAINTENANCE posture is honoured, got {dv2['status']}"
        )


class TestLoadSetupGates:
    def test_load_setup_before_the_booked_window_opens_is_refused(self, api):
        """With the clock still at its 2026-08-01 startup value an in-spec setup is
        refused, and the identical payload succeeds once the clock reaches 08:00.

        PRD: "The logical clock must have reached the run's `scheduled_start_utc`;
        loading a run whose window has not opened is refused with
        `ERR_RUN_WINDOW_NOT_OPEN`."
        PRD: "The response reports the resulting `current_utc` together with three
        arrays recording what the move set in motion: `lapsed_certification_ids`,
        `suspended_style_ids` and `held_production_run_ids`."

        Design: Corner/state_machines/load_setup_before_scheduled_start_returns_run_window_not_open
        """
        ctx = _scheduled_run(machine_overrides={"changeover_minutes": 0})
        run_id = ctx["run"]["id"]

        validate_error(
            api.load_setup_production_run(
                run_id, factories.load_setup_payload(), PLANNER
            ),
            "ERR_RUN_WINDOW_NOT_OPEN",
        )

        early = validate_success(api.get_production_run(run_id, PLANNER))
        assert early["status"] == "SCHEDULED", (
            f"an early load leaves the run SCHEDULED, got {early['status']}"
        )
        assert early["gauge_loaded_code"] is None, (
            f"an early load persists no setup, got {early['gauge_loaded_code']}"
        )

        clock = validate_success(
            api.set_clock({"to_iso8601": "2026-08-05T08:00:00Z"}, ADMIN)
        )
        assert clock["current_utc"].startswith("2026-08-05T08:00:00"), (
            f"the clock must report the instant it moved to, got {clock['current_utc']}"
        )
        assert clock["lapsed_certification_ids"] == [], (
            f"no certificate exists to lapse, got {clock['lapsed_certification_ids']}"
        )
        assert clock["suspended_style_ids"] == [], (
            f"no style is suspended by the move, got {clock['suspended_style_ids']}"
        )
        assert clock["held_production_run_ids"] == [], (
            f"no run is held by the move, got {clock['held_production_run_ids']}"
        )

        loaded = validate_success(
            api.load_setup_production_run(
                run_id, factories.load_setup_payload(), PLANNER
            )
        )
        assert loaded["status"] == "TUFTING", (
            f"the same payload tufts once the window is open, got {loaded['status']}"
        )
        assert loaded["stitch_rate_per_inch"] == pytest.approx(10.0, abs=0.1), (
            f"the dialled stitch rate is persisted, got {loaded['stitch_rate_per_inch']}"
        )

    def test_setup_checks_style_gauge_then_pile_deviation_then_pattern_repeat(
        self, api
    ):
        """Peeling the setup chain apart: a payload violating gauge and pattern
        repeat reports the gauge error; fixing the gauge exposes the 0.6 mm pile
        deviation; at 8.5 mm the pattern-repeat error surfaces; then it tufts.

        PRD: "Five setup checks then run, in this fixed order, and the first to
        fail decides the error."
        PRD: "The loaded gauge must equal the style's `gauge_code`, failing which
        the refusal is `ERR_GAUGE_MISMATCH`."
        PRD: "the absolute difference between `pile_height_set_mm` and the style's
        `pile_height_mm` may be at most 0.5 mm, and a larger deviation is refused
        with `ERR_PILE_HEIGHT_SPEC_DEVIATION`"
        PRD: "Finally the loaded `pattern_repeat_loaded_mm` must equal the style's
        `pattern_repeat_mm` exactly, failing which the refusal is
        `ERR_PATTERN_REPEAT_MISMATCH`."

        Design: Corner/validations/tufter_setup_checks_style_gauge_then_pile_deviation_then_pattern_repeat
        """
        ctx = _scheduled_run(machine_overrides={"changeover_minutes": 0})
        run_id = ctx["run"]["id"]
        fixtures.set_clock("2026-08-05T08:00:00Z")

        attempts = [
            (
                {
                    "gauge_loaded_code": "G_1_8",
                    "pile_height_set_mm": 8.0,
                    "pattern_repeat_loaded_mm": 200.0,
                    "stitch_rate_per_inch": 10.0,
                },
                "ERR_GAUGE_MISMATCH",
            ),
            (
                {
                    "gauge_loaded_code": "G_1_10",
                    "pile_height_set_mm": 8.6,
                    "pattern_repeat_loaded_mm": 200.0,
                    "stitch_rate_per_inch": 10.0,
                },
                "ERR_PILE_HEIGHT_SPEC_DEVIATION",
            ),
            (
                {
                    "gauge_loaded_code": "G_1_10",
                    "pile_height_set_mm": 8.5,
                    "pattern_repeat_loaded_mm": 200.0,
                    "stitch_rate_per_inch": 10.0,
                },
                "ERR_PATTERN_REPEAT_MISMATCH",
            ),
        ]
        for payload, expected_error in attempts:
            validate_error(
                api.load_setup_production_run(run_id, payload, PLANNER),
                expected_error,
            )
            interim = validate_success(api.get_production_run(run_id, PLANNER))
            assert interim["status"] == "SCHEDULED", (
                f"a refusal with {expected_error} leaves the run SCHEDULED, got "
                f"{interim['status']}"
            )

        loaded = validate_success(
            api.load_setup_production_run(
                run_id,
                {
                    "gauge_loaded_code": "G_1_10",
                    "pile_height_set_mm": 8.5,
                    "pattern_repeat_loaded_mm": 300.0,
                    "stitch_rate_per_inch": 10.0,
                },
                PLANNER,
            )
        )
        assert loaded["status"] == "TUFTING", (
            f"the fully correct payload tufts, got {loaded['status']}"
        )
        assert loaded["pile_height_set_mm"] == pytest.approx(8.5, abs=0.1), (
            f"the dialled 8.5 mm is persisted, got {loaded['pile_height_set_mm']}"
        )
        assert loaded["pattern_repeat_loaded_mm"] == pytest.approx(300.0, abs=0.1), (
            f"the loaded 300.0 mm repeat is persisted, got {loaded['pattern_repeat_loaded_mm']}"
        )

    def test_machine_gauge_and_pile_range_precede_the_spec_deviation_check(self, api):
        """On a G_1_8 tufter a style-correct G_1_10 setup fails machine
        compatibility; on a 9.0-14.0 mm tufter the style-perfect 8.0 mm fails range
        even at zero deviation, and 9.0 mm then fails the deviation check.

        PRD: "The loaded gauge must also equal the tufter's `native_gauge_code`,
        because a needle bar cannot be re-gauged on the fly, failing which the
        refusal is `ERR_MACHINE_GAUGE_INCOMPATIBLE`."
        PRD: "The dialled `pile_height_set_mm` must lie within the tufter's
        inclusive envelope — at least the machine's `min_pile_height_mm` and at most
        its `max_pile_height_mm` — failing which the refusal is
        `ERR_PILE_HEIGHT_OUT_OF_RANGE`."

        Design: Corner/validations/tufter_setup_checks_machine_gauge_before_the_pile_height_range
        """
        lot = fixtures.create_polymer_lot(received_kg=8000.0)
        fb_a = fixtures.create_released_fiber_batch(lot["id"], batch_code="FB-A")
        fb_b = fixtures.create_released_fiber_batch(lot["id"], batch_code="FB-B")
        style = fixtures.create_active_style()
        tm8 = fixtures.create_tufting_machine(
            machine_code="TM-08", native_gauge_code="G_1_8", changeover_minutes=0
        )
        tm10 = fixtures.create_tufting_machine(
            machine_code="TM-10",
            native_gauge_code="G_1_10",
            min_pile_height_mm=9.0,
            max_pile_height_mm=14.0,
            changeover_minutes=0,
        )
        pr8 = fixtures.create_scheduled_run(
            style["id"], tm8["id"], fb_a["id"], run_code="PR-08"
        )
        pr10 = fixtures.create_scheduled_run(
            style["id"], tm10["id"], fb_b["id"], run_code="PR-10"
        )
        fixtures.set_clock("2026-08-05T08:00:00Z")

        in_spec = {
            "gauge_loaded_code": "G_1_10",
            "pile_height_set_mm": 8.0,
            "pattern_repeat_loaded_mm": 300.0,
            "stitch_rate_per_inch": 10.0,
        }

        validate_error(
            api.load_setup_production_run(pr8["id"], dict(in_spec), PLANNER),
            "ERR_MACHINE_GAUGE_INCOMPATIBLE",
        )
        validate_error(
            api.load_setup_production_run(pr10["id"], dict(in_spec), PLANNER),
            "ERR_PILE_HEIGHT_OUT_OF_RANGE",
        )

        in_range = dict(in_spec, pile_height_set_mm=9.0)
        validate_error(
            api.load_setup_production_run(pr10["id"], in_range, PLANNER),
            "ERR_PILE_HEIGHT_SPEC_DEVIATION",
        )

        for run_id, label in ((pr8["id"], "PR-08"), (pr10["id"], "PR-10")):
            run = validate_success(api.get_production_run(run_id, PLANNER))
            assert run["status"] == "SCHEDULED", (
                f"{label} stays SCHEDULED after a refused setup, got {run['status']}"
            )

    def test_complete_greige_from_scheduled_is_an_invalid_state(self, api):
        """complete-greige is declared only from TUFTING, so firing it on a
        SCHEDULED run inside its window is ERR_INVALID_STATE.

        PRD: "Closing out tufting advances the run from `TUFTING` to `GREIGE` and
        carries a single input, `greige_yards`"
        PRD: "The target resource is in a status from which the requested
        transition is declared. The generic failure is `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/complete_greige_from_scheduled_returns_invalid_state
        """
        ctx = _scheduled_run(machine_overrides={"changeover_minutes": 0})
        run_id = ctx["run"]["id"]
        fixtures.set_clock("2026-08-05T08:00:00Z")

        validate_error(
            api.complete_greige_production_run(
                run_id, {"greige_yards": 400.0}, PLANNER
            ),
            "ERR_INVALID_STATE",
        )

        run = validate_success(api.get_production_run(run_id, PLANNER))
        assert run["status"] == "SCHEDULED", (
            f"the refused close-out leaves the run SCHEDULED, got {run['status']}"
        )
        assert run["greige_yards"] is None, (
            f"greige_yards must stay null, got {run['greige_yards']}"
        )
        assert run["face_weight_oz_per_sy"] is None, (
            f"face weight is never computed, got {run['face_weight_oz_per_sy']}"
        )

        batch = validate_success(api.get_fiber_batch(ctx["fiber_batch"]["id"], PLANNER))
        assert batch["status"] == "ALLOCATED", (
            f"the creel stays ALLOCATED, got {batch['status']}"
        )


class TestDoffingRollGoods:
    def test_doffing_under_an_unknown_run_reports_the_parent_not_found(self, api):
        """A roll good is only reachable through a run path segment, so an unknown
        parent id is a 404 on the run and no roll is created.

        PRD: "A request for a sub-resource under a parent that does not exist
        reports the parent's not-found error and never looks for the child."

        Design: Corner/entities/doff_roll_good_under_unknown_production_run_returns_not_found
        """
        fixtures.create_tufting_machine(changeover_minutes=0)

        validate_error(
            api.doff_roll_good(
                UNKNOWN_RUN_ID,
                {"roll_number": "RG-01", "width_ft": 12.0, "initial_yards": 200.0},
                PLANNER,
            ),
            "ERR_PRODUCTION_RUN_NOT_FOUND",
        )

        _, meta = validate_paginated(
            api.list_roll_goods(PLANNER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"no RollGood may be created, got total_count {meta['total_count']}"
        )

    def test_first_roll_passing_qa_releases_the_run(self, api):
        """Releasing the run's first roll flips the roll to PASSED / AVAILABLE and
        drives ProductionRun BACKED -> RELEASED in the same request.

        PRD: "Release sets `qa_status` to `PASSED` and, on the independent inventory
        dimension, moves `inventory_status` from `IN_PROCESS` to `AVAILABLE`. It
        also cascades upward: when this is the first roll of the run to reach
        `PASSED`, the run transitions `BACKED` to `RELEASED`."
        PRD: "a solution-dyed roll takes a `shade_band` of `SOLUTION`"

        Design: Corner/state_machines/run_auto_releases_when_its_first_roll_passes_qa
        """
        ctx = fixtures.setup_backed_solution_dyed_run(
            machine_overrides={"changeover_minutes": 0}
        )
        roll = fixtures.doff_roll_good(ctx["run"]["id"])

        before = validate_success(api.get_production_run(ctx["run"]["id"], PLANNER))
        assert before["status"] == "BACKED", (
            f"the run must be BACKED before inspection, got {before['status']}"
        )
        assert before["delamination_strength_lbf"] == pytest.approx(3.10, abs=0.01), (
            "the default formulation gives 3.10 lbf, got "
            f"{before['delamination_strength_lbf']}"
        )
        assert roll["qa_status"] == "PENDING", (
            f"a doffed roll starts PENDING on quality, got {roll['qa_status']}"
        )
        assert roll["inventory_status"] == "IN_PROCESS", (
            f"a doffed roll starts IN_PROCESS, got {roll['inventory_status']}"
        )

        released = validate_success(
            api.qa_disposition_roll_good(roll["id"], {"disposition": "RELEASE"}, QA)
        )
        assert released["qa_status"] == "PASSED", (
            f"RELEASE sets qa_status to PASSED, got {released['qa_status']}"
        )
        assert released["inventory_status"] == "AVAILABLE", (
            f"RELEASE moves inventory to AVAILABLE, got {released['inventory_status']}"
        )
        assert released["available_yards"] == pytest.approx(200.0, abs=0.1), (
            f"the full 200.0 yards are sellable, got {released['available_yards']}"
        )
        assert released["shade_band"] == "SOLUTION", (
            f"a solution-dyed roll bands SOLUTION, got {released['shade_band']}"
        )
        assert released["is_remnant"] is False, (
            f"a doffed roll is not a remnant, got {released['is_remnant']}"
        )

        after = validate_success(api.get_production_run(ctx["run"]["id"], PLANNER))
        assert after["status"] == "RELEASED", (
            f"the first passing roll releases the run, got {after['status']}"
        )
        batch = validate_success(api.get_fiber_batch(ctx["fiber_batch"]["id"], PLANNER))
        assert batch["status"] == "CONSUMED", (
            f"the creel was consumed at greige completion, got {batch['status']}"
        )

    def test_dye_lot_linkage_on_a_roll_follows_the_runs_dyeing_route(self, api):
        """dye_lot_id is forbidden on a solution-dyed run and mandatory on a
        piece-dyed one; the compliant pair takes bands SOLUTION and A.

        PRD: "a roll doffed off a piece-dyed run must name a `dye_lot_id`, and
        omitting it is refused with `ERR_DYE_LOT_REQUIRED`, while a roll doffed off
        a solution-dyed run must omit it, and supplying it is refused with
        `ERR_SOLUTION_DYED_NO_DYE_LOT`"
        PRD: "The named run's style must have a `dye_method` of `PIECE_DYED` —
        formulating a lot against a solution-dyed style's run is refused with
        `ERR_DYE_METHOD_MISMATCH`"
        PRD: "A piece-dyed roll copies its `shade_band` from the named dye lot at
        the moment of creation"

        Design: Corner/validations/roll_good_dye_lot_linkage_must_follow_the_runs_dyeing_route
        """
        lot = fixtures.create_polymer_lot(received_kg=8000.0)
        fb_pd = fixtures.create_released_fiber_batch(
            lot["id"],
            batch_code="FB-PD",
            dye_method="PIECE_DYED_READY",
            solution_color_code=None,
        )
        fb_sd = fixtures.create_released_fiber_batch(lot["id"], batch_code="FB-SD")
        style_pd = fixtures.create_active_piece_dyed_style()
        style_sd = fixtures.create_active_style()
        tm1 = fixtures.create_tufting_machine(
            machine_code="TM-01", changeover_minutes=0
        )
        tm2 = fixtures.create_tufting_machine(
            machine_code="TM-02", changeover_minutes=0
        )
        vessel = fixtures.create_dye_vessel()
        run_pd = fixtures.create_scheduled_run(
            style_pd["id"], tm1["id"], fb_pd["id"], run_code="PR-PD"
        )
        run_sd = fixtures.create_scheduled_run(
            style_sd["id"], tm2["id"], fb_sd["id"], run_code="PR-SD"
        )
        fixtures.advance_run_to_backed(run_pd["id"])
        fixtures.advance_run_to_backed(run_sd["id"])
        dye_lot = fixtures.create_approved_dye_lot(
            run_pd["id"],
            vessel["id"],
            measurement_overrides={
                "measured_lab_l": 55.5,
                "measured_lab_a": 12.63,
                "measured_lab_b": -8.0,
            },
        )
        assert dye_lot["shade_band"] == "A", (
            f"a delta_e of 0.80 bands A, got {dye_lot['shade_band']}"
        )

        validate_error(
            api.create_dye_lot(
                factories.create_dye_lot_payload(
                    run_sd["id"],
                    vessel["id"],
                    lot_code="DL-BAD",
                    dye_start_utc="2026-08-07T08:00:00Z",
                    dye_end_utc="2026-08-07T14:00:00Z",
                ),
                DYER,
            ),
            "ERR_DYE_METHOD_MISMATCH",
        )
        validate_error(
            api.doff_roll_good(
                run_sd["id"],
                {
                    "roll_number": "RG-SD-BAD",
                    "width_ft": 12.0,
                    "initial_yards": 100.0,
                    "dye_lot_id": dye_lot["id"],
                },
                PLANNER,
            ),
            "ERR_SOLUTION_DYED_NO_DYE_LOT",
        )
        validate_error(
            api.doff_roll_good(
                run_pd["id"],
                {
                    "roll_number": "RG-PD-BAD",
                    "width_ft": 12.0,
                    "initial_yards": 100.0,
                },
                PLANNER,
            ),
            "ERR_DYE_LOT_REQUIRED",
        )

        roll_sd = validate_success(
            api.doff_roll_good(
                run_sd["id"],
                {
                    "roll_number": "RG-SD-OK",
                    "width_ft": 12.0,
                    "initial_yards": 100.0,
                },
                PLANNER,
            ),
            expected_status=201,
        )
        assert roll_sd["dye_lot_id"] is None, (
            f"a solution-dyed roll carries no dye lot, got {roll_sd['dye_lot_id']}"
        )
        assert roll_sd["shade_band"] == "SOLUTION", (
            f"a solution-dyed roll bands SOLUTION, got {roll_sd['shade_band']}"
        )

        roll_pd = validate_success(
            api.doff_roll_good(
                run_pd["id"],
                {
                    "roll_number": "RG-PD-OK",
                    "width_ft": 12.0,
                    "initial_yards": 100.0,
                    "dye_lot_id": dye_lot["id"],
                },
                PLANNER,
            ),
            expected_status=201,
        )
        assert roll_pd["dye_lot_id"] == dye_lot["id"], (
            f"a piece-dyed roll names its lot, got {roll_pd['dye_lot_id']}"
        )
        assert roll_pd["shade_band"] == "A", (
            f"a piece-dyed roll copies band A off its lot, got {roll_pd['shade_band']}"
        )

        _, roll_meta = validate_paginated(
            api.list_roll_goods(
                PLANNER,
                params={"production_run_id": run_sd["id"], "limit": 100, "offset": 0},
            )
        )
        assert roll_meta["total_count"] == 1, (
            "only the compliant solution-dyed roll exists on PR-SD, got total_count "
            f"{roll_meta['total_count']}"
        )
        _, lot_meta = validate_paginated(
            api.list_dye_lots(
                DYER,
                params={"production_run_id": run_sd["id"], "limit": 100, "offset": 0},
            )
        )
        assert lot_meta["total_count"] == 0, (
            "no dye lot may exist against the solution-dyed run, got total_count "
            f"{lot_meta['total_count']}"
        )
