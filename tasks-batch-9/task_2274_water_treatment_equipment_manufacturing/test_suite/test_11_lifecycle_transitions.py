"""Legal transitions, refused transitions and the side effects each one carries."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLOCK_SEED,
    ApiErrorId,
    assert_bay_ledger,
    assert_money,
    assert_project_state,
    assert_skid_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
    make_engineer_of_record_headers,
    make_fabrication_manager_headers,
    make_quality_engineer_headers,
)


class TestOnceOnlyTransitions:
    """Departures that exist only from one state cannot be fired twice."""

    def test_submitting_an_approved_package_for_review_again_is_refused(self, api):
        """Submission departs from DRAFT only, so an APPROVED package is refused.

        The PRD says "an `ApplicationEngineer` submits a `DRAFT` package with an
        optional `submittal_note`, moving it `DRAFT → IN_REVIEW`, re-stamping
        `budgetary_cost_cents`, and advancing its `version` by 1", and the only
        package lifecycle-state code is the one used for revision: "revision is only
        accepted while the package is in `DRAFT` — any other package state is
        `ERR_PACKAGE_INVALID_STATE`".

        Design: Corner/state_machines/submit_for_review_on_approved_package_is_rejected
        """
        state = fixtures.project_with_approved_package(api)

        response = api.submit_package_for_review(
            state["package"]["id"], make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.PACKAGE_INVALID_STATE.value, 409)

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "APPROVED"
        assert package["revision_round"] == 0
        assert package["version"] == 3
        assert_money(package["firm_cost_cents"], 286915200, "firm_cost_cents")

    def test_a_second_qa_disposition_on_the_same_profile_is_refused(self, api):
        """ACCEPTED is terminal, so a follow-up rejection cannot rewrite the decision.

        The PRD says "both `ACCEPTED` and `REJECTED` are terminal: a second
        disposition on the same profile is refused with
        `ERR_PROFILE_ALREADY_DECIDED`." An accepted disposition stores "the acting
        operator's identifier as `qa_decided_by_user_id`" and advances "the profile's
        `version` by 1."

        Design: Corner/state_machines/second_qa_decision_on_same_profile_is_rejected
        """
        project = fixtures.create_draft_project(api)
        profile = fixtures.add_accepted_influent_profile(api, project["id"])

        response = api.decide_influent_profile_qa(
            profile["id"], {"decision": "REJECT"}, make_quality_engineer_headers()
        )

        validate_error(response, ApiErrorId.PROFILE_ALREADY_DECIDED.value, 409)

        stored = validate_success(
            api.get_influent_profile(profile["id"], make_quality_engineer_headers())
        )
        assert stored["qa_status"] == "ACCEPTED"
        assert stored["qa_decided_by_user_id"] == "qa-1"
        assert stored["version"] == 2

    def test_dispositioning_a_withdrawn_deviation_again_is_refused(self, api):
        """WITHDRAWN is terminal, so the quarter-weight acceptance never lands.

        The PRD says "the `EngineerOfRecord` ... dispositions a deviation that is still
        `PENDING`, supplying `disposition` and an optional `disposition_note`. A second
        disposition on the same deviation is refused with
        `ERR_DEVIATION_ALREADY_DISPOSITIONED`, which is the only state gate on this
        operation carrying an error code." A withdrawal "moves the deviation
        `PENDING → WITHDRAWN`, writes its `weighted_penalty_points` to 0.00 so it
        contributes nothing".

        Design: Corner/state_machines/disposition_on_withdrawn_deviation_is_rejected
        """
        state = fixtures.scoped_single_stage_project(api)
        filed = fixtures.submitted_submittal(api, state["project"]["id"], "MODERATE")
        validate_success(
            api.disposition_spec_deviation(
                filed["deviation"]["id"],
                {"disposition": "WITHDRAWN"},
                make_engineer_of_record_headers(),
            )
        )

        response = api.disposition_spec_deviation(
            filed["deviation"]["id"],
            {"disposition": "ACCEPTED"},
            make_engineer_of_record_headers(),
        )

        validate_error(response, ApiErrorId.DEVIATION_ALREADY_DISPOSITIONED.value, 409)

        deviation = validate_success(
            api.get_spec_deviation(
                filed["deviation"]["id"], make_engineer_of_record_headers()
            )
        )
        assert deviation["disposition"] == "WITHDRAWN"
        assert deviation["weighted_penalty_points"] == 0.00

        submittal = validate_success(
            api.get_or_equal_submittal(
                filed["submittal"]["id"], make_engineer_of_record_headers()
            )
        )
        assert submittal["compliance_score"] == 100.00
        assert submittal["open_fundamental_count"] == 0
        assert submittal["status"] == "SUBMITTED"


class TestTransitionPreconditions:
    """A transition refused because its guard is unmet leaves nothing behind."""

    def test_process_selection_needs_an_accepted_sample_not_merely_a_logged_one(
        self, api
    ):
        """A single rejected sample does not satisfy the accepted-profile precondition.

        The PRD says the run "refuses to run unless the project is in `DRAFT` or
        `SCOPED` — any other lifecycle state yields `ERR_INVALID_PROJECT_STATE` — and
        unless the project holds at least one `ACCEPTED` influent profile (otherwise
        `ERR_NO_ACCEPTED_INFLUENT_PROFILE`) and at least one `ACTIVE` treatment
        objective (otherwise `ERR_NO_TREATMENT_OBJECTIVES`)."

        Design: Corner/state_machines/process_selection_without_accepted_profile_is_rejected
        """
        fixtures.seed_catalog(api)
        project = fixtures.create_draft_project(api)
        profile = fixtures.add_influent_profile(api, project["id"])
        fixtures.decide_profile(api, profile["id"], "REJECT")
        fixtures.add_turbidity_objective(api, project["id"])

        response = api.run_process_selection(
            project["id"], make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.NO_ACCEPTED_INFLUENT_PROFILE.value, 422)

        stored = validate_success(
            api.get_project(project["id"], make_application_engineer_headers())
        )
        assert_project_state(stored, status="DRAFT")
        assert stored["governing_influent_profile_id"] is None
        assert stored["version"] == 1

        _, meta = validate_paginated(
            api.list_treatment_stages(
                make_application_engineer_headers(), {"project_id": project["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_a_milestone_that_skips_a_step_is_refused(self, api):
        """From FRAME_SET the only legal mechanical target is PIPING_COMPLETE.

        The PRD says "the requested state must be the *immediate* successor of the
        skid's current state on the addressed axis; skipping a step, repeating one, or
        naming a state that belongs to the other axis is refused with
        `ERR_SKID_MILESTONE_OUT_OF_ORDER`."

        Design: Corner/state_machines/skid_milestone_out_of_order_is_rejected
        """
        state = fixtures.released_single_stage_project(api)

        response = api.record_skid_milestone(
            state["skid"]["id"],
            factories.milestone_payload("MECHANICAL", "HYDROTEST_PASSED"),
            make_fabrication_manager_headers(),
        )

        validate_error(response, ApiErrorId.SKID_MILESTONE_OUT_OF_ORDER.value, 409)

        skid = fixtures.current_skid(api, state["skid"]["id"])
        assert_skid_state(
            skid,
            mechanical_status="FRAME_SET",
            controls_status="PANEL_BUILD",
            fat_readiness="NOT_READY",
        )
        assert skid["version"] == 1


class TestTransitionSideEffects:
    """One accepted call, several declared consequences."""

    def test_release_stamps_the_clock_mints_a_skid_and_drags_the_project(self, api):
        """All four declared consequences of a release land in the same request.

        The PRD says "release moves the package `APPROVED → RELEASED_FOR_FAB`, stamps
        `released_at` with the logical clock, advances the package's `version` by 1, and
        on the project's *first* release moves the project `AWARDED → IN_FABRICATION`
        with the project's `delivery_posture` recomputed and its `version` advanced by
        1."

        Design: Corner/state_machines/release_for_fabrication_executes_every_declared_side_effect
        """
        state = fixtures.awarded_single_stage_project(api, offered_price_cents=400000000)

        package = fixtures.release_package(api, state["package"]["id"])

        assert package["status"] == "RELEASED_FOR_FAB"
        assert package["released_at"] == CLOCK_SEED

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="IN_FABRICATION", delivery_posture="ON_TRACK")
        assert_money(project["contract_amount_cents"], 400000000, "contract_amount_cents")

        stage = validate_success(
            api.get_treatment_stage(
                state["filtration_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert stage["status"] == "ENGINEERED"

        rows, meta = validate_paginated(
            api.list_skids(
                make_fabrication_manager_headers(),
                {"equipment_package_id": state["package"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["serial_no"] == "SKID-1-0"
        assert rows[0]["footprint_sf"] == 5400

    def test_redeclaring_a_parameter_retires_the_incumbent_objective(self, api):
        """The new turbidity limit takes over and the old row is retired in the same request.

        The PRD says "at most one objective may be `ACTIVE` for a given parameter on a
        given project: when an incoming objective declares a parameter that an existing
        `ACTIVE` objective of the same project already covers, the incumbent transitions
        `ACTIVE → RETIRED` and its `version` advances by 1. `RETIRED` is terminal, and
        retired objectives are invisible to every downstream calculation."

        Design: Corner/state_machines/treatment_objective_redeclaration_retires_the_prior_row
        """
        project = fixtures.create_draft_project(api)
        first = fixtures.add_turbidity_objective(api, project["id"], limit_value=0.300)

        second = validate_success(
            api.create_treatment_objective(
                project["id"],
                factories.turbidity_objective_payload(
                    limit_value=0.200,
                    regulatory_driver="State SWTR amendment 2026",
                ),
                make_application_engineer_headers(),
            ),
            201,
        )

        retired = validate_success(
            api.get_treatment_objective(first["id"], make_application_engineer_headers())
        )
        assert retired["status"] == "RETIRED"
        assert retired["version"] == 2

        assert second["status"] == "ACTIVE"
        assert second["limit_value"] == 0.200
        assert second["version"] == 1

        rows, meta = validate_paginated(
            api.list_project_treatment_objectives(
                project["id"], make_application_engineer_headers(), {"status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == second["id"]

    def test_the_last_passing_factory_test_bubbles_the_project_to_commissioning(
        self, api
    ):
        """Run, package and project all move, and the bay hands its minutes back.

        The PRD says "a recorded `PASS` moves the run `SCHEDULED → PASSED` and the
        parent package `RELEASED_FOR_FAB → FAT_PASSED`. If, after that transition, every
        equipment package on a non-superseded stage of the project is in `FAT_PASSED` or
        `SHIPPED`, the project moves `IN_FABRICATION → COMMISSIONING`, its
        `delivery_posture` is recomputed, and its `version` advances by 1." Every
        outcome "releases the run's footprint-minutes from the bay ledger by subtracting
        exactly `footprint_sf` multiplied by `duration_minutes`".

        Design: Corner/state_machines/final_fat_pass_bubbles_project_to_commissioning
        """
        state = fixtures.scheduled_fat_run_project(api)

        run = validate_success(
            api.witness_fat_run(
                state["fat_run"]["id"],
                {"result": "PASS", "punchlist_item_count": 0},
                make_quality_engineer_headers(),
            )
        )

        assert run["status"] == "PASSED"
        assert run["duration_minutes"] == 480
        assert run["footprint_sf"] == 5400
        assert run["punchlist_item_count"] == 0
        assert run["witnessed_by_user_id"] == "qa-1"

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "FAT_PASSED"

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="COMMISSIONING", delivery_posture="ON_TRACK")

        bay = validate_success(
            api.get_test_bay(state["test_bay"]["id"], make_fabrication_manager_headers())
        )
        assert_bay_ledger(bay, 0)


class TestConditionalCascades:
    """A decision that reaches selectively into its children."""

    def test_a_not_awarded_decision_closes_the_project_and_rejects_open_submittals(
        self, api
    ):
        """The DRAFT submittal is rejected, the pre-approved one is left alone.

        The PRD says "a `NOT_AWARDED` decision moves the project
        `BID_SUBMITTED → CLOSED`, which is terminal, and cascades one cleanup: every
        or-equal submittal of the project still sitting in `DRAFT` or `SUBMITTED` is
        written to `REJECTED`, since there is no longer a bid for them to support." Only
        an award "copies `offered_price_cents` into `contract_amount_cents` ... and
        stamps `awarded_at` with the logical clock."

        Design: Corner/state_machines/not_awarded_decision_closes_project_and_rejects_open_submittals
        """
        state = fixtures.bid_ready_single_stage_project(api)
        second = fixtures.add_submittal(
            api,
            state["project"]["id"],
            spec_section="11 21 14",
            named_basis_of_design="Acme MF-7",
        )
        fixtures.post_bid(api, state["project"]["id"], 400000000)

        project = validate_success(
            api.decide_award(
                state["project"]["id"],
                {"award_decision": "NOT_AWARDED"},
                make_contracts_administrator_headers(),
            )
        )

        assert_project_state(project, status="CLOSED")
        assert_money(project["contract_amount_cents"], 0, "contract_amount_cents")
        assert project["awarded_at"] is None
        assert_money(project["offered_price_cents"], 400000000, "offered_price_cents")

        rejected = validate_success(
            api.get_or_equal_submittal(second["id"], make_engineer_of_record_headers())
        )
        assert rejected["status"] == "REJECTED"

        untouched = validate_success(
            api.get_or_equal_submittal(
                state["submittal"]["id"], make_engineer_of_record_headers()
            )
        )
        assert untouched["status"] == "PRE_APPROVED"

    def test_requesting_a_revision_rejects_the_pending_fundamental_deviation(self, api):
        """The returned submittal comes back with its fundamental objection at full weight.

        The PRD says `REQUEST_REVISION` "moves the submittal `SUBMITTED → DRAFT`,
        increments `revision_round` by 1, stores `decided_by_user_id`, and applies one
        pointed side effect: every child deviation that is still `PENDING` **and** of
        severity `FUNDAMENTAL` is dispositioned `REJECTED`, after which
        `compliance_score` and `open_fundamental_count` are re-derived — so a returned
        submittal comes back with its fundamental objections on the record at full
        weight rather than unresolved."

        Design: Corner/state_machines/request_revision_rejects_the_pending_fundamental_deviation
        """
        state = fixtures.scoped_single_stage_project(api)
        filed = fixtures.submitted_submittal(
            api, state["project"]["id"], "FUNDAMENTAL"
        )

        submittal = validate_success(
            api.decide_or_equal_submittal(
                filed["submittal"]["id"],
                {"decision": "REQUEST_REVISION"},
                make_engineer_of_record_headers(),
            )
        )

        assert submittal["status"] == "DRAFT"
        assert submittal["revision_round"] == 1
        assert submittal["decided_by_user_id"] == "eor-1"
        assert submittal["compliance_score"] == 70.00
        assert submittal["open_fundamental_count"] == 1

        deviation = validate_success(
            api.get_spec_deviation(
                filed["deviation"]["id"], make_engineer_of_record_headers()
            )
        )
        assert deviation["disposition"] == "REJECTED"
        assert deviation["weighted_penalty_points"] == 30.00

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="SCOPED")
