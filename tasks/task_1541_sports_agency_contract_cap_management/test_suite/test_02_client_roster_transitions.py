"""Client roster: listing/pagination, release gates, transitions, fee splits."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_proposal,
    add_certified_agent,
    add_client,
    approve_endorsement,
    create_agency,
    create_contract,
    create_draft_proposal,
    create_endorsement,
    fee_entries_for_contract,
    make_agency_manager_headers,
    make_agent_headers,
    register_client,
    setup_agency_with_manager_and_agent,
    setup_negotiation_env,
    setup_signed_contract,
    sign_contract,
    submit_proposal,
    validate_error,
    validate_paginated,
    validate_success,
)

LEAGUE = TEST_USERS["league_officer_headers"]


class TestClientListing:
    def test_list_clients_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips that many leading items and defaults to 0."
        PRD §2.3: "List responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/list_clients_pagination_envelope
        """
        bundle = setup_agency_with_manager_and_agent(name="PageCo")
        register_client(bundle["agency"]["id"], bundle["agent"]["id"], full_name="P1")
        register_client(bundle["agency"]["id"], bundle["agent"]["id"], full_name="P2")
        resp = api.list_clients(bundle["agency"]["id"], LEAGUE)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["limit"] == 10, "limit defaults to 10"
        assert meta["offset"] == 0, "offset defaults to 0"
        assert meta["has_more"] is False
        assert len(data) == 2

    def test_list_clients_filter_by_status(self, api):
        """PRD §3.2: "Clients begin `ACTIVE` and can be listed with filters on
        `status` and `primary_agent_id`."

        Design: Corner/entities/list_clients_filter_by_status
        """
        bundle = setup_agency_with_manager_and_agent(name="FilterCo")
        agency_id = bundle["agency"]["id"]
        stay = register_client(agency_id, bundle["agent"]["id"], full_name="Stay")
        go = register_client(agency_id, bundle["agent"]["id"], full_name="Go")
        validate_success(api.release_client(
            agency_id, go["id"], make_agency_manager_headers(bundle["manager"]["id"])))
        data, meta = validate_paginated(
            api.list_clients(agency_id, LEAGUE, params={"status": "RELEASED"}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == go["id"]
        assert data[0]["status"] == "RELEASED"


class TestClientReleaseGates:
    def test_release_empty_obligation_set_succeeds_and_negotiating_contract_blocks(self, api):
        """PRD §3.2: "From `ACTIVE`, a client may be released only when no
        contract for that client stands in `NEGOTIATING` or `SIGNED` and no
        endorsement deal is `ACTIVE`. ... Breaching either gate is rejected with
        `ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS`."

        Boundary on the obligation count: zero obligations releases; a single
        NEGOTIATING contract blocks.

        Design: Difficulty/boundary_precision_check/client_release_with_no_active_obligations_empty_set
        """
        env = setup_negotiation_env(agency_name="RelAgency")
        manager_headers = make_agency_manager_headers(env["manager"]["id"])
        c_free = add_client(env, full_name="Free")
        c_busy = add_client(env, full_name="Busy")
        create_contract(env, client_id=c_busy["id"])

        released = validate_success(
            api.release_client(env["agency"]["id"], c_free["id"], manager_headers))
        assert released["status"] == "RELEASED", "empty obligation set permits release"

        resp = api.release_client(env["agency"]["id"], c_busy["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS,
                       expected_status=409)

    def test_release_blocked_by_active_endorsement_until_terminated(self, api):
        """PRD §3.2: "From `ACTIVE`, a client may be released only when no
        contract for that client stands in `NEGOTIATING` or `SIGNED` and no
        endorsement deal is `ACTIVE`. ... Breaching either gate is rejected with
        `ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS`."
        PRD §3.8: "An `AgencyManager` may instead terminate an `ACTIVE` deal
        early, moving it to `TERMINATED` and voiding the deal's fee ledger entry
        while it is still `ACCRUED`."

        Boundary on the endorsement dimension: one ACTIVE deal blocks; once the
        deal is TERMINATED the obligation count returns to zero and release
        succeeds.

        Design: Difficulty/boundary_precision_check/client_release_with_no_active_obligations_empty_set
        """
        env = setup_negotiation_env(agency_name="RelAgency2")
        manager_headers = make_agency_manager_headers(env["manager"]["id"])
        deal = create_endorsement(env, deal_value_cents=10_000_000)
        approve_endorsement(env, deal["id"])

        resp = api.release_client(env["agency"]["id"], env["client"]["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS,
                       expected_status=409)

        validate_success(api.terminate_endorsement(
            env["agency"]["id"], env["client"]["id"], deal["id"], manager_headers))
        released = validate_success(
            api.release_client(env["agency"]["id"], env["client"]["id"], manager_headers))
        assert released["status"] == "RELEASED"


class TestTransitionFeeSplit:
    def test_transition_split_conserves_total_fee(self, api):
        """PRD §3.2: "the remaining term is the contract's `years` minus the
        number of seasons already elapsed, measured as the current season year
        minus the contract's `start_season_year`; the remaining value is the
        contract's `aav_cents` multiplied by that remaining term; and the
        remaining fee is that value multiplied by the agency's `fee_cap_pct`,
        rounded half up to a whole cent. Two fee ledger entries of kind
        `TRANSITION_ADJUSTMENT` are then written per signed contract: one
        crediting the outgoing agent with `split_pct` 0.25 — twenty-five percent
        of the remaining fee, rounded half up — and one crediting the incoming
        agent with `split_pct` 0.75. Because the two entries are rounded
        independently, any cent of rounding residue is assigned to the incoming
        agent, whose amount is computed as the remaining fee minus the outgoing
        agent's amount, so the pair always sums exactly to the remaining fee."

        fee_cap_pct=0.04, years=3, aav=10,000,000, current season = start season
        (2026): remaining_fee = round_half_up(10,000,000 * 3 * 0.04) =
        1,200,000; old = 300,000; new = 1,200,000 - 300,000 = 900,000.

        Design: Difficulty/compensating_invariant/fee_ledger_invariant_across_transition_split
        """
        env = setup_signed_contract(fee_cap_pct=0.04, base_salary_cents=10_000_000,
                                    years=3, guaranteed_cents=25_000_000)
        agency_id = env["agency"]["id"]
        old_agent_id = env["agent"]["id"]
        new_agent = add_certified_agent(env)
        manager_headers = make_agency_manager_headers(env["manager"]["id"])

        validate_success(api.initiate_transition(
            agency_id, env["client"]["id"], new_agent["id"], manager_headers))
        client = validate_success(
            api.complete_transition(agency_id, env["client"]["id"], manager_headers))
        assert client["status"] == "ACTIVE"
        assert client["primary_agent_id"] == new_agent["id"]

        entries = fee_entries_for_contract(agency_id, env["contract"]["id"],
                                           kind="TRANSITION_ADJUSTMENT")
        assert len(entries) == 2, "two TRANSITION_ADJUSTMENT entries per signed contract"
        old_entry = next(e for e in entries if e["agent_id"] == old_agent_id)
        new_entry = next(e for e in entries if e["agent_id"] == new_agent["id"])
        assert old_entry["split_pct"] == 0.25
        assert new_entry["split_pct"] == 0.75
        assert old_entry["amount_cents"] == 300_000
        assert new_entry["amount_cents"] == 900_000
        assert old_entry["amount_cents"] + new_entry["amount_cents"] == 1_200_000, \
            "invariant: the split conserves the unsplit remaining fee"

    def test_transition_split_rounding_residue_goes_to_incoming_agent(self, api):
        """PRD §3.2: "Because the two entries are rounded independently, any
        cent of rounding residue is assigned to the incoming agent, whose amount
        is computed as the remaining fee minus the outgoing agent's amount, so
        the pair always sums exactly to the remaining fee."

        Residue-pinning case: fee_cap_pct=0.01, years=1, aav=30,000,200 gives
        remaining_fee = round_half_up(30,000,200 * 0.01) = 300,002. Outgoing
        entry = round_half_up(300,002 * 0.25) = round_half_up(75,000.5) =
        75,001; incoming = 300,002 - 75,001 = 225,001 (independent half-up
        rounding of 0.75 * 300,002 = 225,001.5 would give 225,002 — the residue
        rule pins 225,001).

        Design: Difficulty/compensating_invariant/fee_ledger_invariant_across_transition_split
        """
        env = setup_signed_contract(fee_cap_pct=0.01, base_salary_cents=30_000_200,
                                    years=1, guaranteed_cents=30_000_200)
        agency_id = env["agency"]["id"]
        old_agent_id = env["agent"]["id"]
        new_agent = add_certified_agent(env)
        manager_headers = make_agency_manager_headers(env["manager"]["id"])

        validate_success(api.initiate_transition(
            agency_id, env["client"]["id"], new_agent["id"], manager_headers))
        validate_success(api.complete_transition(agency_id, env["client"]["id"],
                                                 manager_headers))

        entries = fee_entries_for_contract(agency_id, env["contract"]["id"],
                                           kind="TRANSITION_ADJUSTMENT")
        assert len(entries) == 2
        old_entry = next(e for e in entries if e["agent_id"] == old_agent_id)
        new_entry = next(e for e in entries if e["agent_id"] == new_agent["id"])
        assert old_entry["amount_cents"] == 75_001
        assert new_entry["amount_cents"] == 225_001, \
            "cent residue from rounding is assigned to the incoming agent"
        assert old_entry["amount_cents"] + new_entry["amount_cents"] == 300_002


class TestSignGatedByClientState:
    def test_sign_rejected_while_client_transitioning(self, api):
        """PRD §3.6: "An `Agent` signs a `NEGOTIATING` contract once at least
        one of its proposals stands `ACCEPTED`; the signer must be `CERTIFIED`,
        must be the client's current `primary_agent_id`, and the client must be
        `ACTIVE`. A request that fails these state preconditions is rejected
        with `ERR_INVALID_STATE`, while the certification and ownership failures
        surface `ERR_AGENT_NOT_CERTIFIED` and `ERR_OWNERSHIP_VIOLATION` as
        usual."

        A TRANSITIONING client blocks signing even though the contract is
        NEGOTIATING with an ACCEPTED proposal.

        Design: Difficulty/cross_entity_state_dependency/contract_sign_gated_by_client_active
        """
        env = setup_negotiation_env(agency_name="SigAgency")
        old_agent_id = env["agent"]["id"]
        new_agent = add_certified_agent(env)
        manager_headers = make_agency_manager_headers(env["manager"]["id"])

        contract = create_contract(env, base_salary_cents=15_000_000,
                                   guaranteed_cents=15_000_000)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        proposal = create_draft_proposal(env, contract["id"],
                                         proposed_aav_cents=15_000_000,
                                         proposed_guaranteed_cents=15_000_000)
        submit_proposal(env, contract["id"], proposal["id"])
        accept_proposal(env, contract["id"], proposal["id"])

        validate_success(api.initiate_transition(
            env["agency"]["id"], env["client"]["id"], new_agent["id"], manager_headers))

        current = validate_success(api.get_contract(
            env["agency"]["id"], env["client"]["id"], contract["id"],
            make_agent_headers(old_agent_id)))
        resp = api.sign_contract(env["agency"]["id"], env["client"]["id"],
                                 contract["id"], current["version"],
                                 make_agent_headers(old_agent_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_contract(
            env["agency"]["id"], env["client"]["id"], contract["id"], LEAGUE))
        assert after["signing_status"] == "NEGOTIATING", "failed sign leaves state unchanged"

    def test_sign_follows_primary_agent_after_completed_transition(self, api):
        """PRD §3.6: "An `Agent` signs a `NEGOTIATING` contract once at least
        one of its proposals stands `ACCEPTED`; the signer must be `CERTIFIED`,
        must be the client's current `primary_agent_id`, and the client must be
        `ACTIVE`. A request that fails these state preconditions is rejected
        with `ERR_INVALID_STATE`, while the certification and ownership failures
        surface `ERR_AGENT_NOT_CERTIFIED` and `ERR_OWNERSHIP_VIOLATION` as
        usual."
        PRD §3.2: "Completion — again a manager's act — requires that the
        recorded successor still be `CERTIFIED`; it copies
        `transition_to_agent_id` into `primary_agent_id`, clears
        `transition_to_agent_id`, returns the client to `ACTIVE`, and settles
        the money between the outgoing and the incoming representative."

        After the transition completes, the outgoing agent fails the ownership
        check and the incoming (now primary) agent can sign.

        Design: Difficulty/cross_entity_state_dependency/contract_sign_gated_by_client_active
        """
        env = setup_negotiation_env(agency_name="SigAgency2")
        old_agent_id = env["agent"]["id"]
        new_agent = add_certified_agent(env)
        manager_headers = make_agency_manager_headers(env["manager"]["id"])

        contract = create_contract(env, base_salary_cents=15_000_000,
                                   guaranteed_cents=15_000_000)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        proposal = create_draft_proposal(env, contract["id"],
                                         proposed_aav_cents=15_000_000,
                                         proposed_guaranteed_cents=15_000_000)
        submit_proposal(env, contract["id"], proposal["id"])
        accept_proposal(env, contract["id"], proposal["id"])

        validate_success(api.initiate_transition(
            env["agency"]["id"], env["client"]["id"], new_agent["id"], manager_headers))
        validate_success(api.complete_transition(env["agency"]["id"],
                                                 env["client"]["id"], manager_headers))

        # Outgoing agent is CERTIFIED but no longer the primary -> ownership fails.
        current = validate_success(api.get_contract(
            env["agency"]["id"], env["client"]["id"], contract["id"], LEAGUE))
        resp = api.sign_contract(env["agency"]["id"], env["client"]["id"],
                                 contract["id"], current["version"],
                                 make_agent_headers(old_agent_id))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION, expected_status=422)

        # Incoming (now primary) agent signs successfully.
        signed = sign_contract(env, contract["id"], agent_id=new_agent["id"])
        assert signed["signing_status"] == "SIGNED"
        assert signed["cap_posting_status"] == "POSTED"
