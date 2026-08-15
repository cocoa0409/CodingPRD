"""Agency onboarding, agent certification lifecycle, auth, and agent RBAC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_agency,
    assert_agent,
    certify_agent,
    create_agency,
    create_agency_payload,
    create_agent_payload,
    create_contract,
    create_draft_proposal,
    fresh_cap_season,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_agency_manager_headers,
    make_agent_headers,
    register_agent,
    setup_agency_with_manager_and_agent,
    setup_negotiation_env,
    make_team_headers,
    submit_proposal,
    validate_error,
    validate_success,
)

LEAGUE = TEST_USERS["league_officer_headers"]


class TestAgencyCreation:
    def test_agency_creation_returns_defaults(self, api):
        """PRD §3.1: "A new agency begins `ACTIVE`."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
        `created_at` field is an ISO 8601 UTC timestamp with three fractional
        digits recording when the resource was created."

        Design: Corner/entities/agency_creation_returns_defaults
        """
        resp = api.create_agency(create_agency_payload(name="DefaultCo", fee_cap_pct=0.03),
                                 LEAGUE)
        agency = validate_success(resp, 201)
        assert_agency(agency)
        assert agency["status"] == "ACTIVE", "A new agency begins ACTIVE"
        assert is_valid_uuid(agency["id"]), "id is a server-minted UUID"
        assert is_iso8601_timestamp(agency["created_at"]), "created_at populated"
        assert isinstance(agency["version"], int)

    def test_agency_creation_missing_required_field_returns_400(self, api):
        """PRD §3.1: "A `LeagueOfficer` founds an agency by supplying its legal
        `name` and its `fee_cap_pct`, the maximum agent fee expressed as a
        fraction of a contract's average annual value — 0.03 for a three-percent
        cap — configured per agency within league limits."
        PRD §5: "`ERR_INVALID_REQUEST` | 400" is the catalogue's only 400.

        Design: Corner/entities/agency_creation_missing_required_field_returns_400
        """
        resp = api.create_agency({"name": "NoFee"}, LEAGUE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestAgentBasics:
    def test_agent_get_returns_stored_entity(self, api):
        """PRD §3.1: "Every agent begins in `PENDING` certification."
        PRD §3.1: "an `AgencyManager` registers agents with a `full_name`, a
        contact `email` that must be unique within the agency, the league-issued
        `cert_number`, and an optional `is_manager` flag — defaulting to false —
        that marks agents empowered to certify colleagues and resolve roster
        matters."

        Design: Corner/entities/agent_get_returns_stored_entity
        """
        agency = create_agency(fee_cap_pct=0.05, name="FetchCo")
        agent = validate_success(
            api.create_agent(agency["id"],
                             create_agent_payload(full_name="Gettable",
                                                  email="g@f.example",
                                                  cert_number="GET-1"),
                             TEST_USERS["agency_manager_headers"]),
            201)
        fetched = validate_success(api.get_agent(agency["id"], agent["id"], LEAGUE))
        assert_agent(fetched)
        assert fetched["full_name"] == "Gettable"
        assert fetched["cert_status"] == "PENDING"
        assert fetched["is_manager"] is False, "is_manager defaults to false"

    def test_get_nonexistent_agent_returns_404(self, api):
        """PRD §2.7: "the request is rejected with `ERR_NOT_FOUND` (404) at the
        first identifier that does not resolve, before any later identifier is
        examined."

        Design: Corner/entities/get_nonexistent_agent_returns_404
        """
        agency = create_agency(fee_cap_pct=0.05, name="404Co")
        resp = api.get_agent(agency["id"], NON_EXISTENT_UUID, LEAGUE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_agent_is_manager_default_false(self, api):
        """PRD §3.1: "an `AgencyManager` registers agents with a `full_name`, a
        contact `email` that must be unique within the agency, the league-issued
        `cert_number`, and an optional `is_manager` flag — defaulting to false —
        that marks agents empowered to certify colleagues and resolve roster
        matters."

        Design: Corner/entities/agent_is_manager_default_false
        """
        agency = create_agency(fee_cap_pct=0.05, name="DefAg")
        agent = validate_success(
            api.create_agent(agency["id"],
                             create_agent_payload(full_name="NoMgr",
                                                  email="nm@d.example",
                                                  cert_number="DNM"),
                             TEST_USERS["agency_manager_headers"]),
            201)
        assert agent["is_manager"] is False, "is_manager defaults to false"

    def test_agent_initial_state_is_pending(self, api):
        """PRD §3.1: "Every agent begins in `PENDING` certification."

        Design: Corner/state_machines/agent_initial_state_is_pending
        """
        agency = create_agency(fee_cap_pct=0.03, name="InitCo")
        agent = validate_success(
            api.create_agent(agency["id"],
                             create_agent_payload(full_name="Fresh",
                                                  email="f@i.example",
                                                  cert_number="F1"),
                             TEST_USERS["agency_manager_headers"]),
            201)
        assert agent["cert_status"] == "PENDING", "Every agent begins PENDING"


class TestCertificationLifecycle:
    def test_certify_from_certified_returns_invalid_state(self, api):
        """PRD §3.1: "Certification, a manager's act that moves `cert_status`
        from `PENDING` to `CERTIFIED`, is permitted only while the agency itself
        is `ACTIVE`, and it stamps `certified_at` with the current UTC
        timestamp."
        PRD §2.7: "Fourth, state: the target entity must be in the exact state
        the requested transition demands — a proposal must be in `DRAFT` to be
        submitted, a cap season in `OPEN` to be locked — else `ERR_INVALID_STATE`
        (409)."

        Design: Corner/state_machines/certify_from_certified_returns_invalid_state
        """
        bundle = setup_agency_with_manager_and_agent(name="CertCo")
        agency_id = bundle["agency"]["id"]
        manager_id = bundle["manager"]["id"]
        agent_id = bundle["agent"]["id"]
        resp = api.certify_agent(agency_id, agent_id, make_agency_manager_headers(manager_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestAgentRBAC:
    def test_agent_cannot_certify_another_agent(self, api):
        """PRD §2.1: "When the role is recognized but is not among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_FORBIDDEN` (403)."
        PRD §4: "POST | `/agencies/{agencyId}/agents/{agentId}/certify` |
        Certify a PENDING agent | AgencyManager".

        Design: Corner/rbac/agent_cannot_certify_another_agent
        """
        bundle = setup_agency_with_manager_and_agent(name="RBA")
        agency_id = bundle["agency"]["id"]
        manager_id = bundle["manager"]["id"]
        regular = bundle["agent"]
        target = register_agent(agency_id,
                                acting_headers=make_agency_manager_headers(manager_id))
        resp = api.certify_agent(agency_id, target["id"],
                                 make_agent_headers(regular["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = validate_success(api.get_agent(agency_id, target["id"], LEAGUE))
        assert after["cert_status"] == "PENDING", "failed certify leaves state unchanged"


class TestAgentSuspensionCascade:
    def test_agent_suspend_withdraws_inflight_proposals_and_releases_reserved(self, api):
        """PRD §3.1: "Suspending a `CERTIFIED` agent moves them to `SUSPENDED`
        and immediately withdraws every proposal they authored that sits in
        `SUBMITTED` or `COUNTERED`, releasing the reserved cap space those
        proposals held on the linked cap season."

        Depth-3 cascade: cert_status -> SUSPENDED (level 1) causes each
        in-flight proposal -> WITHDRAWN (level 2) causes reserved_cents to be
        released (level 3).

        Design: Difficulty/transitive_cascade/agent_suspend_cascade_depth3
        """
        env = setup_negotiation_env(agency_name="Cascade Agency")
        # Client 1 + contract + SUBMITTED proposal at 25M
        c1 = env["client"]
        con1 = create_contract(env, base_salary_cents=25_000_000,
                               guaranteed_cents=25_000_000)
        env.setdefault("contract_clients", {})[con1["id"]] = c1["id"]
        p1 = create_draft_proposal(env, con1["id"], proposed_aav_cents=25_000_000,
                                   proposed_guaranteed_cents=25_000_000)
        submit_proposal(env, con1["id"], p1["id"])
        # Client 2 + contract + proposal countered to 30M (COUNTERED state)
        c2 = validate_success(api.create_client(
            env["agency"]["id"],
            {"primary_agent_id": env["agent"]["id"], "full_name": "P2", "position": "SF"},
            make_agent_headers(env["agent"]["id"])), 201)
        con2 = create_contract(env, client_id=c2["id"], base_salary_cents=30_000_000,
                               guaranteed_cents=30_000_000)
        env["contract_clients"][con2["id"]] = c2["id"]
        p2 = create_draft_proposal(env, con2["id"], proposed_aav_cents=32_000_000,
                                   proposed_guaranteed_cents=32_000_000)
        submit_proposal(env, con2["id"], p2["id"])
        p2 = validate_success(api.counter_proposal(
            env["agency"]["id"], c2["id"], con2["id"], p2["id"], 30_000_000,
            make_team_headers(env["team"]["id"])))
        assert p2["status"] == "COUNTERED"
        season_mid = fresh_cap_season(env)
        assert season_mid["reserved_cents"] == 55_000_000, \
            "25M SUBMITTED + 30M COUNTERED reserved before suspension"

        # Trigger: suspend the authoring agent.
        suspended = validate_success(api.suspend_agent(
            env["agency"]["id"], env["agent"]["id"],
            make_agency_manager_headers(env["manager"]["id"])))
        assert suspended["cert_status"] == "SUSPENDED"  # level 1

        p1_after = validate_success(api.get_proposal(
            env["agency"]["id"], c1["id"], con1["id"], p1["id"], LEAGUE))
        p2_after = validate_success(api.get_proposal(
            env["agency"]["id"], c2["id"], con2["id"], p2["id"], LEAGUE))
        assert p1_after["status"] == "WITHDRAWN", "level 2: SUBMITTED proposal withdrawn"
        assert p2_after["status"] == "WITHDRAWN", "level 2: COUNTERED proposal withdrawn"
        season_after = fresh_cap_season(env)
        assert season_after["reserved_cents"] == 0, \
            "level 3: both reservations released by the cascade"

    def test_agent_suspend_leaves_draft_proposals_untouched(self, api):
        """PRD §3.1: "Suspending a `CERTIFIED` agent moves them to `SUSPENDED`
        and immediately withdraws every proposal they authored that sits in
        `SUBMITTED` or `COUNTERED`, releasing the reserved cap space those
        proposals held on the linked cap season."

        The cascade is scoped to SUBMITTED/COUNTERED proposals: a DRAFT holds
        no reservation and is not withdrawn by the suspension.

        Design: Difficulty/transitive_cascade/agent_suspend_cascade_depth3
        """
        env = setup_negotiation_env(agency_name="Cascade Agency 2")
        con = create_contract(env, base_salary_cents=20_000_000,
                              guaranteed_cents=20_000_000)
        env.setdefault("contract_clients", {})[con["id"]] = env["client"]["id"]
        p_draft = create_draft_proposal(env, con["id"], proposed_aav_cents=20_000_000,
                                        proposed_guaranteed_cents=20_000_000)
        p_live = create_draft_proposal(env, con["id"], proposed_aav_cents=21_000_000,
                                       proposed_guaranteed_cents=21_000_000)
        submit_proposal(env, con["id"], p_live["id"])
        assert fresh_cap_season(env)["reserved_cents"] == 21_000_000

        validate_success(api.suspend_agent(env["agency"]["id"], env["agent"]["id"],
                                           make_agency_manager_headers(env["manager"]["id"])))

        draft_after = validate_success(api.get_proposal(
            env["agency"]["id"], env["client"]["id"], con["id"], p_draft["id"], LEAGUE))
        live_after = validate_success(api.get_proposal(
            env["agency"]["id"], env["client"]["id"], con["id"], p_live["id"], LEAGUE))
        assert draft_after["status"] == "DRAFT", \
            "DRAFT proposals hold no reservation and are not cascade-withdrawn"
        assert live_after["status"] == "WITHDRAWN"
        assert fresh_cap_season(env)["reserved_cents"] == 0


class TestAuthentication:
    def test_unauthenticated_request_returns_401(self, api):
        """PRD §2.1: "A request whose headers are missing or malformed, or whose
        role is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        agency = create_agency(name="AuthCo")
        resp = api.get_agency(agency["id"], {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
