"""Entity-level contracts: creation, retrieval, listing, defaults and identity."""

from test_helpers import (
    ADMIN,
    ANALYST,
    EQUITY,
    NON_EXISTENT_UUID,
    REVIEWER,
    ApiErrorId,
    api_client,
    assert_error_envelope,
    assert_fields,
    assert_identity_fields,
    assert_all_null,
    assert_link_carries_no_mutable_identity,
    asset_payload,
    create_asset,
    create_harbor,
    create_jurisdiction,
    create_plan_cycle,
    create_screened_project,
    hazard_profile_payload,
    is_valid_uuid,
    jurisdiction_payload,
    make_jurisdiction_delegate_headers,
    make_project_sponsor_headers,
    pact_payload,
    plan_cycle_payload,
    project_payload,
    read_asset,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestJurisdictionRegistration:
    """Registering and reading back a member government."""

    def test_creation_returns_every_declared_field(self):
        """A full payload returns 201 and the whole row, computed fields included.

        PRD 3.1: "A `RegionalAdministrator` admits a member by supplying its display
        `name`, its agency-assigned `jurisdiction_code`, its resident `population`, its
        `svi_score`, and the `endorsement_weight` that member will carry in plan
        endorsement tallies; `status` may also be supplied and defaults to `ACTIVE`
        when omitted."  PRD 3.1 also derives the pair: "`HIGH` when the score is at
        least 0.50 but below 0.75" and "`disadvantaged_flag` is true exactly when
        `svi_tier` is `HIGH` or `SEVERE`".

        Design: Corner/entities/jurisdiction_creation_returns_all_declared_fields
        """
        response = api_client.create_jurisdiction(
            jurisdiction_payload(
                name="Harbor City",
                jurisdiction_code="CITY-HARBOR",
                population=180000,
                svi_score=0.62,
                endorsement_weight=4,
            ),
            ADMIN(),
        )

        jurisdiction = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object", (
            f"a single created row is an object envelope, got {body['response_type']}"
        )
        assert_fields(
            jurisdiction,
            {
                "name": "Harbor City",
                "jurisdiction_code": "CITY-HARBOR",
                "population": 180000,
                "svi_score": 0.62,
                "endorsement_weight": 4,
                "status": "ACTIVE",
                "svi_tier": "HIGH",
                "disadvantaged_flag": True,
            },
            "the newly admitted member government",
        )
        assert_identity_fields(jurisdiction, "the newly admitted member government")

    def test_retrieval_by_id_echoes_the_stored_row(self):
        """A read of the same row returns the same values to a different role.

        PRD 2.4: "Every persisted record carries an `id` that is a server-minted UUID
        with no type prefix and no embedded semantics; clients never supply it."  The
        banded tier travels with the row, since PRD 3.1 says the server "derives the
        banded `svi_tier` from that score and the boolean `disadvantaged_flag` from the
        tier".

        Design: Corner/entities/jurisdiction_retrieval_by_id_returns_the_stored_row
        """
        created = create_harbor(name="Harbor City")

        stored = validate_success(api_client.get_jurisdiction(created["id"], EQUITY()), 200)

        assert_fields(
            stored,
            {
                "id": created["id"],
                "jurisdiction_code": "CITY-HARBOR",
                "svi_tier": "HIGH",
                "endorsement_weight": 4,
                "version": 1,
            },
            "the member government read back by identifier",
        )

    def test_the_computed_pair_tracks_the_score_and_is_never_supplied(self):
        """Two scores in different bands produce two different computed pairs.

        PRD 3.1: "Two fields are never supplied by the client. On creation, and again
        on any subsequent amendment that supplies a new `svi_score`, the server derives
        the banded `svi_tier` from that score and the boolean `disadvantaged_flag` from
        the tier. The banding is: `SEVERE` when the score is at least 0.75; `HIGH` when
        the score is at least 0.50 but below 0.75; `MODERATE` when the score is at
        least 0.25 but below 0.50; and `LOW` otherwise."

        Design: Corner/entities/jurisdiction_svi_tier_and_disadvantaged_flag_are_computed_not_accepted
        """
        low = create_jurisdiction(
            name="Ridge Town",
            jurisdiction_code="TOWN-RIDGE",
            population=40000,
            svi_score=0.18,
            endorsement_weight=3,
        )
        severe = create_jurisdiction(
            name="Delta Village",
            jurisdiction_code="VILL-DELTA",
            population=12000,
            svi_score=0.81,
            endorsement_weight=2,
        )

        assert_fields(
            low,
            {"svi_tier": "LOW", "disadvantaged_flag": False},
            "the low-vulnerability member government",
        )
        assert_fields(
            severe,
            {"svi_tier": "SEVERE", "disadvantaged_flag": True},
            "the severely vulnerable member government",
        )


