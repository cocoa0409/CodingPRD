"""The three registries, filing a development, and how a request is refused.

These are the roots of every chain in the contract: a sponsor, an investor and a
program-year cap pool depend on nothing, and a development depends only on its
sponsor. The tests here pin the declared defaults on those roots, prove the
server owns its own system fields, and walk the front of the refusal ladder —
payload well-formedness, path-entity existence and foreign-key resolution order.
"""

from test_helpers import (
    ALLOCATION_OFFICER,
    COMPLIANCE_OFFICER,
    ApiErrorId,
    assert_common_properties,
    assert_fields,
    assert_nulls,
    assert_page,
    assert_pool_ledger,
    assert_project_fractions,
    assert_unit_counts,
    constants,
    factories,
    fixtures,
    make_developer_headers,
    make_investor_headers,
    types,
    validate_error,
    validate_success,
)


class TestRegistryDefaults:
    """What the contract says a brand-new root row looks like."""

    def test_developer_creation_returns_active_status_and_zero_active_projects(self, api):
        """Register a sponsor with only its three declared inputs.

        The three system fields must come back at their declared openings rather
        than null, and the row must carry the whole common quartet on the create
        response itself, not only on a later read.

        PRD: "A newly registered sponsor opens with `status` `ACTIVE`, with `sanction_reason` null, and with `active_project_count` at zero — that counter is derived, not supplied, and reflects how many of the sponsor's developments are in any `development_status` other than `WITHDRAWN`."
        PRD: "`version` starts at 1 when the row is created and increments by exactly 1 on every mutation of that row"

        Design: Corner/entities/developer_creation_returns_active_status_and_zero_active_projects
        """
        response = api.create_developer(ALLOCATION_OFFICER, **factories.developer_payload())
        developer = validate_success(response, 201)

        assert_fields(
            developer,
            "developer",
            name=constants.SPONSOR_NAME,
            tax_id=constants.SPONSOR_TAX_ID,
            contact_email=constants.SPONSOR_EMAIL,
            status="ACTIVE",
            active_project_count=0,
            version=1,
        )
        assert_nulls(developer, ("sanction_reason",), "developer")
        assert_common_properties(developer, "developer")
        assert developer["id"], "the create response must carry the server-minted id"

    def test_developer_system_fields_are_server_owned_and_body_input_ignored(self, api):
        """Try to seed id, status, sanction_reason, version and created_at in the body.

        None of those five is a declared input, so the create is accepted and
        every one of them is solved by the server instead: the id is minted fresh,
        the status is the machine's initial state and the version opens at 1. The
        forced id must not be addressable afterwards.

        PRD: "Unknown keys are ignored rather than rejected."
        PRD: "Every stored resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp and an integer `version`."
        PRD: "A newly registered sponsor opens with `status` `ACTIVE`, with `sanction_reason` null, and with `active_project_count` at zero"

        Design: Corner/entities/developer_system_fields_are_server_owned_and_body_input_ignored
        """
        response = api.create_developer(
            ALLOCATION_OFFICER,
            id="dev-forced-1",
            status="DEBARRED",
            sanction_reason="seeded",
            version=7,
            created_at="2001-01-01T00:00:00Z",
            **factories.developer_payload()
        )
        developer = validate_success(response, 201)

        assert developer["id"] != "dev-forced-1", "the id must be server-minted"
        assert_fields(developer, "developer", status="ACTIVE", version=1)
        assert_nulls(developer, ("sanction_reason",), "developer")
        assert developer["created_at"] != "2001-01-01T00:00:00Z", (
            "created_at must be stamped by the server, not taken from the body"
        )

        forced = api.get_developer("dev-forced-1", ALLOCATION_OFFICER)
        validate_error(forced, ApiErrorId.ERR_DEVELOPER_NOT_FOUND, 404)

    def test_cap_pool_created_without_carryforward_applies_the_declared_zero_default(
        self, api
    ):
        """Open a program-year pool naming only the year and the base cap.

        The optional carryforward must default to zero and that zero has to flow
        through the whole six-figure ledger rather than turning any of the derived
        amounts null.

        PRD: "An optional `carryforward_cents` records unused cap rolled forward from prior years; it defaults to zero and may not be negative."
        PRD: "`total_cap_cents` becomes the base cap plus the carryforward, `reserved_cents` and `committed_cents` are both zero, `available_cents` and `awardable_cents` both equal the total cap, and `pool_status` opens at `OPEN`."

        Design: Corner/entities/cap_pool_created_without_carryforward_applies_the_declared_zero_default
        """
        response = api.create_cap_pool(
            ALLOCATION_OFFICER,
            program_year=constants.PROGRAM_YEAR,
            base_cap_cents=constants.POOL_BASE_CAP_CENTS,
        )
        pool = validate_success(response, 201)

        assert_fields(
            pool,
            "cap_pool",
            carryforward_cents=0,
            total_cap_cents=constants.POOL_BASE_CAP_CENTS,
            version=1,
        )
        assert_pool_ledger(
            pool,
            reserved_cents=0,
            committed_cents=0,
            available_cents=constants.POOL_BASE_CAP_CENTS,
            awardable_cents=constants.POOL_BASE_CAP_CENTS,
            pool_status="OPEN",
        )

    def test_investor_create_then_read_round_trips_and_exposes_no_update_endpoint(
        self, api
    ):
        """Register an investor, read it back, and list its deliveries.

        Investor is the one entity whose only mutable figure is derived: accepted
        credit opens at zero and moves only when a delivery is accepted or an
        accepted delivery is rescinded, so a read straight after the create still
        shows zero at version 1 and the delivery list is an empty page rather than
        a 404.

        PRD: "An investor opens with `total_credit_accepted_cents` at zero; thereafter that figure is the sum of `delivered_credit_cents` across every delivery to this investor whose `status` is `ACCEPTED`, and it is re-derived whenever a delivery is accepted or an accepted delivery is rescinded."
        PRD: "`total_count` (the number of rows matching the filters before the page window is applied)"

        Design: Corner/endpoints/investor_create_then_read_round_trips_and_exposes_no_update_endpoint
        """
        developer = validate_success(
            api.create_developer(ALLOCATION_OFFICER, **factories.developer_payload()), 201
        )

        created = validate_success(
            api.create_investor(ALLOCATION_OFFICER, **factories.investor_payload()), 201
        )
        assert created["version"] == 1, "a freshly registered investor opens at version 1"
        investor_headers = make_investor_headers(created["id"])

        read_back = validate_success(
            api.get_investor(created["id"], investor_headers)
        )
        assert_fields(
            read_back,
            "investor",
            id=created["id"],
            name=constants.INVESTOR_NAME,
            tax_id=constants.INVESTOR_TAX_ID,
            investor_type=constants.INVESTOR_TYPE,
            total_credit_accepted_cents=0,
            version=1,
        )
        assert_common_properties(read_back, "investor")

        deliveries, _ = assert_page(
            api.list_investor_deliveries(investor_headers, investor_id=created["id"]),
            total_count=0,
            has_more=False,
        )
        assert deliveries == [], "an investor with no deliveries lists an empty page"

        sponsor = validate_success(
            api.get_developer(developer["id"], ALLOCATION_OFFICER)
        )
        assert sponsor["active_project_count"] == 0, (
            "registering an investor must not touch the sponsor registry"
        )


