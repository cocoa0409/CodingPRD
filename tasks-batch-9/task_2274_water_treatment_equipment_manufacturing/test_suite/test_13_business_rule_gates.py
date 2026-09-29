"""Business rules that refuse a well-formed request, and the boundaries they turn on."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
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
    make_owner_representative_headers,
    make_platform_admin_headers,
    make_quality_engineer_headers,
)

BID_DUE_INSTANT = "2026-09-15T00:00:00.000Z"
ZERO_MONEY_FIELDS = (
    "base_bid_amount_cents",
    "bond_premium_cents",
    "contingency_cents",
    "evaluated_bid_price_cents",
    "offered_price_cents",
)


class TestUniquenessScope:
    """The tag number is unique per stage, and only per stage."""

    def test_a_second_package_reusing_the_tag_on_one_stage_is_rejected(self, api):
        """F-100 is already taken on this stage, so the duplicate never lands.

        A package supplies "a `tag_number`, non-empty and unique among the packages
        sharing that same `treatment_stage_id` — a collision is
        `ERR_DUPLICATE_TAG_NUMBER`, and the same tag string may legitimately be reused on
        a different stage".

        Design: Corner/validations/duplicate_tag_number_on_the_same_stage_is_rejected
        """
        state = fixtures.scoped_single_stage_project(api)
        incumbent = fixtures.add_draft_package(
            api,
            state["filtration_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="F-100",
            design_pressure_psig=150,
        )

        response = api.create_equipment_package(
            state["filtration_stage"]["id"],
            factories.equipment_package_payload(
                state["material_spec"]["id"],
                tag_number="F-100",
                design_pressure_psig=200,
            ),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.DUPLICATE_TAG_NUMBER.value, 409)

        stored = validate_success(
            api.get_equipment_package(
                incumbent["id"], make_application_engineer_headers()
            )
        )
        assert stored["design_pressure_psig"] == 150
        assert stored["version"] == 1

        _, meta = validate_paginated(
            api.list_equipment_packages(
                make_application_engineer_headers(),
                {"treatment_stage_id": state["filtration_stage"]["id"]},
            )
        )
        assert meta["total_count"] == 1


class TestMaterialServiceScreens:
    """A material can pass every number and still be wrong for the water."""

    def test_a_material_whose_service_class_list_excludes_the_duty_is_rejected(self, api):
        """Acid-service fibreglass clears every numeric screen but not the service class.

        The service screen says "its `max_chloride_ppm` must be at least the governing
        influent profile's `chloride_mg_l`; its `max_temp_c` must be at least the
        governing profile's `temperature_c`; the governing profile's `ph` must fall within
        the material's band, meaning `ph_min` is at most the pH and `ph_max` is at least
        it; and the stage technology's `chemical_service_class` must be one of the members
        of the material's `service_classes_allowed`. Any of those four failing is
        `ERR_MATERIAL_NOT_RATED_FOR_SERVICE`."

        Design: Corner/validations/material_outside_its_service_class_list_is_rejected
        """
        state = fixtures.scoped_single_stage_project(api)
        acid_only = fixtures.seed_material_spec(
            api,
            code="MAT-FRP-ACID",
            max_chloride_ppm=20000.0,
            max_temp_c=150.0,
            max_pressure_psig=600,
            ph_min=1.0,
            ph_max=13.0,
            service_classes_allowed=["ACIDIC"],
        )

        response = api.create_equipment_package(
            state["filtration_stage"]["id"],
            factories.equipment_package_payload(acid_only["id"]),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.MATERIAL_NOT_RATED_FOR_SERVICE.value, 422)

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


class TestSubmittalQualityFloor:
    """The compliance floor is checked at transmission, on the score already stored."""

    def test_three_major_deviations_put_the_score_below_the_floor(self, api):
        """45 points of penalty leave 55.00, and the transmission is refused.

        Transmission requires that the submittal's "`compliance_score` must be **at
        least** the pinned floor of 70.00, so a score of exactly 70.00 passes and 69.99
        does not; falling short is `ERR_COMPLIANCE_SCORE_TOO_LOW`." The score itself is
        maintained eagerly: "the score and the count are re-derived on every deviation
        disclosure, on every disposition, and on every engineer decision."

        Design: Corner/validations/submit_below_the_compliance_floor_is_rejected
        """
        state = fixtures.scoped_single_stage_project(api)
        submittal = fixtures.add_submittal(api, state["project"]["id"])
        for paragraph in ("2.03.B", "2.04.A", "2.05.C"):
            fixtures.add_deviation(
                api, submittal["id"], "MAJOR", spec_paragraph=paragraph
            )

        response = api.submit_or_equal_submittal(
            submittal["id"], make_application_engineer_headers()
        )

        validate_error(response, ApiErrorId.COMPLIANCE_SCORE_TOO_LOW.value, 422)

        stored = validate_success(
            api.get_or_equal_submittal(
                submittal["id"], make_application_engineer_headers()
            )
        )
        assert stored["status"] == "DRAFT"
        assert stored["submitted_at"] is None
        assert stored["compliance_score"] == 55.00
        assert stored["revision_round"] == 0

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="SCOPED")


class TestBidGates:
    """Five gates in a pinned order, each leaving the derived figures unwritten."""

    def test_an_offer_one_cent_below_the_floor_is_refused_and_nothing_is_stored(
        self, api
    ):
        """378,209,894 fails the cross-multiplication that 378,209,895 passes.

        The floor says "`offered_price_cents` multiplied by 10,000 must be at least
        `evaluated_bid_price_cents` multiplied by 10,800. A margin of exactly eight
        percent therefore passes; anything below is refused with
        `ERR_BID_MARGIN_BELOW_FLOOR`. When every gate clears, the four derived figures are
        stored on the project, `offered_price_cents` is captured from the request body".

        Design: Corner/validations/bid_one_cent_below_the_margin_floor_is_rejected
        """
        state = fixtures.bid_ready_single_stage_project(api)

        response = api.submit_bid(
            state["project"]["id"],
            {"offered_price_cents": 378209894},
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.BID_MARGIN_BELOW_FLOOR.value, 422)

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="BID_READY")
        for field in ZERO_MONEY_FIELDS:
            assert_money(project[field], 0, field)

    def test_a_bid_posted_exactly_at_the_due_instant_is_refused(self, api):
        """The window test is strictly-before, so the closing instant is already too late.

        The PRD says "the logical clock must be strictly before the project's
        `bid_due_at`, and a bid posted at or after that instant is refused with
        `ERR_BID_WINDOW_CLOSED`."

        Design: Corner/validations/bid_posted_exactly_at_the_due_instant_is_rejected
        """
        state = fixtures.bid_ready_single_stage_project(api)
        validate_success(
            api.set_clock(BID_DUE_INSTANT, make_platform_admin_headers())
        )

        response = api.submit_bid(
            state["project"]["id"],
            {"offered_price_cents": 400000000},
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.BID_WINDOW_CLOSED.value, 422)

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="BID_READY")
        assert_money(
            project["evaluated_bid_price_cents"], 0, "evaluated_bid_price_cents"
        )
        assert_money(project["offered_price_cents"], 0, "offered_price_cents")

        submittal = validate_success(
            api.get_or_equal_submittal(
                state["submittal"]["id"], make_engineer_of_record_headers()
            )
        )
        assert submittal["status"] == "PRE_APPROVED"

    def test_one_unpriced_stage_invalidates_the_whole_bid(self, api):
        """A DRAFT disinfection package is not skipped; it refuses the bid.

        The PRD says "every treatment stage of the project that is still `SELECTED` or
        `ENGINEERED` must carry exactly one equipment package whose status is `APPROVED`,
        `RELEASED_FOR_FAB`, `FAT_PASSED` or `SHIPPED` and whose `firm_cost_cents` is
        strictly greater than 0, and at least one of the project's or-equal submittals
        must hold `PRE_APPROVED`; either shortfall is `ERR_OR_EQUAL_NOT_PREAPPROVED`."

        Design: Corner/validations/bid_with_one_unpriced_stage_is_rejected
        """
        state = fixtures.scoped_two_stage_project(api)
        filtration = fixtures.add_draft_package(
            api,
            state["filtration_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="F-100",
            design_pressure_psig=150,
        )
        approved = fixtures.approve_package(api, filtration["id"])
        unpriced = fixtures.add_draft_package(
            api,
            state["disinfection_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="D-200",
            design_pressure_psig=100,
        )
        fixtures.preapproved_submittal(api, state["project"]["id"])

        response = api.submit_bid(
            state["project"]["id"],
            {"offered_price_cents": 700000000},
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.OR_EQUAL_NOT_PREAPPROVED.value, 422)

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="BID_READY")
        assert_money(project["base_bid_amount_cents"], 0, "base_bid_amount_cents")
        assert_money(
            project["evaluated_bid_price_cents"], 0, "evaluated_bid_price_cents"
        )

        assert approved["status"] == "APPROVED"
        assert_money(approved["firm_cost_cents"], 286915200, "firm_cost_cents")

        still_draft = validate_success(
            api.get_equipment_package(
                unpriced["id"], make_application_engineer_headers()
            )
        )
        assert still_draft["status"] == "DRAFT"
        assert_money(still_draft["firm_cost_cents"], 0, "firm_cost_cents")

    def test_a_rejected_submittal_blocks_the_bid_on_the_project_state_gate(self, api):
        """The rejection cascade drives the project to BID_BLOCKED, which the bid hits first.

        A rejection's link three says "because this submittal is rejected, the project
        loses its only path to pre-approval, so the owning project transitions to
        `BID_BLOCKED`", and the first bid gate says "a project that has not yet reached
        bidding — one still in `DRAFT`, `SCOPED` or `BID_BLOCKED` — is refused with
        `ERR_INVALID_PROJECT_STATE`."

        Design: Corner/validations/bid_after_submittal_rejection_is_refused_because_the_project_is_bid_blocked
        """
        state = fixtures.project_with_approved_package(api)
        filed = fixtures.submitted_submittal(api, state["project"]["id"], "MODERATE")
        validate_success(
            api.decide_or_equal_submittal(
                filed["submittal"]["id"],
                {"decision": "REJECTED"},
                make_engineer_of_record_headers(),
            )
        )

        response = api.submit_bid(
            state["project"]["id"],
            {"offered_price_cents": 400000000},
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.INVALID_PROJECT_STATE.value, 409)

        submittal = validate_success(
            api.get_or_equal_submittal(
                filed["submittal"]["id"], make_engineer_of_record_headers()
            )
        )
        assert submittal["status"] == "REJECTED"
        assert submittal["compliance_score"] == 100.00
        assert submittal["open_fundamental_count"] == 0

        deviation = validate_success(
            api.get_spec_deviation(
                filed["deviation"]["id"], make_engineer_of_record_headers()
            )
        )
        assert deviation["disposition"] == "WITHDRAWN"
        assert deviation["weighted_penalty_points"] == 0.00

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="BID_BLOCKED")
        assert_money(
            project["evaluated_bid_price_cents"], 0, "evaluated_bid_price_cents"
        )


class TestBayAvailability:
    """A bay that is out of service is refused before any geometry is considered."""

    def test_booking_into_an_out_of_service_bay_is_refused(self, api):
        """The bay status gate stands ahead of the overlap and capacity arithmetic.

        The PRD says "The target bay's `status` must be `AVAILABLE`; an `OUT_OF_SERVICE`
        bay is `ERR_TEST_BAY_UNAVAILABLE`. Occupancy is then evaluated over a **buffered
        half-open interval**."

        Design: Corner/validations/fat_scheduled_into_an_out_of_service_bay_is_rejected
        """
        state = fixtures.fat_ready_single_stage_project(api)
        closed_bay = fixtures.seed_test_bay(
            api, bay_code="BAY-OOS", status="OUT_OF_SERVICE"
        )
        skid = fixtures.current_skid(api, state["skid"]["id"])

        response = api.create_fat_run(
            factories.fat_run_payload(
                skid["id"], closed_bay["id"], skid["version"]
            ),
            make_fabrication_manager_headers(),
        )

        validate_error(response, ApiErrorId.TEST_BAY_UNAVAILABLE.value, 409)

        bay = validate_success(
            api.get_test_bay(closed_bay["id"], make_fabrication_manager_headers())
        )
        assert bay["status"] == "OUT_OF_SERVICE"
        assert bay["reserved_footprint_minutes"] == 0

        assert skid["fat_readiness"] == "READY"

        _, meta = validate_paginated(
            api.list_fat_runs(
                make_fabrication_manager_headers(), {"skid_id": skid["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestGuaranteeGates:
    """Certification coverage, the round cap and their pinned order."""

    def test_an_objective_declared_after_the_readings_blocks_certification(self, api):
        """The evaluation walks the objectives active at certification, and one has no reading.

        The PRD says "The samples are every reading on the demonstration whose
        `parameter` matches the objective's `parameter`. If there are none, the whole
        certification is refused with `ERR_DEMO_READING_MISSING` — nothing partial is
        stored." The walk itself covers "the project's treatment objectives whose `status`
        is `ACTIVE`, in ascending `parameter` and then ascending `created_at`".

        Design: Corner/validations/objective_declared_after_the_readings_blocks_certification
        """
        state = fixtures.commissioning_project(api)
        demo = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.250}],
        )
        fixtures.add_ecoli_objective(api, state["project"]["id"])

        response = api.certify_performance_demo(
            demo["id"], {"certification": "PASS"}, make_quality_engineer_headers()
        )

        validate_error(response, ApiErrorId.DEMO_READING_MISSING.value, 422)

        stored = validate_success(
            api.get_performance_demo(demo["id"], make_commissioning_engineer_headers())
        )
        assert stored["result"] == "PENDING"
        assert stored["evaluation"] == []
        assert stored["min_margin_pct"] is None
        assert stored["certified_by_user_id"] is None

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="COMMISSIONING")
        assert project["guarantee_status"] != "MET"

    def test_the_round_cap_outranks_the_commissioning_prerequisite(self, api):
        """After two burnt rounds the diagnosis is the cap, not the lifecycle state.

        The PRD says "The retest cap comes first: if the project already has two
        demonstrations whose `result` is `PASSED`, `FAILED` or `CONDITIONAL_PASS`, the
        request is refused with `ERR_MAX_DEMO_ROUNDS_EXCEEDED`, and this check
        deliberately outranks the commissioning prerequisite below, because a project that
        has burned both rounds has by construction already left `COMMISSIONING` for
        `GUARANTEED` or `REMEDIATION` and the retest cap is the more specific diagnosis."
        Damages stay at zero because "when the certification happens at or before
        `guarantee_deadline_at`, the elapsed days are 0 and `liquidated_damages_cents`
        stays 0".

        Design: Corner/validations/third_demonstration_round_is_refused_by_the_round_cap_not_the_prerequisite
        """
        state = fixtures.commissioning_project(api)
        fixtures.accept_all_deliverables(api, state["project"]["id"])
        first = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.500}],
        )
        fixtures.certify_demo(api, first["id"], "FAIL")
        second = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.400}],
            "2026-09-01T00:00:00.000Z",
            "2026-09-08T00:00:00.000Z",
        )
        certified = fixtures.certify_demo(api, second["id"], "FAIL")

        response = api.create_performance_demo(
            factories.performance_demo_payload(
                state["project"]["id"],
                state["skid"]["id"],
                [{"parameter": "TURBIDITY_NTU", "measured_value": 0.290}],
                "2026-09-20T00:00:00.000Z",
                "2026-09-27T00:00:00.000Z",
            ),
            make_commissioning_engineer_headers(),
        )

        validate_error(response, ApiErrorId.MAX_DEMO_ROUNDS_EXCEEDED.value, 422)

        assert certified["result"] == "FAILED"
        assert certified["round_no"] == 2

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(
            project, status="REMEDIATION", guarantee_status="DEFAULTED"
        )
        assert_money(
            project["liquidated_damages_cents"], 0, "liquidated_damages_cents"
        )

        _, meta = validate_paginated(
            api.list_performance_demos(
                make_commissioning_engineer_headers(),
                {"project_id": state["project"]["id"]},
            )
        )
        assert meta["total_count"] == 2


class TestServiceAgreementGates:
    """The owner's paperwork is a hard prerequisite, and the reserve gate is inclusive."""

    def test_one_pending_deliverable_refuses_the_service_agreement(self, api):
        """Two accepted deliverables out of three are not enough to open the service.

        The PRD says "all three closeout deliverable statuses must be `ACCEPTED` — a
        single `PENDING` or `REJECTED` deliverable is `ERR_DELIVERABLES_INCOMPLETE`. Owner
        acceptance of the paperwork is a hard prerequisite for the service relationship,
        not a formality."

        Design: Corner/validations/service_agreement_without_all_three_deliverables_is_rejected
        """
        state = fixtures.commissioning_project(api)
        for deliverable_type in ("OM_MANUAL", "OPERATOR_TRAINING"):
            validate_success(
                api.accept_deliverable(
                    state["project"]["id"],
                    {"deliverable_type": deliverable_type, "decision": "ACCEPT"},
                    make_owner_representative_headers(),
                )
            )
        demo = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.250}],
        )
        fixtures.certify_demo(api, demo["id"], "PASS")

        response = api.create_service_agreement(
            state["project"]["id"],
            factories.service_agreement_payload(),
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.DELIVERABLES_INCOMPLETE.value, 422)

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="GUARANTEED", guarantee_status="MET")
        assert project["om_manual_status"] == "ACCEPTED"
        assert project["operator_training_status"] == "ACCEPTED"
        assert project["spare_parts_list_status"] == "PENDING"

        _, meta = validate_paginated(
            api.list_service_agreements(
                make_contracts_administrator_headers(),
                {"project_id": state["project"]["id"]},
            )
        )
        assert meta["total_count"] == 0

    def test_a_draw_exactly_equal_to_the_available_reserve_is_accepted(self, api):
        """The fiscal gate is strictly greater-than, so the reserve may be spent to zero.

        The PRD says "the draw is refused with `ERR_RESERVE_INSUFFICIENT` when its
        accrual line is **strictly greater** than the agreement's current
        `reserve_available_cents`. A draw whose accrual line exactly equals the available
        reserve is therefore accepted, spends the reserve down to exactly zero, and drives
        the agreement `ACTIVE → SUSPENDED` in the same operation. The settled line is
        never consulted by this gate, however large it is."

        Design: Corner/validations/draw_exactly_equal_to_available_reserve_is_accepted
        """
        state = fixtures.service_active_project(api)

        draw = fixtures.post_draw(
            api,
            state["agreement"]["id"],
            draw_type="CONSUMABLE",
            item_code="MF-ELEM-8",
            quantity=10,
            catalog_unit_cost_cents=1000000,
            invoiced_unit_cost_cents=980000,
        )

        assert_money(draw["accrual_amount_cents"], 12200000, "accrual_amount_cents")
        assert_money(draw["settled_amount_cents"], 10437000, "settled_amount_cents")

        agreement = fixtures.current_agreement(api, state["agreement"]["id"])
        assert_money(
            agreement["reserve_committed_accrual_cents"],
            12200000,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            agreement["reserve_available_cents"], 0, "reserve_available_cents"
        )
        assert_money(
            agreement["settlement_variance_cents"],
            -1763000,
            "settlement_variance_cents",
        )
        assert agreement["status"] == "SUSPENDED"

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="SERVICE_ACTIVE")