class TestLifelineRegister:
    """The asset register's listing, retrieval and default behaviour."""

    def test_listing_paginates_and_filters_the_register(self):
        """Three assets page two at a time and filter down to one by class.

        PRD 2.3: "For every response whose `response_type` is `"array"`, the four
        pagination fields `limit`, `offset`, `total_count` and `has_more` are returned
        inside `meta` alongside `api_request_id` and `api_request_timestamp`.
        `total_count` counts every row matching the supplied filters across the whole
        collection, not merely the rows on the current page, and `has_more` is true
        exactly when rows matching the filters remain beyond the current page."  PRD
        2.3 also declares the
        register's filters: "The lifeline asset register accepts `jurisdiction_id`,
        `upstream_asset_id`, `asset_class`, `criticality_status`, `criticality_tier`
        and `is_shared`."

        Design: Corner/entities/assets_listing_paginates_with_total_count_and_has_more
        """
        harbor = create_harbor()
        create_asset(harbor["id"], name="Asset One", asset_class="WATER", is_shared=True)
        second = create_asset(
            harbor["id"],
            name="Asset Two",
            asset_class="POWER",
            replacement_value_cents=400000000,
            service_population=40000,
            redundancy_factor=0.10,
            is_shared=None,
        )
        create_asset(
            harbor["id"],
            name="Asset Three",
            asset_class="TRANSPORT",
            replacement_value_cents=800000000,
            service_population=90000,
            redundancy_factor=0.20,
            is_shared=None,
        )

        first_page, first_meta = validate_paginated(
            api_client.list_assets(ADMIN(), params={"limit": 2, "offset": 0})
        )
        second_page, second_meta = validate_paginated(
            api_client.list_assets(ADMIN(), params={"limit": 2, "offset": 2})
        )
        filtered, filtered_meta = validate_paginated(
            api_client.list_assets(ADMIN(), params={"asset_class": "POWER"})
        )

        assert len(first_page) == 2, f"limit 2 must return 2 rows, got {len(first_page)}"
        assert_fields(
            first_meta,
            {"total_count": 3, "has_more": True, "limit": 2, "offset": 0},
            "the first page of the register",
        )
        assert len(second_page) == 1, f"the tail page holds 1 row, got {len(second_page)}"
        assert_fields(
            second_meta,
            {"total_count": 3, "has_more": False},
            "the tail page of the register",
        )
        assert len(filtered) == 1 and filtered[0]["id"] == second["id"], (
            "filtering by asset_class POWER must return exactly the power asset, "
            f"got {[row['id'] for row in filtered]}"
        )
        assert filtered_meta["total_count"] == 1, (
            "total_count counts the rows matching the filter, got "
            f"{filtered_meta['total_count']}"
        )
        first_ids = {row["id"] for row in first_page}
        second_ids = {row["id"] for row in second_page}
        assert not (first_ids & second_ids), (
            f"pages must not overlap, both carry {first_ids & second_ids}"
        )

    def test_an_unknown_asset_identifier_returns_the_asset_not_found_code(self):
        """A path identifier that resolves to nothing is a 404 with its own code.

        PRD 2.5: "Every identifier embedded in the URL must resolve to an existing
        row, and they are checked in the order they appear in the path from left to
        right, so on a nested path the leftmost unresolved identifier decides the
        error."  The map names this one: "`asset_id` yields `ERR_ASSET_NOT_FOUND`".

        Design: Corner/entities/asset_get_with_unknown_id_returns_not_found
        """
        response = api_client.get_asset(NON_EXISTENT_UUID, ANALYST())

        validate_error(response, ApiErrorId.ERR_ASSET_NOT_FOUND.value, 404)
        assert_error_envelope(response.json(), ApiErrorId.ERR_ASSET_NOT_FOUND.value)

    def test_the_two_optional_asset_inputs_default_and_the_ranking_starts_empty(self):
        """Omitting both optional inputs yields false and null, with no ranking yet.

        PRD 3.4: "Two optional fields complete the picture: `is_shared`, which defaults
        to false and marks an asset that serves more than one member jurisdiction, and
        `upstream_asset_id`, which defaults to null and names the asset this one depends
        on for continued service. A new asset always begins in `criticality_status`
        `UNRANKED` with `consequence_score`, `criticality_tier` and `dependency_depth`
        all null."

        Design: Corner/entities/asset_creation_defaults_is_shared_false_and_upstream_null
        """
        harbor = create_harbor()

        response = api_client.create_asset(
            asset_payload(
                harbor["id"],
                name="Harbor Clinic",
                asset_class="HEALTH",
                replacement_value_cents=300000000,
                service_population=25000,
                redundancy_factor=0.05,
                is_shared=None,
            ),
            ADMIN(),
        )

        asset = validate_success(response, 201)
        assert_fields(
            asset,
            {
                "is_shared": False,
                "upstream_asset_id": None,
                "criticality_status": "UNRANKED",
            },
            "an asset created without its optional inputs",
        )
        assert_all_null(
            asset,
            ["consequence_score", "criticality_tier", "dependency_depth"],
            "an asset that has never been ranked",
        )

    def test_client_supplied_system_fields_are_ignored_on_creation(self):
        """Smuggled identity and ranking values never reach the stored row.

        PRD 2.4: "Every persisted record carries an `id` that is a server-minted UUID
        with no type prefix and no embedded semantics; clients never supply it", and a
        "`version` integer that starts at 1 when the record is created".  The ranking
        outputs are the server's too, since PRD 3.4 says "A new asset always begins in
        `criticality_status` `UNRANKED` with `consequence_score`, `criticality_tier` and
        `dependency_depth` all null."

        Design: Corner/entities/asset_creation_ignores_client_supplied_system_fields_input_ignored
        """
        harbor = create_harbor()
        smuggled_id = "11111111-1111-1111-1111-111111111111"

        response = api_client.create_asset(
            asset_payload(
                harbor["id"],
                name="Harbor Radio Tower",
                asset_class="COMMS",
                replacement_value_cents=200000000,
                service_population=60000,
                redundancy_factor=0.15,
                is_shared=None,
                id=smuggled_id,
                created_at="2020-01-01T00:00:00.000Z",
                updated_at="2020-01-01T00:00:00.000Z",
                version=99,
                consequence_score=42.42,
            ),
            ADMIN(),
        )

        asset = validate_success(response, 201)
        assert asset["id"] != smuggled_id, (
            "the server mints the identifier, so a smuggled id must be discarded"
        )
        assert is_valid_uuid(asset["id"]), f"the minted id must be a UUID, got {asset['id']}"
        assert_fields(
            asset,
            {"version": 1, "consequence_score": None, "criticality_status": "UNRANKED"},
            "an asset whose payload tried to dictate its system fields",
        )
        assert_fields(
            read_asset(asset["id"]),
            {"version": 1, "consequence_score": None},
            "the stored asset, read back",
        )


