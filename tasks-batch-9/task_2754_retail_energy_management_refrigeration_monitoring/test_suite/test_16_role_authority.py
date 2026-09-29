"""Role authority: exclusive operations, shared operations, store scope and duty separation."""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_bms_gateway_headers,
    make_energy_analyst_headers,
    make_energy_manager_headers,
    make_food_safety_officer_headers,
    make_maintenance_tech_headers,
    make_store_manager_headers,
)

COLD_WINTER_DRAFT = {
    "climate_zone": "COLD",
    "store_format": "EXPRESS",
    "season": "WINTER",
    "cooling_setpoint_f": 72.0,
    "heating_setpoint_f": 66.0,
    "deadband_f": 2.0,
    "lighting_lux_target": 600,
}

RB_FAULT = {
    "equipment_ref": "RACK-R",
    "equipment_class": "REFRIGERATION",
    "fault_code": "SUCTION-HI",
    "severity": "MINOR",
    "occurrence_count": 2,
    "affected_load_kw": 20.0,
}


def _every_target_valid_for_its_operation(api):
    """An activated store with a published standard, a spare DRAFT standard, a
    RECEIVED bill, a DETECTED fault and a case driven to an OPEN excursion."""
    ctx = fx.setup_commissioned_store(api, clock="2026-08-01T09:00:00Z", code="STR-RB")
    ctx["draft"] = fx.create_standard(api, **COLD_WINTER_DRAFT)
    account = fx.create_account(api, ctx["store_id"])
    ctx["account_id"] = account["id"]
    bill = fx.create_bill(api, account["id"])
    ctx["bill_id"] = bill["id"]
    case = fx.create_case(api, ctx["store_id"], case_code="CASE-RB")
    ctx["case_id"] = case["id"]
    fault = fx.create_fault(api, ctx["store_id"], **RB_FAULT)
    ctx["fault_id"] = fault["id"]
    readings = fx.post_readings(
        api,
        case["id"],
        ctx["store_id"],
        [(43.0, "2026-08-01T04:00:00Z"), (43.0, "2026-08-01T04:15:00Z")],
    )
    ctx["excursion_id"] = readings[-1]["excursion_id"]
    return ctx


