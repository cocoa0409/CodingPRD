"""Each declared refusal, reached deliberately, with the state it must leave behind."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    UNKNOWN_ID,
    ApiErrorId,
    assert_money,
    assert_project_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_commissioning_engineer_headers,
    make_contracts_administrator_headers,
    make_engineer_of_record_headers,
    make_fabrication_manager_headers,
    make_platform_admin_headers,
    make_quality_engineer_headers,
)

PAST_THE_TERM = "2032-01-01T00:00:00.000Z"


class TestUnknownPathIdentifiers:
    """Every addressable identifier answers with its own not-found code."""

    def test_a_qa_decision_on_an_unknown_profile_is_not_found(self, api):
        """Existence outranks the already-decided conflict, so this is a 404 not a 409.

        Section 2.9 pins that the path identifiers "each has its own not-found code:
        `ERR_PROJECT_NOT_FOUND`, `ERR_INFLUENT_PROFILE_NOT_FOUND`,
        `ERR_TREATMENT_OBJECTIVE_NOT_FOUND`, `ERR_TREATMENT_STAGE_NOT_FOUND`,
        `ERR_EQUIPMENT_PACKAGE_NOT_FOUND`, `ERR_SKID_NOT_FOUND`, `ERR_FAT_RUN_NOT_FOUND`,
        `ERR_SUBMITTAL_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND`, `ERR_DEMO_NOT_FOUND`,
        `ERR_SERVICE_AGREEMENT_NOT_FOUND` and `ERR_CONSUMABLE_DRAW_NOT_FOUND`, each HTTP
        404", and the precedence ladder places "path existence" above the lifecycle-state
        checks.

        Design: Corner/errors/qa_decision_on_an_unknown_influent_profile_is_not_found
        """
        response = api.decide_influent_profile_qa(
            UNKNOWN_ID, {"decision": "ACCEPT"}, make_quality_engineer_headers()
        )

        validate_error(response, ApiErrorId.INFLUENT_PROFILE_NOT_FOUND.value, 404)

    def test_creating_a_package_under_an_unknown_stage_is_not_found(self, api):
        """The stage path segment is resolved before the body's material reference.

        Section 2.9 says "a request addressing a package under a stage resolves the
        `stage_id` before it looks at the body", and puts "path existence, in the order the
        identifiers appear above: `ERR_PROJECT_NOT_FOUND`, then
        `ERR_INFLUENT_PROFILE_NOT_FOUND`, `ERR_TREATMENT_STAGE_NOT_FOUND`" ahead of the
        catalog reference check.

        Design: Corner/errors/package_creation_under_an_unknown_stage_is_not_found
        """
        material = fixtures.seed_material_spec(api)

        response = api.create_equipment_package(
            UNKNOWN_ID,
            factories.equipment_package_payload(material["id"]),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.TREATMENT_STAGE_NOT_FOUND.value, 404)

    def test_submitting_an_unknown_package_for_review_is_not_found(self, api):
        """The package action route answers 404 before any package state guard runs.

        Section 2.9's ladder puts "path existence" — including
        `ERR_EQUIPMENT_PACKAGE_NOT_FOUND` — above the "lifecycle-state checks, in order:
        `ERR_INVALID_PROJECT_STATE`, `ERR_BID_ALREADY_SUBMITTED`,
        `ERR_PROFILE_ALREADY_DECIDED`, `ERR_PACKAGE_INVALID_STATE`".

        Design: Corner/errors/submit_for_review_on_an_unknown_package_is_not_found
        """
        response = api.submit_package_for_review(
            UNKNOWN_ID, make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.EQUIPMENT_PACKAGE_NOT_FOUND.value, 404)

    def test_cancelling_an_unknown_factory_test_run_is_not_found(self, api):
        """An unknown run is a 404, never the not-scheduled conflict.

        The identifier list includes `ERR_FAT_RUN_NOT_FOUND` among the codes that are
        "each HTTP 404", and it is resolved ahead of the state gate that says "`PASSED`,
        `FAILED`, `CONDITIONAL`, `CANCELLED` and `SUPERSEDED` are all terminal for a run,
        and a run in any of them can be neither witnessed nor cancelled."

        Design: Corner/errors/cancel_on_an_unknown_fat_run_is_not_found
        """
        response = api.cancel_fat_run(
            UNKNOWN_ID,
            make_fabrication_manager_headers(),
            {"cancel_reason": "Bay reassigned"},
        )

        validate_error(response, ApiErrorId.FAT_RUN_NOT_FOUND.value, 404)

    def test_submitting_an_unknown_or_equal_submittal_is_not_found(self, api):
        """Neither the DRAFT state guard nor the compliance floor is consulted.

        `ERR_SUBMITTAL_NOT_FOUND` is one of the codes that are "each HTTP 404", and path
        existence sits above both the lifecycle-state checks and the "or-equal gates, in
        order: `ERR_FUNDAMENTAL_DEVIATION_OPEN`, then `ERR_COMPLIANCE_SCORE_TOO_LOW`."

        Design: Corner/errors/submit_on_an_unknown_submittal_is_not_found
        """
        response = api.submit_or_equal_submittal(
            UNKNOWN_ID, make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.SUBMITTAL_NOT_FOUND.value, 404)

    def test_dispositioning_an_unknown_deviation_is_not_found(self, api):
        """The deviation has its own top-level route and its own not-found code.

        `ERR_DEVIATION_NOT_FOUND` appears in the per-identifier list of codes that are
        "each HTTP 404", ahead of the state gate under which "a second disposition on the
        same deviation is refused with `ERR_DEVIATION_ALREADY_DISPOSITIONED`, which is the
        only state gate on this operation carrying an error code."

        Design: Corner/errors/disposition_on_an_unknown_deviation_is_not_found
        """
        response = api.disposition_spec_deviation(
            UNKNOWN_ID, {"disposition": "ACCEPTED"}, make_engineer_of_record_headers()
        )

        validate_error(response, ApiErrorId.DEVIATION_NOT_FOUND.value, 404)

    def test_certifying_an_unknown_demonstration_is_not_found(self, api):
        """The demo identifier resolves before the already-certified conflict.

        `ERR_DEMO_NOT_FOUND` is one of the codes that are "each HTTP 404", and it is
        reached before the rule that "the demonstration's `result` must still be `PENDING`
        — an already-certified demonstration is `ERR_DEMO_ALREADY_CERTIFIED`".

        Design: Corner/errors/certify_on_an_unknown_demo_is_not_found
        """
        response = api.certify_performance_demo(
            UNKNOWN_ID, {"certification": "PASS"}, make_quality_engineer_headers()
        )

        validate_error(response, ApiErrorId.DEMO_NOT_FOUND.value, 404)

    def test_reading_an_unknown_service_agreement_is_not_found(self, api):
        """The agreement carries its own code rather than the project's.

        Section 2.9 lists `ERR_SERVICE_AGREEMENT_NOT_FOUND` separately from
        `ERR_PROJECT_NOT_FOUND` among the identifiers that "each has its own not-found
        code", all of them "each HTTP 404".

        Design: Corner/errors/reading_an_unknown_service_agreement_is_not_found
        """
        response = api.get_service_agreement(
            UNKNOWN_ID, make_contracts_administrator_headers()
        )

        validate_error(response, ApiErrorId.SERVICE_AGREEMENT_NOT_FOUND.value, 404)

    def test_reversing_an_unknown_draw_is_not_found(self, api):
        """No compensating row is minted for an identifier that does not resolve.

        `ERR_CONSUMABLE_DRAW_NOT_FOUND` is one of the codes that are "each HTTP 404", and
        existence precedes the guard under which a target "cannot be reversed again, and
        neither can a row whose own `draw_type` is `REVERSAL`; either attempt is
        `ERR_DRAW_ALREADY_REVERSED`."

        Design: Corner/errors/reversal_of_an_unknown_draw_is_not_found
        """
        response = api.reverse_consumable_draw(
            UNKNOWN_ID,
            make_contracts_administrator_headers(),
            {"reversal_reason": "Wrong item shipped"},
        )

        validate_error(response, ApiErrorId.CONSUMABLE_DRAW_NOT_FOUND.value, 404)

    def test_reading_an_unknown_treatment_objective_is_not_found(self, api):
        """A missing objective is a 404, not an empty success.

        `ERR_TREATMENT_OBJECTIVE_NOT_FOUND` is one of the per-identifier codes that are
        "each HTTP 404". Retirement does not hide a row: "`RETIRED` is terminal, and
        retired objectives are invisible to every downstream calculation."

        Design: Corner/errors/reading_an_unknown_treatment_objective_is_not_found
        """
        response = api.get_treatment_objective(
            UNKNOWN_ID, make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.TREATMENT_OBJECTIVE_NOT_FOUND.value, 404)


class TestCatalogCodeUniqueness:
    """A catalog code is claimed once per catalog and never upserted."""

    def test_registering_a_second_material_under_the_same_code_is_refused(self, api):
        """The incumbent MAT-316L keeps its own cost index and pressure rating.

        The PRD says "attempting to register a technology, material or bay whose code
        already exists in its own catalog is rejected with `ERR_DUPLICATE_CATALOG_CODE`.
        Uniqueness is scoped per catalog: a technology may share a code string with a
        material without conflict."

        Design: Corner/errors/reusing_a_material_spec_code_is_rejected
        """
        incumbent = fixtures.seed_material_spec(api)

        response = api.create_material_spec(
            factories.material_spec_payload(
                code="MAT-316L",
                max_chloride_ppm=500.0,
                max_temp_c=90.0,
                max_pressure_psig=400,
                ph_min=3.0,
                ph_max=12.0,
                cost_index=1.20,
                service_classes_allowed=["NEUTRAL"],
            ),
            make_platform_admin_headers(),
        )

        validate_error(response, ApiErrorId.DUPLICATE_CATALOG_CODE.value, 409)

        stored = validate_success(
            api.get_material_spec(incumbent["id"], make_platform_admin_headers())
        )
        assert stored["cost_index"] == 1.10
        assert stored["max_pressure_psig"] == 300

        _, meta = validate_paginated(
            api.list_material_specs(make_platform_admin_headers())
        )
        assert meta["total_count"] == 1


class TestProcessSelectionPrerequisites:
    """The run refuses rather than laying out a partial or empty train."""

    def test_selection_without_any_active_objective_is_refused(self, api):
        """An accepted sample on its own is not a scope, so no stage is created.

        The PRD says the run "refuses to run unless the project is in `DRAFT` or `SCOPED`
        — any other lifecycle state yields `ERR_INVALID_PROJECT_STATE` — and unless the
        project holds at least one `ACCEPTED` influent profile (otherwise
        `ERR_NO_ACCEPTED_INFLUENT_PROFILE`) and at least one `ACTIVE` treatment objective
        (otherwise `ERR_NO_TREATMENT_OBJECTIVES`)."

        Design: Corner/errors/process_selection_without_any_objective_is_rejected
        """
        fixtures.seed_catalog(api)
        project = fixtures.create_draft_project(api)
        fixtures.add_accepted_influent_profile(api, project["id"])

        response = api.run_process_selection(
            project["id"], make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.NO_TREATMENT_OBJECTIVES.value, 422)

        stored = validate_success(
            api.get_project(project["id"], make_application_engineer_headers())
        )
        assert_project_state(stored, status="DRAFT")

        _, meta = validate_paginated(
            api.list_treatment_stages(
                make_application_engineer_headers(), {"project_id": project["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_selection_with_an_empty_candidate_pool_creates_no_stage_at_all(self, api):
        """A 5.0 NTU turbidity cap against a 12.0 NTU sample empties the filtration pool.

        The PRD says "if any required duty ends up with an empty pool, the whole run fails
        with `ERR_NO_ELIGIBLE_TECHNOLOGY` and no treatment stage is created for any duty,
        not even for the duties that did have candidates." The screen itself requires that
        a candidate's "`max_feed_turbidity_ntu` is at least the governing sample's
        `turbidity_ntu`".

        Design: Corner/errors/process_selection_with_no_eligible_technology_is_rejected
        """
        fixtures.seed_material_spec(api)
        fixtures.seed_filtration_technology(
            api, code="TECH-FILT-LOWTURB", max_feed_turbidity_ntu=5.0
        )
        project = fixtures.create_draft_project(api)
        fixtures.add_accepted_influent_profile(api, project["id"], turbidity_ntu=12.0)
        fixtures.add_turbidity_objective(api, project["id"])

        response = api.run_process_selection(
            project["id"], make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.NO_ELIGIBLE_TECHNOLOGY.value, 422)

        stored = validate_success(
            api.get_project(project["id"], make_application_engineer_headers())
        )
        assert_project_state(stored, status="DRAFT")

        _, meta = validate_paginated(
            api.list_treatment_stages(
                make_application_engineer_headers(), {"project_id": project["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestBidIsPostedOnce:
    """A project past bidding reports the more specific already-submitted code."""

    def test_a_second_bid_on_the_same_project_is_refused(self, api):
        """The first offer of 400,000,000 cents stands and is not overwritten.

        The PRD says "a project that is at `BID_SUBMITTED` or anywhere beyond it
        (`AWARDED`, `IN_FABRICATION`, `COMMISSIONING`, `GUARANTEED`, `REMEDIATION`,
        `SERVICE_ACTIVE` or `CLOSED`) falls past that first gate and is instead refused
        with `ERR_BID_ALREADY_SUBMITTED`, because its bid is already on record; only a
        project in `BID_READY` proceeds."

        Design: Corner/errors/second_bid_on_the_same_project_is_rejected
        """
        state = fixtures.bid_ready_single_stage_project(api)
        fixtures.post_bid(api, state["project"]["id"], 400000000)

        response = api.submit_bid(
            state["project"]["id"],
            {"offered_price_cents": 500000000},
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.BID_ALREADY_SUBMITTED.value, 409)

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="BID_SUBMITTED")
        assert_money(project["offered_price_cents"], 400000000, "offered_price_cents")
        assert_money(
            project["evaluated_bid_price_cents"],
            350194347,
            "evaluated_bid_price_cents",
        )
        assert_money(project["contract_amount_cents"], 0, "contract_amount_cents")


class TestSubmittalStateAndQualityGates:
    """A fresh concurrency token does not buy a state transition."""

    def test_filing_a_deviation_on_a_transmitted_submittal_is_refused(self, api):
        """The deviation list is frozen at transmission, so the score stays at 94.00.

        The PRD says that "on a `DRAFT` submittal — and only on a `DRAFT` submittal,
        `ERR_SUBMITTAL_INVALID_STATE` otherwise — the same engineer discloses each
        **specification deviation**". A `MODERATE` objection weighs 6 of the pinned
        weights: "2 points for `MINOR`, 6 for `MODERATE`, 15 for `MAJOR` and 30 for
        `FUNDAMENTAL`."

        Design: Corner/errors/filing_a_deviation_on_a_submitted_submittal_is_rejected
        """
        state = fixtures.scoped_single_stage_project(api)
        filed = fixtures.submitted_submittal(api, state["project"]["id"], "MODERATE")
        current = validate_success(
            api.get_or_equal_submittal(
                filed["submittal"]["id"], make_application_engineer_headers()
            )
        )
        assert current["compliance_score"] == 94.00

        response = api.create_spec_deviation(
            filed["submittal"]["id"],
            factories.spec_deviation_payload(
                current["version"],
                severity="MINOR",
                spec_paragraph="2.05.C",
                description="Nameplate layout differs from named basis",
            ),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.SUBMITTAL_INVALID_STATE.value, 409)

        stored = validate_success(
            api.get_or_equal_submittal(
                filed["submittal"]["id"], make_application_engineer_headers()
            )
        )
        assert stored["status"] == "SUBMITTED"
        assert stored["compliance_score"] == 94.00
        assert stored["open_fundamental_count"] == 0

        _, meta = validate_paginated(
            api.list_spec_deviations(
                make_engineer_of_record_headers(),
                {"or_equal_submittal_id": filed["submittal"]["id"]},
            )
        )
        assert meta["total_count"] == 1

    def test_pre_approval_with_one_open_fundamental_deviation_is_refused(self, api):
        """A score of exactly 70.00 clears the floor and the fundamental gate still bites.

        The PRD says `PRE_APPROVED` "requires `open_fundamental_count` to be exactly 0 — a
        single still-open fundamental deviation refuses the pre-approval with
        `ERR_FUNDAMENTAL_DEVIATION_OPEN` — and it requires `compliance_score` to be at
        least 70.00, refused otherwise with `ERR_COMPLIANCE_SCORE_TOO_LOW`."

        Design: Corner/errors/pre_approval_with_an_open_fundamental_deviation_is_rejected
        """
        state = fixtures.scoped_single_stage_project(api)
        filed = fixtures.submitted_submittal(
            api, state["project"]["id"], "FUNDAMENTAL"
        )

        response = api.decide_or_equal_submittal(
            filed["submittal"]["id"],
            {"decision": "PRE_APPROVED"},
            make_engineer_of_record_headers(),
        )

        validate_error(response, ApiErrorId.FUNDAMENTAL_DEVIATION_OPEN.value, 422)

        submittal = validate_success(
            api.get_or_equal_submittal(
                filed["submittal"]["id"], make_engineer_of_record_headers()
            )
        )
        assert submittal["status"] == "SUBMITTED"
        assert submittal["compliance_score"] == 70.00
        assert submittal["open_fundamental_count"] == 1

        deviation = validate_success(
            api.get_spec_deviation(
                filed["deviation"]["id"], make_engineer_of_record_headers()
            )
        )
        assert deviation["disposition"] == "PENDING"
        assert deviation["weighted_penalty_points"] == 30.00

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="SCOPED")


class TestCertificationIsOnceOnly:
    """The guarantee is not re-evaluated on a repeat certification."""

    def test_certifying_the_same_demonstration_twice_is_refused(self, api):
        """The demo keeps its PASSED result and the project stays guaranteed.

        The PRD says "the demonstration's `result` must still be `PENDING` — an
        already-certified demonstration is `ERR_DEMO_ALREADY_CERTIFIED` — and the
        certifier must not be the operator who recorded the readings, per section 2.7 and
        `ERR_SOD_RECORDER_IS_CERTIFIER`."

        Design: Corner/errors/second_certification_of_the_same_demo_is_rejected
        """
        state = fixtures.guaranteed_project(api)

        response = api.certify_performance_demo(
            state["demo"]["id"],
            {"certification": "PASS"},
            make_quality_engineer_headers(),
        )

        validate_error(response, ApiErrorId.DEMO_ALREADY_CERTIFIED.value, 409)

        demo = validate_success(
            api.get_performance_demo(
                state["demo"]["id"], make_commissioning_engineer_headers()
            )
        )
        assert demo["result"] == "PASSED"
        assert demo["round_no"] == 1
        assert demo["certified_by_user_id"] == "qa-1"

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(
            project, status="GUARANTEED", guarantee_status="MET"
        )


class TestDrawRefusals:
    """The quantity floor, the reversal guard and the lazy expiry sweep."""

    def test_a_draw_of_zero_units_is_refused_before_the_fiscal_gate(self, api):
        """A zero-cent accrual would slip past the reserve test, so quantity is checked first.

        The PRD says "the `quantity` must be an integer of at least 1, enforced as a
        business rule with `ERR_INVALID_DRAW_QUANTITY` rather than as a schema constraint,
        so a well-formed request carrying zero or a negative count reaches that rule and is
        refused by it." The gate ordering is "closeout and reserve gates, in order:
        `ERR_DELIVERABLES_INCOMPLETE`, `ERR_INVALID_DRAW_QUANTITY`, then
        `ERR_RESERVE_INSUFFICIENT`."

        Design: Corner/errors/draw_of_zero_units_is_rejected
        """
        state = fixtures.service_active_project(api)
        agreement = fixtures.current_agreement(api, state["agreement"]["id"])

        response = api.create_consumable_draw(
            agreement["id"],
            factories.consumable_draw_payload(
                agreement["version"],
                item_code="MF-ELEM-8",
                quantity=0,
                catalog_unit_cost_cents=500000,
                invoiced_unit_cost_cents=480000,
            ),
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.INVALID_DRAW_QUANTITY.value, 422)

        after = fixtures.current_agreement(api, agreement["id"])
        assert after["status"] == "ACTIVE"
        assert_money(
            after["reserve_committed_accrual_cents"],
            0,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            after["reserve_available_cents"], 12200000, "reserve_available_cents"
        )

        _, meta = validate_paginated(
            api.list_consumable_draws(
                make_contracts_administrator_headers(),
                {"service_agreement_id": agreement["id"]},
            )
        )
        assert meta["total_count"] == 0

    def test_reversing_the_same_draw_twice_is_refused(self, api):
        """Compensation is idempotent by refusal, so the ledger does not swing positive.

        The PRD says "a target that has already been reversed — meaning some row already
        carries its id in `reverses_draw_id` — cannot be reversed again, and neither can a
        row whose own `draw_type` is `REVERSAL`; either attempt is
        `ERR_DRAW_ALREADY_REVERSED`."

        Design: Corner/errors/second_reversal_of_the_same_draw_is_rejected
        """
        state = fixtures.service_active_project(api)
        draw = fixtures.post_draw(
            api,
            state["agreement"]["id"],
            draw_type="CONSUMABLE",
            quantity=3,
            catalog_unit_cost_cents=500000,
            invoiced_unit_cost_cents=480000,
        )
        reversal = validate_success(
            api.reverse_consumable_draw(
                draw["id"],
                make_contracts_administrator_headers(),
                {"reversal_reason": "Wrong item shipped"},
            ),
            201,
        )

        response = api.reverse_consumable_draw(
            draw["id"],
            make_contracts_administrator_headers(),
            {"reversal_reason": "Wrong item shipped"},
        )

        validate_error(response, ApiErrorId.DRAW_ALREADY_REVERSED.value, 409)

        assert reversal["draw_type"] == "REVERSAL"
        assert reversal["reverses_draw_id"] == draw["id"]
        assert_money(draw["accrual_amount_cents"], 1830000, "accrual_amount_cents")

        agreement = fixtures.current_agreement(api, state["agreement"]["id"])
        assert_money(
            agreement["reserve_committed_accrual_cents"],
            0,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            agreement["reserve_committed_settled_cents"],
            0,
            "reserve_committed_settled_cents",
        )
        assert_money(
            agreement["reserve_available_cents"], 12200000, "reserve_available_cents"
        )
        assert_money(
            agreement["settlement_variance_cents"], 0, "settlement_variance_cents"
        )
        assert agreement["status"] == "ACTIVE"

        _, meta = validate_paginated(
            api.list_consumable_draws(
                make_contracts_administrator_headers(),
                {"service_agreement_id": agreement["id"]},
            )
        )
        assert meta["total_count"] == 2

    def test_a_draw_past_the_term_expires_the_agreement_and_is_then_refused(self, api):
        """The refused request still persists the expiry, and the reserve is untouched.

        The PRD says "when the logical clock is at or after the agreement's `expires_at`,
        the agreement is written to `EXPIRED` — `ACTIVE → EXPIRED` or
        `SUSPENDED → EXPIRED`, whichever applies — its `version` advances by 1, the status
        change is persisted, and the draw is then refused with `ERR_AGREEMENT_EXPIRED`. No
        draw row is created and the reserve totals are untouched."

        Design: Corner/errors/draw_after_the_agreement_term_expires_is_rejected
        """
        state = fixtures.service_active_project(api)
        agreement = fixtures.current_agreement(api, state["agreement"]["id"])
        validate_success(
            api.set_clock(PAST_THE_TERM, make_platform_admin_headers())
        )

        response = api.create_consumable_draw(
            agreement["id"],
            factories.consumable_draw_payload(
                agreement["version"],
                item_code="MF-ELEM-8",
                quantity=3,
                catalog_unit_cost_cents=500000,
                invoiced_unit_cost_cents=480000,
            ),
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.AGREEMENT_EXPIRED.value, 409)

        after = fixtures.current_agreement(api, agreement["id"])
        assert after["status"] == "EXPIRED"
        assert_money(
            after["reserve_committed_accrual_cents"],
            0,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            after["reserve_committed_settled_cents"],
            0,
            "reserve_committed_settled_cents",
        )
        assert_money(
            after["reserve_available_cents"], 12200000, "reserve_available_cents"
        )
        assert_money(
            after["settlement_variance_cents"], 0, "settlement_variance_cents"
        )

        _, meta = validate_paginated(
            api.list_consumable_draws(
                make_contracts_administrator_headers(),
                {"service_agreement_id": agreement["id"]},
            )
        )
        assert meta["total_count"] == 0

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="SERVICE_ACTIVE")


class TestExclusiveBayClaim:
    """A stamped vessel claims the whole bay, whatever the capacity arithmetic says."""

    FILTRATION_WINDOW = ("2026-08-10T12:00:00.000Z", "2026-08-10T20:00:00.000Z")
    DISINFECTION_WINDOW = ("2026-08-10T08:00:00.000Z", "2026-08-10T16:00:00.000Z")

    def _two_ready_skids_one_of_them_exclusive(self, api):
        """A stamped filtration skid and an unstamped disinfection skid in one large bay."""
        state = {
            "material_spec": fixtures.seed_material_spec(api),
            "filtration_technology": fixtures.seed_filtration_technology(
                api, code="TECH-FILT-U", requires_code_stamp="ASME_U"
            ),
            "disinfection_technology": fixtures.seed_disinfection_technology(api),
            "test_bay": fixtures.seed_test_bay(
                api,
                bay_code="BAY-BIG",
                max_skid_footprint_sf=20000.0,
                changeover_buffer_minutes=120,
            ),
        }
        project = fixtures.create_draft_project(api)
        state["project"] = project
        fixtures.add_accepted_influent_profile(api, project["id"])
        fixtures.add_turbidity_objective(api, project["id"])
        fixtures.add_ecoli_objective(api, project["id"])
        stages = fixtures.run_selection(api, project["id"])
        filtration_package = fixtures.add_draft_package(
            api,
            stages[0]["id"],
            state["material_spec"]["id"],
            tag_number="F-100",
            design_pressure_psig=150,
        )
        state["filtration_package"] = fixtures.approve_package(
            api, filtration_package["id"]
        )
        disinfection_package = fixtures.add_draft_package(
            api,
            stages[1]["id"],
            state["material_spec"]["id"],
            tag_number="D-100",
            design_pressure_psig=100,
        )
        state["disinfection_package"] = fixtures.approve_package(
            api, disinfection_package["id"]
        )
        fixtures.preapproved_submittal(api, project["id"])
        fixtures.post_bid(api, project["id"], 900000000)
        fixtures.record_award(api, project["id"], "AWARDED")
        for key in ("filtration_package", "disinfection_package"):
            fixtures.release_package(api, state[key]["id"])
        state["filtration_skid"] = fixtures.drive_skid_fat_ready(
            api, fixtures.skid_of_package(api, state["filtration_package"]["id"])["id"]
        )
        state["disinfection_skid"] = fixtures.drive_skid_fat_ready(
            api,
            fixtures.skid_of_package(api, state["disinfection_package"]["id"])["id"],
        )
        state["disinfection_run"] = fixtures.schedule_fat_run(
            api,
            fixtures.current_skid(api, state["disinfection_skid"]["id"]),
            state["test_bay"]["id"],
            *self.DISINFECTION_WINDOW,
        )
        return state

    def test_an_overlapping_booking_for_an_exclusive_skid_is_refused(self, api):
        """The stamped skid cannot share the bay even though the footprints would fit.

        A skid's "`requires_exclusive_bay` is true exactly when the package's
        `code_stamp_required` is `ASME_U`, because hydrostatic proof testing of a stamped
        vessel occupies the whole bay." The booking rule follows: "if any run in the set
        has `requires_exclusive_bay` true, or if the incoming run requires an exclusive bay
        while the overlap set is non-empty, the booking is refused with
        `ERR_TEST_BAY_EXCLUSIVE_CONFLICT`."

        Design: Corner/errors/overlapping_run_against_an_exclusive_skid_is_rejected
        """
        state = self._two_ready_skids_one_of_them_exclusive(api)
        filtration_skid = fixtures.current_skid(
            api, state["filtration_skid"]["id"]
        )

        response = api.create_fat_run(
            factories.fat_run_payload(
                filtration_skid["id"],
                state["test_bay"]["id"],
                filtration_skid["version"],
                *self.FILTRATION_WINDOW,
            ),
            make_fabrication_manager_headers(),
        )

        validate_error(response, ApiErrorId.TEST_BAY_EXCLUSIVE_CONFLICT.value, 409)

        assert filtration_skid["requires_exclusive_bay"] is True
        assert filtration_skid["footprint_sf"] == 5400

        disinfection_skid = fixtures.current_skid(
            api, state["disinfection_skid"]["id"]
        )
        assert disinfection_skid["requires_exclusive_bay"] is False
        assert disinfection_skid["footprint_sf"] == 1200

        incumbent = validate_success(
            api.get_fat_run(
                state["disinfection_run"]["id"], make_fabrication_manager_headers()
            )
        )
        assert incumbent["status"] == "SCHEDULED"
        assert incumbent["duration_minutes"] == 480

        bay = validate_success(
            api.get_test_bay(
                state["test_bay"]["id"], make_fabrication_manager_headers()
            )
        )
        assert bay["reserved_footprint_minutes"] == 576000

        _, meta = validate_paginated(
            api.list_fat_runs(
                make_fabrication_manager_headers(),
                {"skid_id": filtration_skid["id"]},
            )
        )
        assert meta["total_count"] == 0