class TestDeclaredDefaults:
    """Optional governance inputs fall back to the values the contract declares."""

    def test_a_plan_cycle_created_with_two_fields_takes_all_three_defaults(self):
        """The governance parameters default and the counters start at zero.

        PRD 3.8: "Three governance parameters may also be supplied:
        `quorum_weight_bps`, the supporting-weight share required to adopt, which
        defaults to 6600 basis points — two-thirds rounded up to the nearest hundredth
        of a percent, or sixty-six percent — and must lie between 1 and 10000
        inclusive; `max_revision_rounds`, the revision budget, which defaults to 2 and
        must lie between 0 and 5 inclusive; and `required_session_count`, the number of
        completed engagement sessions needed before an endorsement round may open, which
        defaults to 2 and must lie between 0 and 10 inclusive. A new cycle reads
        `status` `DRAFT`, `round_number` 0, `revision_count` 0, `achieved_weight_bps`
        null and `adopted_at` null."

        Design: Corner/entities/plan_cycle_creation_applies_quorum_and_revision_defaults
        """
        response = api_client.create_plan_cycle(
            plan_cycle_payload(
                cycle_label="Default Cycle",
                endorsement_deadline="2026-12-01T00:00:00Z",
                quorum_weight_bps=None,
                max_revision_rounds=None,
                required_session_count=None,
            ),
            ADMIN(),
        )

        cycle = validate_success(response, 201)
        assert_fields(
            cycle,
            {
                "status": "DRAFT",
                "quorum_weight_bps": 6600,
                "max_revision_rounds": 2,
                "required_session_count": 2,
                "round_number": 0,
                "revision_count": 0,
            },
            "a plan cycle created on its defaults",
        )
        assert_all_null(
            cycle,
            ["achieved_weight_bps", "adopted_at"],
            "a plan cycle that has never been endorsed",
        )

    def test_a_pact_created_without_a_cap_takes_three_concurrent_commitments(self):
        """The concurrency cap defaults and the unit ledger opens empty.

        PRD 3.9: "An optional `max_concurrent_commitments` caps how many existing
        commitments' windows may overlap a new one; it defaults to 3 and must lie
        between 1 and 20 inclusive."  PRD 3.9 also fixes the opening ledger: "A new
        pact reads `reserved_units` 0, `free_units` equal to `pledged_units`, and
        `status` `OPEN`."

        Design: Corner/entities/mutual_aid_pact_creation_defaults_max_concurrent_commitments_to_three
        """
        harbor = create_harbor()

        response = api_client.create_pact(
            pact_payload(
                harbor["id"],
                resource_class="COOLING_UNITS",
                pledged_units=12,
                window_start="2026-09-01T00:00:00Z",
                window_end="2026-10-01T00:00:00Z",
                max_concurrent_commitments=None,
            ),
            make_jurisdiction_delegate_headers(harbor["id"]),
        )

        pact = validate_success(response, 201)
        assert_fields(
            pact,
            {
                "max_concurrent_commitments": 3,
                "reserved_units": 0,
                "free_units": 12,
                "status": "OPEN",
                "version": 1,
            },
            "a pledge created without a concurrency cap",
        )