class TestFilingADevelopment:
    """The sponsor's own write, and the body rules that guard it."""

    def test_project_computed_basis_and_fraction_fields_are_recomputed_and_body_input_ignored(
        self, api
    ):
        """File a development whose body also asserts its own computed figures.

        Computed fields are not inputs, so the extra keys are ignored and every
        one of them is solved from scratch: the aggregate basis from the two cost
        inputs, and — with no unit designated yet — zero for all three fractions
        with the set-aside unsatisfied rather than null.

        PRD: "Unknown keys are ignored rather than rejected."
        PRD: "On creation the server solves `aggregate_basis_cents` as the land cost plus the filed depreciable basis — this is the denominator of the provisional fifty-percent test — sets both status axes to their initial values `PLANNING` and `UNRESTRICTED`, raises the sponsor's `active_project_count` by 1 and increments the sponsor's `version` by 1."
        PRD: "With zero restricted units both fractions are zero and the applicable fraction is zero — not null, and not an error."

        Design: Corner/entities/project_computed_basis_and_fraction_fields_are_recomputed_and_body_input_ignored
        """
        developer = validate_success(
            api.create_developer(ALLOCATION_OFFICER, **factories.developer_payload()), 201
        )
        payload = factories.compact_project_payload(developer["id"])

        project = validate_success(
            api.create_project(
                make_developer_headers(developer["id"]),
                aggregate_basis_cents=999,
                applicable_fraction_bps=9999,
                set_aside_satisfied=True,
                automatic_credit_triggered=True,
                **payload
            ),
            201,
        )

        assert_fields(
            project,
            "project",
            aggregate_basis_cents=constants.COMPACT_AGGREGATE_BASIS_CENTS,
            set_aside_ratio_bps=0,
            set_aside_satisfied=False,
            automatic_credit_triggered=False,
        )
        assert_project_fractions(
            project, unit_fraction=0, floor_space_fraction=0, applicable_fraction=0
        )
        assert_nulls(project, ("provisional_fifty_percent_ratio_bps",), "project")

        sponsor = validate_success(
            api.get_developer(developer["id"], ALLOCATION_OFFICER)
        )
        assert sponsor["active_project_count"] == 1, (
            "filing a development raises the sponsor's active project count by 1"
        )

    def test_project_with_unknown_developer_id_returns_developer_not_found(self, api):
        """File a development naming a sponsor id that was never registered.

        The body is well formed and no development exists yet, so neither the
        payload rule nor the development's own 404 applies: the unresolvable
        foreign key must surface the sponsor's own 404. A second call with the
        stored id proves the payload itself was sound.

        PRD: "Every foreign key in the request body must resolve, returning the referenced entity's own 404."
        PRD: "A `Developer` files a development by supplying its own `developer_id` — which must equal `X-User-ID`, and a mismatch is `ERR_NOT_RESOURCE_OWNER`"

        Design: Corner/entities/project_with_unknown_developer_id_returns_developer_not_found
        """
        developer = validate_success(
            api.create_developer(ALLOCATION_OFFICER, **factories.developer_payload()), 201
        )

        orphan = api.create_project(
            make_developer_headers(constants.MISSING_UUID_B),
            **factories.compact_project_payload(
                constants.MISSING_UUID_B, name="Orphan Annex"
            )
        )
        validate_error(orphan, ApiErrorId.ERR_DEVELOPER_NOT_FOUND, 404)

        project = validate_success(
            api.create_project(
                make_developer_headers(developer["id"]),
                **factories.compact_project_payload(developer["id"])
            ),
            201,
        )
        assert project["developer_id"] == developer["id"]

        sponsor = validate_success(
            api.get_developer(developer["id"], ALLOCATION_OFFICER)
        )
        assert sponsor["active_project_count"] == 1, (
            "only the development that was actually stored may count"
        )

    def test_out_of_set_enum_and_zero_unit_count_are_rejected_by_the_body_rule(self, api):
        """Probe three separate payload rules against one sponsor and development.

        An election outside its declared set, a unit count of zero where at least
        one is required, and a negative `_cents` amount are all the same
        well-formedness violation, and none of the three may leave a row behind.

        PRD: "All required inputs present and non-null; every enum value inside its declared set; every `_cents` and `_bps` field an integer that is not negative; every count-of-units field an integer of at least 1 where the entity requires at least one; every datetime an ISO-8601 string with a `Z` suffix."
        PRD: "The seventh input is the `set_aside_election`, the income and rent restriction election that governs the whole development and takes one of three values: `MIN_20_50`, `MIN_40_60` or `AVG_INCOME`."
        PRD: "Both `total_units` and `total_floor_space_sqft` must be greater than zero"

        Design: Corner/entities/out_of_set_enum_and_zero_unit_count_are_rejected_by_the_body_rule
        """
        deal = fixtures.setup_project(api)
        sponsor_headers = deal.developer_headers

        bad_election = api.create_project(
            sponsor_headers,
            **factories.compact_project_payload(
                deal.developer_id, name="Bad Election", set_aside_election="MIN_30_60"
            )
        )
        validate_error(bad_election, ApiErrorId.ERR_INVALID_REQUEST, 400)

        zero_units = api.create_project(
            sponsor_headers,
            **factories.compact_project_payload(
                deal.developer_id, name="Zero Units", total_units=0
            )
        )
        validate_error(zero_units, ApiErrorId.ERR_INVALID_REQUEST, 400)

        negative_cents = api.create_unit_restriction(
            sponsor_headers,
            **factories.unit_payload(
                deal.project_id,
                "201",
                bedroom_count=1,
                floor_space_sqft=850,
                designation="MARKET",
                utility_allowance_cents=-10000,
                market_rent_cents=180000,
            )
        )
        validate_error(negative_cents, ApiErrorId.ERR_INVALID_REQUEST, 400)

        sponsor = validate_success(
            api.get_developer(deal.developer_id, ALLOCATION_OFFICER)
        )
        assert sponsor["active_project_count"] == 1, (
            "neither rejected development may have been stored"
        )
        project = fixtures.read_project(api, deal)
        assert_unit_counts(project, designated=0)


