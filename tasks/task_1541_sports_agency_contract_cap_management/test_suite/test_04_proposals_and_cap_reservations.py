"""Proposal negotiation cycle, cap reservations, OCC, and signing fee accrual."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_proposal,
    add_client,
    create_contract,
    create_draft_proposal,
    fee_entries_for_contract,
    fresh_cap_season,
    make_agency_manager_headers,
    make_agent_headers,
    make_team_headers,
    setup_negotiation_env,
    sign_contract,
    sign_contract_via_proposal,
    submit_proposal,
    validate_error,
    validate_success,
)

LEAGUE = TEST_USERS["league_officer_headers"]


def _mk_contract_with_draft(env, aav, client_id=None, base=None):
    """Contract + one DRAFT proposal whose ask is `aav`. Returns (contract, proposal)."""
    base = base if base is not None else aav
    contract = create_contract(env, client_id=client_id, base_salary_cents=base,
                               guaranteed_cents=base)
    env.setdefault("contract_clients", {})[contract["id"]] = client_id or env["client"]["id"]
    proposal = create_draft_proposal(env, contract["id"], proposed_aav_cents=aav,
                                     proposed_guaranteed_cents=aav)
    return contract, proposal


class TestProposalBasics:
    def test_proposal_get_returns_entity(self, api):
        """PRD §3.5: "the draft begins in `DRAFT` and is assigned a
        `round_index` one greater than the highest round index already used on
        that contract, so the first proposal carries round index one."

        Design: Corner/endpoints/proposal_get_returns_entity
        """
        env = setup_negotiation_env(agency_name="PGA")
        contract = create_contract(env, base_salary_cents=5_000_000,
                                   guaranteed_cents=5_000_000)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        proposal = create_draft_proposal(env, contract["id"],
                                         proposed_aav_cents=5_000_000,
                                         proposed_guaranteed_cents=5_000_000)
        fetched = validate_success(api.get_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            make_agent_headers(env["agent"]["id"])))
        assert fetched["round_index"] == 1, "the first proposal carries round index one"
        assert fetched["status"] == "DRAFT"
        assert fetched["proposed_aav_cents"] == 5_000_000


class TestCounterResubmitCycle:
    def test_counter_resubmit_cycle_tracks_reservation(self, api):
        """PRD §3.5: "Countering — a `Team` act carrying a `counter_aav_cents`
        figure — moves a `SUBMITTED` proposal to `COUNTERED`, shrinks the
        season's reservation by the previously proposed figure, grows it again
        by the counter figure, and rewrites the proposal's own
        `proposed_aav_cents` to the counter amount. The agent may in turn
        resubmit, moving the proposal from `COUNTERED` back to `SUBMITTED` with
        a revised `proposed_aav_cents`; resubmission replays every gate of the
        initial submission — certified authoring agent, open season, and the
        soft-cap check evaluated against the new figure — and shifts the
        reservation from the prior figure to the new one."

        Two full loop iterations: 22M submitted, countered to 21M, resubmitted
        at 21.5M, countered again to 21.2M.

        Design: Difficulty/non_linear_state_machine/proposal_counter_resubmit_cycle
        """
        env = setup_negotiation_env(agency_name="Cycle Agency")
        contract = create_contract(env, years=4, base_salary_cents=20_000_000,
                                   guaranteed_cents=50_000_000, escalator_pct=0.05)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        proposal = create_draft_proposal(env, contract["id"],
                                         proposed_aav_cents=22_000_000,
                                         proposed_guaranteed_cents=55_000_000)
        submit_proposal(env, contract["id"], proposal["id"])
        team_headers = make_team_headers(env["team"]["id"])

        # Round 1: 22M -> 21M.
        countered = validate_success(api.counter_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            21_000_000, team_headers))
        assert countered["status"] == "COUNTERED"
        assert countered["proposed_aav_cents"] == 21_000_000
        assert fresh_cap_season(env)["reserved_cents"] == 21_000_000

        # Agent resubmits at 21.5M.
        resubmitted = validate_success(api.resubmit_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            21_500_000, make_agent_headers(env["agent"]["id"])))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["proposed_aav_cents"] == 21_500_000
        assert fresh_cap_season(env)["reserved_cents"] == 21_500_000

        # Round 2: 21.5M -> 21.2M.
        countered2 = validate_success(api.counter_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            21_200_000, team_headers))
        assert countered2["status"] == "COUNTERED", "completed second loop iteration"
        assert countered2["proposed_aav_cents"] == 21_200_000
        assert fresh_cap_season(env)["reserved_cents"] == 21_200_000, \
            "reserved tracks the latest counter amount"

    def test_cycle_then_withdraw_drains_reservation(self, api):
        """PRD §3.5: "Withdrawal moves the proposal to `WITHDRAWN`, releasing
        the reservation where one exists — drafts hold none, so withdrawing a
        draft touches nothing outside the proposal itself."
        PRD §2.8: "`reserved_cents` is the sum of `proposed_aav_cents` across
        proposals currently sitting in `SUBMITTED` or `COUNTERED` against
        contracts linked to that season; reservations are created by submission,
        adjusted by counters and resubmissions, and released by acceptance,
        rejection, withdrawal, and by the cascades described throughout §3 —
        agent suspension or revocation, season lock, contract signing or
        voiding."

        One cycle (22M -> counter 21M -> resubmit 23M) followed by withdrawal
        drains the reservation back to zero.

        Design: Difficulty/non_linear_state_machine/proposal_counter_resubmit_cycle
        """
        env = setup_negotiation_env(agency_name="Cycle Agency 2")
        contract = create_contract(env, years=4, base_salary_cents=20_000_000,
                                   guaranteed_cents=50_000_000, escalator_pct=0.05)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        proposal = create_draft_proposal(env, contract["id"],
                                         proposed_aav_cents=22_000_000,
                                         proposed_guaranteed_cents=55_000_000)
        submit_proposal(env, contract["id"], proposal["id"])
        validate_success(api.counter_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            21_000_000, make_team_headers(env["team"]["id"])))
        validate_success(api.resubmit_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            23_000_000, make_agent_headers(env["agent"]["id"])))
        assert fresh_cap_season(env)["reserved_cents"] == 23_000_000

        withdrawn = validate_success(api.withdraw_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            make_agent_headers(env["agent"]["id"])))
        assert withdrawn["status"] == "WITHDRAWN"
        assert fresh_cap_season(env)["reserved_cents"] == 0


class TestAcceptHardCapThreshold:
    def _three_client_env(self, api):
        env = setup_negotiation_env(cap_limit_cents=200_000_000,
                                    luxury_threshold_cents=250_000_000,
                                    agency_name="Threshold Agency")
        return env

    def test_accept_at_exactly_hard_cap_succeeds(self, api):
        """PRD §3.5: "Acceptance, a `Team` act on a `SUBMITTED` proposal, first
        demands the season still be `OPEN` and then applies the hard-cap check:
        `committed_cents` plus `proposed_aav_cents` must not exceed
        `cap_limit_cents`, else `ERR_CAP_HARD_LIMIT`. On acceptance the proposal
        becomes `ACCEPTED`, its reservation is released from `reserved_cents`,
        and every sibling proposal on the same contract still sitting in
        `DRAFT`, `SUBMITTED`, or `COUNTERED` is withdrawn with its reservation
        released."

        Three inputs interact: committed=100M (one signed contract),
        reserved=50M (a second submitted proposal), and the accepted proposal's
        100M. The accept-time check excludes reserved: 100M + 100M == 200M ==
        cap_limit, so the boundary accept succeeds, and only the signing act
        posts committed.

        Design: Difficulty/combinatorial_formula/proposal_accept_capacity_three_input_threshold
        """
        env = self._three_client_env(api)
        # committed = 100M via a signed contract for client 1.
        con1, p1 = _mk_contract_with_draft(env, 100_000_000)
        sign_contract_via_proposal(env, con1["id"], p1["id"])
        assert fresh_cap_season(env)["committed_cents"] == 100_000_000
        # reserved = 50M via a submitted proposal on client 2's contract.
        c2 = add_client(env, position="SG")
        con2, p2 = _mk_contract_with_draft(env, 50_000_000, client_id=c2["id"])
        submit_proposal(env, con2["id"], p2["id"])
        # Third proposal: 100M, submitted (100+50+100 == 250 == luxury, <= passes).
        c3 = add_client(env, position="C")
        con3, p3 = _mk_contract_with_draft(env, 100_000_000, client_id=c3["id"])
        submit_proposal(env, con3["id"], p3["id"])
        assert fresh_cap_season(env)["reserved_cents"] == 150_000_000

        accepted = accept_proposal(env, con3["id"], p3["id"])
        assert accepted["status"] == "ACCEPTED", \
            "boundary: committed + proposed == cap_limit, so accept succeeds (<=)"
        season = fresh_cap_season(env)
        assert season["committed_cents"] == 100_000_000, \
            "accept does not post; only signing does"
        assert season["reserved_cents"] == 50_000_000, \
            "p3's 100M reservation released; p2's 50M still reserved"

    def test_accept_one_cent_over_hard_cap_rejected(self, api):
        """PRD §3.5: "Acceptance, a `Team` act on a `SUBMITTED` proposal, first
        demands the season still be `OPEN` and then applies the hard-cap check:
        `committed_cents` plus `proposed_aav_cents` must not exceed
        `cap_limit_cents`, else `ERR_CAP_HARD_LIMIT`."

        Same three-input interaction, one cent past the boundary: committed
        100M + proposed 100,000,001 = 200,000,001 > cap_limit 200M. The
        submit-time soft-cap check (against luxury 250M with only 10M reserved)
        passes, isolating the accept-time hard-cap failure.

        Design: Difficulty/combinatorial_formula/proposal_accept_capacity_three_input_threshold
        """
        env = setup_negotiation_env(cap_limit_cents=200_000_000,
                                    luxury_threshold_cents=250_000_000,
                                    agency_name="Threshold Agency 2")
        con1, p1 = _mk_contract_with_draft(env, 100_000_000)
        sign_contract_via_proposal(env, con1["id"], p1["id"])
        c2 = add_client(env, position="SG")
        con2, p2 = _mk_contract_with_draft(env, 10_000_000, client_id=c2["id"])
        submit_proposal(env, con2["id"], p2["id"])
        c3 = add_client(env, position="C")
        con3, p3 = _mk_contract_with_draft(env, 100_000_001, client_id=c3["id"])
        submit_proposal(env, con3["id"], p3["id"])

        resp = api.accept_proposal(env["agency"]["id"], c3["id"], con3["id"],
                                   p3["id"], make_team_headers(env["team"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CAP_HARD_LIMIT, expected_status=422)
        after = validate_success(api.get_proposal(
            env["agency"]["id"], c3["id"], con3["id"], p3["id"], LEAGUE))
        assert after["status"] == "SUBMITTED", "failed accept leaves the proposal live"
        assert fresh_cap_season(env)["reserved_cents"] == 110_000_001


class TestSubmitLuxuryBoundary:
    def test_submit_at_exactly_luxury_threshold_succeeds(self, api):
        """PRD §3.5: "Before the reservation posts, the soft-cap check runs: the
        season's `committed_cents` plus its `reserved_cents` plus the proposal's
        `proposed_aav_cents` must not exceed `luxury_threshold_cents`, or the
        submission is rejected with `ERR_CAP_WOULD_EXCEED`."

        committed 100M + reserved 50M + proposed 100M == luxury 250M: the
        equality boundary passes ("must not exceed").

        Design: Difficulty/boundary_precision_check/proposal_submit_luxury_threshold_equality
        """
        env = setup_negotiation_env(cap_limit_cents=200_000_000,
                                    luxury_threshold_cents=250_000_000,
                                    agency_name="BoundAgency")
        con1, p1 = _mk_contract_with_draft(env, 100_000_000)
        sign_contract_via_proposal(env, con1["id"], p1["id"])
        c2 = add_client(env, position="SF")
        con2, p2 = _mk_contract_with_draft(env, 50_000_000, client_id=c2["id"])
        submit_proposal(env, con2["id"], p2["id"])
        c3 = add_client(env, position="C")
        con3, p3 = _mk_contract_with_draft(env, 100_000_000, client_id=c3["id"])

        submitted = submit_proposal(env, con3["id"], p3["id"])
        assert submitted["status"] == "SUBMITTED", \
            "boundary: 100M + 50M + 100M = 250M == luxury; <= passes"
        assert fresh_cap_season(env)["reserved_cents"] == 150_000_000

    def test_submit_one_cent_over_luxury_threshold_rejected(self, api):
        """PRD §3.5: "Before the reservation posts, the soft-cap check runs: the
        season's `committed_cents` plus its `reserved_cents` plus the proposal's
        `proposed_aav_cents` must not exceed `luxury_threshold_cents`, or the
        submission is rejected with `ERR_CAP_WOULD_EXCEED`."

        One cent past the boundary: 100M + 50M + 100,000,001 = 250,000,001 >
        250M luxury.

        Design: Difficulty/boundary_precision_check/proposal_submit_luxury_threshold_equality
        """
        env = setup_negotiation_env(cap_limit_cents=200_000_000,
                                    luxury_threshold_cents=250_000_000,
                                    agency_name="BoundAgency 2")
        con1, p1 = _mk_contract_with_draft(env, 100_000_000)
        sign_contract_via_proposal(env, con1["id"], p1["id"])
        c2 = add_client(env, position="SF")
        con2, p2 = _mk_contract_with_draft(env, 50_000_000, client_id=c2["id"])
        submit_proposal(env, con2["id"], p2["id"])
        c3 = add_client(env, position="C")
        con3, p3 = _mk_contract_with_draft(env, 100_000_001, client_id=c3["id"])

        season = fresh_cap_season(env)
        resp = api.submit_proposal(env["agency"]["id"], c3["id"], con3["id"],
                                   p3["id"], season["version"],
                                   make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CAP_WOULD_EXCEED, expected_status=422)
        after = validate_success(api.get_proposal(
            env["agency"]["id"], c3["id"], con3["id"], p3["id"], LEAGUE))
        assert after["status"] == "DRAFT", "rejected submission leaves the draft in place"
        assert fresh_cap_season(env)["reserved_cents"] == 50_000_000


class TestCapSeasonGating:
    def test_submit_rejected_when_season_locked(self, api):
        """PRD §2.7: "Tenth, resource locks: a cap season that is not `OPEN`
        blocks submissions, resubmissions, and acceptances, and a suspended
        agency blocks agent certification and endorsement approval, else
        `ERR_RESOURCE_LOCKED` (409)."
        PRD §3.5: "Submitting is reserved to the authoring agent, who must be
        `CERTIFIED` and must equal `proposed_by_agent_id` — failing which the
        request meets `ERR_AGENT_NOT_CERTIFIED` or `ERR_OWNERSHIP_VIOLATION`
        respectively — and it requires the contract still be `NEGOTIATING` and
        the season still be `OPEN`."

        The proposal is in the correct state (DRAFT); the linked season's LOCK
        is what blocks the submission.

        Design: Difficulty/cross_entity_state_dependency/proposal_submit_gated_by_capseason_open
        """
        env = setup_negotiation_env(agency_name="DepAgency")
        contract, proposal = _mk_contract_with_draft(env, 10_000_000)
        validate_success(api.lock_cap_season(env["team"]["id"],
                                             env["cap_season"]["id"], LEAGUE))
        season = fresh_cap_season(env)
        resp = api.submit_proposal(env["agency"]["id"], env["client"]["id"],
                                   contract["id"], proposal["id"], season["version"],
                                   make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RESOURCE_LOCKED, expected_status=409)
        after = validate_success(api.get_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            LEAGUE))
        assert after["status"] == "DRAFT", "rejected submission leaves the draft in place"

    def test_unlock_restores_submission(self, api):
        """PRD §3.3: "Locking moves a season from `OPEN` to `LOCKED` and
        force-withdraws every proposal in `SUBMITTED` or `COUNTERED` against
        contracts linked to that season, releasing their reserved space — the
        league's way of freezing a market. Unlocking returns a `LOCKED` season
        to `OPEN` with no further effects."
        PRD §3.5: "On success the proposal moves from `DRAFT` to `SUBMITTED` and
        the season's `reserved_cents` grows by the proposed average annual
        value."

        A DRAFT survives the lock (it holds no reservation), submission is
        blocked while LOCKED, and unlocking reopens the market for it.

        Design: Difficulty/cross_entity_state_dependency/proposal_submit_gated_by_capseason_open
        """
        env = setup_negotiation_env(agency_name="DepAgency 2")
        contract, proposal = _mk_contract_with_draft(env, 10_000_000)
        validate_success(api.lock_cap_season(env["team"]["id"],
                                             env["cap_season"]["id"], LEAGUE))
        season = fresh_cap_season(env)
        resp = api.submit_proposal(env["agency"]["id"], env["client"]["id"],
                                   contract["id"], proposal["id"], season["version"],
                                   make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RESOURCE_LOCKED, expected_status=409)

        validate_success(api.unlock_cap_season(env["team"]["id"],
                                               env["cap_season"]["id"], LEAGUE))
        submitted = submit_proposal(env, contract["id"], proposal["id"])
        assert submitted["status"] == "SUBMITTED"
        assert fresh_cap_season(env)["reserved_cents"] == 10_000_000


class TestReservedInvariant:
    def test_submit_then_withdraw_restores_reserved(self, api):
        """PRD §2.8: "`reserved_cents` is the sum of `proposed_aav_cents` across
        proposals currently sitting in `SUBMITTED` or `COUNTERED` against
        contracts linked to that season; reservations are created by submission,
        adjusted by counters and resubmissions, and released by acceptance,
        rejection, withdrawal, and by the cascades described throughout §3 —
        agent suspension or revocation, season lock, contract signing or
        voiding."
        PRD §3.5: "Withdrawal moves the proposal to `WITHDRAWN`, releasing the
        reservation where one exists — drafts hold none, so withdrawing a draft
        touches nothing outside the proposal itself."

        Compensating invariant from a zero baseline: submit(20M) then
        withdraw(P) leaves reserved_cents at its pre-submit value of 0.

        Design: Difficulty/compensating_invariant/reserved_cents_invariant_across_submit_withdraw
        """
        env = setup_negotiation_env(agency_name="InvAgency")
        contract, proposal = _mk_contract_with_draft(env, 20_000_000)
        before = fresh_cap_season(env)
        assert before["reserved_cents"] == 0

        submit_proposal(env, contract["id"], proposal["id"])
        assert fresh_cap_season(env)["reserved_cents"] == 20_000_000
        withdrawn = validate_success(api.withdraw_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            make_agent_headers(env["agent"]["id"])))
        assert withdrawn["status"] == "WITHDRAWN"
        assert fresh_cap_season(env)["reserved_cents"] == 0, \
            "invariant: forward + compensating action restores the original value"

    def test_submit_counter_withdraw_restores_nonzero_baseline(self, api):
        """PRD §2.8: "`reserved_cents` is the sum of `proposed_aav_cents` across
        proposals currently sitting in `SUBMITTED` or `COUNTERED` against
        contracts linked to that season; reservations are created by submission,
        adjusted by counters and resubmissions, and released by acceptance,
        rejection, withdrawal, and by the cascades described throughout §3 —
        agent suspension or revocation, season lock, contract signing or
        voiding."

        Same invariant against a non-zero baseline and with a counter in the
        middle: baseline 50M; submit 20M -> 70M; counter to 18M -> 68M;
        withdraw -> back to exactly the 50M baseline.

        Design: Difficulty/compensating_invariant/reserved_cents_invariant_across_submit_withdraw
        """
        env = setup_negotiation_env(agency_name="InvAgency 2")
        c_base = add_client(env, position="SF")
        con_base, p_base = _mk_contract_with_draft(env, 50_000_000, client_id=c_base["id"])
        submit_proposal(env, con_base["id"], p_base["id"])
        assert fresh_cap_season(env)["reserved_cents"] == 50_000_000

        contract, proposal = _mk_contract_with_draft(env, 20_000_000)
        submit_proposal(env, contract["id"], proposal["id"])
        assert fresh_cap_season(env)["reserved_cents"] == 70_000_000
        validate_success(api.counter_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            18_000_000, make_team_headers(env["team"]["id"])))
        assert fresh_cap_season(env)["reserved_cents"] == 68_000_000
        validate_success(api.withdraw_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            make_agent_headers(env["agent"]["id"])))
        assert fresh_cap_season(env)["reserved_cents"] == 50_000_000, \
            "invariant holds against the non-zero baseline"


class TestRejectSideEffect:
    def test_reject_releases_reserved(self, api):
        """PRD §3.5: "Rejection, likewise a `Team` act, moves the proposal to
        `REJECTED` and releases its reservation."

        Design: Corner/state_machines/proposal_side_effect_releases_reserved_on_reject
        """
        env = setup_negotiation_env(agency_name="RejA")
        contract, proposal = _mk_contract_with_draft(env, 20_000_000)
        submit_proposal(env, contract["id"], proposal["id"])
        assert fresh_cap_season(env)["reserved_cents"] == 20_000_000

        rejected = validate_success(api.reject_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            make_team_headers(env["team"]["id"])))
        assert rejected["status"] == "REJECTED"
        assert fresh_cap_season(env)["reserved_cents"] == 0, "side effect applied"


class TestCapSeasonClose:
    def test_close_blocked_while_reserved_nonzero(self, api):
        """PRD §3.3: "Closing is terminal and is permitted from either `OPEN` or
        `LOCKED`, but only once `reserved_cents` has drained to zero; the season
        becomes `CLOSED`."
        PRD §2.7: "Fourth, state: the target entity must be in the exact state
        the requested transition demands — a proposal must be in `DRAFT` to be
        submitted, a cap season in `OPEN` to be locked — else `ERR_INVALID_STATE`
        (409)."

        Design: Corner/state_machines/cap_season_close_blocked_when_reserved_nonzero
        """
        env = setup_negotiation_env(agency_name="ClA")
        contract, proposal = _mk_contract_with_draft(env, 10_000_000)
        submit_proposal(env, contract["id"], proposal["id"])
        assert fresh_cap_season(env)["reserved_cents"] == 10_000_000

        resp = api.close_cap_season(env["team"]["id"], env["cap_season"]["id"], LEAGUE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        season = fresh_cap_season(env)
        assert season["status"] == "OPEN", "failed close leaves the season OPEN"


class TestValidationPriority:
    def test_withdrawn_proposal_and_suspended_agent_yields_invalid_state(self, api):
        """PRD §2.7: "Beyond path resolution, every request passes a fixed
        validation pipeline, evaluated in order so that an earlier failure masks
        all later checks. First, authentication: ... Fourth, state: the target
        entity must be in the exact state the requested transition demands — a
        proposal must be in `DRAFT` to be submitted, a cap season in `OPEN` to
        be locked — else `ERR_INVALID_STATE` (409). Fifth, certification:
        actions league rules reserve for certified agents require the acting
        agent's `cert_status` to be `CERTIFIED`, else `ERR_AGENT_NOT_CERTIFIED`
        (422)."

        A submit where the proposal is already WITHDRAWN (state violation) AND
        the acting agent is SUSPENDED (certification violation) surfaces the
        earlier pipeline failure: ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_proposal_submit
        """
        env = setup_negotiation_env(agency_name="PriAgency")
        contract, proposal = _mk_contract_with_draft(env, 10_000_000)
        submit_proposal(env, contract["id"], proposal["id"])
        validate_success(api.withdraw_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            make_agent_headers(env["agent"]["id"])))
        validate_success(api.suspend_agent(
            env["agency"]["id"], env["agent"]["id"],
            make_agency_manager_headers(env["manager"]["id"])))

        season = fresh_cap_season(env)
        resp = api.submit_proposal(env["agency"]["id"], env["client"]["id"],
                                   contract["id"], proposal["id"], season["version"],
                                   make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_draft_proposal_and_suspended_agent_yields_not_certified(self, api):
        """PRD §2.7: "Beyond path resolution, every request passes a fixed
        validation pipeline, evaluated in order so that an earlier failure masks
        all later checks. ... Fifth, certification: actions league rules reserve
        for certified agents require the acting agent's `cert_status` to be
        `CERTIFIED`, else `ERR_AGENT_NOT_CERTIFIED` (422)."
        PRD §3.1: "Only `CERTIFIED` agents may submit or resubmit proposals,
        sign contracts, or exercise tender options; an attempt by anyone else is
        rejected with `ERR_AGENT_NOT_CERTIFIED`."

        The proposal is in the correct state (DRAFT) and ownership matches, so
        only the certification check can fire — and it does.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_proposal_submit
        """
        env = setup_negotiation_env(agency_name="PriAgency 2")
        contract, proposal = _mk_contract_with_draft(env, 10_000_000)
        validate_success(api.suspend_agent(
            env["agency"]["id"], env["agent"]["id"],
            make_agency_manager_headers(env["manager"]["id"])))

        season = fresh_cap_season(env)
        resp = api.submit_proposal(env["agency"]["id"], env["client"]["id"],
                                   contract["id"], proposal["id"], season["version"],
                                   make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_CERTIFIED, expected_status=422)


class TestSuspendedAgentSubmit:
    def test_suspended_agent_cannot_submit_proposal(self, api):
        """PRD §3.1: "Only `CERTIFIED` agents may submit or resubmit proposals,
        sign contracts, or exercise tender options; an attempt by anyone else is
        rejected with `ERR_AGENT_NOT_CERTIFIED`."

        Design: Corner/validations/suspended_agent_cannot_submit_proposal
        """
        env = setup_negotiation_env(agency_name="SAA")
        contract, proposal = _mk_contract_with_draft(env, 5_000_000)
        validate_success(api.suspend_agent(
            env["agency"]["id"], env["agent"]["id"],
            make_agency_manager_headers(env["manager"]["id"])))
        season = fresh_cap_season(env)
        resp = api.submit_proposal(env["agency"]["id"], env["client"]["id"],
                                   contract["id"], proposal["id"], season["version"],
                                   make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_CERTIFIED, expected_status=422)


class TestOptimisticConcurrency:
    def test_stale_cap_season_version_rejected(self, api):
        """PRD §2.9: "Submitting a proposal requires the request to carry
        `expected_cap_season_version`, holding the cap season `version` the
        client last observed. If that value does not match the season's current
        `version` — because another proposal's submission, counter, acceptance,
        rejection, or withdrawal has already moved the season's reservation
        arithmetic since the client read it — the submission is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so the client never submits against
        capacity figures it has not observed."

        Design: Corner/errors/err_stale_version_triggered_by_occ_mismatch
        """
        env = setup_negotiation_env(agency_name="OCCA")
        con1, p1 = _mk_contract_with_draft(env, 10_000_000)
        c2 = add_client(env, position="SG")
        con2, p2 = _mk_contract_with_draft(env, 20_000_000, client_id=c2["id"])
        # Observer reads the season version before p1's submission moves it.
        stale_version = fresh_cap_season(env)["version"]
        submit_proposal(env, con1["id"], p1["id"])

        resp = api.submit_proposal(env["agency"]["id"], c2["id"], con2["id"],
                                   p2["id"], stale_version,
                                   make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        after = validate_success(api.get_proposal(
            env["agency"]["id"], c2["id"], con2["id"], p2["id"], LEAGUE))
        assert after["status"] == "DRAFT", "stale submission changes nothing"
        assert fresh_cap_season(env)["reserved_cents"] == 10_000_000, \
            "only the first reservation applied"

    def test_correct_version_submit_succeeds_and_bumps_version(self, api):
        """PRD §2.9: "Submitting a proposal requires the request to carry
        `expected_cap_season_version`, holding the cap season `version` the
        client last observed."
        PRD §2.4: "The `version` field is an integer that increments by one on
        every mutation. Mutations caused by cascading side effects — a cap
        season's counters moving because a proposal was submitted, a client
        sliding into transition because an agent's certification was revoked —
        count as mutations of the affected resource and therefore refresh its
        `updated_at` and increment its `version`."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_correct_version_succeeds
        """
        env = setup_negotiation_env(agency_name="OHA")
        contract, proposal = _mk_contract_with_draft(env, 10_000_000)
        before = fresh_cap_season(env)
        submitted = validate_success(api.submit_proposal(
            env["agency"]["id"], env["client"]["id"], contract["id"], proposal["id"],
            before["version"], make_agent_headers(env["agent"]["id"])))
        assert submitted["status"] == "SUBMITTED"
        after = fresh_cap_season(env)
        assert after["version"] == before["version"] + 1, \
            "the reservation mutation increments the season version by one"


class TestProposalRBAC:
    def test_league_officer_cannot_submit_proposal(self, api):
        """PRD §2.1: "When the role is recognized but is not among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_FORBIDDEN` (403)."
        PRD §4: "POST | .../proposals/{proposalId}/submit` | Submit a DRAFT
        proposal; reserves cap space | Agent".

        Design: Corner/rbac/league_officer_cannot_submit_proposal
        """
        env = setup_negotiation_env(agency_name="LOA")
        contract, proposal = _mk_contract_with_draft(env, 5_000_000)
        season = fresh_cap_season(env)
        resp = api.submit_proposal(env["agency"]["id"], env["client"]["id"],
                                   contract["id"], proposal["id"], season["version"],
                                   LEAGUE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestSigningFeeAccrual:
    def test_signing_accrues_playing_contract_fee(self, api):
        """PRD §3.6: "A successful signing moves `signing_status` from
        `NEGOTIATING` to `SIGNED` and, on the parallel ledger dimension,
        `cap_posting_status` from `UNPOSTED` to `POSTED`. The linked season's
        `committed_cents` grows by the contract's `aav_cents`; a fee ledger
        entry of kind `PLAYING_CONTRACT` is written for the contract's gross fee
        — `aav_cents` multiplied by the agency's `fee_cap_pct`, rounded half up
        — credited entirely, a `split_pct` of 1.0, to the client's primary
        agent; and every remaining open proposal on the contract, whether
        `DRAFT`, `SUBMITTED`, or `COUNTERED`, is withdrawn with its reservation
        released."

        aav 20,000,000 under fee_cap_pct 0.03 accrues exactly one
        PLAYING_CONTRACT entry of 600,000 to the primary agent.

        Design: Corner/calculations/contract_fee_accrual_computed_correctly
        """
        env = setup_negotiation_env(fee_cap_pct=0.03, agency_name="FeeA")
        contract = create_contract(env, base_salary_cents=20_000_000,
                                   guaranteed_cents=20_000_000)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        proposal = create_draft_proposal(env, contract["id"],
                                         proposed_aav_cents=20_000_000,
                                         proposed_guaranteed_cents=20_000_000)
        signed = sign_contract_via_proposal(env, contract["id"], proposal["id"])
        assert signed["signing_status"] == "SIGNED"
        assert fresh_cap_season(env)["committed_cents"] == 20_000_000

        entries = fee_entries_for_contract(env["agency"]["id"], contract["id"],
                                           kind="PLAYING_CONTRACT")
        assert len(entries) == 1, "exactly one PLAYING_CONTRACT entry per signing"
        entry = entries[0]
        assert entry["status"] == "ACCRUED"
        assert entry["agent_id"] == env["agent"]["id"]
        assert entry["split_pct"] == 1.0
        assert entry["amount_cents"] == 600_000, \
            "round_half_up(20,000,000 * 0.03)"
