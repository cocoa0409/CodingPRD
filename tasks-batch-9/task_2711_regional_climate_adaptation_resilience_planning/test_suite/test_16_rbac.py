"""The three-step authorization ladder, the scope rule and the shared reads.

PRD 2.1 orders the ladder — authentication, then role recognition, then the
endpoint's own permitted-role list — and PRD 2.5 places all three above path
existence, so every refusal below is decided before the request touches a row.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    EQUITY,
    REVIEWER,
    ApiErrorId,
    all_role_headers,
    api_client,
    asset_link_payload,
    assert_error_envelope,
    assert_fields,
    create_analysis,
    create_asset_link,
    create_capital_program,
    create_harbor,
    create_plan_cycle,
    create_project,
    create_ridge,
    create_screened_project,
    endorsement_payload,
    equity_waiver_payload,
    jurisdiction_payload,
    make_jurisdiction_delegate_headers,
    make_project_sponsor_headers,
    make_role_headers,
    make_unknown_role_headers,
    open_endorsement_round,
    open_engagement,
    project_payload,
    ranked_asset_context,
    read_analysis,
    read_project,
    ridge_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


class TestAuthenticationRunsFirst:
    """A request with no identity is refused before existence is even considered."""

    def test_a_headerless_read_of_an_unknown_id_is_401_and_not_404(self):
        """The missing header pair beats the unresolvable path identifier.

        PRD 2.1: "Every request to any endpoint under `/resilience` must carry two
        headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
        role that user is acting in. If either header is missing or present but empty,
        the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything
        else is examined."  PRD 2.5 confirms the ordering by numbering authentication
        priority 1 and "Path existence, left to right" priority 4, and "the **first**
        violated rule short-circuits the request".

        Design: Corner/rbac/missing_x_user_headers_returns_unauthenticated
        """
        response = api_client.get_jurisdiction(NON_EXISTENT, None)

        assert response.status_code == 401, (
            f"an unauthenticated call must answer 401, got {response.status_code}: "
            f"{response.text}"
        )
        assert_error_envelope(response.json(), ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_a_role_without_a_user_id_writes_nothing(self):
        """Half a header pair is still unauthenticated, so no member is admitted.

        PRD 2.1: "If either header is missing or present but empty, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is
        examined."  PRD 2.5 adds that on a violated rule "its error is returned and
        nothing at all is written, not even partially".

        Design: Corner/rbac/missing_x_user_headers_returns_unauthenticated
        """
        response = api_client.create_jurisdiction(
            jurisdiction_payload(), {"X-User-Role": "RegionalAdministrator"}
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        _rows, meta = validate_paginated(api_client.list_jurisdictions(ADMIN()))
        assert meta["total_count"] == 0, (
            f"an unauthenticated write must admit no member, got {meta['total_count']}"
        )


class TestRoleRecognitionRunsBeforePermission:
    """An undeclared role name is refused as unknown, not as unpermitted."""

    def test_a_role_outside_the_declared_six_is_refused_as_unknown(self):
        """ClimateIntern sees ERR_UNKNOWN_ROLE rather than ERR_ROLE_NOT_PERMITTED.

        PRD 2.1: "If both headers are present but `X-User-Role` is not one of the six
        declared roles, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 403). If
        the role is recognised but is not among the roles that the requested endpoint
        permits, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). These
        three checks run in exactly that order, so a caller sending a garbage role to an
        endpoint they would not be allowed to reach anyway sees `ERR_UNKNOWN_ROLE`, not
        `ERR_ROLE_NOT_PERMITTED`."  PRD 2.1 also fixes the roster: "The six roles are
        `RegionalAdministrator`, `HazardAnalyst`, `ProjectSponsor`, `BCAReviewer`,
        `JurisdictionDelegate` and `EquityOfficer`. Their spellings are exact and
        case-sensitive."

        Design: Corner/rbac/unknown_role_header_returns_forbidden
        """
        response = api_client.create_jurisdiction(
            jurisdiction_payload(), make_unknown_role_headers()
        )

        validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE.value, 403)
        _rows, meta = validate_paginated(api_client.list_jurisdictions(ADMIN()))
        assert meta["total_count"] == 0, (
            f"an unrecognised role must admit no member, got {meta['total_count']}"
        )


class TestWritesStayExclusiveWhileReadsAreShared:
    """An analyst may read the capital program it can neither open nor fund."""

    def test_two_administrator_only_writes_are_refused_to_a_hazard_analyst(self):
        """Admission and the clock are both closed to the analyst, but the read is open.

        PRD 2.1: "If the role is recognised but is not among the roles that the
        requested endpoint permits, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."  PRD 4 assigns both writes to one role:
        admitting a member government and moving the logical clock are listed as
        `RegionalAdministrator` operations, while "Read access is deliberately broad:
        every retrieval endpoint in the system is open to all six roles, so an analyst
        can see the funding consequences of a republication and a delegate can see how a
        neighbour's assets were ranked" (PRD 2.1).  Since PRD 2.4 says the clock "never
        advances on its own", a refused clock call leaves later writes on the boot
        instant.

        Design: Corner/rbac/hazard_analyst_cannot_create_a_jurisdiction_or_allocate_capital
        """
        harbor = create_harbor()
        program = create_capital_program()

        admission = api_client.create_jurisdiction(ridge_payload(), ANALYST())
        clock = api_client.set_clock("2026-10-01T00:00:00Z", ANALYST())

        validate_error(admission, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        validate_error(clock, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        readable = validate_success(
            api_client.get_capital_program(program["id"], ANALYST()), 200
        )
        assert_fields(
            readable,
            {"id": program["id"], "authorized_cents": 60000000},
            "the program the analyst may read",
        )
        _rows, meta = validate_paginated(api_client.list_jurisdictions(ANALYST()))
        assert meta["total_count"] == 1, (
            f"the refused admission left only Harbor on the register, got {meta['total_count']}"
        )
        later = create_project(create_plan_cycle()["id"], harbor["id"])
        assert later["created_at"] == harbor["created_at"], (
            "the refused clock call cannot have moved the logical now, expected "
            f"{harbor['created_at']!r}, got {later['created_at']!r}"
        )

    def test_screening_and_linking_cannot_cross_between_their_owning_roles(self):
        """The sponsor cannot screen and the administrator cannot link.

        PRD 4 splits the two acts between two roles, and PRD 3.5 confirms
        "**Screening** is a `RegionalAdministrator` act, and it is where the project
        first acquires a price", while PRD 3.6 confirms "A `ProjectSponsor` attributes
        benefit by linking the project to an asset".  Either crossing is refused by PRD
        2.1's third check: "If the role is recognised but is not among the roles that the
        requested endpoint permits, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/screening_and_asset_linking_cannot_cross_between_their_owning_roles
        """
        context = ranked_asset_context()
        harbor_id = context["harbor"]["id"]
        cycle = create_plan_cycle()
        project = create_project(cycle["id"], harbor_id)
        sponsor = make_project_sponsor_headers(harbor_id)
        payload = asset_link_payload(
            context["asset"]["id"], 3333333, benefit_reaches_disadvantaged=True
        )

        sponsor_screening = api_client.screen_project(project["id"], sponsor)

        validate_error(sponsor_screening, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        assert_fields(
            read_project(project["id"]),
            {"screening_status": "PROPOSED", "version": project["version"]},
            "the project the sponsor could not screen",
        )

        screened = validate_success(api_client.screen_project(project["id"], ADMIN()), 200)
        assert_fields(screened, {"screening_status": "SCREENED_IN"}, "the screened project")

        administrator_linking = api_client.create_asset_link(project["id"], payload, ADMIN())

        validate_error(administrator_linking, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        link = validate_success(
            api_client.create_asset_link(project["id"], payload, sponsor), 201
        )
        assert_fields(
            link,
            {"avoided_loss_annual_cents": 3333333, "link_sequence": 1},
            "the link only the sponsor could write",
        )

    def test_only_the_equity_officer_may_waive_the_equity_floor(self):
        """The sponsor and the administrator are both refused the waiver.

        PRD 2.10: "The party who may **waive the equity floor** is a third role again,
        `EquityOfficer`, which can neither prepare nor certify an analysis and cannot
        allocate capital. Only that role may set a project's `equity_waiver_granted`, and
        the waiver request must carry a `waiver_rationale` explaining it."  PRD 3.7 adds
        what the waiver does and does not do: "The request carries a `waiver_rationale`
        recording why the exception is justified, sets `equity_waiver_granted` to true on
        the project, and increments the project's `version` by 1", which leaves the
        programming dimension exactly where PRD 3.5 put it.

        Design: Corner/rbac/equity_waiver_is_forbidden_to_every_role_but_the_equity_officer
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=0)
        project = create_screened_project(cycle["id"], harbor["id"])
        assert_fields(project, {"equity_waiver_granted": False}, "the project before any waiver")

        by_sponsor = api_client.grant_equity_waiver(
            project["id"],
            equity_waiver_payload(waiver_rationale="Sponsor asserts an equity case."),
            make_project_sponsor_headers(harbor["id"]),
        )
        by_administrator = api_client.grant_equity_waiver(
            project["id"],
            equity_waiver_payload(waiver_rationale="Administrator asserts an equity case."),
            ADMIN(),
        )

        validate_error(by_sponsor, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        validate_error(by_administrator, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        assert_fields(
            read_project(project["id"]),
            {"equity_waiver_granted": False, "version": project["version"]},
            "the project neither refusal touched",
        )

        waived = validate_success(
            api_client.grant_equity_waiver(project["id"], equity_waiver_payload(), EQUITY()), 200
        )

        assert_fields(
            waived,
            {
                "equity_waiver_granted": True,
                "program_status": "UNPROGRAMMED",
                "version": project["version"] + 1,
            },
            "the waived project",
        )


class TestTheScopeRuleReadsTheTargetRow:
    """An entity-backed role may only act for the jurisdiction its identifier names."""

    def test_a_delegate_cannot_cast_another_members_endorsement(self):
        """Ridge's delegate is refused Harbor's vote; Harbor's own delegate casts it.

        PRD 2.1: "For the two entity-backed roles — `ProjectSponsor` and
        `JurisdictionDelegate` — a write whose target row belongs to a different
        jurisdiction than the one `X-User-ID` resolves to is rejected with
        `ERR_JURISDICTION_SCOPE_VIOLATION` (HTTP 403)."  PRD 2.5, priority 6, names the
        field compared: "For a `JurisdictionDelegate` it is the endorsement's
        `jurisdiction_id`, the engagement session's `host_jurisdiction_id`, the mutual aid
        pact's `host_jurisdiction_id`, or the mutual aid commitment's
        `requesting_jurisdiction_id`, whichever the endpoint targets."  The accepted cast
        then follows PRD 3.8: it "is stamped with `round_number` copied from the cycle's
        current round, `cast_at` from the logical clock, and `weight_at_cast` **frozen**
        from the casting jurisdiction's `endorsement_weight` at that instant."

        Design: Corner/rbac/delegate_cannot_endorse_for_another_jurisdiction
        """
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = create_plan_cycle(required_session_count=0)
        create_screened_project(cycle["id"], harbor["id"])
        open_engagement(cycle["id"])
        open_endorsement_round(cycle["id"])
        payload = endorsement_payload(harbor["id"], decision="ENDORSED")

        refused = api_client.cast_endorsement(
            cycle["id"], payload, make_jurisdiction_delegate_headers(ridge["id"])
        )

        validate_error(refused, ApiErrorId.ERR_JURISDICTION_SCOPE_VIOLATION.value, 403)

        accepted = api_client.cast_endorsement(
            cycle["id"], payload, make_jurisdiction_delegate_headers(harbor["id"])
        )

        endorsement = validate_success(accepted, 201)
        assert_fields(
            endorsement,
            {
                "jurisdiction_id": harbor["id"],
                "decision": "ENDORSED",
                "weight_at_cast": 4,
                "round_number": 1,
            },
            "the endorsement Harbor's own delegate cast",
        )
        _rows, meta = validate_paginated(
            api_client.list_endorsements(ADMIN(), params={"plan_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 1, (
            f"only the in-scope cast was recorded, got {meta['total_count']}"
        )

    def test_a_sponsor_cannot_propose_a_project_for_another_member(self):
        """The scope check reads the body's jurisdiction_id, not just the header.

        PRD 2.1: "When `X-User-Role` is `ProjectSponsor`, `X-User-ID` is the `id` of the
        acting `Jurisdiction`; ownership checks on any adaptation project compare the
        project's `jurisdiction_id` to `X-User-ID`, and a caller may only act on projects
        whose `jurisdiction_id` equals that value."  The refusal code is PRD 2.1's "a
        write whose target row belongs to a different jurisdiction than the one
        `X-User-ID` resolves to is rejected with `ERR_JURISDICTION_SCOPE_VIOLATION` (HTTP
        403)", and PRD 3.5 fixes the accepted row's standing: "A freshly proposed project
        reads `screening_status` `PROPOSED`."

        Design: Corner/rbac/sponsor_cannot_create_a_project_for_another_jurisdiction
        """
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = create_plan_cycle()
        payload = project_payload(
            cycle["id"], ridge["id"], name="Ridge Culvert Upsizing", hazard_type="FLOOD",
            strategy_type="ACCOMMODATE", base_cost_cents=30000000, service_life_years=25,
            cobenefit_points=10, feasibility_score=0.65,
        )

        refused = api_client.create_project(payload, make_project_sponsor_headers(harbor["id"]))

        validate_error(refused, ApiErrorId.ERR_JURISDICTION_SCOPE_VIOLATION.value, 403)
        _rows, meta = validate_paginated(api_client.list_projects(ADMIN()))
        assert meta["total_count"] == 0, (
            f"the out-of-scope proposal wrote nothing, got {meta['total_count']} projects"
        )

        accepted = api_client.create_project(
            payload, make_project_sponsor_headers(ridge["id"])
        )

        project = validate_success(accepted, 201)
        assert_fields(
            project,
            {"jurisdiction_id": ridge["id"], "screening_status": "PROPOSED"},
            "the project Ridge's own sponsor proposed",
        )


class TestSegregationOfDutiesIsCheckedOnTheUser:
    """The preparer cannot clear their own case in either direction."""

    def test_the_preparer_can_neither_certify_nor_reject_their_own_case(self):
        """Both reviewer verbs are closed to the preparing identifier and open to another.

        PRD 2.10: "When an analysis is created, the acting user's `X-User-ID` is recorded
        on the analysis as `prepared_by_user_id`. When a reviewer later certifies or
        rejects that analysis, the server compares the reviewer's `X-User-ID` against
        `prepared_by_user_id`; if they are equal the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The rule applies equally to certification
        and to rejection — a preparer cannot self-clear an analysis by rejecting it
        either. On a successful certification the reviewer's identifier is recorded as
        `certified_by_user_id`."  PRD 3.6 supplies the certified figures, since
        "`benefit_measure_cents` is the exact integer sum of every link's
        `avoided_loss_annual_cents`" against a cost of 1709120 plus 1025472.

        Design: Corner/rbac/reviewer_cannot_certify_an_analysis_they_prepared
        """
        context = ranked_asset_context()
        harbor_id = context["harbor"]["id"]
        cycle = create_plan_cycle(required_session_count=0)
        project = create_screened_project(cycle["id"], harbor_id)
        create_asset_link(
            project["id"], harbor_id, context["asset"]["id"], 3333333,
            benefit_reaches_disadvantaged=True,
        )
        analysis = create_analysis(
            project["id"], harbor_id, method="ANNUALIZED_EQUIVALENT", discount_rate_bps=None
        )
        assert_fields(
            analysis,
            {"prepared_by_user_id": harbor_id, "status": "DRAFT"},
            "the case the sponsor prepared",
        )

        self_certify = api_client.certify_analysis(
            analysis["id"], make_role_headers("BCAReviewer", harbor_id)
        )
        self_reject = api_client.reject_analysis(
            analysis["id"], make_role_headers("BCAReviewer", harbor_id)
        )

        validate_error(self_certify, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        validate_error(self_reject, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        assert_fields(
            read_analysis(analysis["id"]),
            {"status": "DRAFT", "version": 1, "certified_by_user_id": None},
            "the case the preparer could not clear",
        )

        response = api_client.certify_analysis(analysis["id"], REVIEWER("reviewer-01"))

        certified = validate_success(response, 200)
        assert_fields(
            certified,
            {
                "status": "CERTIFIED",
                "certified_by_user_id": "reviewer-01",
                "bcr": 1.2190,
                "grant_eligible": True,
                "version": 2,
            },
            "the case an independent reviewer certified",
        )


class TestEveryRoleMayReadEveryCollection:
    """Read access is shared across all six declared roles."""

    def test_all_six_roles_receive_the_same_collection(self):
        """Six header sets, six 200s, one identical total_count.

        PRD 2.1: "Read access is deliberately broad: every retrieval endpoint in the
        system is open to all six roles, so an analyst can see the funding consequences
        of a republication and a delegate can see how a neighbour's assets were ranked."
        PRD 4 spells the roster out for the list endpoints: "In the Authorized Role(s)
        column, **All roles** means all six roles named in §2.1: `RegionalAdministrator`,
        `HazardAnalyst`, `ProjectSponsor`, `BCAReviewer`, `JurisdictionDelegate` and
        `EquityOfficer`."

        Design: Corner/rbac/every_role_may_read_every_collection
        """
        harbor = create_harbor()
        headers_by_role = all_role_headers(harbor["id"])
        assert len(headers_by_role) == 6, (
            f"PRD 2.1 declares exactly six roles, got {sorted(headers_by_role)}"
        )

        for role, headers in headers_by_role.items():
            response = api_client.list_jurisdictions(headers)
            rows, meta = validate_paginated(response)
            assert response.json()["response_type"] == "array", (
                f"{role} must receive an array envelope, got "
                f"{response.json()['response_type']!r}"
            )
            assert meta["total_count"] == 1, (
                f"{role} must see the whole register, got {meta['total_count']}"
            )
            assert [row["id"] for row in rows] == [harbor["id"]], (
                f"{role} must see Harbor itself, got {rows}"
            )
