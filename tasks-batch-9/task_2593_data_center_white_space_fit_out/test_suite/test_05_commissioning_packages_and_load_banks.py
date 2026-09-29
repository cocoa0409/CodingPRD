"""Commissioning packages carry two independent dimensions, and load bank runs
compete for one pooled reserve over closed windows."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    CA,
    add_powered_rack,
    advance_phase,
    approve_script,
    create_package,
    execute_script,
    prove_zone_and_cooling,
    read_hall,
    read_load_bank_test,
    read_package,
    schedule_load_bank,
    setup_commissioning_hall,
    setup_fit_out_hall,
    witness_package,
)


class TestPackageDimensionsMoveIndependently:
    """script_status and witness_status are stored separately; package_state is only
    ever a projection of the pair."""

    def _package_rejected_then_re_executed(self):
        ctx = setup_commissioning_hall("HG1")
        package = create_package(ctx["hall_id"], "L1", target_load_kw=10.00)
        approve_script(package["id"], 1)
        ctx["after_approval"] = read_package(package["id"])
        execute_script(package["id"])
        ctx["rejected"] = witness_package(package["id"], "REJECTED", note="re-run it")
        ctx["re_executed"] = execute_script(package["id"])
        ctx["package_id"] = package["id"]
        return ctx

    def test_rejection_rolls_the_script_back_and_re_execution_certifies(self):
        """A witness rejection drives the package to FAILED and rolls the script from
        EXECUTED back to SCRIPT_APPROVED; re-executing re-opens the witness dimension,
        and the second decision certifies the package on script revision 1.

        PRD: "`REJECTED` sets `witness_status` to `REJECTED`, brings `package_state` to
        `FAILED`, and rolls the script dimension **backwards** from `EXECUTED` to
        `SCRIPT_APPROVED` so that the agent can re-run the script against the same
        approved revision."

        Design: Difficulty/non_linear_state_machine/commissioning_package_parallel_script_and_witness_dimensions
        """
        ctx = self._package_rejected_then_re_executed()

        assert ctx["rejected"]["witness_status"] == "REJECTED"
        assert ctx["rejected"]["package_state"] == "FAILED"
        assert ctx["rejected"]["script_status"] == "SCRIPT_APPROVED", (
            "the script dimension rolls backwards on rejection"
        )
        assert ctx["re_executed"]["script_status"] == "EXECUTED"
        assert ctx["re_executed"]["witness_status"] == "PENDING", (
            "executing the script resets a rejected witness dimension to PENDING"
        )

        certified = witness_package(ctx["package_id"], "WITNESSED")
        assert certified["script_status"] == "EXECUTED"
        assert certified["witness_status"] == "WITNESSED"
        assert certified["package_state"] == "CERTIFIED"
        assert certified["executed_by_user_id"] == "u-ca-1"
        assert certified["witnessed_by_user_id"] == "u-wa-1"
        assert certified["script_revision"] == 1, (
            "the re-run uses the same approved revision"
        )

    def test_neither_dimension_drags_the_other_and_the_state_is_a_projection(self):
        """Approving a script leaves the witness dimension at PENDING, and while the
        witness dimension reads REJECTED the projected state is FAILED even though the
        script had reached EXECUTED — the rejection branch outranks the certified one.

        PRD: "Neither dimension constrains the other's storage: approving a script
        leaves `witness_status` untouched, and a witness decision does not by itself
        move `script_status` forward."

        Design: Difficulty/non_linear_state_machine/commissioning_package_parallel_script_and_witness_dimensions
        """
        ctx = self._package_rejected_then_re_executed()

        assert ctx["after_approval"]["script_status"] == "SCRIPT_APPROVED"
        assert ctx["after_approval"]["witness_status"] == "PENDING"
        assert ctx["after_approval"]["package_state"] == "IN_EXECUTION"

        witness_package(ctx["package_id"], "WITNESSED")
        hall = read_hall(ctx["hall_id"])
        assert hall["status"] == "COMMISSIONING", (
            "a hall with a single certified L1 package does not go live"
        )

        rows, meta = validate_paginated(
            api_client.list_commissioning_packages(CA, {"hall_id": ctx["hall_id"]})
        )
        assert meta["total_count"] == 1, "only one package was ever opened"
        assert rows[0]["package_state"] == "CERTIFIED"


class TestLoadBankReserveAndConcurrency:
    """The hall's commissioning reserve is a pool shared over closed windows, and no
    more than two runs may overlap."""

    def _hall_with_two_scheduled_runs(self):
        ctx = setup_fit_out_hall(
            "HR1",
            cu_rated_sensible_kw=200.00,
            cu_design_airflow_cfm=40000,
            cu_supply_delta_t_f=18.0,
        )
        prove_zone_and_cooling(ctx)
        add_powered_rack(ctx, design_kw=150.00, feed_kw=75.00, breaker_amps=400)
        advance_phase(ctx["hall_id"], "COMMISSIONING")
        package = create_package(ctx["hall_id"], "L1", target_load_kw=10.00)
        approve_script(package["id"], 1)
        ctx["package_id"] = package["id"]
        ctx["run_a"] = schedule_load_bank(
            package["id"], 20.00, "2026-08-10T02:00:00Z", "2026-08-10T04:00:00Z"
        )
        ctx["run_b"] = schedule_load_bank(
            package["id"], 20.00, "2026-08-10T03:00:00Z", "2026-08-10T05:00:00Z"
        )
        return ctx

    def _schedule(self, ctx, target_kw, start, end):
        return api_client.create_load_bank_test(
            {
                "package_id": ctx["package_id"],
                "target_kw": target_kw,
                "window_start": start,
                "window_end": end,
                "step_pct_sequence": [25, 50, 75, 100],
            },
            CA,
        )

    def test_a_run_touching_a_peer_endpoint_is_the_third_overlap(self):
        """A window starting exactly where the first run ends still overlaps it, so with
        two peers already scheduled the request is refused on concurrency; moving the
        start half an hour later leaves one peer and is admitted.

        PRD: "two runs whose windows merely touch at an endpoint *do* overlap, since a
        run occupies both endpoints of its window."

        Design: Difficulty/resource_temporal_overlap/loadbank_aggregate_reserve_and_concurrency_on_hall
        """
        ctx = self._hall_with_two_scheduled_runs()
        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(150.00, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(50.00, abs=0.005)

        validate_error(
            self._schedule(ctx, 5.00, "2026-08-10T04:00:00Z", "2026-08-10T06:00:00Z"),
            ApiErrorId.ERR_LOADBANK_CONCURRENCY_EXCEEDED.value,
            409,
        )
        admitted = validate_success(
            self._schedule(ctx, 15.00, "2026-08-10T04:30:00Z", "2026-08-10T06:00:00Z"),
            201,
        )
        assert admitted["status"] == "SCHEDULED"
        assert admitted["target_kw"] == pytest.approx(15.00, abs=0.005)
        assert admitted["measured_kw"] is None
        assert admitted["result"] is None
        assert read_load_bank_test(ctx["run_a"]["id"])["status"] == "SCHEDULED"
        assert read_load_bank_test(ctx["run_b"]["id"])["status"] == "SCHEDULED"

    def test_pooled_reserve_demand_is_inclusive_at_the_tier_figure(self):
        """Against a 50.00 kW reserve the overlapping demand of 15.00 plus 36.00 is
        refused while 15.00 plus 35.00 is admitted, and scheduling runs moves neither
        the committed load nor the reserve itself.

        PRD: "The reserve demand — the sum of `target_kw` across the peers plus this
        run's own `target_kw`, rounded to two decimal places — must be no more than the
        hall's current `commissioning_reserve_kw`."

        Design: Difficulty/resource_temporal_overlap/loadbank_aggregate_reserve_and_concurrency_on_hall
        """
        ctx = self._hall_with_two_scheduled_runs()
        third = validate_success(
            self._schedule(ctx, 15.00, "2026-08-10T04:30:00Z", "2026-08-10T06:00:00Z"),
            201,
        )

        validate_error(
            self._schedule(ctx, 36.00, "2026-08-10T05:30:00Z", "2026-08-10T07:00:00Z"),
            ApiErrorId.ERR_COMMISSIONING_RESERVE_EXCEEDED.value,
            422,
        )
        fourth = validate_success(
            self._schedule(ctx, 35.00, "2026-08-10T05:30:00Z", "2026-08-10T07:00:00Z"),
            201,
        )
        assert fourth["status"] == "SCHEDULED"

        rows, meta = validate_paginated(
            api_client.list_load_bank_tests(CA, {"package_id": ctx["package_id"]})
        )
        assert meta["total_count"] == 4, "the refused request left no run behind"
        assert {row["status"] for row in rows} == {"SCHEDULED"}
        assert third["id"] in {row["id"] for row in rows}

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(150.00, abs=0.005), (
            "load banking borrows the reserve without committing white space load"
        )
        assert hall["commissioning_reserve_kw"] == pytest.approx(50.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(200.00, abs=0.005)
