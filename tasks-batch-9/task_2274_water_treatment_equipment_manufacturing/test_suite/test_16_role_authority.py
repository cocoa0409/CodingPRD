"""Who may act, whose identity blocks the act, and what a refusal leaves untouched."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    UNKNOWN_ID,
    ApiErrorId,
    assert_bay_ledger,
    assert_money,
    assert_project_state,
    fixtures,
    make_application_engineer_headers,
    make_commissioning_engineer_headers,
    make_contracts_administrator_headers,
    make_design_reviewer_headers,
    make_fabrication_manager_headers,
    make_headers_without_role,
    make_owner_representative_headers,
    make_platform_admin_headers,
    make_quality_engineer_headers,
)

DESIGNER_ID = "eng-1"
RECORDER_ID = "comm-1"


class TestDesignerIndependence:
    """The author of a design is barred from both approval points on it."""

    def test_the_designer_cannot_render_the_review_decision_on_its_own_package(
        self, api
    ):
        """Holding DesignReviewer is not enough, so the firm price is never frozen.

        The PRD says "an operator may not review a design it produced. When a design review
        decision is rendered, the acting `X-User-ID` must differ from the
        `designed_by_user_id` stored on the package under review", and either violation of
        that comparison "is rejected with `ERR_SOD_DESIGNER_IS_REVIEWER` (HTTP 403)". The
        rules are "checked against the opaque `X-User-ID` of the acting operator rather
        than against a role name — holding the right role is necessary but not sufficient."

        Design: Corner/rbac/designer_reviewing_its_own_package_is_forbidden
        """
        state = fixtures.scoped_single_stage_project(api)
        package = fixtures.add_draft_package(
            api,
            state["filtration_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="F-100",
            design_pressure_psig=150,
        )
        validate_success(
            api.submit_package_for_review(
                package["id"], make_application_engineer_headers()
            )
        )

        response = api.decide_package_review(
            package["id"],
            {"decision": "APPROVE"},
            make_design_reviewer_headers(DESIGNER_ID),
        )

        validate_error(response, ApiErrorId.SOD_DESIGNER_IS_REVIEWER.value, 403)

        stored = validate_success(
            api.get_equipment_package(
                package["id"], make_application_engineer_headers()
            )
        )
        assert stored["status"] == "IN_REVIEW"
        assert stored["designed_by_user_id"] == DESIGNER_ID
        assert stored["reviewed_by_user_id"] is None
        assert stored["approved_at"] is None
        assert_money(stored["firm_cost_cents"], 0, "firm_cost_cents")

        stage = validate_success(
            api.get_treatment_stage(
                state["filtration_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert stage["status"] == "SELECTED"

    def test_the_designer_cannot_witness_the_factory_test_of_its_own_package(self, api):
        """The comparison reaches through the run to the skid's parent package.

        The PRD extends the review rule: "the same comparison is applied when a factory
        acceptance test result is witnessed, against the `designed_by_user_id` of the
        package whose skid is on test. Either violation is rejected with
        `ERR_SOD_DESIGNER_IS_REVIEWER` (HTTP 403)." Because no exit from `SCHEDULED`
        happens, the ledger still holds what the booking added: "at every instant it equals
        the sum, over every factory test run booked on that bay whose status is still
        `SCHEDULED`, of that run's `footprint_sf` multiplied by its `duration_minutes`."

        Design: Corner/rbac/designer_witnessing_the_fat_for_its_own_package_is_forbidden
        """
        state = fixtures.scheduled_fat_run_project(api)

        response = api.witness_fat_run(
            state["fat_run"]["id"],
            {"result": "PASS", "punchlist_item_count": 0},
            make_quality_engineer_headers(DESIGNER_ID),
        )

        validate_error(response, ApiErrorId.SOD_DESIGNER_IS_REVIEWER.value, 403)

        run = validate_success(
            api.get_fat_run(
                state["fat_run"]["id"], make_fabrication_manager_headers()
            )
        )
        assert run["status"] == "SCHEDULED"
        assert run["witnessed_by_user_id"] is None

        bay = validate_success(
            api.get_test_bay(
                state["test_bay"]["id"], make_fabrication_manager_headers()
            )
        )
        assert_bay_ledger(bay, 2592000)

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "RELEASED_FOR_FAB"

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="IN_FABRICATION")


class TestCommercialIndependence:
    """The commercial act is separated from the engineering act behind it."""

    def test_the_submittal_author_cannot_post_the_bid_that_rests_on_it(self, api):
        """The refusal precedes the window, pre-approval and margin gates.

        The PRD says "an operator may not bid on a pre-approval it authored. When a
        project's bid is posted, the acting `X-User-ID` must differ from the
        `authored_by_user_id` of the pre-approved or-equal submittal the bid rests on; a
        violation is `ERR_SOD_AUTHOR_IS_BIDDER` (HTTP 403)." A new project starts with
        "every money field at zero: `base_bid_amount_cents`, `bond_premium_cents`,
        `contingency_cents`, `evaluated_bid_price_cents`, `offered_price_cents`,
        `contract_amount_cents` and `liquidated_damages_cents`."

        Design: Corner/rbac/submittal_author_posting_the_bid_is_forbidden
        """
        state = fixtures.bid_ready_single_stage_project(api)

        response = api.submit_bid(
            state["project"]["id"],
            {"offered_price_cents": 400000000},
            make_contracts_administrator_headers(DESIGNER_ID),
        )

        validate_error(response, ApiErrorId.SOD_AUTHOR_IS_BIDDER.value, 403)

        submittal = validate_success(
            api.get_or_equal_submittal(
                state["submittal"]["id"], make_application_engineer_headers()
            )
        )
        assert submittal["authored_by_user_id"] == DESIGNER_ID
        assert submittal["status"] == "PRE_APPROVED"

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="BID_READY")
        assert_money(project["base_bid_amount_cents"], 0, "base_bid_amount_cents")
        assert_money(
            project["evaluated_bid_price_cents"], 0, "evaluated_bid_price_cents"
        )
        assert_money(project["offered_price_cents"], 0, "offered_price_cents")

    def test_the_operator_who_recorded_the_readings_cannot_certify_them(self, api):
        """A comfortably compliant reading is still never evaluated.

        The PRD says "an operator may not certify readings it recorded. When a performance
        demonstration is certified, the acting `X-User-ID` must differ from the
        demonstration's `recorded_by_user_id`; a violation is
        `ERR_SOD_RECORDER_IS_CERTIFIER` (HTTP 403)." The demonstration therefore keeps its
        creation state: "an accepted demonstration is created with `result` `PENDING`,
        `evaluation` an empty array, `min_margin_pct` null, `certified_by_user_id` null,
        `recorded_by_user_id` from the acting operator".

        Design: Corner/rbac/recorder_certifying_its_own_demonstration_is_forbidden
        """
        state = fixtures.commissioning_project(api)
        demo = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.250}],
        )

        response = api.certify_performance_demo(
            demo["id"],
            {"certification": "PASS"},
            make_quality_engineer_headers(RECORDER_ID),
        )

        validate_error(response, ApiErrorId.SOD_RECORDER_IS_CERTIFIER.value, 403)

        stored = validate_success(
            api.get_performance_demo(
                demo["id"], make_commissioning_engineer_headers()
            )
        )
        assert stored["recorded_by_user_id"] == RECORDER_ID
        assert stored["result"] == "PENDING"
        assert stored["min_margin_pct"] is None
        assert stored["certified_by_user_id"] is None

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_contracts_administrator_headers()
            )
        )
        assert_project_state(project, status="COMMISSIONING")


class TestExclusiveWriteRoutes:
    """The role check answers first, so the reported code is about the role."""

    def test_an_application_engineer_is_unauthorized_to_render_the_review_decision(
        self, api
    ):
        """The same actor would also have failed the identity rule, and the role code wins.

        The precedence ladder places "role authorization for the addressed operation —
        `ERR_UNAUTHORIZED`" at priority 2 and "segregation of duties, in order:
        `ERR_SOD_DESIGNER_IS_REVIEWER`, `ERR_SOD_AUTHOR_IS_BIDDER`,
        `ERR_SOD_RECORDER_IS_CERTIFIER`" far below it, and the review decision is
        exclusive: "only a `DesignReviewer` renders it, only on an `IN_REVIEW` package, and
        never on a package it designed itself".

        Design: Corner/rbac/application_engineer_rendering_a_review_decision_is_unauthorized
        """
        state = fixtures.scoped_single_stage_project(api)
        package = fixtures.add_draft_package(
            api,
            state["filtration_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="F-100",
            design_pressure_psig=150,
        )
        validate_success(
            api.submit_package_for_review(
                package["id"], make_application_engineer_headers(DESIGNER_ID)
            )
        )

        response = api.decide_package_review(
            package["id"],
            {"decision": "APPROVE"},
            make_application_engineer_headers(DESIGNER_ID),
        )

        validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

        stored = validate_success(
            api.get_equipment_package(
                package["id"], make_application_engineer_headers()
            )
        )
        assert stored["status"] == "IN_REVIEW"
        assert_money(stored["firm_cost_cents"], 0, "firm_cost_cents")

        stage = validate_success(
            api.get_treatment_stage(
                state["filtration_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert stage["status"] == "SELECTED"

    def test_the_platform_admin_cannot_run_process_selection(self, api):
        """A perfectly scoped project still gets no treatment train from the catalog owner.

        The PRD says "a `PlatformAdmin` maintains the three shared catalogs — unit-process
        technologies, wetted-material specifications and factory test bays — and the
        logical clock. It holds no project authority whatsoever: it cannot open a project,
        engineer a stage, or post a bid." A well-formed but unauthorized request is refused
        at priority 2: "role authorization for the addressed operation —
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/platform_admin_running_process_selection_is_unauthorized
        """
        fixtures.seed_material_spec(api)
        fixtures.seed_filtration_technology(api)
        project = fixtures.create_draft_project(api)
        fixtures.add_accepted_influent_profile(api, project["id"])
        fixtures.add_turbidity_objective(api, project["id"])

        response = api.run_process_selection(
            project["id"], make_platform_admin_headers()
        )

        validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

        stored = validate_success(
            api.get_project(project["id"], make_contracts_administrator_headers())
        )
        assert_project_state(stored, status="DRAFT")

        _, meta = validate_paginated(
            api.list_treatment_stages(
                make_application_engineer_headers(), {"project_id": project["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestSharedReadRoutes:
    """Commercial visibility is not restricted to the roles that produced the numbers."""

    def test_the_owner_representative_reads_both_prices_and_the_variance_flag(
        self, api
    ):
        """A 10 percent variance is stored as 0.1000 and leaves the flag clear.

        The PRD says "every read (GET) route is available to all nine roles without
        exception", and pins the comparison: "`cost_variance_pct` is the firm price minus
        the budgetary price, divided by the budgetary price, rounded half up to four
        decimal places — a fraction, not a percentage figure, so a fifteen-percent overrun
        is stored as 0.15. `variance_flag` becomes true when that fraction is **strictly
        greater than** 0.15; a variance of exactly 0.15 leaves the flag false."

        Design: Corner/rbac/every_role_shares_the_read_routes
        """
        state = fixtures.scoped_single_stage_project(api)
        package = fixtures.add_draft_package(
            api,
            state["filtration_stage"]["id"],
            state["material_spec"]["id"],
            tag_number="F-100",
            design_pressure_psig=150,
        )
        fixtures.approve_package(api, package["id"])

        stored = validate_success(
            api.get_equipment_package(
                package["id"], make_owner_representative_headers()
            )
        )

        assert stored["status"] == "APPROVED"
        assert_money(
            stored["budgetary_cost_cents"], 260832000, "budgetary_cost_cents"
        )
        assert_money(stored["firm_cost_cents"], 286915200, "firm_cost_cents")
        assert stored["cost_variance_pct"] == 0.1000
        assert stored["variance_flag"] is False


class TestAuthenticationComesFirst:
    """No role header means no rule below authentication is ever reached."""

    def test_a_request_without_a_role_header_is_unauthenticated_not_unauthorized(
        self, api
    ):
        """An unresolvable project in the path does not turn this into a 404.

        The PRD says "if either header is absent or empty, or if `X-User-Role` is not one
        of the nine role names below spelled exactly as shown, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)". The ladder puts "authentication of the two
        headers — `ERR_UNAUTHENTICATED`" at priority 1, above role authorization at
        priority 2 and above "path existence, in the order the identifiers appear above:
        `ERR_PROJECT_NOT_FOUND`" at priority 3.

        Design: Corner/rbac/missing_x_user_role_header_returns_401_unauthenticated
        """
        response = api.run_process_selection(UNKNOWN_ID, make_headers_without_role())

        validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)
