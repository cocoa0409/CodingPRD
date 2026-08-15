"""Compensating / conservation invariants (PRD §3.7, §3.8) and the modernization
unit-count conservation (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_application,
    create_dispatched_call,
    create_grant_program,
    create_project_payload,
    create_quoted_project,
    create_registered_project,
    create_service_call,
    create_technician,
    create_unit_with_contract,
    factories,
    get_success_data,
    make_homeowner_headers,
    make_inspector_headers,
    make_installer_headers,
    validate_paginated,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


# ===========================================================================
# Queue A — compensating_invariant / grant_pool_conservation
# ===========================================================================

class TestGrantPoolConservation:
    def _setup(self, api):
        ctx = create_quoted_project()
        program = create_grant_program()
        app = create_approved_application(ctx, program)  # 10000.00 debited
        return ctx, program, app

    def test_approve_then_withdraw_conserves_pool(self, api):
        """PRD §3.8: "The pool obeys a conservation invariant: `remaining_pool` always
        equals `total_pool` minus the sum of `final_award` over the program's `APPROVED`
        and `DISBURSED` applications."
        PRD §3.8: "From `APPROVED`, withdrawal additionally credits the `final_award`
        back to the program's `remaining_pool`".

        Design: Difficulty/compensating_invariant/grant_pool_conservation
        """
        ctx, program, app = self._setup(api)
        program = get_success_data(api.get_grant_program(program["id"], OFFICER))
        assert program["remaining_pool"] == 40000.00
        get_success_data(api.withdraw_grant_application(
            app["id"], make_homeowner_headers(ctx["prop"]["owner_user_id"])))
        program = get_success_data(api.get_grant_program(program["id"], OFFICER))
        assert program["remaining_pool"] == 50000.00
        assert program["remaining_pool"] == program["total_pool"]

    def test_withdrawal_recomputes_funding_posture_to_unfunded(self, api):
        """PRD §3.8: "From `APPROVED`, withdrawal additionally credits the `final_award`
        back to the program's `remaining_pool` — reopening an `EXHAUSTED` program if the
        credit lifts the pool above zero — and recomputes the project's
        `funding_posture`."
        PRD §3.8: "when nothing is committed it is `UNFUNDED`."

        Design: Difficulty/compensating_invariant/grant_pool_conservation
        """
        ctx, _program, app = self._setup(api)
        app = get_success_data(api.withdraw_grant_application(
            app["id"], make_homeowner_headers(ctx["prop"]["owner_user_id"])))
        assert app["status"] == "WITHDRAWN"
        project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
        assert project["funding_posture"] == "UNFUNDED"


# ===========================================================================
# Queue A — compensating_invariant / contract_visit_conservation
# ===========================================================================

class TestContractVisitConservation:
    def _setup_dispatched_maintenance(self, api):
        ctx = create_unit_with_contract(tier="STANDARD")  # included_visits 2
        call = create_dispatched_call(ctx, call_type="MAINTENANCE_VISIT")
        return ctx, call

    def test_dispatch_then_cancel_restores_visit(self, api):
        """PRD §3.7: "When a visit was consumed at dispatch, cancellation decrements
        `visits_consumed` by 1 as compensation. This bookkeeping obeys a conservation
        invariant: at every moment, `visits_consumed` plus the derived remaining visits
        equals the contract's `included_visits` for the current contract year."

        Design: Difficulty/compensating_invariant/contract_visit_conservation
        """
        ctx, call = self._setup_dispatched_maintenance(api)
        contract = get_success_data(api.get_service_contract(ctx["contract"]["id"], COORD))
        assert contract["visits_consumed"] == 1
        get_success_data(api.cancel_service_call(
            call["id"], make_homeowner_headers(ctx["prop"]["owner_user_id"])))
        contract = get_success_data(api.get_service_contract(ctx["contract"]["id"], COORD))
        assert contract["visits_consumed"] == 0

    def test_included_visits_unchanged_by_dispatch_cancel_pair(self, api):
        """PRD §3.7: "This bookkeeping obeys a conservation invariant: at every moment,
        `visits_consumed` plus the derived remaining visits equals the contract's
        `included_visits` for the current contract year."
        PRD §3.7: "`STANDARD` carries $1,200.00 with 2 visits and 120 minutes".

        Design: Difficulty/compensating_invariant/contract_visit_conservation
        """
        ctx, call = self._setup_dispatched_maintenance(api)
        call = get_success_data(api.cancel_service_call(
            call["id"], make_homeowner_headers(ctx["prop"]["owner_user_id"])))
        assert call["status"] == "CANCELLED"
        contract = get_success_data(api.get_service_contract(ctx["contract"]["id"], COORD))
        assert contract["included_visits"] == 2
        assert contract["visits_consumed"] == 0


# ===========================================================================
# Queue A — compensating_invariant / property_unit_count_conservation
# ===========================================================================

class TestPropertyUnitCountConservation:
    def _setup_modernization_acceptance(self, api):
        """Unit U1 IN_SERVICE/REGISTERED; MODERNIZATION project driven to
        INSTALL_COMPLETE producing replacement unit U2; MODERNIZATION_ACCEPTANCE
        scheduled with the clock inside its window."""
        ctx = create_registered_project()
        unit1 = ctx["unit"]
        proj2 = get_success_data(api.create_project(
            create_project_payload(ctx["prop"]["id"], ctx["survey"]["id"],
                                   project_type="MODERNIZATION",
                                   modernize_unit_id=unit1["id"]), COORD))
        proj2 = get_success_data(api.update_project(proj2["id"],
            factories.select_product_payload(ctx["model"]["id"], ctx["installer"]["id"],
                                             proj2["version"]), COORD))
        permit2 = get_success_data(api.create_permit(
            factories.create_permit_payload(proj2["id"]), COORD))
        get_success_data(api.approve_permit(permit2["id"], REGULATOR))
        get_success_data(api.schedule_installation(proj2["id"], {
            "install_start_date": "2026-08-15T08:00:00Z",
            "install_end_date": "2026-08-18T17:00:00Z",
        }, COORD))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T09:00:00Z"}, ADMIN))
        get_success_data(api.complete_installation(
            proj2["id"], {"serial_number": "SN-200"},
            make_installer_headers(ctx["installer"]["id"])))
        units, _meta = validate_paginated(api.list_units(COORD, params={"project_id": proj2["id"]}))
        unit2 = units[0]
        insp = get_success_data(api.create_inspection(
            factories.create_inspection_payload(
                unit2["id"], ctx["inspector"]["id"],
                inspection_type="MODERNIZATION_ACCEPTANCE", project_id=proj2["id"],
                scheduled_start="2026-08-15T10:00:00Z",
                scheduled_end="2026-08-15T11:00:00Z"), COORD))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T10:05:00Z"}, ADMIN))
        return ctx, proj2, unit1, unit2, insp

    def test_acceptance_decommissions_old_unit_and_keeps_lineage(self, api):
        """PRD §3.5: "a passing `MODERNIZATION_ACCEPTANCE` additionally decommissions
        the replaced unit, moving it from `UNDER_MODERNIZATION` to `DECOMMISSIONED`
        while the replacement unit remains `INSTALLED`".
        PRD §3.5: "For a modernization, the new unit's `modernized_from_unit_id` records
        the lineage back to the unit being replaced."

        Design: Difficulty/compensating_invariant/property_unit_count_conservation
        """
        ctx, proj2, unit1, unit2, insp = self._setup_modernization_acceptance(api)
        get_success_data(api.record_inspection_result(
            insp["id"], {"result": "PASSED"}, make_inspector_headers(ctx["inspector"]["id"])))
        unit1 = get_success_data(api.get_unit(unit1["id"], COORD))
        assert unit1["equipment_status"] == "DECOMMISSIONED"
        unit2 = get_success_data(api.get_unit(unit2["id"], COORD))
        assert unit2["modernized_from_unit_id"] == unit1["id"]
        project2 = get_success_data(api.get_project(proj2["id"], COORD))
        assert project2["status"] == "AWAITING_REGISTRATION"

    def test_non_decommissioned_unit_count_conserved(self, api):
        """PRD §3.5: "a passing `MODERNIZATION_ACCEPTANCE` additionally decommissions
        the replaced unit, moving it from `UNDER_MODERNIZATION` to `DECOMMISSIONED`
        while the replacement unit remains `INSTALLED`, so the property's count of
        non-decommissioned units is unchanged across the pair."

        Design: Difficulty/compensating_invariant/property_unit_count_conservation
        """
        ctx, _proj2, _unit1, _unit2, insp = self._setup_modernization_acceptance(api)
        get_success_data(api.record_inspection_result(
            insp["id"], {"result": "PASSED"}, make_inspector_headers(ctx["inspector"]["id"])))
        units, _meta = validate_paginated(
            api.list_units(COORD, params={"property_id": ctx["prop"]["id"]}))
        assert len(units) == 2
        live = [u for u in units if u["equipment_status"] != "DECOMMISSIONED"]
        assert len(live) == 1, "1 unit before modernization, 1 after acceptance"