class TestExistenceAndReferenceOrder:
    """The path-entity 404s, and which 404 wins when a body carries two."""

    def test_unknown_path_ids_return_the_entity_specific_not_found_code_for_all_fourteen_entities(
        self, api
    ):
        """Read every one of the fourteen resources by the same unstored id.

        The contract gives each entity its own 404 rather than one shared code, so
        the fourteen reads must return fourteen distinct identifiers. Holding the
        id and the caller's role constant leaves the entity as the only variable.

        PRD: "The `{id}` in the path must resolve to a stored row of that endpoint's own entity, otherwise that entity's specific 404 is returned: `ERR_PROJECT_NOT_FOUND`, `ERR_DEVELOPER_NOT_FOUND`, `ERR_INVESTOR_NOT_FOUND`, `ERR_CAP_POOL_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_BOND_ISSUE_NOT_FOUND`, `ERR_DRAW_REQUEST_NOT_FOUND`, `ERR_UNIT_RESTRICTION_NOT_FOUND`, `ERR_REG_AGREEMENT_NOT_FOUND`, `ERR_COST_CERT_NOT_FOUND`, `ERR_CREDIT_ALLOCATION_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_COMPLIANCE_REPORT_NOT_FOUND` or `ERR_INSPECTION_NOT_FOUND`."
        PRD: "When it fails to resolve, the response is that entity's own 404 rather than a generic one, so that a client can tell which record is missing."

        Design: Corner/entities/unknown_path_ids_return_the_entity_specific_not_found_code_for_all_fourteen_entities
        """
        seen = {}
        for entity in types.ALL_ENTITIES:
            response = api.get_by_entity(
                entity, constants.MISSING_UUID_A, ALLOCATION_OFFICER
            )
            expected = types.NOT_FOUND_BY_ENTITY[entity]
            error = validate_error(response, expected, 404)
            seen[entity] = error["error_id"]

        assert len(seen) == 14, "all fourteen resource types must be probed"
        assert len(set(seen.values())) == 14, (
            "each entity owns a distinct 404, got {0}".format(seen)
        )

    def test_flat_topology_bond_issue_with_two_bad_foreign_keys_reports_the_first_in_declaration_order(
        self, api
    ):
        """Size a bond issue naming two unresolvable references, then only one.

        A bond issue carries two independent foreign keys, so the pair of calls
        separates declaration order from the mere fact that a 404 happens: with
        both keys bad the development's 404 wins because developments are declared
        first; with the development resolving, the allocation's own 404 surfaces.

        PRD: "When one body carries more than one unresolvable reference, they are resolved in the entity declaration order used in §3 — so a bond-issue creation naming both a bad `project_id` and a bad `volume_cap_allocation_id` returns `ERR_PROJECT_NOT_FOUND`."

        Design: Corner/entities/flat_topology_bond_issue_with_two_bad_foreign_keys_reports_the_first_in_declaration_order
        """
        deal = fixtures.setup_project(api)

        both_bad = api.create_bond_issue(
            deal.developer_headers,
            **factories.bond_issue_payload(
                constants.MISSING_UUID_C, constants.MISSING_UUID_D
            )
        )
        validate_error(both_bad, ApiErrorId.ERR_PROJECT_NOT_FOUND, 404)

        allocation_bad = api.create_bond_issue(
            deal.developer_headers,
            **factories.bond_issue_payload(deal.project_id, constants.MISSING_UUID_D)
        )
        validate_error(allocation_bad, ApiErrorId.ERR_ALLOCATION_NOT_FOUND, 404)

        assert_page(
            api.list_bond_issues(ALLOCATION_OFFICER, project_id=deal.project_id),
            total_count=0,
        )


