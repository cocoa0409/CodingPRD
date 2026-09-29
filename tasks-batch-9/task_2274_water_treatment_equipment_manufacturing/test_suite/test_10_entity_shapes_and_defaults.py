"""Created rows, their declared defaults, their derived fields and their shapes."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    UNKNOWN_ID,
    ApiErrorId,
    assert_append_only_fields,
    assert_common_fields,
    assert_flow,
    assert_money,
    assert_project_state,
    assert_skid_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
    make_fabrication_manager_headers,
    make_platform_admin_headers,
)

MONEY_FIELDS = (
    "base_bid_amount_cents",
    "bond_premium_cents",
    "contingency_cents",
    "evaluated_bid_price_cents",
    "offered_price_cents",
    "contract_amount_cents",
    "liquidated_damages_cents",
)


class TestProjectCreation:
    """A new project's declared starting position."""

    def test_new_project_carries_every_declared_system_default(self, api):
        """Creation returns 201 with the whole declared opening position of a project.

        The PRD says "a new project begins life in `DRAFT` with `delivery_posture`
        `ON_TRACK`, `guarantee_status` `NOT_STARTED`, `governing_influent_profile_id`
        null, all three closeout deliverable statuses -- `om_manual_status`,
        `operator_training_status` and `spare_parts_list_status` -- at `PENDING`, and
        every money field at zero: `base_bid_amount_cents`, `bond_premium_cents`,
        `contingency_cents`, `evaluated_bid_price_cents`, `offered_price_cents`,
        `contract_amount_cents` and `liquidated_damages_cents`. Its `awarded_at` is
        null."

        Design: Corner/entities/project_creation_returns_declared_system_defaults
        """
        response = api.create_project(
            factories.project_payload(), make_contracts_administrator_headers()
        )
        project = validate_success(response, 201)

        assert_project_state(
            project,
            status="DRAFT",
            delivery_posture="ON_TRACK",
            guarantee_status="NOT_STARTED",
        )
        assert project["governing_influent_profile_id"] is None
        assert project["om_manual_status"] == "PENDING"
        assert project["operator_training_status"] == "PENDING"
        assert project["spare_parts_list_status"] == "PENDING"
        for field in MONEY_FIELDS:
            assert_money(project[field], 0, field)
        assert project["awarded_at"] is None
        assert_common_fields(project, expected_version=1)

    def test_project_retrieval_returns_the_stored_row_unchanged(self, api):
        """A read echoes every supplied input and leaves the version at 1.

        Section 2.4 says "every row also carries `created_at`, an ISO 8601 UTC
        timestamp with three fractional digits, fixed at insertion and never
        rewritten", and `version` "starts at 1 on creation and increases by exactly 1
        on every accepted mutation of that row."

        Design: Corner/entities/project_retrieval_returns_the_stored_row
        """
        payload = factories.project_payload()
        created = fixtures.create_draft_project(api)

        project = validate_success(
            api.get_project(created["id"], make_contracts_administrator_headers())
        )

        assert project["id"] == created["id"]
        assert project["name"] == payload["name"]
        assert project["owner_agency_name"] == payload["owner_agency_name"]
        assert project["procurement_type"] == payload["procurement_type"]
        assert project["bid_due_at"] == payload["bid_due_at"]
        assert project["guarantee_deadline_at"] == payload["guarantee_deadline_at"]
        assert project["footprint_allowance_sf_per_stage"] == payload[
            "footprint_allowance_sf_per_stage"
        ]
        assert_common_fields(project, expected_version=1)

    def test_project_listing_paginates_newest_first(self, api):
        """A limit of 2 over three projects returns the two newest and reports more remain.

        Section 2.3 says "`limit` defaults to 10, must be at least 1, and may not
        exceed 100" and that "every list response echoes `limit` and `offset` in `meta`
        alongside `total_count` -- the number of rows matching the filters before
        pagination is applied -- and `has_more`, which is true exactly when rows remain
        beyond the current page." The project list is one of the pinned exceptions to
        the default ordering: it "is ordered by `created_at` **descending**, newest
        first".

        Design: Corner/entities/project_listing_paginates_with_limit_and_offset
        """
        # Section 2.5 pins every `*_at` stamp the server writes to the logical
        # clock, so the clock is advanced between the three creations to give the
        # three rows genuinely distinct `created_at` instants to order by.
        api.set_clock("2026-08-01T00:00:00.000Z", make_platform_admin_headers())
        first = fixtures.create_draft_project(api, name="Northgate WTP Membrane Upgrade")
        api.set_clock("2026-08-02T00:00:00.000Z", make_platform_admin_headers())
        second = fixtures.create_draft_project(api, name="Riverbend WRF Expansion")
        api.set_clock("2026-08-03T00:00:00.000Z", make_platform_admin_headers())
        third = fixtures.create_draft_project(api, name="Ashfield Desalter Package")

        rows, meta = validate_paginated(
            api.list_projects(
                make_contracts_administrator_headers(), {"limit": 2, "offset": 0}
            )
        )

        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert len(rows) == 2
        assert [row["id"] for row in rows] == [third["id"], second["id"]]
        assert first["id"] not in [row["id"] for row in rows]

    def test_a_guarantee_deadline_before_the_bid_due_date_is_rejected(self, api):
        """The guarantee deadline must fall strictly after the bid due date.

        A project request supplies "the `guarantee_deadline_at` instant by which the
        contractual performance guarantee must be demonstrated, which must fall
        strictly after `bid_due_at`." Request-shape validation covers "every datetime
        pair ordered with the end strictly after its start".

        Design: Corner/entities/project_guarantee_deadline_before_bid_due_is_rejected
        """
        response = api.create_project(
            factories.project_payload(
                bid_due_at="2026-09-15T00:00:00.000Z",
                guarantee_deadline_at="2026-09-01T00:00:00.000Z",
            ),
            make_contracts_administrator_headers(),
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(
            api.list_projects(make_contracts_administrator_headers())
        )
        assert meta["total_count"] == 0


class TestDeclaredDefaultsOnOmittedInputs:
    """Optional inputs left out of the body fall back to their declared defaults."""

    def test_omitted_optional_inputs_fall_back_to_their_declared_defaults(self, api):
        """A bay without a buffer or status, and a project without a procurement type.

        A test bay's `changeover_buffer_minutes` is "the rigging and changeover
        allowance, defaulting to 120 minutes (two hours) and required to be at least 0",
        and "a new bay starts with `reserved_footprint_minutes` at 0 and `status`
        `AVAILABLE`". A project supplies "an optional `procurement_type` that defaults
        to `MUNICIPAL_BID` and may instead be `DESIGN_BUILD` or `SOLE_SOURCE`".

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
        """
        bay = validate_success(
            api.create_test_bay(
                factories.test_bay_payload(
                    omit=("changeover_buffer_minutes", "status")
                ),
                make_platform_admin_headers(),
            ),
            201,
        )
        assert bay["changeover_buffer_minutes"] == 120
        assert bay["status"] == "AVAILABLE"
        assert bay["reserved_footprint_minutes"] == 0

        project = validate_success(
            api.create_project(
                factories.project_payload(omit=("procurement_type",)),
                make_contracts_administrator_headers(),
            ),
            201,
        )
        assert project["procurement_type"] == "MUNICIPAL_BID"


class TestDerivedFieldsAtCreation:
    """Fields the server computes rather than accepts."""

    def test_equipment_package_copies_its_code_stamp_and_prices_itself(self, api):
        """The package copies the stamp from its stage technology and stamps a budgetary price.

        A package "copies `code_stamp_required` from the stage technology's
        `requires_code_stamp` at creation, and enters `status` `DRAFT` with
        `revision_round` at 0, `designed_by_user_id` set to the acting operator's
        identifier, `reviewed_by_user_id` null, `firm_cost_cents` at 0,
        `cost_variance_pct` at 0, `variance_flag` false, and both `approved_at` and
        `released_at` null." The BUDGETARY variant is "stamped when the package is
        created".

        Design: Corner/entities/equipment_package_code_stamp_and_budgetary_cost_are_computed
        """
        state = fixtures.scoped_single_stage_project(api)

        response = api.create_equipment_package(
            state["filtration_stage"]["id"],
            factories.equipment_package_payload(state["material_spec"]["id"]),
            make_application_engineer_headers(),
        )
        package = validate_success(response, 201)

        assert package["code_stamp_required"] == "AWWA"
        assert_money(package["budgetary_cost_cents"], 260832000, "budgetary_cost_cents")
        assert_money(package["firm_cost_cents"], 0, "firm_cost_cents")
        assert package["cost_variance_pct"] == 0
        assert package["variance_flag"] is False
        assert package["status"] == "DRAFT"
        assert package["revision_round"] == 0
        assert package["designed_by_user_id"] == "eng-1"
        assert package["reviewed_by_user_id"] is None
        assert package["approved_at"] is None
        assert package["released_at"] is None
        assert_common_fields(package, expected_version=1)

    def test_release_derives_the_skid_serial_number_and_footprint(self, api):
        """The minted skid names itself from the stage index and revision round.

        A released package "mints exactly one **skid** ... [which] receives a shop
        `serial_no` composed as the literal prefix `SKID-` followed by the parent
        stage's `stage_index`, a hyphen, and the package's `revision_round` at release".
        Its footprint "is snapshotted at creation as the stage technology's
        `footprint_sf_per_mgd` multiplied by the stage's `design_flow_mgd`, rounded
        **up** to a whole square foot", and "the skid starts with `mechanical_status`
        `FRAME_SET`, `controls_status` `PANEL_BUILD`, `fat_readiness` `NOT_READY` and
        `rework_count` at 0."

        Design: Corner/entities/skid_serial_number_and_footprint_are_system_derived
        """
        state = fixtures.released_single_stage_project(api)

        skid = state["skid"]
        assert skid["serial_no"] == "SKID-1-0"
        assert skid["footprint_sf"] == 5400
        assert skid["requires_exclusive_bay"] is False
        assert_skid_state(
            skid,
            mechanical_status="FRAME_SET",
            controls_status="PANEL_BUILD",
            fat_readiness="NOT_READY",
            rework_count=0,
        )
        assert_common_fields(skid, expected_version=1)

    def test_a_consumable_draw_is_append_only_and_carries_no_version(self, api):
        """The draw row exposes id and created_at but neither updated_at nor version.

        Section 2.4 says "the single exception is the consumable draw. A draw row is an
        append-only accounting line: it is never mutated after insertion, and so it
        carries only `id` and `created_at`. Both `updated_at` and `version` are
        **absent** from a consumable draw -- not null, absent. A correction to a draw is
        expressed by minting a compensating reversal row, never by editing the
        original."

        Design: Corner/entities/consumable_draw_is_append_only_with_no_version_field
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

        assert_append_only_fields(draw)
        assert_money(draw["accrual_amount_cents"], 1830000, "accrual_amount_cents")
        assert_money(draw["settled_amount_cents"], 1533600, "settled_amount_cents")
        assert_money(draw["warranty_credit_cents"], 0, "warranty_credit_cents")
        assert draw["reverses_draw_id"] is None
        assert draw["posted_by_user_id"] == "ca-1"

        agreement = fixtures.current_agreement(api, state["agreement"]["id"])
        assert_money(
            agreement["reserve_committed_accrual_cents"],
            1830000,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            agreement["reserve_available_cents"], 10370000, "reserve_available_cents"
        )
        assert_money(
            agreement["settlement_variance_cents"], -296400, "settlement_variance_cents"
        )


class TestExistenceAndShapeFailures:
    """Unresolvable identifiers and malformed bodies."""

    def test_reading_an_unknown_skid_reports_the_skid_not_found_code(self, api):
        """Each path identifier has its own not-found code, and a skid reports its own.

        Section 2.9 says "nested paths are resolved strictly left to right, and the
        first segment that fails to resolve determines the error", and lists
        `ERR_SKID_NOT_FOUND` among the codes that are "each HTTP 404".

        Design: Corner/entities/skid_get_with_unknown_id_returns_404_not_found
        """
        response = api.get_skid(UNKNOWN_ID, make_fabrication_manager_headers())

        validate_error(response, ApiErrorId.SKID_NOT_FOUND.value, 404)

    def test_an_influent_profile_without_a_design_flow_is_rejected(self, api):
        """The design flow is required, so omitting it is a request-shape failure.

        Each sample carries "`design_flow_mgd`, the strictly positive average design
        flow in million gallons per day the sample represents, carried at three decimal
        places", and request-shape validation checks that "required fields present,
        types correct, enum members declared" hold, reporting `ERR_INVALID_REQUEST`.

        Design: Corner/entities/influent_profile_missing_design_flow_is_rejected
        """
        project = fixtures.create_draft_project(api)

        response = api.create_influent_profile(
            project["id"],
            factories.influent_profile_payload(omit=("design_flow_mgd",)),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(
            api.list_project_influent_profiles(
                project["id"], make_application_engineer_headers()
            )
        )
        assert meta["total_count"] == 0

    def test_an_undeclared_treatment_parameter_is_rejected(self, api):
        """Only the eight declared parameters are accepted for a treatment objective.

        Each objective "names a `parameter` from `TURBIDITY_NTU`, `TOC_MG_L`,
        `TDS_MG_L`, `CHLORIDE_MG_L`, `ECOLI_CFU_100ML`, `GIARDIA_LOG_REMOVAL`,
        `BOD5_MG_L` and `AMMONIA_N_MG_L`", and an undeclared enum member is a
        request-shape failure.

        Design: Corner/entities/treatment_objective_rejects_undeclared_parameter_enum
        """
        project = fixtures.create_draft_project(api)

        response = api.create_treatment_objective(
            project["id"],
            factories.turbidity_objective_payload(parameter="ARSENIC_UG_L"),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

    def test_logging_a_profile_under_an_unknown_project_reports_the_project(self, api):
        """The project path segment resolves before the body is looked at.

        Section 2.9 says "a request addressing a package under a stage resolves the
        `stage_id` before it looks at the body" and puts path existence at step 3 with
        `ERR_PROJECT_NOT_FOUND` first, noting that request-shape validation "sits
        *below* existence: a body that is malformed against a path that does not
        resolve reports the not-found code."

        Design: Corner/entities/influent_profile_creation_requires_existing_parent_project
        """
        response = api.create_influent_profile(
            UNKNOWN_ID,
            factories.influent_profile_payload(),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.PROJECT_NOT_FOUND.value, 404)

    def test_a_package_naming_an_unknown_material_reports_a_catalog_reference(self, api):
        """A body foreign key that does not resolve is a catalog reference failure.

        Section 2.9 says the catalog reads "report an unresolvable identifier as
        `ERR_CATALOG_REF_NOT_FOUND` (HTTP 404), and so does any foreign key supplied in
        a *request body* -- `material_spec_id`, `skid_id`, `test_bay_id` or `project_id`
        -- that does not resolve to a live row."

        Design: Corner/entities/equipment_package_material_spec_reference_must_resolve
        """
        state = fixtures.scoped_single_stage_project(api)

        response = api.create_equipment_package(
            state["filtration_stage"]["id"],
            factories.equipment_package_payload(UNKNOWN_ID),
            make_application_engineer_headers(),
        )

        validate_error(response, ApiErrorId.CATALOG_REF_NOT_FOUND.value, 404)


class TestInfluentProfileEcho:
    """The laboratory sample keeps the flow figures it was given."""

    def test_a_logged_profile_starts_submitted_with_no_decision(self, api):
        """A newly logged sample carries its flows and an undecided QA status.

        The PRD says "every logged profile enters `qa_status` `SUBMITTED` with
        `qa_decided_by_user_id` and `qa_note` null", and section 2.6 pins that "design
        flows in million gallons per day are carried and compared at three decimal
        places, rounded half up."

        Design: Corner/entities/project_retrieval_returns_the_stored_row
        """
        project = fixtures.create_draft_project(api)

        profile = validate_success(
            api.create_influent_profile(
                project["id"],
                factories.influent_profile_payload(),
                make_application_engineer_headers(),
            ),
            201,
        )

        assert profile["project_id"] == project["id"]
        assert profile["qa_status"] == "SUBMITTED"
        assert profile["qa_decided_by_user_id"] is None
        assert profile["qa_note"] is None
        assert_flow(profile["design_flow_mgd"], 4.000)
        assert_common_fields(profile, expected_version=1)
