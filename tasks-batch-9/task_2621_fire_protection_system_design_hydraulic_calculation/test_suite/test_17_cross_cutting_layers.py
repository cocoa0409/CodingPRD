"""Optimistic concurrency, ledger reconciliation and read-your-own-write consistency."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_demand_ledger,
    assert_flow,
    assert_margin,
    assert_pressure,
)
from test_helpers.factories import (
    build_commission_payload,
    build_fire_pump_payload,
    build_withdraw_payload,
)
from test_helpers.fixtures import (
    ADMIN_HEADERS,
    CONTRACTOR_HEADERS,
    PROJECT_TOTAL_DEMAND_GPM,
    STANDPIPE_DEMAND_GPM,
    build_converged_stage,
    build_project_stage,
    create_auxiliary_system,
    create_evaluation,
    create_flow_test,
    read_auxiliary_system,
    read_evaluation,
    read_project,
)
from test_helpers.test_users import make_design_engineer_headers

WEAK_HYDRANT = dict(
    hydrant_tag="H-22", static_psi=50.0, residual_psi=30.0, flow_gpm=4000.0,
    tested_at="2026-06-20T10:00:00.000Z",
)


def _weak_evaluation(client, ctx):
    """The same converged design evaluated against the 50 / 30 / 4000 hydrant."""
    weak_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **WEAK_HYDRANT)
    return create_evaluation(
        client, ctx["project_id"], weak_test["id"], ctx["calculation_id"], ctx["lead_id"]
    )


def _size_pump(client, ctx, evaluation_id, pinned_version, model_tag):
    return client.create_fire_pump(
        build_fire_pump_payload(
            project_id=ctx["project_id"],
            water_supply_evaluation_id=evaluation_id,
            expected_water_supply_evaluation_version=pinned_version,
            model_tag=model_tag,
        ),
        make_design_engineer_headers(ctx["lead_id"]),
    )


class TestPumpSizingVersionPin:
    def test_01_the_version_captured_at_creation_sizes_exactly_one_pump(self, client):
        """When `expected_water_supply_evaluation_version` does not equal the evaluation's
        current `version`, the request is rejected with
        `ERR_STALE_SUPPLY_EVALUATION_VERSION` (HTTP 412).

        Design: Corner/cross-cutting complexity layers/pump_sizing_refuses_a_supply_evaluation_version_captured_before_the_first_pump
        """
        ctx = build_converged_stage(client)
        weak = _weak_evaluation(client, ctx)
        captured_version = weak["version"]
        assert_margin(weak, 43.77, -11.77, -26.9, "INADEQUATE_PUMP_REQUIRED")

        pump = validate_success(
            _size_pump(client, ctx, weak["id"], captured_version, "PUMP-A"),
            expected_status=201,
        )
        assert_flow(pump["rated_flow_gpm"], 2500.0)
        assert pump["sizing_verdict"] == "ACCEPTABLE"
        assert pump["state"] == "SIZED"

        consumed = read_evaluation(client, weak["id"])
        assert consumed["pump_sized"] is True
        assert consumed["version"] == captured_version + 1

        # The same captured value is now stale: it never saw pump_sized turn true.
        refused = _size_pump(client, ctx, weak["id"], captured_version, "PUMP-B")
        validate_error(refused, "ERR_STALE_SUPPLY_EVALUATION_VERSION", expected_status=412)

        rows, meta = validate_paginated(
            client.list_fire_pumps(ADMIN_HEADERS, params={"project_id": ctx["project_id"]})
        )
        assert meta["total_count"] == 1, "the refused attempt minted no second pump"
        assert [row["model_tag"] for row in rows] == ["PUMP-A"]

    def test_02_the_re_read_version_reaches_the_state_guard_behind_it(self, client):
        """Sizing a fire pump requires `expected_water_supply_evaluation_version` matching the
        referenced water supply evaluation's current `version`. A pump selection legitimately
        supersedes any prior selection made against the same evaluation ...

        Design: Corner/cross-cutting complexity layers/pump_sizing_refuses_a_supply_evaluation_version_captured_before_the_first_pump
        """
        ctx = build_converged_stage(client)
        weak = _weak_evaluation(client, ctx)
        captured_version = weak["version"]
        validate_success(
            _size_pump(client, ctx, weak["id"], captured_version, "PUMP-A"),
            expected_status=201,
        )
        validate_error(
            _size_pump(client, ctx, weak["id"], captured_version, "PUMP-B"),
            "ERR_STALE_SUPPLY_EVALUATION_VERSION",
        )

        current_version = read_evaluation(client, weak["id"])["version"]
        assert current_version == captured_version + 1, "one write, one increment"

        # The version is current, so the guard that answers is about the pump, not the pin.
        refused = _size_pump(client, ctx, weak["id"], current_version, "PUMP-C")
        validate_error(refused, "ERR_PUMP_ALREADY_SIZED", expected_status=409)


HOOD = dict(
    system_type="COOKING", label="Kitchen hood line", appliance_count=4,
    water_wash_enabled=True, agent_type="WET_CHEMICAL",
)
HOSE_STATION = dict(system_type="STANDPIPE_CLASS_II", label="Hose station", riser_count=1)
HOOD_DEMAND_GPM = 160.0
HOSE_DEMAND_GPM = 100.0
OUTAGE = ("2026-09-05T08:00:00.000Z", "2026-09-05T12:00:00.000Z")


def _three_lines(client):
    """The standpipe, the cooking line and the hose station, on a project with no design."""
    ctx = build_project_stage(client)
    ctx["standpipe"] = create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"])
    ctx["hood"] = create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"], **HOOD)
    ctx["hose"] = create_auxiliary_system(
        client, ctx["project_id"], ctx["lead_id"], **HOSE_STATION
    )
    return ctx


class TestAuxiliaryLedgerReconciles:
    def test_03_each_create_raises_the_roll_up_by_exactly_its_own_demand(self, client):
        """... the project ledger is recomputed so `auxiliary_demand_gpm` and
        `total_system_demand_gpm` rise by the new `demand_gpm`, and the project's `version`
        advances.

        Design: Corner/cross-cutting complexity layers/auxiliary_ledger_field_reconciles_after_create_after_commission_and_after_withdrawal
        """
        ctx = build_project_stage(client)
        assert_demand_ledger(read_project(client, ctx["project_id"]), None, 0.0, 0.0, 0.0)

        create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"])
        assert_demand_ledger(
            read_project(client, ctx["project_id"]),
            None, 0.0, STANDPIPE_DEMAND_GPM, STANDPIPE_DEMAND_GPM,
        )

        hood = create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"], **HOOD)
        assert_flow(hood["demand_gpm"], HOOD_DEMAND_GPM)
        assert_demand_ledger(read_project(client, ctx["project_id"]), None, 0.0, 910.0, 910.0)

        hose = create_auxiliary_system(
            client, ctx["project_id"], ctx["lead_id"], **HOSE_STATION
        )
        assert_flow(hose["demand_gpm"], HOSE_DEMAND_GPM)
        assert_demand_ledger(
            read_project(client, ctx["project_id"]), None, 0.0, 1010.0, 1010.0
        )

    def test_04_commissioning_a_line_leaves_the_roll_up_exactly_where_it_was(self, client):
        """Third, `auxiliary_demand_gpm` is the sum of `demand_gpm` over every auxiliary system
        of the project whose `status` is anything other than `WITHDRAWN` ...

        Design: Corner/cross-cutting complexity layers/auxiliary_ledger_field_reconciles_after_create_after_commission_and_after_withdrawal
        """
        ctx = _three_lines(client)
        before = read_project(client, ctx["project_id"])
        assert_demand_ledger(before, None, 0.0, 1010.0, 1010.0)

        start, end = OUTAGE
        commissioned = validate_success(
            client.commission_auxiliary_system(
                ctx["hose"]["id"],
                build_commission_payload(outage_start_at=start, outage_end_at=end),
                CONTRACTOR_HEADERS,
            )
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert_flow(commissioned["demand_gpm"], HOSE_DEMAND_GPM)

        # A COMMISSIONED row is still part of the design demand.
        assert_demand_ledger(read_project(client, ctx["project_id"]), None, 0.0, 1010.0, 1010.0)

    def test_05_withdrawal_is_the_exact_arithmetic_inverse_of_the_create(self, client):
        """Withdrawal moves `status` to `WITHDRAWN`, clears `outage_start_at` and
        `outage_end_at` back to null, and recomputes the project ledger without the withdrawn
        system, so `auxiliary_demand_gpm` and `total_system_demand_gpm` fall by exactly that
        system's `demand_gpm`.

        Design: Corner/cross-cutting complexity layers/auxiliary_ledger_field_reconciles_after_create_after_commission_and_after_withdrawal
        """
        ctx = _three_lines(client)
        withdrawn = validate_success(
            client.withdraw_auxiliary_system(
                ctx["hood"]["id"],
                make_design_engineer_headers(ctx["lead_id"]),
                payload=build_withdraw_payload(
                    withdraw_note="Kitchen deleted from the tenant fit out"
                ),
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        # The withdrawn row keeps its own figure; only the roll-up drops it.
        assert_flow(read_auxiliary_system(client, ctx["hood"]["id"])["demand_gpm"], 160.0)
        assert_demand_ledger(read_project(client, ctx["project_id"]), None, 0.0, 850.0, 850.0)


RACK_TIER = dict(
    system_type="IN_RACK", label="Rack tier heads", in_rack_head_count=20,
)
RACK_TIER_DEMAND_GPM = 480.0


class TestEveryDerivedFieldIsAlreadyInItsOwnResponse:
    def test_06_the_evaluation_creation_response_already_carries_its_supply_figures(
        self, client
    ):
        """The remaining figures follow from the basis. `design_demand_gpm` is the referenced
        calculation's `hazard_total_demand_gpm` plus the project's `auxiliary_demand_gpm`,
        rounded to 1 decimal place.

        Design: Corner/consistency model/every_derived_field_is_already_correct_in_the_writing_requests_own_response
        """
        ctx = build_converged_stage(client)
        # No re-read: the create response itself is inspected.
        weak = _weak_evaluation(client, ctx)
        assert_flow(weak["design_demand_gpm"], PROJECT_TOTAL_DEMAND_GPM)
        assert_margin(weak, 43.77, -11.77, -26.9, "INADEQUATE_PUMP_REQUIRED")
        assert weak["pump_sized"] is False

    def test_07_the_pump_creation_response_already_carries_the_whole_worksheet(self, client):
        """Three further figures describe the pump's curve. `churn_discharge_psi` is
        `rated_pressure_psi` multiplied by a churn factor of 1.40, plus `basis_static_psi`,
        rounded to 1 decimal place.

        Design: Corner/consistency model/every_derived_field_is_already_correct_in_the_writing_requests_own_response
        """
        ctx = build_converged_stage(client)
        weak = _weak_evaluation(client, ctx)
        pump = validate_success(
            _size_pump(client, ctx, weak["id"], weak["version"], "PUMP-A"),
            expected_status=201,
        )
        assert_flow(pump["rated_flow_gpm"], 2500.0)
        assert_pressure(pump["suction_psi_at_rated"], 41.62)
        assert_pressure(pump["required_discharge_psi"], 65.54)
        assert_pressure(pump["rated_pressure_psi"], 40.0)
        assert_pressure(pump["churn_discharge_psi"], 106.0)
        assert_flow(pump["flow_150_pct_gpm"], 3750.0)
        assert_pressure(pump["suction_psi_at_150_pct"], 32.25)
        assert_pressure(pump["available_psi_at_150_pct"], 58.25)
        assert pump["sizing_verdict"] == "ACCEPTABLE"
        assert pump["state"] == "SIZED"

    def test_08_the_collateral_writes_have_already_landed_when_the_call_returns(self, client):
        """The write also sets the evaluation's `pump_sized` to true and advances the
        evaluation's `version`, sets the project's `pump_required_flag` to true and advances the
        project's `version`.

        Design: Corner/consistency model/every_derived_field_is_already_correct_in_the_writing_requests_own_response
        """
        ctx = build_converged_stage(client)
        weak = _weak_evaluation(client, ctx)
        version_at_evaluation = read_project(client, ctx["project_id"])["version"]
        validate_success(
            _size_pump(client, ctx, weak["id"], weak["version"], "PUMP-A"),
            expected_status=201,
        )
        consumed = read_evaluation(client, weak["id"])
        assert consumed["pump_sized"] is True
        assert consumed["version"] == weak["version"] + 1
        # Sizing a pump does not rewrite the unassisted supply figures.
        assert_pressure(consumed["available_psi_at_demand"], 43.77)

        rack = create_auxiliary_system(
            client, ctx["project_id"], ctx["lead_id"], hazard_area_id=ctx["hazard_area_id"],
            **RACK_TIER,
        )
        assert_flow(rack["demand_gpm"], RACK_TIER_DEMAND_GPM)
        assert rack["status"] == "PROPOSED"

        project = read_project(client, ctx["project_id"])
        assert_demand_ledger(project, ctx["calculation_id"], 1380.0, 1230.0, 2610.0)
        assert project["pump_required_flag"] is True
        assert project["version"] > version_at_evaluation, "the ledger update is a write"