class TestInitialAndTerminalStates:
    """Where each machine opens, and what a terminal sponsor standing refuses."""

    def test_newly_created_rows_open_in_their_declared_initial_states(self, api):
        """Create one row of four different machines over the same development.

        Four machines declare four different openings, and two of them carry round
        counters that start on opposite sides of one: an allocation opens on
        decision round one, while a certification opens on submission round zero
        because the first submit is what makes it one.

        PRD: "Opens `PENDING` and immediately reserves the requested amount."
        PRD: "Draft the final cost certification. Opens `DRAFT` with a submission round of zero."
        PRD: "Every unit opens in `status` `PROPOSED`."
        PRD: "sets both status axes to their initial values `PLANNING` and `UNRESTRICTED`"

        Design: Corner/state_machines/newly_created_rows_open_in_their_declared_initial_states
        """
        deal = fixtures.setup_project(api)
        fixtures.setup_cap_request(api, deal)
        fixtures.setup_drafted_agreement(api, deal)
        fixtures.setup_drafted_cost_certification(api, deal)
        unit = fixtures.designate_unit(api, deal, unit_number="101")

        assert_fields(
            deal.allocation, "volume_cap_allocation", status="PENDING", decision_round=1
        )
        assert_nulls(
            deal.allocation,
            ("awarded_amount_cents", "expiry_date"),
            "volume_cap_allocation",
        )

        assert_fields(
            deal.agreement, "regulatory_agreement", status="DRAFT", amendment_count=0
        )
        assert_nulls(deal.agreement, ("instrument_number",), "regulatory_agreement")

        assert_fields(
            deal.cost_certification, "cost_certification", status="DRAFT",
            submission_round=0,
        )

        assert_fields(
            unit,
            "unit_restriction",
            status="PROPOSED",
            imputed_household_size=3,
            restricted_rent_cents=109500,
        )

        project = fixtures.read_project(api, deal)
        assert_fields(
            project,
            "project",
            development_status="PLANNING",
            compliance_status="UNRESTRICTED",
        )

    def test_debarred_sponsor_admits_no_further_sanction_action(self, api):
        """Debar a sponsor, then try to debar it again and to reinstate it.

        Debarment is the only terminal standing and the machine declares nothing
        leaving it, so both follow-up actions are refused with the sponsor code —
        the machine owns no state error of its own. The reason recorded by the
        successful debarment survives, and the version proves the refused calls
        wrote nothing at all.

        PRD: "A `DEBAR` action is available from either `ACTIVE` or `SUSPENDED`, records `sanction_reason`, and lands the sponsor in `DEBARRED`, which is terminal — no further sanction action of any kind may follow it."
        PRD: "A sanction action with no outgoing transition from the sponsor's current standing — a suspension of an already-`SUSPENDED` sponsor, or anything at all aimed at a `DEBARRED` one — is refused with `ERR_DEVELOPER_NOT_ACTIVE`, because the sponsor machine has no state error of its own."
        PRD: "Each sanction action increments the sponsor's `version` by 1."

        Design: Corner/state_machines/debarred_sponsor_admits_no_further_sanction_action
        """
        developer = validate_success(
            api.create_developer(ALLOCATION_OFFICER, **factories.developer_payload()), 201
        )
        reason = "material misrepresentation in the application"

        debarred = validate_success(
            api.sanction_developer(
                developer["id"], COMPLIANCE_OFFICER, action="DEBAR", reason=reason
            )
        )
        assert_fields(
            debarred, "developer", status="DEBARRED", sanction_reason=reason, version=2
        )

        replay = api.sanction_developer(
            developer["id"],
            COMPLIANCE_OFFICER,
            action="DEBAR",
            reason="second debarment attempt",
        )
        validate_error(replay, ApiErrorId.ERR_DEVELOPER_NOT_ACTIVE, 409)

        reinstate = api.sanction_developer(
            developer["id"],
            COMPLIANCE_OFFICER,
            action="REINSTATE",
            reason="appeal granted",
        )
        validate_error(reinstate, ApiErrorId.ERR_DEVELOPER_NOT_ACTIVE, 409)

        after = validate_success(api.get_developer(developer["id"], ALLOCATION_OFFICER))
        assert_fields(
            after, "developer", status="DEBARRED", sanction_reason=reason, version=2
        )
