"""The header-driven access surface and the family list endpoints (PRD §2.1, §2.3, §4).

Six roles share fourteen entity families here, and the interesting failures are the
ones that are easy to conflate: an absent header is not a forbidden role, a forbidden
role is not a failed ownership check, and a peer of the same role is still a stranger.
The positive half matters too — a read four roles are entitled to must come back
field-for-field identical — and every list endpoint must filter on its own declared
foreign key rather than on a shared one.
"""

from test_helpers import (
    ALLOCATION_OFFICER,
    ALLOCATION_OFFICER_USER_ID,
    COMPLIANCE_OFFICER,
    SYSTEM_OPERATOR,
    TRUSTEE,
    ApiErrorId,
    assert_fields,
    assert_ids_equal,
    assert_nulls,
    assert_page,
    constants,
    factories,
    fixtures,
    make_developer_headers,
    make_headers_without_role,
    make_investor_headers,
    validate_error,
    validate_success,
)


class TestTheTwoFourZeroThreeFamilies:
    """An absent role, a foreign sponsor, and the one call that is allowed to land."""

    def test_missing_role_header_is_unauthenticated_and_a_foreign_sponsor_is_not_the_owner(
        self, api
    ):
        """One development, two sponsors, and three refusals that must not be confused.

        A read carrying an identifier but no role at all is refused at the first gate,
        before the development is looked up, so it can be neither a 403 nor a 404 and the
        row is never disclosed. The two ownership probes are the sharper half: the caller
        holds the `Developer` role, which *is* on both endpoints' role lists, so the only
        thing that fails is the ownership comparison — designating a unit on somebody
        else's development and filing a development under somebody else's `developer_id`
        both return `ERR_NOT_RESOURCE_OWNER` rather than `ERR_FORBIDDEN_ROLE`. Neither
        refusal leaves a row behind, which the owner's own designation then proves by
        becoming the development's first and only unit.

        PRD: "A missing or blank header of either kind is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before the service so much as looks up the entity named in the path. A well-formed but unauthorized caller receives `ERR_FORBIDDEN_ROLE` (HTTP 403); a caller acting on somebody else's resource receives `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD: "**Caller owns the resource.** For a `Developer` caller the target must resolve to a `Project` whose `developer_id` equals `X-User-ID`; for an `Investor` caller the target `InvestorDelivery`'s `investor_id` must equal `X-User-ID`. Violation is `ERR_NOT_RESOURCE_OWNER`."
        PRD: "A `Developer` files a development by supplying its own `developer_id` — which must equal `X-User-ID`, and a mismatch is `ERR_NOT_RESOURCE_OWNER`"

        Design: Corner/errors/missing_role_header_is_unauthenticated_and_a_foreign_sponsor_is_not_the_resource_owner
        """
        deal = fixtures.setup_project(api)
        foreign = fixtures.register_second_developer(api)
        foreign_headers = make_developer_headers(foreign["id"])

        validate_error(
            api.get_project(
                deal.project_id, make_headers_without_role(deal.developer_id)
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

        unit_spec = dict(factories.COMPACT_ROSTER[0], project_id=deal.project_id)
        validate_error(
            api.create_unit_restriction(foreign_headers, **unit_spec),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.create_project(
                foreign_headers,
                **factories.compact_project_payload(
                    deal.developer_id, name="Poached Filing", total_units=2,
                    total_floor_space_sqft=1600, land_cost_cents=10000000,
                    depreciable_basis_cents=90000000,
                )
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )

        unit = validate_success(
            api.create_unit_restriction(deal.developer_headers, **unit_spec), 201
        )
        assert_fields(
            unit,
            "unit_101",
            designation="RESTRICTED",
            restricted_rent_cents=109500,
        )
        assert_fields(
            fixtures.read_project(api, deal), "project", designated_unit_count=1
        )
        assert_fields(
            validate_success(api.get_developer(foreign["id"], ALLOCATION_OFFICER)),
            "foreign_developer",
            active_project_count=0,
        )


class TestRoleExclusivity:
    """Four exclusive operations reached for by the wrong desk, then by the right one."""

    def test_each_role_cannot_reach_another_roles_exclusive_operation(self, api):
        """A cross-product denial sweep over the four writing roles and the operator.

        Each refusal here is decided on the role alone, before ownership and before any
        state rule: the sponsor owns the development but may not sign its own award, the
        trustee may not record the covenant, the allocation desk may not sanction a
        sponsor, and the compliance desk may not touch the clock. The two cells worth
        pointing at are the `SystemOperator`, which holds no business permission at all
        and so cannot even read a development, and the trustee, whose read surface simply
        does not include the compliance families. The rightful officer then signs the very
        award that was refused first, which proves the sweep left no partial state.

        PRD: "**Role is permitted for the endpoint.** The `X-User-Role` value must appear in that endpoint's authorized-role list, and this is checked before existence — so an `HfaComplianceOfficer` deciding a cap allocation whose id does not exist receives `ERR_FORBIDDEN_ROLE`, not a 404."
        PRD: "When `X-User-Role` is `SystemOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and not compared to any entity's `id`; this identity owns the logical clock and holds no business permission on any domain endpoint."
        PRD: "When `X-User-Role` is `BondTrustee`, `X-User-ID` is an opaque operator identifier that the server may record but never compares to any entity's `id`; the trustee closes the issue, approves, funds and voids construction draws, converts to permanent financing and executes mandatory redemption, and touches nothing else."

        Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_the_operator_cannot_read_a_project
        """
        deal = fixtures.setup_drafted_agreement(api)
        allocation = fixtures.request_cap(api, deal)
        assert_fields(allocation, "allocation", status="PENDING")
        award = dict(
            decision="AWARD",
            awarded_amount_cents=200000000,
            expiry_date=constants.AWARD_EXPIRY_DATE,
            expected_cap_pool_version=fixtures.pool_version(api, deal),
        )

        validate_error(
            api.decide_volume_cap_allocation(
                allocation["id"], deal.developer_headers, **award
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.record_regulatory_agreement(
                deal.agreement_id, TRUSTEE,
                instrument_number=constants.INSTRUMENT_NUMBER,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.sanction_developer(
                deal.developer_id, ALLOCATION_OFFICER,
                action="SUSPEND", reason="allocation officer overreach",
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.set_clock("2030-01-01T00:00:00Z", COMPLIANCE_OFFICER),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.get_project(deal.project_id, SYSTEM_OPERATOR),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.list_compliance_reports(TRUSTEE),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )

        untouched = validate_success(
            api.get_volume_cap_allocation(allocation["id"], ALLOCATION_OFFICER)
        )
        assert_fields(untouched, "allocation", status="PENDING")
        assert_nulls(
            untouched, ("awarded_amount_cents", "decided_by_user_id"), "allocation"
        )
        agreement = validate_success(
            api.get_regulatory_agreement(deal.agreement_id, COMPLIANCE_OFFICER)
        )
        assert_fields(agreement, "agreement", status="DRAFT")
        assert_nulls(agreement, ("instrument_number", "recorded_date"), "agreement")
        assert_fields(
            fixtures.read_developer(api, deal), "developer", status="ACTIVE"
        )

        decided = validate_success(
            api.decide_volume_cap_allocation(
                allocation["id"], ALLOCATION_OFFICER, **award
            )
        )
        assert_fields(
            decided,
            "allocation",
            status="AWARDED",
            awarded_amount_cents=200000000,
            decided_by_user_id=ALLOCATION_OFFICER_USER_ID,
        )


class TestTheSharedRead:
    """The positive half of the surface: one read, four entitled roles, one body."""

    def test_project_read_is_shared_by_the_sponsor_the_two_desks_and_the_trustee(
        self, api
    ):
        """The same development read by every role that lists it, compared field for field.

        `GET /projects/{id}` names four roles, and a shared read must not be narrowed or
        masked by the caller's identity: the trustee sees the sponsor's own applicable
        fraction, and the compliance desk sees the same version the sponsor sees. Two
        restricted units of four is 5,000 basis points and 1,700 of 3,400 square feet is
        also 5,000, so the applicable fraction is unambiguous. The list form is then
        exercised by two of those roles under the same filter to show the sponsor's write
        scope does not leak into a read scope.

        PRD: "Fetch one development with both status axes, the derived unit-designation counts, the applicable fraction, the set-aside ratio and both fifty-percent-test ratios. | Developer, HfaAllocationOfficer, HfaComplianceOfficer, BondTrustee"
        PRD: "This scope covers the developer-scoped and investor-scoped endpoints only; the agency and trustee roles are exempt."
        PRD: "List developments, optionally narrowed to one sponsor or one development status. Ordered by `created_at` ascending. | Developer, HfaAllocationOfficer, HfaComplianceOfficer, BondTrustee"

        Design: Corner/rbac/project_read_is_shared_by_the_sponsor_the_two_agency_desks_and_the_trustee_with_identical_bodies
        """
        deal = fixtures.setup_units(api)

        bodies = [
            validate_success(api.get_project(deal.project_id, headers))
            for headers in (
                deal.developer_headers,
                ALLOCATION_OFFICER,
                COMPLIANCE_OFFICER,
                TRUSTEE,
            )
        ]
        for body in bodies:
            assert_fields(
                body,
                "project",
                id=deal.project_id,
                name=constants.COMPACT_PROJECT_NAME,
                development_status="PLANNING",
                compliance_status="UNRESTRICTED",
                set_aside_election="MIN_40_60",
                designated_unit_count=4,
                restricted_unit_count=2,
                applicable_fraction_bps=5000,
            )
        for other in bodies[1:]:
            assert other == bodies[0], (
                "every role entitled to read a development must receive an identical "
                "body: {0} differs from the sponsor's".format(other)
            )

        for headers in (TRUSTEE, deal.developer_headers):
            items, _ = assert_page(
                api.list_projects(
                    headers,
                    developer_id=deal.developer_id,
                    development_status="PLANNING",
                ),
                total_count=1,
                has_more=False,
            )
            assert_ids_equal(items, [deal.project_id], "projects")


class TestPeerConfinement:
    """A second investor and a second sponsor, each holding exactly the right role."""

    def test_peer_confinement_refuses_a_second_investor_and_a_second_sponsor(self, api):
        """One open delivery, reached for by two strangers who are peers of its owners.

        Both callers hold the role their endpoint names, so nothing but the ownership
        comparison stands between them and someone else's credit strip. The rescission
        probe is the sharp one, because a delivery carries no sponsor column at all: the
        owning sponsor is resolved transitively through the credit allocation to the
        development, so an implementation that only compares `investor_id` would let an
        unrelated sponsor claw the strip back. The rightful investor then accepts the same
        delivery, which shows the obstacle was ownership and not the delivery's state, and
        the price prints at 8,500 basis points — 25,500,000 of capital over 30,000,000 of
        credit.

        PRD: "When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor` entity; an `InvestorDelivery` may be acted on only when its `investor_id` equals `X-User-ID`, and a mismatch is `ERR_NOT_RESOURCE_OWNER`."
        PRD: "An `Investor` is the tax-credit investor or syndicator that accepts delivered credit strips; it can accept a delivery but can neither create nor rescind one."
        PRD: "`price_per_credit_dollar_bps` is then the `capital_contribution_cents` multiplied by 10,000, divided by the clamped `delivered_credit_cents`, floored — which is precisely why a stale allocation version is refused rather than re-priced."

        Design: Corner/rbac/peer_confinement_refuses_a_second_investor_on_a_delivery_and_a_second_sponsor_on_a_foreign_project
        """
        deal = fixtures.setup_delivered_credit(api)
        foreign_investor = fixtures.register_second_investor(api)
        foreign_sponsor = fixtures.register_second_developer(api)
        foreign_investor_headers = make_investor_headers(foreign_investor["id"])
        foreign_sponsor_headers = make_developer_headers(foreign_sponsor["id"])

        validate_error(
            api.accept_investor_delivery(deal.delivery_id, foreign_investor_headers),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.rescind_investor_delivery(
                deal.delivery_id,
                foreign_sponsor_headers,
                rescind_reason="clawback by an unrelated sponsor",
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            api.create_unit_restriction(
                foreign_sponsor_headers,
                project_id=deal.project_id,
                unit_number="301",
                bedroom_count=1,
                floor_space_sqft=500,
                designation="MARKET",
                utility_allowance_cents=10000,
                market_rent_cents=180000,
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        assert_page(
            api.list_unit_restrictions(
                deal.developer_headers, project_id=deal.project_id
            ),
            total_count=4,
        )

        open_delivery = validate_success(
            api.get_investor_delivery(deal.delivery_id, deal.developer_headers)
        )
        assert_fields(open_delivery, "delivery", status="DELIVERED")
        assert_nulls(open_delivery, ("accepted_at", "rescind_reason"), "delivery")

        accepted = validate_success(
            api.accept_investor_delivery(deal.delivery_id, deal.investor_headers)
        )
        assert_fields(
            accepted,
            "delivery",
            status="ACCEPTED",
            delivered_credit_cents=30000000,
            price_per_credit_dollar_bps=8500,
        )
        assert_fields(
            fixtures.read_credit_allocation(api, deal),
            "credit_allocation",
            delivered_credit_cents=30000000,
            undelivered_credit_cents=41000000,
        )
        assert_fields(
            validate_success(
                api.get_investor(foreign_investor["id"], ALLOCATION_OFFICER)
            ),
            "foreign_investor",
            total_credit_accepted_cents=0,
        )


class TestEveryFamilyList:
    """Seven list families, each filtering on the foreign key it declares for itself."""

    def test_every_family_list_endpoint_filters_by_its_own_foreign_key_and_status(
        self, api
    ):
        """Two developments on one pool, so an ignored filter cannot pass by accident.

        Every family declares a different filter — draws hang off the bond issue,
        credit allocations off the certification as well as the development, bond issues
        off the cap allocation as well as the development — and each status filter is
        matched against that family's own enum. The second development holds nothing but a
        pending cap request, so every unfiltered list has a row that the filtered one must
        drop; a filter that were silently ignored would report the same `total_count` as no
        filter at all. The status probes deliberately land on states reached late in the
        lifecycle — `COMMITTED`, `CONVERTED`, `FUNDED`, `ACCEPTED` — so a filter compared
        against an initial state cannot agree by coincidence, and the paging probe shows
        `total_count` reports the filtered population rather than the page.

        PRD: "Every list endpoint accepts two optional query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. Both are echoed in `meta`, alongside `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."
        PRD: "List bond issues, optionally narrowed to one development, one volume cap allocation or one status. Ordered by `created_at` ascending."
        PRD: "List construction draws, optionally narrowed to one bond issue or one status. Ordered by `period_start` ascending then `draw_number` ascending, the same order the negative-arbitrage series uses."
        PRD: "List final credit allocations, optionally narrowed to one development, one cost certification or one status. Ordered by `created_at` ascending."
        PRD: "List physical inspections, optionally narrowed to one development or status. Ordered by `window_start` ascending."

        Design: Corner/endpoints/every_family_list_endpoint_filters_by_its_own_foreign_key_and_status_and_paginates_independently
        """
        deal = fixtures.setup_credit_allocation(api)
        fixtures.setup_converted_bond(api, deal)
        inspection = fixtures.schedule_inspection(api, deal)
        assert_fields(inspection, "inspection", status="SCHEDULED")

        sibling = fixtures.file_second_project(api, deal, name="Bayside Two")
        sibling_request = validate_success(
            api.create_volume_cap_allocation(
                deal.developer_headers,
                **factories.cap_request_payload(
                    sibling["id"], deal.pool_id, requested_amount_cents=50000000
                )
            ),
            201,
        )
        assert_fields(sibling_request, "sibling_request", status="PENDING")

        items, _ = assert_page(
            api.list_volume_cap_allocations(
                ALLOCATION_OFFICER, cap_pool_id=deal.pool_id
            ),
            total_count=2,
            has_more=False,
            limit=10,
            offset=0,
        )
        assert_ids_equal(
            items, [deal.allocation_id, sibling_request["id"]], "cap_allocations"
        )

        items, _ = assert_page(
            api.list_volume_cap_allocations(
                ALLOCATION_OFFICER, cap_pool_id=deal.pool_id, status="COMMITTED"
            ),
            total_count=1,
        )
        assert_ids_equal(items, [deal.allocation_id], "committed_cap_allocations")

        items, _ = assert_page(
            api.list_volume_cap_allocations(
                ALLOCATION_OFFICER, cap_pool_id=deal.pool_id, limit=1, offset=1
            ),
            total_count=2,
            has_more=False,
            limit=1,
            offset=1,
        )
        assert_ids_equal(items, [sibling_request["id"]], "second_page")

        items, _ = assert_page(
            api.list_bond_issues(
                ALLOCATION_OFFICER,
                volume_cap_allocation_id=deal.allocation_id,
                status="CONVERTED",
            ),
            total_count=1,
        )
        assert_ids_equal(items, [deal.bond_issue_id], "bond_issues")
        empty, _ = assert_page(
            api.list_bond_issues(ALLOCATION_OFFICER, project_id=sibling["id"]),
            total_count=0,
            has_more=False,
        )
        assert empty == [], (
            "a list with no matching rows must be an empty data array, not a 404: "
            "{0}".format(empty)
        )

        items, _ = assert_page(
            api.list_draw_requests(
                TRUSTEE, bond_issue_id=deal.bond_issue_id, status="FUNDED"
            ),
            total_count=1,
        )
        assert_ids_equal(items, [deal.draw_id(1)], "funded_draws")
        assert_page(
            api.list_draw_requests(
                TRUSTEE, bond_issue_id=deal.bond_issue_id, status="SUBMITTED"
            ),
            total_count=0,
            has_more=False,
        )

        items, _ = assert_page(
            api.list_regulatory_agreements(
                COMPLIANCE_OFFICER, project_id=deal.project_id, status="RECORDED"
            ),
            total_count=1,
        )
        assert_ids_equal(items, [deal.agreement_id], "agreements")

        items, _ = assert_page(
            api.list_cost_certifications(
                ALLOCATION_OFFICER, project_id=deal.project_id, status="ACCEPTED"
            ),
            total_count=1,
        )
        assert_ids_equal(items, [deal.cost_certification_id], "cost_certifications")

        items, _ = assert_page(
            api.list_credit_allocations(
                ALLOCATION_OFFICER,
                cost_certification_id=deal.cost_certification_id,
                status="PENDING",
            ),
            total_count=1,
        )
        assert_ids_equal(items, [deal.credit_allocation_id], "credit_allocations")

        items, _ = assert_page(
            api.list_physical_inspections(
                COMPLIANCE_OFFICER, project_id=deal.project_id, status="SCHEDULED"
            ),
            total_count=1,
        )
        assert_ids_equal(items, [inspection["id"]], "inspections")
        assert_page(
            api.list_physical_inspections(
                COMPLIANCE_OFFICER, project_id=sibling["id"]
            ),
            total_count=0,
            has_more=False,
            limit=10,
            offset=0,
        )
