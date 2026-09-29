"""The bounded production loop on the assembly floor.

A QA rejection sends a serialized unit back from QA_HOLD through REWORK and
ON_FLOOR to DRUM_DONE, while its rework count, its billable labour and its
passing-log count keep accumulating across the rework round.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_success
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    make_quality_inspector_headers,
    make_technician_headers,
)

# The model of this recipe tolerates two rework rounds and expects a
# four-in-five first-pass record.
MODEL_OVERRIDES = {"max_rework_cycles": 2, "min_first_pass_yield_pct": 80.00}

# The second drum-fabrication visit is scheduled clear of the first visit's
# occupation window, which ran to 09:30 with the station's 30-minute buffer.
SECOND_DRUM_START = "2026-08-01T12:00:00Z"
SECOND_DRUM_END = "2026-08-01T13:00:00Z"
SECOND_DRUM_OCCUPATION_TO = "2026-08-01T13:30:00Z"


def _instant(value: str) -> datetime:
    """Read an ISO 8601 UTC stamp back as an instant, whatever its precision."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _floor_with_unit_in_qa_hold(api):
    """A certified model, three stations, a floor technician, a QA inspector and
    one unit driven to QA_HOLD by three 60-minute passing logs."""
    env = fx.make_floor_environment(api, MODEL_OVERRIDES)
    unit = fx.make_unit_in_qa_hold(api, env)
    return env, unit["build"]


def _reject_at_final_inspection(api, env, build_order_id):
    """The QA inspector, who worked no station on this unit, rejects it."""
    return validate_success(
        api.qa_signoff(
            build_order_id,
            f.qa_signoff_payload("REJECT", defect_code="CONTROL_FIRMWARE"),
            make_quality_inspector_headers(env["inspector"]["id"]),
        ),
        expected_status=200,
    )


def _log_second_drum_visit(api, env, build_order_id):
    """Log the second DRUM_FAB operation of the unit's second round."""
    payload = f.station_log_payload(
        env["stations"]["drum"]["id"],
        "DRUM_FAB",
        SECOND_DRUM_START,
        SECOND_DRUM_END,
        "PASS",
    )
    return validate_success(
        api.create_station_log(
            build_order_id, payload, make_technician_headers(env["technician"]["id"])
        ),
        expected_status=201,
    )


def _read_build(api, build_order_id):
    return validate_success(
        api.get_build_order(build_order_id, PLANT_MANAGER), expected_status=200
    )


class TestQaRejectionReopensTheReworkLoop:
    def test_01_rejection_moves_the_unit_from_qa_hold_back_to_rework(self, api):
        """A rejected unit leaves QA_HOLD for REWORK with its rework count at 1.

        PRD: "The unit's `rework_count` increases by 1, `qa_inspector_user_id` records the deciding inspector, the unit's `version` advances by 1, and the unit moves from `QA_HOLD` to `REWORK` — from which the `PlantManager` may release it to the floor again, restarting the station chain at drum fabrication."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        a.assert_build_state(build, "QA_HOLD")

        rejected = _reject_at_final_inspection(api, env, build["id"])

        a.assert_build_state(rejected, "REWORK")
        assert rejected["rework_count"] == 1

    def test_02_a_first_rework_round_sits_inside_the_ceiling_so_nothing_is_scrapped(
        self, api
    ):
        """A rework count of 1 is not strictly above the ceiling of 2, so the unit lives on.

        PRD: "Whenever `rework_count` is increased — by a failing station log, by a rejecting inspection, or by the release of an integrity hold described in §3.4 — the new value is compared against the model's `max_rework_cycles`, and if it is **strictly greater**, the unit immediately moves from `REWORK` to `SCRAPPED` within the same request."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)

        rejected = _reject_at_final_inspection(api, env, build["id"])

        assert rejected["rework_count"] == 1
        a.assert_build_state(rejected, "REWORK")
        assert rejected["scrap_reason"] == "NONE"

    def test_03_a_reworked_unit_is_released_to_the_floor_a_second_time(self, api):
        """The unit re-enters ON_FLOOR, a state it had already left.

        PRD: "Releasing a unit to the floor moves it from `PLANNED` to `ON_FLOOR`, or from `REWORK` back to `ON_FLOOR`, and advances its `version` by 1."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])

        released = validate_success(
            api.release_to_floor(build["id"], PLANT_MANAGER), expected_status=200
        )

        a.assert_build_state(released, "ON_FLOOR")
        assert released["rework_count"] == 1

    def test_04_the_second_drum_fabrication_pass_advances_the_unit_to_drum_done(
        self, api
    ):
        """The station chain restarts at drum fabrication and a passing log advances the unit.

        PRD: "A unit in `ON_FLOOR` accepts a `DRUM_FAB` log, and a passing one advances `ON_FLOOR` to `DRUM_DONE`."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])

        _log_second_drum_visit(api, env, build["id"])

        reread = _read_build(api, build["id"])
        a.assert_build_state(reread, "DRUM_DONE")
        assert reread["rework_count"] == 1


