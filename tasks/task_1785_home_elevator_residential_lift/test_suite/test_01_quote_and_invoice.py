"""Provisional-vs-final dual variants and combinatorial pricing (PRD §3.2, §3.3, §3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_grant_application_payload,
    create_grant_program,
    create_quoted_project,
    create_service_call,
    create_technician,
    create_unit_with_contract,
    create_change_order_payload,
    factories,
    get_success_data,
    make_homeowner_headers,
    make_inspector_headers,
    make_installer_headers,
    validate_paginated,
)

COORD = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


def _drive_to_registered(api, ctx, serial_number="SN-100"):
    """Advance a QUOTED-project context to REGISTERED and return (project, unit, cert)."""
    project_id = ctx["project"]["id"]
    permit = get_success_data(api.create_permit(factories.create_permit_payload(project_id), COORD))
    get_success_data(api.approve_permit(permit["id"], REGULATOR))
    get_success_data(api.schedule_installation(
        project_id, factories.schedule_installation_payload(), COORD))
    get_success_data(api.set_clock({"to_iso8601": "2026-08-12T09:00:00Z"}, ADMIN))
    get_success_data(api.complete_installation(
        project_id, {"serial_number": serial_number},
        make_installer_headers(ctx["installer"]["id"])))
    units, _ = validate_paginated(api.list_units(COORD, params={"project_id": project_id}))
    inspector = create_technician(name="Quinn Inspector", certification="QEI")
    insp = get_success_data(api.create_inspection(
        factories.create_inspection_payload(units[0]["id"], inspector["id"],
                                            project_id=project_id), COORD))
    get_success_data(api.set_clock({"to_iso8601": "2026-08-12T10:05:00Z"}, ADMIN))
    get_success_data(api.record_inspection_result(
        insp["id"], {"result": "PASSED"}, make_inspector_headers(inspector["id"])))
    cert = get_success_data(api.create_certificate(
        factories.create_certificate_payload(units[0]["id"]), COORD))
    get_success_data(api.issue_certificate(cert["id"], REGULATOR))
    project = get_success_data(api.get_project(project_id, COORD))
    return project, units[0], cert


# ===========================================================================
# Queue A — dual_variant_calc / project_quote_vs_final_invoice
# ===========================================================================

class TestProjectQuoteVsFinalInvoice:
    def _setup_registered_with_change_orders(self, api):
        ctx = create_quoted_project()
        project = ctx["project"]
        owner = make_homeowner_headers(ctx["prop"]["owner_user_id"])
        co1 = get_success_data(api.create_change_order(
            create_change_order_payload(project["id"], description="Add hall call station",
                                        amount=5000.00), COORD))
        co2 = get_success_data(api.create_change_order(
            create_change_order_payload(project["id"], description="Upgrade cab finish",
                                        amount=3000.00), COORD))
        co1 = get_success_data(api.approve_change_order(co1["id"], owner))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, ADMIN))
        co2 = get_success_data(api.approve_change_order(co2["id"], owner))
        project, _unit, _cert = _drive_to_registered(api, ctx)
        return project, co1, co2

    def test_final_invoice_combines_price_and_marked_up_change_orders(self, api):
        """PRD §3.8: "Close first computes `final_invoice`: the `contract_price`, plus the
        sum of `effective_amount` over all approved change orders (each frozen at
        approval by the markup rule), plus the `structural_adjustment`."

        Design: Difficulty/dual_variant_calc/project_quote_vs_final_invoice
        """
        project, _co1, _co2 = self._setup_registered_with_change_orders(api)
        project = get_success_data(api.close_project(project["id"], COORD))
        assert project["status"] == "CLOSED"
        assert project["contract_price"] == 33000.00
        assert project["final_invoice"] == 41300.00
        assert project["final_invoice"] != project["contract_price"]
        assert project["disbursed_grants"] == 0
        assert project["homeowner_balance"] == 41300.00

    def test_change_order_markup_frozen_at_approval(self, api):
        """PRD §3.8: "the project's chronologically first approved change order (ordered
        by `approved_at` ascending, ties broken by `created_at` ascending) takes its
        `amount` with no markup, while every subsequently approved change order takes
        its `amount` increased by 10 percent, rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/project_quote_vs_final_invoice
        """
        project, co1, co2 = self._setup_registered_with_change_orders(api)
        co1 = get_success_data(api.get_change_order(co1["id"], COORD))
        co2 = get_success_data(api.get_change_order(co2["id"], COORD))
        assert co1["effective_amount"] == 5000.00, "first approved: markup waived"
        assert co2["effective_amount"] == 3300.00, "second approved: +10% round_half_up"
        project = get_success_data(api.close_project(project["id"], COORD))
        assert project["final_invoice"] == pytest.approx(33000.00 + 5000.00 + 3300.00, abs=0.01)


# ===========================================================================
# Queue A — dual_variant_calc / grant_provisional_vs_final_award
# ===========================================================================

class TestGrantProvisionalVsFinalAward:
    def _setup(self, api):
        ctx = create_quoted_project(model_overrides={
            "model_code": "HYD-050", "min_pit_depth_inches": 8,
            "min_overhead_clearance_inches": 90, "capacity_lbs": 500,
            "base_price": 12000.00, "install_labor_price": 8000.00,
        })
        program = create_grant_program()  # max 10000, cap 60000, cov 0.40, pool 50000
        owner = make_homeowner_headers(ctx["prop"]["owner_user_id"])
        app = get_success_data(api.create_grant_application(
            create_grant_application_payload(ctx["project"]["id"], program["id"]), owner))
        # Raise the current contract value after submission via an approved change order.
        co = get_success_data(api.create_change_order(
            create_change_order_payload(ctx["project"]["id"], description="Widen doorway",
                                        amount=5000.00), COORD))
        get_success_data(api.approve_change_order(co["id"], owner))
        return ctx, program, app

    def test_provisional_award_anchors_to_submission_value(self, api):
        """PRD §3.8: "A successful submission lands in `SUBMITTED`, stamps
        `submitted_at`, and computes the `provisional_award`: the lesser of the
        program's `max_award` and the `coverage_percent` fraction of the project's
        current contract value — defined as `contract_price` plus
        `approved_change_order_total` — with the coverage product rounded half-up to 2
        decimals."

        Design: Difficulty/dual_variant_calc/grant_provisional_vs_final_award
        """
        _ctx, _program, app = self._setup(api)
        assert app["provisional_award"] == 8000.00  # 0.40 x 20000.00 at submission

    def test_final_award_reanchors_to_current_value(self, api):
        """PRD §3.8: "The **final award** recomputes coverage against the current
        contract value at approval time — again `contract_price` plus
        `approved_change_order_total`, the coverage fraction rounded half-up to 2
        decimals — and then takes the smallest of three caps: that coverage amount, the
        program's `max_award`, and the program's `remaining_pool`."

        Design: Difficulty/dual_variant_calc/grant_provisional_vs_final_award
        """
        _ctx, program, app = self._setup(api)
        approved = get_success_data(api.approve_grant_application(
            app["id"], {"verified_income": 42000.00}, OFFICER))
        assert approved["status"] == "APPROVED"
        assert approved["final_award"] == 10000.00  # min(0.40 x 25000, max 10000, pool)
        assert approved["final_award"] != approved["provisional_award"]
        program = get_success_data(api.get_grant_program(program["id"], OFFICER))
        assert program["remaining_pool"] == 40000.00


# ===========================================================================
# Queue A — dual_variant_calc / entrapment_estimate_vs_final_bill
# ===========================================================================

class TestEntrapmentEstimateVsFinalBill:
    def _setup(self, api):
        ctx = create_unit_with_contract(tier="STANDARD")
        get_success_data(api.set_clock({"to_iso8601": "2026-09-10T17:30:00Z"}, ADMIN))
        call = create_service_call(ctx, call_type="ENTRAPMENT", description="Passenger trapped")
        call = get_success_data(api.dispatch_service_call(
            call["id"], {"technician_id": ctx["installer"]["id"]}, COORD))
        get_success_data(api.set_clock({"to_iso8601": "2026-09-10T19:00:00Z"}, ADMIN))
        call = get_success_data(api.arrive_service_call(
            call["id"], make_installer_headers(ctx["installer"]["id"])))
        get_success_data(api.set_clock({"to_iso8601": "2026-09-10T20:15:00Z"}, ADMIN))
        return ctx, call

    def test_provisional_estimate_is_flat_tier_constant(self, api):
        """PRD §3.7: "Dispatch also computes the commercial baseline: the
        `provisional_estimate` is a flat $0.00 for a `PREMIUM` contract, $150.00 for
        `STANDARD`, $300.00 for `BASIC`, and $450.00 for an ad-hoc call".

        Design: Difficulty/dual_variant_calc/entrapment_estimate_vs_final_bill
        """
        _ctx, call = self._setup(api)
        assert call["provisional_estimate"] == 150.00
        assert call["sla_breached"] is False  # 90 min <= 120 min SLA

    def test_final_billable_computed_from_actuals(self, api):
        """PRD §3.7: "the on-site duration from `arrived_at` to `resolved_at` in minutes
        is rounded **up** to whole half-hour units; each unit bills at $60.00; if the
        arrival's UTC hour is at or after 18 or before 7 the labor amount is multiplied
        by 1.5 and rounded half-up to 2 decimals; parts cost is then added; ... an
        attached `STANDARD` contract halves the gross with round-half-up to 2 decimals".
        PRD §3.7: "The provisional estimate is deliberately approximate by design: it
        ignores duration, parts, after-hours timing, and SLA outcome, and may diverge
        arbitrarily from the final bill."

        Design: Difficulty/dual_variant_calc/entrapment_estimate_vs_final_bill
        """
        ctx, call = self._setup(api)
        resolved = get_success_data(api.resolve_service_call(
            call["id"], {"resolution_notes": "Freed passenger, reset brake", "parts_cost": 125.00},
            make_installer_headers(ctx["installer"]["id"])))
        assert resolved["status"] == "RESOLVED"
        # ceil(75/30)=3 units x 60 = 180; after-hours x1.5 = 270; +125 parts = 395; x0.5 = 197.50
        assert resolved["final_billable"] == 197.50
        assert resolved["final_billable"] != resolved["provisional_estimate"]


# ===========================================================================
# Queue A — combinatorial_formula / quote_structural_tiers_and_floors
# ===========================================================================

class TestQuoteStructuralTiersAndFloors:
    def _setup(self, api):
        return create_quoted_project(
            model_overrides={"model_code": "HYD-200", "min_pit_depth_inches": 16,
                             "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                             "base_price": 30000.00, "install_labor_price": 9500.00},
            survey_overrides={"floors_served": 4},
            prop_overrides={"address_line": "7 Hill Ct", "state_code": "WA"},
            contractor=True)

    def test_structural_estimate_combines_base_pit_overhead(self, api):
        """PRD §3.2: "When `requires_structural` is true, the `structural_estimate` is a
        base structural fee of $1,500.00 plus $250.00 per inch of pit shortfall plus
        $150.00 per inch of overhead shortfall".

        Design: Difficulty/combinatorial_formula/quote_structural_tiers_and_floors
        """
        project = self._setup(api)["project"]
        assert project["requires_structural"] is True
        # 1500.00 base + 4 x 250.00 pit + 4 x 150.00 overhead
        assert project["structural_estimate"] == 3100.00

    def test_contract_price_adds_floor_fee_beyond_two_landings(self, api):
        """PRD §3.2: "The floor fee is $750.00 for each landing beyond the two landings
        included in every installation — that is, the count of `floors_served` above 2,
        floored at zero, times $750.00. The `contract_price` is then the model's
        `base_price` plus its `install_labor_price` plus the `structural_estimate` plus
        the floor fee".

        Design: Difficulty/combinatorial_formula/quote_structural_tiers_and_floors
        """
        project = self._setup(api)["project"]
        assert project["status"] == "QUOTED"
        # 30000.00 + 9500.00 + 3100.00 + (4-2) x 750.00
        assert project["contract_price"] == 44100.00


# ===========================================================================
# Queue A — combinatorial_formula / permit_fee_per_component_rounding
# ===========================================================================

class TestPermitFeePerComponentRounding:
    def _setup_quoted_at_16666_67(self, api):
        return create_quoted_project(model_overrides={
            "model_code": "HYD-300", "drive_type": "TRACTION",
            "min_pit_depth_inches": 8, "min_overhead_clearance_inches": 90,
            "capacity_lbs": 700, "base_price": 8666.67, "install_labor_price": 8000.00,
        })

    def test_fee_rounds_each_component_before_summing(self, api):
        """PRD §3.3: "The permit `fee` is computed at filing with a pinned rounding
        order: each percentage component is rounded half-up to 2 decimal places
        **before** summation, and no rounding happens after the sum."

        Design: Difficulty/combinatorial_formula/permit_fee_per_component_rounding
        """
        ctx = self._setup_quoted_at_16666_67(api)
        permit = get_success_data(api.create_permit(
            factories.create_permit_payload(ctx["project"]["id"], ahj_name="Portland AHJ"), COORD))
        # 250.00 + (50 x 2) + round(0.015 x 16666.67)=250.00 + round(0.004 x)=66.67
        # + round(0.007 x)=116.67
        assert permit["fee"] == 783.34

    def test_fee_diverges_from_sum_then_round(self, api):
        """PRD §2.5: "in particular, the permit fee is rounded per component before
        summation and is never re-rounded after the sum, because summing raw components
        and rounding once at the end is a different algorithm that can diverge by whole
        cents."

        Design: Difficulty/combinatorial_formula/permit_fee_per_component_rounding
        """
        ctx = self._setup_quoted_at_16666_67(api)
        permit = get_success_data(api.create_permit(
            factories.create_permit_payload(ctx["project"]["id"], ahj_name="Portland AHJ"), COORD))
        assert permit["fee"] == 783.34
        assert permit["fee"] != 783.33, "sum-then-round alternative is rejected"
        project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
        assert project["status"] == "PERMIT_IN_PROGRESS"


# ===========================================================================
# Queue A — combinatorial_formula / grant_waterfall_circular_balance
# ===========================================================================

class TestGrantWaterfallCircularBalance:
    def _setup(self, api):
        ctx = create_quoted_project()
        proj_id = ctx["project"]["id"]
        prog1 = create_grant_program(program_name="ProgA", funder_name="Fund A",
                                     max_award=10000.00, coverage_percent=0.40,
                                     total_pool=100000.00)
        prog2 = create_grant_program(program_name="ProgB", funder_name="Fund B",
                                     max_award=6000.00, coverage_percent=0.30,
                                     total_pool=100000.00)
        prog3 = create_grant_program(program_name="ProgC", funder_name="Fund C",
                                     max_award=25000.00, coverage_percent=0.80,
                                     total_pool=100000.00)
        owner = make_homeowner_headers(ctx["prop"]["owner_user_id"])
        app1 = get_success_data(api.create_grant_application(
            create_grant_application_payload(proj_id, prog1["id"]), owner))
        app2 = get_success_data(api.create_grant_application(
            create_grant_application_payload(proj_id, prog2["id"]), owner))
        app3 = get_success_data(api.create_grant_application(
            create_grant_application_payload(proj_id, prog3["id"]), owner))
        app1 = get_success_data(api.approve_grant_application(
            app1["id"], {"verified_income": 42000.00}, OFFICER))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, ADMIN))
        app2 = get_success_data(api.approve_grant_application(
            app2["id"], {"verified_income": 42000.00}, OFFICER))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-03T00:00:00Z"}, ADMIN))
        app3 = get_success_data(api.approve_grant_application(
            app3["id"], {"verified_income": 42000.00}, OFFICER))
        project, _unit, _cert = _drive_to_registered(api, ctx)
        return project, (app1["id"], app2["id"], app3["id"])

    def test_waterfall_disburses_in_approval_order_with_partial_last(self, api):
        """PRD §3.8: "It then runs the **grant disbursement waterfall** over the
        project's `APPROVED` applications — and only `APPROVED` ones; `SUBMITTED`,
        `DENIED`, and `WITHDRAWN` applications are excluded — in pinned chronological
        order by `approved_at` ascending with ties broken by `created_at` ascending."

        Design: Difficulty/combinatorial_formula/grant_waterfall_circular_balance
        """
        project, (a1, a2, a3) = self._setup(api)
        get_success_data(api.close_project(project["id"], COORD))
        app1 = get_success_data(api.get_grant_application(a1, OFFICER))
        app2 = get_success_data(api.get_grant_application(a2, OFFICER))
        app3 = get_success_data(api.get_grant_application(a3, OFFICER))
        assert app1["disbursed"] == 10000.00 and app1["status"] == "DISBURSED"
        assert app2["disbursed"] == 6000.00 and app2["status"] == "DISBURSED"
        # Third clamps to the remaining balance: 33000 - 16000 = 17000.
        assert app3["disbursed"] == 17000.00 and app3["status"] == "DISBURSED"

    def test_waterfall_resolves_circular_balance_dependency(self, api):
        """PRD §3.8: "When the pass completes, the project's `disbursed_grants` is the
        sum of all disbursed amounts and `homeowner_balance` is the final remaining
        balance — `final_invoice` minus `disbursed_grants`. The waterfall resolves what
        would otherwise be a circular dependency between the balance and each
        disbursement cap by fixing the chronological pass."

        Design: Difficulty/combinatorial_formula/grant_waterfall_circular_balance
        """
        project, _apps = self._setup(api)
        project = get_success_data(api.close_project(project["id"], COORD))
        assert project["status"] == "CLOSED"
        assert project["final_invoice"] == 33000.00
        assert project["disbursed_grants"] == 33000.00
        assert project["homeowner_balance"] == 0.00
