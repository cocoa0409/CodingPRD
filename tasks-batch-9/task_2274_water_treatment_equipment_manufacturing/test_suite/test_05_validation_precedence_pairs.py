"""When two rules both reject a request, the higher-priority rule names the error."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    assert_money,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
)


class TestSuspensionOutranksReserveShortfall:
    """A suspended agreement reports inactivity, not the reserve shortfall behind it."""

    def _suspended_agreement(self, api):
        state = fixtures.service_active_project(api)
        state["first_draw"] = fixtures.post_draw(
            api,
            state["agreement"]["id"],
            draw_type="CONSUMABLE",
            quantity=10,
            catalog_unit_cost_cents=1000000,
            invoiced_unit_cost_cents=1000000,
        )
        return state

    def test_a_second_draw_on_a_suspended_agreement_reports_inactivity(self, api):
        """The state gate fires before the fiscal gate, so ERR_AGREEMENT_NOT_ACTIVE wins.

        The precedence ladder places the lifecycle-state checks -- including
        `ERR_AGREEMENT_NOT_ACTIVE` -- at step 9 and the "closeout and reserve gates,
        in order: `ERR_DELIVERABLES_INCOMPLETE`, `ERR_INVALID_DRAW_QUANTITY`, then
        `ERR_RESERVE_INSUFFICIENT`" at step 17. The PRD also states directly that
        "only after the sweep is the agreement's status checked: a `SUSPENDED` or
        `PENDING_ACTIVATION` agreement accepts no draw and is refused with
        `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/agreement_not_active_outranks_reserve_insufficient
        """
        state = self._suspended_agreement(api)
        agreement = fixtures.current_agreement(api, state["agreement"]["id"])

        response = api.create_consumable_draw(
            agreement["id"],
            factories.consumable_draw_payload(
                agreement["version"],
                draw_type="CONSUMABLE",
                quantity=1,
                catalog_unit_cost_cents=1000000,
                invoiced_unit_cost_cents=1000000,
            ),
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.AGREEMENT_NOT_ACTIVE.value, 409)

    def test_the_refused_draw_leaves_the_spent_reserve_exactly_as_it_was(self, api):
        """Nothing is persisted: the reserve stays at zero and only the first draw exists.

        A draw whose accrual line "exactly equals the available reserve is therefore
        accepted, spends the reserve down to exactly zero, and drives the agreement
        `ACTIVE → SUSPENDED` in the same operation." Section 2.11 pins the invariant
        that "at every instant `reserve_committed_accrual_cents` plus
        `reserve_available_cents` equals `reserve_funded_cents`, in whole cents, with
        no rounding slack."

        Design: Difficulty/priority_pair_validation_conflict/agreement_not_active_outranks_reserve_insufficient
        """
        state = self._suspended_agreement(api)
        agreement = fixtures.current_agreement(api, state["agreement"]["id"])

        api.create_consumable_draw(
            agreement["id"],
            factories.consumable_draw_payload(
                agreement["version"],
                draw_type="CONSUMABLE",
                quantity=1,
                catalog_unit_cost_cents=1000000,
                invoiced_unit_cost_cents=1000000,
            ),
            make_contracts_administrator_headers(),
        )

        after = fixtures.current_agreement(api, state["agreement"]["id"])
        assert after["status"] == "SUSPENDED"
        assert_money(after["reserve_available_cents"], 0, "reserve_available_cents")
        assert_money(
            after["reserve_committed_accrual_cents"],
            12200000,
            "reserve_committed_accrual_cents",
        )

        _, meta = validate_paginated(
            api.list_consumable_draws(
                make_contracts_administrator_headers(),
                {"service_agreement_id": agreement["id"]},
            )
        )
        assert meta["total_count"] == 1


class TestPressureRatingOutranksCodeStampability:
    """An unrated pressure is reported even when the material also fails the stamp."""

    def _pvc_against_filtration(self, api):
        state = fixtures.scoped_single_stage_project(api)
        state["pvc"] = fixtures.seed_pvc_material_spec(api)
        return state

    def test_overpressured_pvc_package_reports_the_pressure_screen(self, api):
        """Screen 2 fires before screen 3, so the pressure error wins over the stamp error.

        The three screens "are evaluated in this order", with "*Pressure rating.* The
        package's `design_pressure_psig` must be at most the material's
        `max_pressure_psig`; exceeding it is `ERR_MATERIAL_PRESSURE_EXCEEDED`" ahead of
        "*Code stampability.* The material must be capable of the stamp the stage
        technology demands: a `code_stamp_required` of `ASME_U` demands
        `asme_u_capable` be true, `NSF61` demands `nsf61_certified` be true, `AWWA`
        demands `awwa_compliant` be true, and `NONE` demands nothing at all."

        Design: Difficulty/priority_pair_validation_conflict/material_pressure_outranks_code_stamp_capability
        """
        state = self._pvc_against_filtration(api)

        response = api.create_equipment_package(
            state["filtration_stage"]["id"],
            factories.equipment_package_payload(
                state["pvc"]["id"], tag_number="F-100", design_pressure_psig=200
            ),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.MATERIAL_PRESSURE_EXCEEDED.value, 422)

    def test_the_refused_package_is_not_persisted_and_the_stage_stays_selected(self, api):
        """No package row is written and the parent stage remains SELECTED.

        A rejected design leaves nothing behind: the stage created by the selection run
        has its "`status` is `SELECTED`", and the pressure screen is one of the three
        that "stand between a chosen material and a buildable package, and all three
        are re-run at package creation, at every revision, and again at submission for
        review".

        Design: Difficulty/priority_pair_validation_conflict/material_pressure_outranks_code_stamp_capability
        """
        state = self._pvc_against_filtration(api)

        api.create_equipment_package(
            state["filtration_stage"]["id"],
            factories.equipment_package_payload(
                state["pvc"]["id"], tag_number="F-100", design_pressure_psig=200
            ),
            make_application_engineer_headers(),
        )

        _, meta = validate_paginated(
            api.list_equipment_packages(
                make_application_engineer_headers(),
                {"treatment_stage_id": state["filtration_stage"]["id"]},
            )
        )
        assert meta["total_count"] == 0

        stage = validate_success(
            api.get_treatment_stage(
                state["filtration_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert stage["status"] == "SELECTED"
