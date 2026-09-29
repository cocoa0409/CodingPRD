"""Stale parent tokens, and the selector that ranks by load rather than by recency."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CONTROLS_SEQUENCE,
    MECHANICAL_SEQUENCE,
    ApiErrorId,
    assert_bay_ledger,
    assert_money,
    assert_project_state,
    assert_skid_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
    make_fabrication_manager_headers,
    make_quality_engineer_headers,
)


class TestStaleParentVersions:
    """Each of the three guarded writes refuses the token it no longer matches."""

    def test_a_booking_quoting_a_superseded_skid_version_is_refused(self, api):
        """The skid really is READY, so the 412 proves the version guard fires on its own.

        The PRD says "booking a factory acceptance test run requires
        `expected_skid_version`, matching the target skid's current `version`. A mismatch is
        refused with `ERR_STALE_SKID_VERSION` (HTTP 412). The rule exists because an
        accepted booking legitimately supersedes the skid's outstanding scheduled run and
        releases that run's reserved bay footprint-minutes; a writer holding an out-of-date
        view of the skid would cancel a booking it never saw." When the write is refused
        "nothing is persisted".

        Design: Corner/cross_cutting_complexity_layers/stale_skid_version_refuses_the_fat_booking
        """
        state = fixtures.released_single_stage_project(api)
        skid_id = state["skid"]["id"]
        fixtures.advance_dimension(api, skid_id, "MECHANICAL", MECHANICAL_SEQUENCE)
        fixtures.advance_dimension(
            api, skid_id, "CONTROLS", CONTROLS_SEQUENCE, up_to="LOOP_TESTED"
        )
        stale_version = fixtures.current_skid(api, skid_id)["version"]
        validate_success(
            api.record_skid_milestone(
                skid_id,
                factories.milestone_payload("CONTROLS", "CONTROLS_COMPLETE"),
                make_fabrication_manager_headers(),
            )
        )

        response = api.create_fat_run(
            factories.fat_run_payload(
                skid_id, state["test_bay"]["id"], stale_version
            ),
            make_fabrication_manager_headers(),
        )

        validate_error(response, ApiErrorId.STALE_SKID_VERSION.value, 412)

        skid = fixtures.current_skid(api, skid_id)
        assert_skid_state(
            skid,
            mechanical_status="MECH_COMPLETE",
            controls_status="CONTROLS_COMPLETE",
            fat_readiness="READY",
        )

        bay = validate_success(
            api.get_test_bay(
                state["test_bay"]["id"], make_fabrication_manager_headers()
            )
        )
        assert_bay_ledger(bay, 0)

        _, meta = validate_paginated(
            api.list_fat_runs(
                make_fabrication_manager_headers(), {"skid_id": skid_id}
            )
        )
        assert meta["total_count"] == 0

    def test_two_draws_posted_from_one_read_of_the_agreement_are_refused(self, api):
        """The second draw would have fitted the remaining reserve and is still refused.

        The PRD says "posting a consumable or membrane draw requires
        `expected_service_agreement_version`, matching the target agreement's current
        `version`. A mismatch is refused with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). Each
        accepted draw legitimately reduces `reserve_available_cents`, so a writer working
        from an out-of-date reserve balance would overdraw a reserve it believes is still
        full." The fiscal gate it protects only bites when the accrual line "is **strictly
        greater** than the agreement's current `reserve_available_cents`."

        Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_refuses_the_second_draw
        """
        state = fixtures.service_active_project(api)
        agreement_id = state["agreement"]["id"]
        stale_version = fixtures.current_agreement(api, agreement_id)["version"]
        first = fixtures.post_draw(
            api,
            agreement_id,
            draw_type="CONSUMABLE",
            quantity=3,
            catalog_unit_cost_cents=500000,
            invoiced_unit_cost_cents=480000,
        )

        response = api.create_consumable_draw(
            agreement_id,
            factories.consumable_draw_payload(
                stale_version,
                draw_type="CONSUMABLE",
                item_code="MF-ELEM-8",
                quantity=2,
                catalog_unit_cost_cents=700000,
                invoiced_unit_cost_cents=690000,
            ),
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.STALE_AGREEMENT_VERSION.value, 412)

        assert_money(first["accrual_amount_cents"], 1830000, "accrual_amount_cents")
        assert_money(first["settled_amount_cents"], 1533600, "settled_amount_cents")

        agreement = fixtures.current_agreement(api, agreement_id)
        assert_money(
            agreement["reserve_committed_accrual_cents"],
            1830000,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            agreement["reserve_committed_settled_cents"],
            1533600,
            "reserve_committed_settled_cents",
        )
        assert_money(
            agreement["reserve_available_cents"],
            10370000,
            "reserve_available_cents",
        )
        assert_money(
            agreement["settlement_variance_cents"],
            -296400,
            "settlement_variance_cents",
        )
        assert agreement["status"] == "ACTIVE"

        _, meta = validate_paginated(
            api.list_consumable_draws(
                make_contracts_administrator_headers(),
                {"service_agreement_id": agreement_id},
            )
        )
        assert meta["total_count"] == 1

    def test_a_second_deviation_quoting_the_creation_token_is_refused(self, api):
        """The score the writer never observed is not lowered a second time.

        The PRD says "disclosing a specification deviation on an or-equal submittal requires
        `expected_or_equal_submittal_version`, matching the target submittal's current
        `version`. A mismatch is refused with `ERR_STALE_SUBMITTAL_VERSION` (HTTP 412).
        Every accepted deviation legitimately lowers `compliance_score`, so a writer holding
        an out-of-date score would push the submittal under the compliance floor without
        having observed the penalty it is adding to."

        Design: Corner/cross_cutting_complexity_layers/stale_submittal_version_refuses_the_chained_deviation
        """
        state = fixtures.scoped_single_stage_project(api)
        submittal = fixtures.add_submittal(api, state["project"]["id"])
        creation_version = submittal["version"]
        moderate = fixtures.add_deviation(
            api, submittal["id"], "MODERATE", spec_paragraph="2.03.B"
        )

        response = api.create_spec_deviation(
            submittal["id"],
            factories.spec_deviation_payload(
                creation_version,
                severity="MINOR",
                spec_paragraph="2.05.C",
                description="Nameplate layout differs from named basis",
            ),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.STALE_SUBMITTAL_VERSION.value, 412)

        stored = validate_success(
            api.get_or_equal_submittal(
                submittal["id"], make_application_engineer_headers()
            )
        )
        assert stored["status"] == "DRAFT"
        assert stored["compliance_score"] == 94.00
        assert stored["open_fundamental_count"] == 0
        assert moderate["weighted_penalty_points"] == 6.00

        _, meta = validate_paginated(
            api.list_spec_deviations(
                make_application_engineer_headers(),
                {"or_equal_submittal_id": submittal["id"]},
            )
        )
        assert meta["total_count"] == 1


class TestGoverningSampleSelector:
    """Among accepted samples the worst-case hydraulic load wins, not the newest row."""

    def test_the_earlier_higher_flow_sample_governs_the_train(self, api):
        """A later 2.000 mgd sample is ignored, so the stage is sized on 6.000 mgd.

        The PRD says "among the candidates, the sample with the greatest `design_flow_mgd`
        wins, comparing flows at three decimal places", and sizes the stage from the winner:
        "filtration and disinfection stages are sized on peak flow: the stage's
        `design_flow_mgd` is the governing sample's `design_flow_mgd` multiplied by that
        sample's `peak_factor`, rounded half up to three decimal places." The capital term
        follows: "multiply the candidate's `unit_capex_cents_per_mgd` by the stage design
        flow and round the product **up** to the next whole cent. This capital figure is
        also what the stage stores as its `equipment_base_cost_cents`".

        Design: Corner/cross_cutting_complexity_layers/worst_case_accepted_profile_governs_not_the_latest_one
        """
        fixtures.seed_material_spec(api)
        fixtures.seed_filtration_technology(api)
        project = fixtures.create_draft_project(api)
        worst_case = fixtures.add_accepted_influent_profile(
            api, project["id"], sample_label="RAW-2026-07", design_flow_mgd=4.000
        )
        lighter = fixtures.add_accepted_influent_profile(
            api, project["id"], sample_label="RAW-2026-08", design_flow_mgd=2.000
        )
        fixtures.add_turbidity_objective(api, project["id"])

        stages = validate_success(
            api.run_process_selection(
                project["id"], make_application_engineer_headers()
            ),
            201,
        )

        assert len(stages) == 1
        stage = stages[0]
        assert stage["design_flow_mgd"] == 6.000
        assert_money(
            stage["equipment_base_cost_cents"],
            240000000,
            "equipment_base_cost_cents",
        )
        assert stage["stage_index"] == 1

        stored = validate_success(
            api.get_project(project["id"], make_contracts_administrator_headers())
        )
        assert stored["governing_influent_profile_id"] == worst_case["id"]
        assert stored["governing_influent_profile_id"] != lighter["id"]
        assert_project_state(stored, status="SCOPED")

        ignored = validate_success(
            api.get_influent_profile(lighter["id"], make_quality_engineer_headers())
        )
        assert ignored["qa_status"] == "ACCEPTED"

        _, meta = validate_paginated(
            api.list_treatment_stages(
                make_application_engineer_headers(), {"project_id": project["id"]}
            )
        )
        assert meta["total_count"] == 1
