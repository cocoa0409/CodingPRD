"""Production runs, hold cascade, SPC evaluation and quota (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_quality_inspector_headers,
    plant_base, create_die, qualify_die, create_line, qc_passed_lot,
    released_batch, create_batch, confirmed_order, activated_assignment,
    create_assignment, start_run, post_sample, running_scene, cascade_scene,
    get_run, get_line, get_batch, get_assignment, get_order,
    IN_CONTROL_MEASUREMENTS, WINDOW_10_12, WINDOW_12_14,
)

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["process_engineer_headers"]
LO = TEST_USERS["line_operator_headers"]
QI = TEST_USERS["quality_inspector_headers"]


class TestRunCreation:
    def test_run_create_applies_declared_side_effects(self, api):
        """PRD §3.6: "A started run is born `RUNNING`; its batch moves from
        `QC_RELEASED` to `CONSUMED`; the line moves from `SETUP` to `RUNNING`, or
        simply stays `RUNNING` when a previous run under the same assignment
        already put it there; and the first run created under an order's
        assignments moves that order from `SCHEDULED` to `IN_PRODUCTION`."

        Design: Corner/endpoints/run_create_side_effects
        """
        scene = running_scene()
        run = get_run(scene["run"]["id"])
        assert run["status"] == "RUNNING"
        assert run["samples_posted"] == 0
        assert get_batch(scene["batch"]["id"])["status"] == "CONSUMED"
        assert get_line(scene["line"]["id"])["status"] == "RUNNING"
        assert get_order(scene["wo"]["id"])["status"] == "IN_PRODUCTION"

    def test_run_create_with_blended_batch_rejected(self, api):
        """PRD §3.6: "the assignment must be `ACTIVE` — any other status is
        `ERR_INVALID_STATE`; the batch must be `QC_RELEASED` — anything else is
        `ERR_MATERIAL_NOT_RELEASED`; the speed must satisfy the profile's
        qualified window, at least `min_line_speed_mpm` and at most
        `max_line_speed_mpm`, failing which the rejection is
        `ERR_LINE_SPEED_OUT_OF_RANGE`; and the batch's formulation must be the
        same formulation the assignment's work order names, failing which the
        rejection is `ERR_LOT_INCOMPATIBLE`."

        Design: Difficulty/cross_entity_state_dependency/run_create_requires_batch_released
        """
        base = plant_base()
        die = qualify_die(create_die(base["prof"]["id"])["id"])
        line = create_line()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        batch = create_batch(base["form"]["id"], lot_v["id"], lot_c["id"])  # stays BLENDED
        wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        asg = activated_assignment(wo["id"], die["id"], line["id"], WINDOW_10_12)

        resp = api.create_run({"assignment_id": asg["id"], "batch_id": batch["id"],
                               "line_speed_mpm": 25}, LO)
        validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_RELEASED)
        assert get_line(line["id"])["status"] == "SETUP", "No side effects may fire"
        assert get_order(wo["id"])["status"] == "SCHEDULED"

    def test_run_create_with_quarantined_batch_rejected(self, api):
        """PRD §3.6: "the assignment must be `ACTIVE` — any other status is
        `ERR_INVALID_STATE`; the batch must be `QC_RELEASED` — anything else is
        `ERR_MATERIAL_NOT_RELEASED`; the speed must satisfy the profile's
        qualified window, at least `min_line_speed_mpm` and at most
        `max_line_speed_mpm`, failing which the rejection is
        `ERR_LINE_SPEED_OUT_OF_RANGE`; and the batch's formulation must be the
        same formulation the assignment's work order names, failing which the
        rejection is `ERR_LOT_INCOMPATIBLE`."

        Design: Difficulty/cross_entity_state_dependency/run_create_requires_batch_released
        """
        base = plant_base()
        die = qualify_die(create_die(base["prof"]["id"])["id"])
        line = create_line()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        batch = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"])
        insp1 = make_quality_inspector_headers("insp-1")
        validate_success(api.qc_blend_batch(batch["id"], {"action": "QUARANTINE"}, insp1), 200)
        assert get_batch(batch["id"])["status"] == "QUARANTINED"
        wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        asg = activated_assignment(wo["id"], die["id"], line["id"], WINDOW_10_12)

        resp = api.create_run({"assignment_id": asg["id"], "batch_id": batch["id"],
                               "line_speed_mpm": 25}, LO)
        validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_RELEASED)
        assert get_line(line["id"])["status"] == "SETUP"
        assert get_order(wo["id"])["status"] == "SCHEDULED"

    def test_line_speed_window_enforced_at_run_create(self, api):
        """PRD §3.6: "the speed must satisfy the profile's qualified window, at
        least `min_line_speed_mpm` and at most `max_line_speed_mpm`, failing
        which the rejection is `ERR_LINE_SPEED_OUT_OF_RANGE`".

        Design: Corner/validations/line_speed_out_of_range_rejected
        """
        base = plant_base()
        die = qualify_die(create_die(base["prof"]["id"])["id"])
        line = create_line()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        batch = released_batch(base["form"]["id"], lot_v["id"], lot_c["id"])
        wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        asg = activated_assignment(wo["id"], die["id"], line["id"], WINDOW_10_12)

        too_fast = api.create_run({"assignment_id": asg["id"], "batch_id": batch["id"],
                                   "line_speed_mpm": 45}, LO)
        validate_error(too_fast, ApiErrorId.ERR_LINE_SPEED_OUT_OF_RANGE)

        at_max = api.create_run({"assignment_id": asg["id"], "batch_id": batch["id"],
                                 "line_speed_mpm": 40}, LO)
        assert validate_success(at_max, 201)["status"] == "RUNNING", (
            "line_speed_mpm == max_line_speed_mpm (40) is inside the inclusive window")


class TestHoldCascadeAndSoD:
    def test_manual_hold_and_release_cycle(self, api):
        """PRD §3.6: "A `QualityInspector` imposes a hold by submitting `action`
        `HOLD` against a `RUNNING` run: the run moves to `HOLD` with
        `hold_origin` `MANUAL` and `held_by_user_id` set to the caller's
        `X-User-ID`, the line drops from `RUNNING` to `DOWN`, and the third link
        of the hold cascade fires — every assignment still `SCHEDULED` on that
        line is `CANCELLED`, and each order so affected reverts from `SCHEDULED`
        to `CONFIRMED` wherever it has no remaining `SCHEDULED` or `ACTIVE`
        assignments and no `COMPLETED` runs."
        PRD §3.6: "`action` `RELEASE` against a `HOLD` run returns it to
        `RUNNING`, lifts the line from `DOWN` back to `RUNNING`, and clears
        `hold_origin` and `held_by_user_id`."

        Design: Corner/state_machines/run_hold_release_cycle_valid
        """
        scene = running_scene()
        run_id, line_id = scene["run"]["id"], scene["line"]["id"]
        insp1 = make_quality_inspector_headers("insp-1")
        insp2 = make_quality_inspector_headers("insp-2")

        held = validate_success(api.set_run_hold_status(run_id, {"action": "HOLD"}, insp1), 200)
        assert held["status"] == "HOLD"
        assert held["hold_origin"] == "MANUAL"
        assert held["held_by_user_id"] == "insp-1"
        assert get_line(line_id)["status"] == "DOWN"

        released = validate_success(api.set_run_hold_status(run_id, {"action": "RELEASE"}, insp2), 200)
        assert released["status"] == "RUNNING"
        assert released.get("hold_origin") is None
        assert released.get("held_by_user_id") is None
        assert get_line(line_id)["status"] == "RUNNING"

    def test_release_by_holding_inspector_violates_sod(self, api):
        """PRD §3.6: "Segregation of duties guards exactly one case — releasing a
        `MANUAL` hold: the releasing inspector's `X-User-ID` must differ from
        `held_by_user_id`, or the request is rejected with `ERR_SOD_VIOLATION`; a
        `SYSTEM` hold may be released by any inspector."

        Design: Corner/rbac/sod_hold_release_same_inspector_rejected
        """
        scene = running_scene()
        run_id, line_id = scene["run"]["id"], scene["line"]["id"]
        insp1 = make_quality_inspector_headers("insp-1")
        insp2 = make_quality_inspector_headers("insp-2")
        validate_success(api.set_run_hold_status(run_id, {"action": "HOLD"}, insp1), 200)

        same = api.set_run_hold_status(run_id, {"action": "RELEASE"}, insp1)
        validate_error(same, ApiErrorId.ERR_SOD_VIOLATION)
        assert get_run(run_id)["status"] == "HOLD"

        released = validate_success(api.set_run_hold_status(run_id, {"action": "RELEASE"}, insp2), 200)
        assert released["status"] == "RUNNING"
        assert get_line(line_id)["status"] == "RUNNING"

    def test_cancel_order_with_running_run_rejected(self, api):
        """PRD §3.4: "Cancellation, also by a `SalesEngineer`, is available from
        `QUOTED`, `CONFIRMED`, `SCHEDULED`, or `IN_PRODUCTION` — from anywhere
        else, `ERR_INVALID_STATE` — but is blocked whenever any production run
        under the order's assignments is `RUNNING` or `HOLD`, surfacing
        `ERR_RUN_IN_PROGRESS`."

        Design: Corner/state_machines/work_order_cancel_with_running_run_rejected
        """
        scene = running_scene()
        resp = api.cancel_work_order(scene["wo"]["id"], TEST_USERS["sales_engineer_headers"])
        validate_error(resp, ApiErrorId.ERR_RUN_IN_PROGRESS)
        assert get_order(scene["wo"]["id"])["status"] == "IN_PRODUCTION"
        assert get_assignment(scene["asg"]["id"])["status"] == "ACTIVE"


class TestSpcEvaluation:
    def test_xbar_exactly_at_ucl_is_in_control(self, api):
        """PRD §3.7: "The sample is flagged `ooc` — out of control — only when
        `xbar_mm` is strictly greater than the dimension's `ucl_mm` or strictly
        less than its `lcl_mm`; a mean sitting exactly on either limit is in
        control."
        PRD §3.7: "The subgroup mean `xbar_mm` is the arithmetic mean of the
        measurements, rounded half-up to four decimal places; the `range_mm` is
        the largest measurement minus the smallest, rounded half-up to four
        decimal places."

        Design: Difficulty/boundary_precision_check/spc_xbar_exactly_at_ucl
        """
        scene = running_scene()
        resp = api.create_spc_sample(
            {"run_id": scene["run"]["id"], "dimension_name": "wall",
             "measurements": [2.05, 2.05, 2.05]}, LO)
        sample = validate_success(resp, 201)
        assert sample["xbar_mm"] == pytest.approx(2.05, abs=1e-6)
        assert sample["ooc"] is False, "xbar exactly at ucl 2.05 is in control (strict >)"
        assert get_run(scene["run"]["id"])["status"] == "RUNNING", "No cascade may fire"

    def test_xbar_above_ucl_trips_hold_and_lcl_boundary_stays_in_control(self, api):
        """PRD §3.7: "The sample is flagged `ooc` — out of control — only when
        `xbar_mm` is strictly greater than the dimension's `ucl_mm` or strictly
        less than its `lcl_mm`; a mean sitting exactly on either limit is in
        control."
        PRD §3.7: "And an out-of-control result is the first link of the hold
        cascade: the run moves from `RUNNING` to `HOLD` with `hold_origin`
        `SYSTEM`, and from there the cascade runs exactly as in §3.6 — line to
        `DOWN`, scheduled assignments on the line cancelled, orders reverted
        where they qualify."

        Design: Difficulty/boundary_precision_check/spc_xbar_exactly_at_ucl
        """
        scene = running_scene()
        at_lcl = validate_success(api.create_spc_sample(
            {"run_id": scene["run"]["id"], "dimension_name": "wall",
             "measurements": [1.95, 1.95, 1.95]}, LO), 201)
        assert at_lcl["xbar_mm"] == pytest.approx(1.95, abs=1e-6)
        assert at_lcl["ooc"] is False, "xbar exactly at lcl 1.95 is in control (strict <)"
        assert get_run(scene["run"]["id"])["status"] == "RUNNING"

        over = validate_success(api.create_spc_sample(
            {"run_id": scene["run"]["id"], "dimension_name": "wall",
             "measurements": [2.06, 2.05, 2.05]}, LO), 201)
        assert over["xbar_mm"] == pytest.approx(2.0533, abs=1e-6)  # 6.16/3 -> 2.0533
        assert over["ooc"] is True
        run = get_run(scene["run"]["id"])
        assert run["status"] == "HOLD"
        assert run["hold_origin"] == "SYSTEM"

    def test_spec_violation_without_control_breach(self, api):
        """PRD §3.7: "Separately, `spec_violations` counts the individual
        measurements falling outside the specification band — strictly below
        `nominal_mm` minus `tol_minus_mm`, or strictly above `nominal_mm` plus
        `tol_plus_mm` — so a measurement exactly on a specification limit does
        not violate."
        PRD §3.7: "The sample is flagged `ooc` — out of control — only when
        `xbar_mm` is strictly greater than the dimension's `ucl_mm` or strictly
        less than its `lcl_mm`; a mean sitting exactly on either limit is in
        control."

        Design: Corner/calculations/spc_spec_violation_without_ooc
        """
        scene = running_scene()
        resp = api.create_spc_sample(
            {"run_id": scene["run"]["id"], "dimension_name": "wall",
             "measurements": [2.0, 2.0, 2.11]}, LO)
        sample = validate_success(resp, 201)
        assert sample["xbar_mm"] == pytest.approx(2.0367, abs=1e-6)  # 6.11/3
        assert sample["range_mm"] == pytest.approx(0.11, abs=1e-6)
        assert sample["spec_violations"] == 1, "2.11 > 2.00 + 0.10 violates spec once"
        assert sample["ooc"] is False, "Mean 2.0367 stays inside control limits"
        assert get_run(scene["run"]["id"])["status"] == "RUNNING"

    def test_wrong_measurement_count_rejected(self, api):
        """PRD §3.7: "the `dimension_name` must match the `name` of one entry in
        the profile's `critical_dimensions`, or the rejection is
        `ERR_UNKNOWN_DIMENSION`; and the number of measurements must equal the
        profile's `spc_subgroup_size` exactly, or the rejection is
        `ERR_SPC_SUBGROUP_SIZE`."
        PRD §3.7: "Posting a sample increments the run's `samples_posted` by one."

        Design: Corner/validations/subgroup_size_mismatch_rejected
        """
        scene = running_scene()
        resp = api.create_spc_sample(
            {"run_id": scene["run"]["id"], "dimension_name": "wall",
             "measurements": [2.0, 2.02]}, LO)
        validate_error(resp, ApiErrorId.ERR_SPC_SUBGROUP_SIZE)
        assert get_run(scene["run"]["id"])["samples_posted"] == 0, (
            "A rejected sample must not increment samples_posted")

    def test_unknown_dimension_rejected(self, api):
        """PRD §3.7: "the `dimension_name` must match the `name` of one entry in
        the profile's `critical_dimensions`, or the rejection is
        `ERR_UNKNOWN_DIMENSION`; and the number of measurements must equal the
        profile's `spc_subgroup_size` exactly, or the rejection is
        `ERR_SPC_SUBGROUP_SIZE`."

        Design: Corner/validations/unknown_dimension_rejected
        """
        scene = running_scene()
        resp = api.create_spc_sample(
            {"run_id": scene["run"]["id"], "dimension_name": "flange",
             "measurements": [2.0, 2.02, 1.98]}, LO)
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_DIMENSION)

    def test_completion_below_sample_quota_rejected(self, api):
        """PRD §3.7: "`samples_posted` must be at least the whole-number floor of
        the good length in metres — `good_length_mm` divided by one thousand —
        divided by the profile's `sample_every_m`; in short, one posted sample
        per full `sample_every_m` metres of good output, with a shortfall
        rejected as `ERR_SPC_SAMPLE_QUOTA`."

        Design: Corner/validations/spc_quota_shortfall_rejected
        """
        scene = running_scene(samples=1)
        resp = api.complete_run(
            scene["run"]["id"],
            {"good_length_mm": 4000000, "good_weight_kg": 3000, "trim_scrap_kg": 50}, LO)
        validate_error(resp, ApiErrorId.ERR_SPC_SAMPLE_QUOTA)
        # Quota is floor(4000 / 2000) = 2; only 1 posted.
        assert get_run(scene["run"]["id"])["status"] == "RUNNING"


class TestSpcOocHoldCascade:
    def test_ooc_sample_holds_run_and_downs_line(self, api):
        """PRD §3.7: "And an out-of-control result is the first link of the hold
        cascade: the run moves from `RUNNING` to `HOLD` with `hold_origin`
        `SYSTEM`, and from there the cascade runs exactly as in §3.6 — line to
        `DOWN`, scheduled assignments on the line cancelled, orders reverted
        where they qualify."

        Design: Difficulty/transitive_cascade/spc_ooc_hold_cascade
        """
        scene = cascade_scene()
        sample = validate_success(api.create_spc_sample(
            {"run_id": scene["run1"]["id"], "dimension_name": "wall",
             "measurements": [2.11, 2.09, 2.07]}, LO), 201)
        assert sample["ooc"] is True  # xbar 2.09 > ucl 2.05
        run = get_run(scene["run1"]["id"])
        assert run["status"] == "HOLD"
        assert run["hold_origin"] == "SYSTEM"
        assert get_line(scene["line"]["id"])["status"] == "DOWN"

    def test_ooc_cascade_cancels_scheduled_assignment_and_reverts_order(self, api):
        """PRD §3.7: "And an out-of-control result is the first link of the hold
        cascade: the run moves from `RUNNING` to `HOLD` with `hold_origin`
        `SYSTEM`, and from there the cascade runs exactly as in §3.6 — line to
        `DOWN`, scheduled assignments on the line cancelled, orders reverted
        where they qualify."
        PRD §3.6: "every assignment still `SCHEDULED` on that line is
        `CANCELLED`, and each order so affected reverts from `SCHEDULED` to
        `CONFIRMED` wherever it has no remaining `SCHEDULED` or `ACTIVE`
        assignments and no `COMPLETED` runs."

        Design: Difficulty/transitive_cascade/spc_ooc_hold_cascade
        """
        scene = cascade_scene()
        validate_success(api.create_spc_sample(
            {"run_id": scene["run1"]["id"], "dimension_name": "wall",
             "measurements": [2.11, 2.09, 2.07]}, LO), 201)
        assert get_assignment(scene["asg2"]["id"])["status"] == "CANCELLED"
        assert get_order(scene["wo2"]["id"])["status"] == "CONFIRMED", (
            "Order with no remaining SCHEDULED/ACTIVE assignments and no COMPLETED "
            "runs must revert SCHEDULED -> CONFIRMED")