class TestPayloadShapeOnHazardProfiles:
    """Priority 7 rejects a missing field, an unknown enum member and a bad range."""

    def test_omitting_the_exposure_index_is_rejected_and_persists_nothing(self):
        """A required input with no default cannot be left out.

        PRD 2.5: "Every write endpoint validates its payload shape and rejects a
        violation with `ERR_INVALID_REQUEST` (HTTP 422). All required input fields must
        be present".  PRD 2.5 also promises nothing is written: "the **first** violated
        rule short-circuits the request: its error is returned and nothing at all is
        written, not even partially."

        Design: Corner/entities/hazard_profile_creation_missing_exposure_index_rejected
        """
        harbor = create_harbor()
        payload = hazard_profile_payload(harbor["id"])
        del payload["exposure_index"]

        response = api_client.create_hazard_profile(payload, ANALYST())

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
        _rows, meta = validate_paginated(api_client.list_hazard_profiles(ANALYST()))
        assert meta["total_count"] == 0, (
            f"a rejected creation must persist no projection, found {meta['total_count']}"
        )

    def test_a_hazard_type_outside_the_enumeration_is_rejected(self):
        """WILDFIRE is not a declared member, while FLOOD is.

        PRD 3.2: "The payload names the covered `jurisdiction_id`, the `hazard_type` —
        one of `HEAT`, `FLOOD`, `DROUGHT` or `STORM`".  PRD 2.5 rejects anything else:
        "every enum-valued field must carry a declared member of its enumeration".

        Design: Corner/entities/hazard_profile_creation_with_unknown_hazard_type_enum_rejected
        """
        harbor = create_harbor()

        rejected = api_client.create_hazard_profile(
            hazard_profile_payload(harbor["id"], hazard_type="WILDFIRE"), ANALYST()
        )
        validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

        accepted = api_client.create_hazard_profile(
            hazard_profile_payload(harbor["id"], hazard_type="FLOOD"), ANALYST()
        )
        profile = validate_success(accepted, 201)
        assert_fields(profile, {"hazard_type": "FLOOD"}, "the projection with a declared hazard")

    def test_an_out_of_set_horizon_year_and_an_out_of_range_exposure_are_rejected(self):
        """Two different numeric constraint kinds on the same endpoint.

        PRD 2.5: "every decimal score whose domain is zero through one must lie inside
        that range; ... and `horizon_year` must be one of 2040, 2060 or 2080."  PRD 3.2
        states the same bounds for the field pair: "the projection `horizon_year`, which
        must be exactly 2040, 2060 or 2080, and three quantitative results:
        `exposure_index`, a normalized exposure magnitude with 2 fractional digits
        between 0.00 and 1.00 inclusive".

        Design: Corner/entities/hazard_profile_creation_with_out_of_enum_horizon_year_rejected
        """
        harbor = create_harbor()

        bad_year = api_client.create_hazard_profile(
            hazard_profile_payload(
                harbor["id"],
                hazard_type="HEAT",
                scenario="RCP45",
                horizon_year=2050,
                exposure_index=0.50,
            ),
            ANALYST(),
        )
        bad_exposure = api_client.create_hazard_profile(
            hazard_profile_payload(
                harbor["id"],
                hazard_type="HEAT",
                scenario="RCP45",
                horizon_year=2040,
                exposure_index=1.20,
            ),
            ANALYST(),
        )

        validate_error(bad_year, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
        validate_error(bad_exposure, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
        _rows, meta = validate_paginated(api_client.list_hazard_profiles(ANALYST()))
        assert meta["total_count"] == 0, (
            f"neither rejected creation may persist a projection, found {meta['total_count']}"
        )


class TestJunctionRowsAndParentReferences:
    """The immutable link row, its many-to-many shape and its parent checks."""

    def test_a_link_carries_only_an_identifier_and_a_creation_stamp(self):
        """The junction row has no `updated_at` and no `version`.

        PRD 2.4: "There is one deliberate exception. A project-to-asset link is an
        immutable junction row: it carries only `id` and `created_at`. It has no
        `updated_at` and no `version`, because once written it is never modified — a link
        is added, and its effects propagate outwards, but the link itself never changes."

        Design: Corner/entities/project_asset_link_is_immutable_and_carries_no_version_field
        """
        harbor = create_harbor()
        cycle = create_plan_cycle()
        asset = create_asset(harbor["id"], is_shared=True)
        project = create_screened_project(cycle["id"], harbor["id"], name="Harbor Levee Raise")

        created = validate_success(
            api_client.create_asset_link(
                project["id"],
                {
                    "asset_id": asset["id"],
                    "avoided_loss_annual_cents": 3333333,
                    "benefit_reaches_disadvantaged": True,
                },
                make_project_sponsor_headers(harbor["id"]),
            ),
            201,
        )
        stored = validate_success(api_client.get_asset_link(created["id"], REVIEWER()), 200)

        assert_link_carries_no_mutable_identity(created)
        assert_link_carries_no_mutable_identity(stored)
        assert_fields(stored, {"link_sequence": 1}, "the first link of the project")

    def test_the_junction_supports_two_projects_over_the_same_two_assets(self):
        """Four rows, two per project and two per asset, with per-project sequences.

        PRD 3.6: "A `ProjectSponsor` attributes benefit by linking the project to an
        asset, supplying the `asset_id` of the protected lifeline asset and the
        `avoided_loss_annual_cents` — the annual loss avoided at that asset once the
        project is in service, in whole cents and never negative."  The sequence is per
        project, since PRD 3.6 states "Each accepted link is stamped with a
        `link_sequence` equal to one plus the count of links already held by that project,
        ordered by `created_at` ascending — so the first link on a project is 1, the second
        is 2, and so on."

        Design: Corner/entities/project_asset_link_junction_supports_many_to_many_graph_topology
        """
        harbor = create_harbor()
        cycle = create_plan_cycle()
        first_asset = create_asset(harbor["id"], name="Asset One", is_shared=True)
        second_asset = create_asset(
            harbor["id"],
            name="Asset Two",
            asset_class="POWER",
            replacement_value_cents=400000000,
            service_population=40000,
            redundancy_factor=0.10,
            is_shared=None,
        )
        alpha = create_screened_project(cycle["id"], harbor["id"], name="Project Alpha")
        beta = create_screened_project(
            cycle["id"],
            harbor["id"],
            name="Project Beta",
            strategy_type="ACCOMMODATE",
            base_cost_cents=30000000,
            service_life_years=25,
            cobenefit_points=10,
            feasibility_score=0.65,
        )
        sponsor = make_project_sponsor_headers(harbor["id"])

        rows = {}
        for key, project, asset, avoided, reaches in (
            ("alpha_one", alpha, first_asset, 3333333, True),
            ("alpha_two", alpha, second_asset, 1111111, False),
            ("beta_one", beta, first_asset, 2222222, True),
            ("beta_two", beta, second_asset, 1000000, False),
        ):
            rows[key] = validate_success(
                api_client.create_asset_link(
                    project["id"],
                    {
                        "asset_id": asset["id"],
                        "avoided_loss_annual_cents": avoided,
                        "benefit_reaches_disadvantaged": reaches,
                    },
                    sponsor,
                ),
                201,
            )

        _by_project, project_meta = validate_paginated(
            api_client.list_asset_links(ADMIN(), params={"project_id": alpha["id"]})
        )
        assert project_meta["total_count"] == 2, (
            f"the first project holds two links, found {project_meta['total_count']}"
        )
        _by_asset, asset_meta = validate_paginated(
            api_client.list_asset_links(ADMIN(), params={"asset_id": first_asset["id"]})
        )
        assert asset_meta["total_count"] == 2, (
            f"the shared asset is attributed by two projects, found {asset_meta['total_count']}"
        )
        assert_fields(rows["alpha_one"], {"link_sequence": 1}, "the first link of the first project")
        assert_fields(rows["alpha_two"], {"link_sequence": 2}, "the second link of the first project")
        assert_fields(rows["beta_one"], {"link_sequence": 1}, "the first link of the second project")

    def test_a_body_reference_to_a_missing_plan_cycle_is_a_not_found(self):
        """The parent check runs before any business rule on the sponsor.

        PRD 2.5: "Every foreign reference carried in a request payload must resolve,
        checked in the order the endpoint declares its input fields, using the same
        identifier-to-code map as the path check."  That map gives "`plan_cycle_id`
        yields `ERR_PLAN_CYCLE_NOT_FOUND`", and all thirteen "are HTTP 404".

        Design: Corner/entities/project_creation_with_unknown_plan_cycle_parent_returns_not_found
        """
        harbor = create_harbor()

        response = api_client.create_project(
            project_payload(NON_EXISTENT_UUID, harbor["id"], name="Orphan Project"),
            make_project_sponsor_headers(harbor["id"]),
        )

        validate_error(response, ApiErrorId.ERR_PLAN_CYCLE_NOT_FOUND.value, 404)
        _rows, meta = validate_paginated(api_client.list_projects(ADMIN()))
        assert meta["total_count"] == 0, (
            f"a rejected creation must persist no project, found {meta['total_count']}"
        )

    def test_closing_a_dependency_loop_is_refused_after_the_foreign_key_check(self):
        """An unknown upstream is a 404; a loop-closing upstream is a 409.

        PRD 3.4: "The graph must remain acyclic. Whenever an asset is created, whenever
        its dependency edge is rewritten, and again whenever it is ranked, the server
        walks the chain of `upstream_asset_id` pointers upward and must reach a null
        without revisiting any identifier; pointing an asset's upstream edge at one of
        its own downstream assets closes a loop and is rejected with
        `ERR_ASSET_DEPENDENCY_CYCLE`."  PRD 2.5 puts existence first: "a body `asset_id`
        or `upstream_asset_id` yields `ERR_ASSET_NOT_FOUND`".

        Design: Corner/entities/asset_self_referential_dependency_cycle_rejected
        """
        harbor = create_harbor()
        root = create_asset(
            harbor["id"],
            name="Root Substation",
            asset_class="POWER",
            replacement_value_cents=500000000,
            service_population=100000,
            redundancy_factor=0.20,
            is_shared=None,
        )
        child = create_asset(
            harbor["id"],
            name="Downstream Pump",
            asset_class="WATER",
            replacement_value_cents=300000000,
            service_population=80000,
            redundancy_factor=0.10,
            is_shared=None,
            upstream_asset_id=root["id"],
        )

        unknown_upstream = api_client.patch_asset(
            root["id"], {"upstream_asset_id": NON_EXISTENT_UUID}, ADMIN()
        )
        loop = api_client.patch_asset(root["id"], {"upstream_asset_id": child["id"]}, ADMIN())

        validate_error(unknown_upstream, ApiErrorId.ERR_ASSET_NOT_FOUND.value, 404)
        validate_error(loop, ApiErrorId.ERR_ASSET_DEPENDENCY_CYCLE.value, 409)
        assert_fields(
            read_asset(root["id"]),
            {"upstream_asset_id": None, "version": 1},
            "the root asset neither rejected amendment may touch",
        )
        assert_fields(
            read_asset(child["id"]),
            {"upstream_asset_id": root["id"]},
            "the downstream asset",
        )