class TestCountersAccumulateAcrossTheReworkRound:
    def test_01_labor_minutes_total_keeps_the_first_round_logs(self, api):
        """Four 60-minute operations across two rounds bill 240 whole minutes.

        PRD: "The unit's `labor_minutes_total` is the sum of `labor_minutes` across every station log belonging to that unit, including logs written in earlier rework rounds."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])
        _log_second_drum_visit(api, env, build["id"])

        reread = _read_build(api, build["id"])

        assert reread["labor_minutes_total"] == 240

    def test_02_station_pass_count_counts_all_four_passing_logs(self, api):
        """The passing-log count reaches 4 rather than resetting at the rework round.

        PRD: "Every station log, passing or failing, is created as a new resource, and every one of them advances the parent unit's `version` by 1 and triggers recomputation of `labor_minutes_total` and `station_pass_count`, where `station_pass_count` counts the logs of that unit whose `outcome` is `PASS`."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])
        _log_second_drum_visit(api, env, build["id"])

        reread = _read_build(api, build["id"])

        assert reread["station_pass_count"] == 4

    def test_03_the_second_visit_occupation_window_carries_the_changeover_buffer(
        self, api
    ):
        """The 13:00 finish plus the drum cell's 30-minute changeover ends at 13:30.

        PRD: "`occupation_to` equals `completed_at` advanced by the station's `changeover_buffer_minutes`."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])

        log = _log_second_drum_visit(api, env, build["id"])

        assert _instant(log["occupation_to"]) == _instant(SECOND_DRUM_OCCUPATION_TO)

    def test_04_the_changeover_buffer_is_not_billable_labour(self, api):
        """The second drum visit bills the 60 worked minutes and not the buffer.

        PRD: "And `labor_minutes` is the elapsed time from `started_at` to `completed_at` expressed in whole minutes with any partial minute truncated downward — the changeover buffer is **not** billable labour and never appears in `labor_minutes`."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])

        log = _log_second_drum_visit(api, env, build["id"])

        assert log["labor_minutes"] == 60

    def test_05_the_reworked_unit_carries_no_scrap_hold_or_acceptance_stamp(self, api):
        """A unit back in production is neither scrapped, nor held for integrity, nor accepted.

        PRD: "A new unit begins with `build_state` at `PLANNED`, `rework_count` at 0, `integrity_hold` false, `labor_minutes_total` at 0, `station_pass_count` at 0, `scrap_reason` at `NONE`, `qa_inspector_user_id` null and `accepted_at` null."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])
        _log_second_drum_visit(api, env, build["id"])

        reread = _read_build(api, build["id"])

        assert reread["scrap_reason"] == "NONE"
        assert reread["integrity_hold"] is False
        assert reread["accepted_at"] is None


class TestTheModelSeesNoFinishedUnitYet:
    def test_01_no_unit_has_reached_a_terminal_state(self, api):
        """A unit still going round the loop counts as neither accepted nor scrapped.

        PRD: "`SCRAPPED` and `ACCEPTED` are the two terminal states of a unit; neither is ever left."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])
        _log_second_drum_visit(api, env, build["id"])

        model = validate_success(
            api.get_machine_model(env["model"]["id"], PRODUCT_ENGINEER),
            expected_status=200,
        )

        assert model["accepted_unit_count"] == 0
        assert model["scrapped_unit_count"] == 0

    def test_02_first_pass_yield_stays_at_zero_with_an_empty_denominator(self, api):
        """With no terminal unit the model's headline yield figure reads 0.00.

        PRD: "When the terminal unit count is zero, `first_pass_yield_pct` is `0.00`; otherwise it is the first-pass unit count multiplied by one hundred, divided by the terminal unit count, and rounded half up to two decimal places."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])
        _log_second_drum_visit(api, env, build["id"])

        model = validate_success(
            api.get_machine_model(env["model"]["id"], PRODUCT_ENGINEER),
            expected_status=200,
        )

        a.assert_pct(model["first_pass_yield_pct"], 0.00)

    def test_03_a_zero_yield_without_a_terminal_unit_does_not_suspend_the_model(
        self, api
    ):
        """The model keeps its certification because nothing has finished yet.

        PRD: "The terminal-unit condition matters at the start of a model's life: a brand-new model shows `0.00` yield, which is well below any floor, but it does not breach, because it has finished nothing yet."
        Design: Difficulty/non_linear_state_machine/build_order_rework_cycle_returns_to_on_floor
        """
        env, build = _floor_with_unit_in_qa_hold(api)
        _reject_at_final_inspection(api, env, build["id"])
        fx.release_build(api, build["id"])
        _log_second_drum_visit(api, env, build["id"])

        model = validate_success(
            api.get_machine_model(env["model"]["id"], PRODUCT_ENGINEER),
            expected_status=200,
        )

        assert model["certification_state"] == "CERTIFIED"