class TestExclusiveOperationsRefuseEveryOtherRole:
    def test_eight_cross_role_calls_are_each_refused_with_unauthorized(self, api):
        """Every operation reserved to one role rejects the other six.

        The PRD states: "When the headers are present but the declared role is
        not permitted to invoke the requested operation, the request is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_operation
        """
        ctx = _every_target_valid_for_its_operation(api)
        store_id = ctx["store_id"]

        validate_error(
            api.publish_setpoint_standard(
                ctx["draft"]["id"], make_energy_analyst_headers("u_analyst_rb")
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.activate_bms(store_id, make_maintenance_tech_headers("u_tech_rb")),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.recompute_utility_bill(
                ctx["bill_id"], make_energy_manager_headers("u_mgr_rb")
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.close_excursion(ctx["excursion_id"], fx.ADMIN),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.set_monitoring_state(
                ctx["case_id"],
                f.monitoring_state_payload("BYPASSED"),
                make_bms_gateway_headers(store_id),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.post_reading(
                ctx["case_id"],
                f.reading_payload(39.0, "2026-08-01T05:00:00Z"),
                make_food_safety_officer_headers("u_officer_rb"),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_store(
                f.create_store_payload(
                    code="STR-NOPE", store_format="EXPRESS", floor_area_sqft=9000
                ),
                make_energy_manager_headers("u_mgr_rb"),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.triage_fault(
                ctx["fault_id"],
                f.triage_payload("WORK_ORDER"),
                make_store_manager_headers(store_id),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    def test_the_widest_role_is_denied_as_firmly_as_the_narrowest(self, api):
        """Standards, bills and stores keep their state after the refusals.

        The PRD states: "Role authority is summarised in the endpoint table of
        Section 4. In narrative terms: `PlatformAdmin` onboards stores and owns
        the logical clock; `EnergyManager` owns setpoint standards, BMS
        deployment, utility account attachment, tariff strategy, bill adjustment
        authorisation, demand-response participation, override revocation and
        capital approvals; `EnergyAnalyst` records and validates bills, settles
        demand-response performance and verifies measured savings; `StoreManager`
        requests lighting overrides and acknowledges excursions for its own
        store; `FoodSafetyOfficer` documents dispositions and closes excursions;
        `MaintenanceTech` bypasses and rearms cases, triages faults and executes
        work orders; `BmsGateway` ingests temperature readings and metered demand
        intervals and reports fault diagnostics for its own store."

        Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_operation
        """
        ctx = _every_target_valid_for_its_operation(api)

        api.publish_setpoint_standard(
            ctx["draft"]["id"], make_energy_analyst_headers("u_analyst_rb")
        )
        api.recompute_utility_bill(ctx["bill_id"], make_energy_manager_headers("u_mgr_rb"))
        api.create_store(
            f.create_store_payload(
                code="STR-NOPE", store_format="EXPRESS", floor_area_sqft=9000
            ),
            make_energy_manager_headers("u_mgr_rb"),
        )
        api.close_excursion(ctx["excursion_id"], fx.ADMIN)

        draft = get_success_data(api.get_setpoint_standard(ctx["draft"]["id"], fx.MANAGER))
        bills, _ = fx.list_bills(api, ctx["account_id"])
        bill = fx.find_row(bills, ctx["bill_id"])
        excursion = fx.read_excursion(api, ctx["excursion_id"])
        stores, meta = fx.list_stores(api)

        assert draft["status"] == "DRAFT"
        assert draft["published_at_iso"] is None
        assert draft["published_by_user_id"] is None
        assert bill["validation_state"] == "RECEIVED"
        assert bill["recomputed_amount_usd"] is None
        assert excursion["state"] == "OPEN"
        assert meta["total_count"] == 1
        assert fx.read_store(api, ctx["store_id"])["bms_status"] == "ACTIVE"

    def test_the_refused_reading_and_triage_leave_the_case_and_fault_untouched(self, api):
        """A rejected reading is not stored and a rejected triage raises no order.

        The PRD states: "When the headers are present but the declared role is
        not permitted to invoke the requested operation, the request is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_operation
        """
        ctx = _every_target_valid_for_its_operation(api)

        api.post_reading(
            ctx["case_id"],
            f.reading_payload(39.0, "2026-08-01T05:00:00Z"),
            make_food_safety_officer_headers("u_officer_rb"),
        )
        api.set_monitoring_state(
            ctx["case_id"],
            f.monitoring_state_payload("BYPASSED"),
            make_bms_gateway_headers(ctx["store_id"]),
        )
        api.triage_fault(
            ctx["fault_id"],
            f.triage_payload("WORK_ORDER"),
            make_store_manager_headers(ctx["store_id"]),
        )

        case = get_success_data(api.get_refrigeration_case(ctx["case_id"], fx.TECH))
        fault = get_success_data(api.get_fault_diagnostic(ctx["fault_id"], fx.TECH))
        orders, order_meta = fx.list_work_orders(api, ctx["fault_id"])

        assert case["monitoring_state"] == "ALARM"
        assert case["last_reading_temp_f"] == pytest.approx(43.0, abs=0.05)
        assert case["last_reading_iso"].startswith("2026-08-01T04:15:00")
        assert fault["state"] == "DETECTED"
        assert fault["triaged_by_user_id"] is None
        assert order_meta["total_count"] == 0
        assert orders == []


SH_FAULT = {
    "equipment_ref": "RACK-S1",
    "equipment_class": "REFRIGERATION",
    "fault_code": "SUPERHEAT",
    "severity": "MINOR",
    "occurrence_count": 2,
    "affected_load_kw": 20.0,
}


def _activated_store_with_an_account(api):
    """One activated store carrying a utility account, ready for the four
    operations that two roles share."""
    ctx = fx.setup_commissioned_store(api, code="STR-SH")
    account = fx.create_account(api, ctx["store_id"])
    ctx["account_id"] = account["id"]
    return ctx


class TestSharedOperationsAdmitEveryDeclaredRole:
    def test_a_case_may_be_registered_by_either_of_its_two_roles(self, api):
        """PlatformAdmin and EnergyManager both register cases identically.

        The PRD states: "Cases are registered against a commissioned store by a
        `PlatformAdmin` or an `EnergyManager`."

        Design: Corner/rbac/shared_operations_admit_every_declared_role
        """
        ctx = _activated_store_with_an_account(api)

        by_admin = validate_success(
            api.create_refrigeration_case(
                ctx["store_id"],
                f.create_refrigeration_case_payload(
                    case_code="CASE-P1", product_class="PRODUCE", product_value_usd=1500.00
                ),
                fx.ADMIN,
            ),
            201,
        )
        by_manager = validate_success(
            api.create_refrigeration_case(
                ctx["store_id"],
                f.create_refrigeration_case_payload(
                    case_code="CASE-P2", product_class="MEAT", alarm_high_f=40.0,
                    product_value_usd=2500.00,
                ),
                fx.MANAGER,
            ),
            201,
        )

        rows, meta = fx.list_cases(api, ctx["store_id"])

        assert by_admin["monitoring_state"] == "ARMED"
        assert by_manager["monitoring_state"] == "ARMED"
        assert meta["total_count"] == 2
        assert fx.find_row(rows, by_admin["id"])["monitoring_state"] == "ARMED"
        assert fx.find_row(rows, by_manager["id"])["monitoring_state"] == "ARMED"

    def test_a_fault_scores_the_same_whichever_of_its_two_roles_reports_it(self, api):
        """The gateway and the technician produce identical fault rows.

        The PRD states: "Automated fault detection and diagnostics are reported
        against a commissioned store by either the store's gateway or a
        `MaintenanceTech`."

        Design: Corner/rbac/shared_operations_admit_every_declared_role
        """
        ctx = _activated_store_with_an_account(api)

        by_tech = fx.create_fault(api, ctx["store_id"], **SH_FAULT)
        by_gateway = fx.create_fault(
            api,
            ctx["store_id"],
            headers=make_bms_gateway_headers(ctx["store_id"]),
            **dict(SH_FAULT, equipment_ref="RACK-S2"),
        )

        rows, meta = fx.list_faults(api, ctx["store_id"])

        assert by_tech["state"] == "DETECTED"
        assert by_gateway["state"] == "DETECTED"
        assert by_tech["fault_score"] == pytest.approx(39.2, abs=0.05)
        assert by_gateway["fault_score"] == pytest.approx(39.2, abs=0.05)
        assert meta["total_count"] == 2
        assert fx.find_row(rows, by_gateway["id"])["fault_score"] == pytest.approx(
            39.2, abs=0.05
        )

    def test_demand_intervals_accept_the_analyst_and_the_owning_gateway_alike(self, api):
        """A gateway ingesting for its own account is not a scope violation.

        The PRD states: "Either the store's gateway or an `EnergyAnalyst` may
        submit an `intervals` payload, a non-empty array in which each element
        carries `interval_start_iso`, the inclusive start of a fifteen-minute
        metering interval; `kw_demand`, the average demand over that interval as
        a non-negative value at one decimal place; `is_on_peak`, the utility's own
        classification of the interval; and optionally `is_dr_event_day`, which
        defaults to false and marks intervals that fall on a demand-response
        event day so they can be excluded from baseline candidacy."

        Design: Corner/rbac/shared_operations_admit_every_declared_role
        """
        ctx = _activated_store_with_an_account(api)

        by_analyst = fx.ingest_intervals(
            api, ctx["account_id"], [f.demand_interval("2026-06-15T14:00:00Z", 1200.0, True)]
        )
        by_gateway = fx.ingest_intervals(
            api,
            ctx["account_id"],
            [f.demand_interval("2026-06-15T14:15:00Z", 1190.0, True)],
            headers=make_bms_gateway_headers(ctx["store_id"]),
        )

        rows, meta = fx.list_intervals(api, ctx["account_id"])

        assert len(by_analyst) == 1
        assert len(by_gateway) == 1
        assert meta["total_count"] == 2
        assert [row["utility_account_id"] for row in rows] == [ctx["account_id"]] * 2
        assert sorted(row["kw_demand"] for row in rows) == pytest.approx([1190.0, 1200.0])

    def test_both_proposing_roles_score_a_project_alike_but_are_recorded_apart(self, api):
        """The proposer identity is per row; the scoring is not.

        The PRD states: "A project costing 240240.00 dollars against 520000.00
        projected kilowatt-hours at the default blended rate therefore shows
        annual savings of 57200.00 dollars, a payback of 4.20 years and a
        priority score of 58.0."

        Design: Corner/rbac/shared_operations_admit_every_declared_role
        """
        ctx = _activated_store_with_an_account(api)

        by_analyst = fx.create_retrofit(
            api, ctx["store_id"], proposer_user_id="u_analyst_rt"
        )
        by_manager = validate_success(
            api.create_retrofit_project(
                ctx["store_id"],
                f.create_retrofit_project_payload(measure_type="CASE_DOORS"),
                make_energy_manager_headers("u_mgr_rt"),
            ),
            201,
        )

        rows, meta = fx.list_projects(api, ctx["store_id"])

        assert by_analyst["priority_score"] == pytest.approx(58.0, abs=0.05)
        assert by_manager["priority_score"] == pytest.approx(58.0, abs=0.05)
        assert by_analyst["priority_basis"] == "SIMPLE_PAYBACK"
        assert by_manager["priority_basis"] == "SIMPLE_PAYBACK"
        assert by_analyst["state"] == "PROPOSED"
        assert by_manager["state"] == "PROPOSED"
        assert meta["total_count"] == 2
        assert fx.find_row(rows, by_analyst["id"])["proposed_by_user_id"] == "u_analyst_rt"
        assert fx.find_row(rows, by_manager["id"])["proposed_by_user_id"] == "u_mgr_rt"


def _two_activated_stores_one_holding_an_open_excursion(api):
    """Stores A and B both activated on one published standard; A's case has been
    driven to an OPEN excursion by A's own gateway."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T09:00:00Z", code="STR-A"
    )
    store_b = fx.create_store(api, code="STR-B", floor_area_sqft=130000)
    fx.commission_store(api, store_b["id"], ctx["standard_id"], store_b["version"])
    fx.activate_store_bms(api, store_b["id"])
    case = fx.create_case(api, ctx["store_id"], case_code="CASE-A1")
    readings = fx.post_readings(
        api,
        case["id"],
        ctx["store_id"],
        [(43.0, "2026-08-01T04:00:00Z"), (43.0, "2026-08-01T04:15:00Z")],
    )
    ctx["store_b_id"] = store_b["id"]
    ctx["case_id"] = case["id"]
    ctx["excursion_id"] = readings[-1]["excursion_id"]
    return ctx


class TestEntityBackedRolesAreConfinedToTheirOwnStore:
    def test_a_foreign_gateway_may_not_post_a_reading_to_another_stores_case(self, api):
        """Store B's gateway is refused against store A's case.

        The PRD states: "When `X-User-Role` is `BmsGateway`, `X-User-ID` is
        likewise the `id` of the `Store` whose building-management-system gateway
        is calling; ownership checks compare the resource's store-referencing
        field to `X-User-ID`."

        Design: Corner/rbac/entity_backed_roles_are_confined_to_their_own_store
        """
        ctx = _two_activated_stores_one_holding_an_open_excursion(api)

        validate_error(
            api.post_reading(
                ctx["case_id"],
                f.reading_payload(43.0, "2026-08-01T04:30:00Z"),
                make_bms_gateway_headers(ctx["store_b_id"]),
            ),
            ApiErrorId.ERR_STORE_SCOPE_VIOLATION,
            403,
        )

        case = get_success_data(api.get_refrigeration_case(ctx["case_id"], fx.TECH))
        assert case["last_reading_iso"].startswith("2026-08-01T04:15:00")
        assert case["consecutive_breach_count"] == 2

    def test_a_foreign_store_manager_may_neither_write_nor_read_across_the_boundary(self, api):
        """An override request and a pure read are both scope breaches.

        The PRD states: "When `X-User-Role` is `StoreManager`, `X-User-ID` is the
        `id` of the acting `Store`; ownership checks on any resource that
        references a `Store` compare the resource's store-referencing field to
        `X-User-ID`."

        Design: Corner/rbac/entity_backed_roles_are_confined_to_their_own_store
        """
        ctx = _two_activated_stores_one_holding_an_open_excursion(api)

        validate_error(
            api.create_lighting_override(
                ctx["store_id"],
                f.create_lighting_override_payload(
                    override_type="OCCUPANCY_DISABLE",
                    start_iso="2026-08-02T00:00:00Z",
                    end_iso="2026-08-02T06:00:00Z",
                    zone_load_kw=20.0,
                    requested_reason="cross-store attempt",
                ),
                make_store_manager_headers(ctx["store_b_id"]),
            ),
            ApiErrorId.ERR_STORE_SCOPE_VIOLATION,
            403,
        )
        validate_error(
            api.get_store(ctx["store_id"], make_store_manager_headers(ctx["store_b_id"])),
            ApiErrorId.ERR_STORE_SCOPE_VIOLATION,
            403,
        )

        store_a = fx.read_store(api, ctx["store_id"])
        _, a_meta = fx.list_overrides(api, ctx["store_id"])
        _, b_meta = fx.list_overrides(api, ctx["store_b_id"])

        assert store_a["override_kwh_used_month"] == pytest.approx(0.0, abs=0.01)
        assert a_meta["total_count"] == 0
        assert b_meta["total_count"] == 0

    def test_the_excursion_scope_is_resolved_two_hops_from_the_path_id(self, api):
        """Acknowledgement scopes through excursion, case and store.

        The PRD states: "For these two roles the comparison follows the reachable
        path as well as the direct one: a refrigeration case is scoped through its
        owning store, an excursion through its case's owning store, and a utility
        account through the store it hangs from."

        Design: Corner/rbac/entity_backed_roles_are_confined_to_their_own_store
        """
        ctx = _two_activated_stores_one_holding_an_open_excursion(api)

        validate_error(
            api.acknowledge_excursion(
                ctx["excursion_id"], make_store_manager_headers(ctx["store_b_id"])
            ),
            ApiErrorId.ERR_STORE_SCOPE_VIOLATION,
            403,
        )
        blocked = fx.read_excursion(api, ctx["excursion_id"])
        assert blocked["state"] == "OPEN"
        assert blocked["acknowledged_by_user_id"] is None

        acknowledged = validate_success(
            api.acknowledge_excursion(
                ctx["excursion_id"], make_store_manager_headers(ctx["store_id"])
            )
        )
        own_override = validate_success(
            api.create_lighting_override(
                ctx["store_b_id"],
                f.create_lighting_override_payload(
                    override_type="OCCUPANCY_DISABLE",
                    start_iso="2026-08-02T00:00:00Z",
                    end_iso="2026-08-02T06:00:00Z",
                    zone_load_kw=20.0,
                    requested_reason="own-store request",
                ),
                make_store_manager_headers(ctx["store_b_id"]),
            ),
            201,
        )
        own_read = validate_success(
            api.get_store(ctx["store_b_id"], make_store_manager_headers(ctx["store_b_id"]))
        )

        assert acknowledged["state"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_by_user_id"] == ctx["store_id"]
        assert own_override["store_id"] == ctx["store_b_id"]
        assert own_read["id"] == ctx["store_b_id"]

    def test_existence_and_role_are_both_decided_before_the_scope_check(self, api):
        """An unknown excursion is a 404 and a wrong role is a plain 403.

        The PRD states: "Checks are therefore evaluated in a single global order,
        and the **first** violated check determines the response; later checks are
        never reached and never reported."

        Design: Corner/rbac/entity_backed_roles_are_confined_to_their_own_store
        """
        ctx = _two_activated_stores_one_holding_an_open_excursion(api)

        validate_error(
            api.acknowledge_excursion(
                NON_EXISTENT_UUID, make_store_manager_headers(ctx["store_b_id"])
            ),
            ApiErrorId.ERR_EXCURSION_NOT_FOUND,
            404,
        )
        validate_error(
            api.acknowledge_excursion(
                ctx["excursion_id"], make_maintenance_tech_headers("u_tech_sc")
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        assert fx.read_excursion(api, ctx["excursion_id"])["state"] == "OPEN"


PEER_GROUP = {"climate_zone": "MIXED", "store_format": "SUPERCENTER"}


def _store_whose_account_carries_a_candidate_tariff(api):
    """One store with an account offering a candidate tariff and no bills at all."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-RP")
    account = fx.create_account(api, store["id"], **f.candidate_tariff_fields())
    return {"store_id": store["id"], "account_id": account["id"]}


class TestPortfolioReadsAreNarrowerThanEveryOtherRead:
    def test_the_operational_roles_are_denied_the_benchmark_report(self, api):
        """Three roles that may read stores may not read the portfolio benchmark.

        The PRD states: "Benchmarking closes the loop between spend and
        performance, and is available to `PlatformAdmin`, `EnergyManager` and
        `EnergyAnalyst`."

        Design: Corner/rbac/portfolio_report_reads_are_denied_to_the_operational_roles
        """
        ctx = _store_whose_account_carries_a_candidate_tariff(api)

        for headers in (
            make_store_manager_headers(ctx["store_id"]),
            make_food_safety_officer_headers("u_officer_rp"),
            make_maintenance_tech_headers("u_tech_rp"),
        ):
            validate_error(
                api.get_benchmark_report(headers, params=dict(PEER_GROUP)),
                ApiErrorId.ERR_UNAUTHORIZED,
                403,
            )

    def test_the_gateway_is_denied_the_tariff_comparison_of_its_own_account(self, api):
        """The refusal is a role decision, not a scope decision.

        The PRD states: "The tariff-comparison read, available to
        `PlatformAdmin`, `EnergyManager` and `EnergyAnalyst`, is a pure projection
        that writes nothing."

        Design: Corner/rbac/portfolio_report_reads_are_denied_to_the_operational_roles
        """
        ctx = _store_whose_account_carries_a_candidate_tariff(api)

        validate_error(
            api.get_tariff_comparison(
                ctx["account_id"], make_bms_gateway_headers(ctx["store_id"])
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.get_tariff_comparison(
                ctx["account_id"], make_maintenance_tech_headers("u_tech_rp")
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    def test_the_three_portfolio_roles_are_admitted_on_the_same_fixture(self, api):
        """The narrowing applies to exactly these two reads.

        The PRD states: "When the account has no `VALIDATED` or `ADJUSTED` bill at
        all, all of the projection's outputs are null."

        Design: Corner/rbac/portfolio_report_reads_are_denied_to_the_operational_roles
        """
        ctx = _store_whose_account_carries_a_candidate_tariff(api)

        for headers in (fx.ADMIN, fx.MANAGER, fx.ANALYST):
            report = validate_success(api.get_benchmark_report(headers, params=dict(PEER_GROUP)))
            assert report["climate_zone"] == "MIXED"
            assert report["store_format"] == "SUPERCENTER"

            projection = validate_success(api.get_tariff_comparison(ctx["account_id"], headers))
            assert projection["reference_bill_id"] is None
            assert projection["current_annual_cost_usd"] is None
            assert projection["candidate_annual_cost_usd"] is None
            assert projection["annual_delta_usd"] is None
            assert projection["switch_recommended"] is None

        _, meta = fx.list_cases(
            api, ctx["store_id"], headers=make_maintenance_tech_headers("u_tech_rp")
        )
        assert meta["total_count"] == 0


def _one_manager_proposing_on_two_stores(api):
    """Store X never commissioned and store Y activated; u_mgr_dual proposes an
    EMS upgrade on each."""
    ctx = fx.setup_commissioned_store(api, code="STR-Y")
    store_x = fx.create_store(api, code="STR-X", floor_area_sqft=110000)
    proposals = {}
    for key, store_id in (("x", store_x["id"]), ("y", ctx["store_id"])):
        proposals[key] = validate_success(
            api.create_retrofit_project(
                store_id,
                f.create_retrofit_project_payload(measure_type="EMS_UPGRADE"),
                make_energy_manager_headers("u_mgr_dual"),
            ),
            201,
        )
    ctx["store_x_id"] = store_x["id"]
    ctx["project_x"] = proposals["x"]
    ctx["project_y"] = proposals["y"]
    return ctx


class TestARetrofitProposerMayNotApproveTheirOwnProject:
    def test_duty_separation_is_decided_before_the_commissioning_guard(self, api):
        """On an uncommissioned store the self-approval reports the duty code.

        The PRD states: "The capital decision is an `EnergyManager`'s, expressed
        as a `decision` of either `APPROVE` or `REJECT`, and it is subject in
        order to duty separation (the operator must differ from
        `proposed_by_user_id`), to the project being in `PROPOSED`, and to the
        store having a deployed building management system in `ACTIVE` or
        `DEGRADED`."

        Design: Corner/rbac/a_retrofit_proposer_may_not_approve_their_own_project
        """
        ctx = _one_manager_proposing_on_two_stores(api)
        project_x = ctx["project_x"]
        assert project_x["proposed_by_user_id"] == "u_mgr_dual"
        assert project_x["priority_score"] == pytest.approx(58.0, abs=0.05)
        assert project_x["priority_basis"] == "SIMPLE_PAYBACK"

        validate_error(
            api.approve_retrofit_project(
                project_x["id"],
                f.approve_retrofit_payload("APPROVE"),
                make_energy_manager_headers("u_mgr_dual"),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        validate_error(
            api.approve_retrofit_project(
                project_x["id"],
                f.approve_retrofit_payload("APPROVE"),
                make_energy_manager_headers("u_mgr_other"),
            ),
            ApiErrorId.ERR_BMS_NOT_COMMISSIONED,
            409,
        )

        rows, _ = fx.list_projects(api, ctx["store_x_id"])
        assert fx.find_row(rows, project_x["id"])["state"] == "PROPOSED"

    def test_the_self_approval_is_refused_where_nothing_else_can_be_wrong(self, api):
        """On the fully commissioned store only the identity can fail.

        The PRD states: "The project is persisted in `PROPOSED` with
        `priority_basis` `SIMPLE_PAYBACK`, `escalated_review` false, the proposing
        operator recorded in `proposed_by_user_id`, and every measurement field —
        `install_completed_iso`, `baseline_period_kwh`, `post_period_kwh`,
        `mv_period_days`, `adjusted_baseline_kwh`, `measured_savings_kwh`,
        `realization_rate`, `approved_by_user_id` and `revocation_reason` — null."

        Design: Corner/rbac/a_retrofit_proposer_may_not_approve_their_own_project
        """
        ctx = _one_manager_proposing_on_two_stores(api)

        validate_error(
            api.approve_retrofit_project(
                ctx["project_y"]["id"],
                f.approve_retrofit_payload("APPROVE"),
                make_energy_manager_headers("u_mgr_dual"),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        rows, _ = fx.list_projects(api, ctx["store_id"])
        project = fx.find_row(rows, ctx["project_y"]["id"])

        assert project["state"] == "PROPOSED"
        assert project["priority_basis"] == "SIMPLE_PAYBACK"
        assert project["priority_score"] == pytest.approx(58.0, abs=0.05)
        assert project["approved_by_user_id"] is None

    def test_a_different_manager_carries_the_identical_call_through(self, api):
        """The refusal was about identity, not about the project.

        The PRD states: "The project above, approved with no refrigeration faults
        outstanding, drops to 48620.00 dollars of annual savings, a 4.94-year
        payback and a score of 50.6 — a deliberate seven-and-a-half-point haircut
        against its proposal score; the same project approved with five
        refrigeration faults outstanding takes the capped bonus of twenty-four
        points and scores 74.6."

        Design: Corner/rbac/a_retrofit_proposer_may_not_approve_their_own_project
        """
        ctx = _one_manager_proposing_on_two_stores(api)

        approved = validate_success(
            api.approve_retrofit_project(
                ctx["project_y"]["id"],
                f.approve_retrofit_payload("APPROVE"),
                make_energy_manager_headers("u_mgr_other"),
            )
        )

        assert approved["state"] == "APPROVED"
        assert approved["priority_basis"] == "RISK_ADJUSTED"
        assert approved["priority_score"] == pytest.approx(50.6, abs=0.05)
        assert approved["annual_savings_usd"] == pytest.approx(48620.00, abs=0.01)
        assert approved["payback_years"] == pytest.approx(4.94, abs=0.01)
        assert approved["approved_by_user_id"] == "u_mgr_other"
