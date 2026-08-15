"""Contract creation, AAV/total-value valuation, field constraints, uniqueness."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_client,
    assert_contract,
    create_contract,
    create_draft_proposal,
    fee_entries_for_contract,
    fresh_cap_season,
    make_agency_manager_headers,
    make_agent_headers,
    make_team_headers,
    setup_negotiation_env,
    sign_contract_via_proposal,
    validate_error,
    validate_success,
)

LEAGUE = TEST_USERS["league_officer_headers"]


class TestContractValuation:
    def test_contract_aav_ltbe_inclusive_exact_figures(self, api):
        """PRD §3.4: "Incentives are treated as likely to be earned and are
        likewise spread evenly across the seasons, again with half-up rounding
        per season. Each season's cap hit is the sum of that season's base, that
        season's bonus share, and that season's incentive share; the contract's
        `aav_cents` is the total of those per-season cap hits divided by
        `years`, rounded half up to a whole cent. The headline
        `total_value_cents` is the sum of the per-season bases plus the full
        signing bonus plus the full incentive pool."

        base=10,000,000, escalator=0.10, years=3, bonus=3,000,000,
        incentive=1,500,000: per-season bases 10,000,000 / 11,000,000 /
        12,100,000; bonus share 1,000,000; incentive share 500,000; cap hits
        11,500,000 / 12,500,000 / 13,600,000; total 37,600,000; LTBE-inclusive
        aav = round_half_up(37,600,000 / 3) = 12,533,333.

        Design: Difficulty/dual_variant_calc/contract_aav_ltbe_vs_ultbe_projection
        """
        env = setup_negotiation_env(cap_limit_cents=200_000_000,
                                    luxury_threshold_cents=250_000_000,
                                    agency_name="Apex Sports")
        contract = create_contract(
            env, years=3, base_salary_cents=10_000_000,
            guaranteed_cents=25_000_000, signing_bonus_cents=3_000_000,
            incentive_cents=1_500_000, escalator_pct=0.10)
        assert_contract(contract)
        assert contract["aav_cents"] == 12_533_333, \
            "LTBE-inclusive aav: per-season cap hits include the incentive share"
        assert contract["total_value_cents"] == 37_600_000, \
            "base_sum 33,100,000 + bonus 3,000,000 + incentive 1,500,000"

    def test_contract_aav_incentive_inclusion_delta(self, api):
        """PRD §3.4: "Incentives are treated as likely to be earned and are
        likewise spread evenly across the seasons, again with half-up rounding
        per season. Each season's cap hit is the sum of that season's base, that
        season's bonus share, and that season's incentive share; the contract's
        `aav_cents` is the total of those per-season cap hits divided by
        `years`, rounded half up to a whole cent."

        Same base/bonus/escalator with incentive 0 vs 1,500,000 across 3
        seasons: the incentive share is 500,000 per season, so the aav differs
        by exactly 500,000 cents — incentives count toward AAV.

        Design: Difficulty/dual_variant_calc/contract_aav_ltbe_vs_ultbe_projection
        """
        env = setup_negotiation_env(cap_limit_cents=200_000_000,
                                    luxury_threshold_cents=250_000_000,
                                    agency_name="Delta Sports")
        base_kwargs = dict(years=3, base_salary_cents=10_000_000,
                           guaranteed_cents=25_000_000,
                           signing_bonus_cents=3_000_000, escalator_pct=0.10)
        # A second client avoids the one-active-contract-per-pair gate.
        client2 = add_client(env)
        with_incentive = create_contract(env, incentive_cents=1_500_000, **base_kwargs)
        without_incentive = create_contract(env, client_id=client2["id"],
                                            incentive_cents=0, **base_kwargs)
        assert with_incentive["aav_cents"] - without_incentive["aav_cents"] == 500_000, \
            "LTBE inclusion adds exactly incentive_per_year to each season's cap hit"
        assert without_incentive["aav_cents"] == 12_033_333
        assert with_incentive["total_value_cents"] - \
            without_incentive["total_value_cents"] == 1_500_000

    def test_contract_aav_nested_rounding_order(self, api):
        """PRD §2.6: "Whenever a calculation produces a fractional cent, it is
        rounded half up to a whole cent. Multi-step calculations round at each
        per-season or per-ledger-entry step exactly where the governing rule in
        §3 specifies, and again at any final division step — never twice at the
        same step, never later than specified."
        PRD §3.4: "The signing bonus is prorated evenly across the term, each
        season's share rounded half up to a whole cent. Incentives are treated
        as likely to be earned and are likewise spread evenly across the
        seasons, again with half-up rounding per season. Each season's cap hit
        is the sum of that season's base, that season's bonus share, and that
        season's incentive share; the contract's `aav_cents` is the total of
        those per-season cap hits divided by `years`, rounded half up to a whole
        cent."

        base=10,000,000, escalator=0.075, years=2, bonus=1,000,001,
        incentive=500,001: bases 10,000,000 / 10,750,000; bonus share
        round_half_up(500,000.5) = 500,001; incentive share
        round_half_up(250,000.5) = 250,001; cap hits 10,750,002 / 11,500,002;
        total 22,250,004; aav = round_half_up(22,250,004 / 2) = 11,125,002.

        Design: Difficulty/combinatorial_formula/contract_aav_nested_rounding_order
        """
        env = setup_negotiation_env(fee_cap_pct=0.04, cap_limit_cents=300_000_000,
                                    luxury_threshold_cents=350_000_000,
                                    agency_name="Precision Agency")
        contract = create_contract(
            env, years=2, base_salary_cents=10_000_000,
            guaranteed_cents=15_000_000, signing_bonus_cents=1_000_001,
            incentive_cents=500_001, escalator_pct=0.075)
        assert contract["aav_cents"] == 11_125_002, \
            "per-season rounding first, then the final division rounds again"
        assert contract["total_value_cents"] == 22_250_002, \
            "20,750,000 base_sum + 1,000,001 bonus + 500,001 incentive"

    def test_contract_aav_nested_rounding_order_second_case(self, api):
        """PRD §3.4: "The escalator compounds per season: the first season's
        base is `base_salary_cents`, and each later season's base is
        `base_salary_cents` grown by `escalator_pct` once per elapsed season —
        the second season applies the escalator one time, the third season two
        times, and so on — with every season's base individually rounded half up
        to a whole cent. The signing bonus is prorated evenly across the term,
        each season's share rounded half up to a whole cent."

        base=5,000,000, escalator=0.05, years=3, bonus=700,001, incentive=0:
        bases 5,000,000 / 5,250,000 / 5,512,500; bonus share
        round_half_up(233,333.67) = 233,334; cap hits 5,233,334 / 5,483,334 /
        5,745,834; total 16,462,502; aav = round_half_up(5,487,500.67) =
        5,487,501.

        Design: Difficulty/combinatorial_formula/contract_aav_nested_rounding_order
        """
        env = setup_negotiation_env(agency_name="Precision Agency 2")
        contract = create_contract(
            env, years=3, base_salary_cents=5_000_000,
            guaranteed_cents=10_000_000, signing_bonus_cents=700_001,
            incentive_cents=0, escalator_pct=0.05)
        assert contract["aav_cents"] == 5_487_501
        assert contract["total_value_cents"] == 16_462_501, \
            "15,762,500 base_sum + 700,001 bonus + 0 incentive"

    def test_contract_aav_calculation_correct_result(self, api):
        """PRD §3.4: "Each season's cap hit is the sum of that season's base,
        that season's bonus share, and that season's incentive share; the
        contract's `aav_cents` is the total of those per-season cap hits divided
        by `years`, rounded half up to a whole cent. The headline
        `total_value_cents` is the sum of the per-season bases plus the full
        signing bonus plus the full incentive pool."

        base=20,000,000, escalator=0, years=4, bonus=4,000,000,
        incentive=2,000,000: per-season hit 21,500,000; total 86,000,000;
        aav = 21,500,000.

        Design: Corner/calculations/contract_aav_calculation_correct_result
        """
        env = setup_negotiation_env(agency_name="CalcA")
        contract = create_contract(
            env, years=4, base_salary_cents=20_000_000,
            guaranteed_cents=80_000_000, signing_bonus_cents=4_000_000,
            incentive_cents=2_000_000, escalator_pct=0)
        assert contract["aav_cents"] == 21_500_000
        assert contract["total_value_cents"] == 86_000_000, "80M + 4M + 2M"

    def test_escalator_projection_per_year_compound_growth(self, api):
        """PRD §3.4: "The escalator compounds per season: the first season's
        base is `base_salary_cents`, and each later season's base is
        `base_salary_cents` grown by `escalator_pct` once per elapsed season —
        the second season applies the escalator one time, the third season two
        times, and so on — with every season's base individually rounded half up
        to a whole cent."

        base=10,000,000, escalator=0.10, years=3, no bonus/incentive: bases
        10,000,000 / 11,000,000 / 12,100,000; total 33,100,000; aav =
        round_half_up(33,100,000 / 3) = 11,033,333.

        Design: Corner/calculations/escalator_projection_produces_per_year_array
        """
        env = setup_negotiation_env(agency_name="EscA")
        contract = create_contract(
            env, years=3, base_salary_cents=10_000_000,
            guaranteed_cents=25_000_000, signing_bonus_cents=0,
            incentive_cents=0, escalator_pct=0.10)
        assert contract["aav_cents"] == 11_033_333
        assert contract["total_value_cents"] == 33_100_000

    def test_contract_aav_is_computed_input_ignored(self, api):
        """PRD §3.4: "Valuation is deterministic and happens at creation,
        recomputed whenever a valuation input changes while the contract remains
        `NEGOTIATING`."
        PRD §4: "POST | `/agencies/{agencyId}/clients/{clientId}/contracts` |
        Create a Contract; valuation computed at creation | Agent".

        A flat 10,000,000 one-season deal with no bonus or incentive values to
        aav_cents == total_value_cents == 10,000,000 — computed server-side.

        Design: Corner/entities/contract_aav_is_computed_input_ignored
        """
        env = setup_negotiation_env(agency_name="CalcA-flat")
        contract = create_contract(env, years=1, base_salary_cents=10_000_000,
                                   guaranteed_cents=10_000_000)
        assert contract["aav_cents"] == 10_000_000, "computed: (10M + 0 + 0) / 1"
        assert contract["total_value_cents"] == 10_000_000


class TestContractFieldConstraints:
    def test_invalid_years_returns_invalid_request(self, api):
        """PRD §3.4: "Three field constraints guard creation, and any later
        adjustment while the deal is still being negotiated: the term must run
        at least one season and no more than five; the guaranteed portion may
        not exceed the year-one base salary multiplied by the number of seasons;
        and the escalator must lie between zero and 0.15 inclusive. Violations
        are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_years_returns_invalid_request
        """
        env = setup_negotiation_env(agency_name="VA")
        resp = api.create_contract(
            env["agency"]["id"], env["client"]["id"],
            {"team_id": env["team"]["id"], "cap_season_id": env["cap_season"]["id"],
             "start_season_year": 2026, "years": 6, "base_salary_cents": 5_000_000,
             "guaranteed_cents": 25_000_000, "signing_bonus_cents": 0,
             "incentive_cents": 0, "escalator_pct": 0},
            make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_guaranteed_exceeds_base_times_years_returns_invalid_request(self, api):
        """PRD §3.4: "the guaranteed portion may not exceed the year-one base
        salary multiplied by the number of seasons; and the escalator must lie
        between zero and 0.15 inclusive. Violations are rejected with
        `ERR_INVALID_REQUEST`."

        base * years = 20,000,000 < guaranteed 25,000,000.

        Design: Corner/validations/guaranteed_exceeds_base_times_years_returns_invalid_request
        """
        env = setup_negotiation_env(agency_name="GA")
        resp = api.create_contract(
            env["agency"]["id"], env["client"]["id"],
            {"team_id": env["team"]["id"], "cap_season_id": env["cap_season"]["id"],
             "start_season_year": 2026, "years": 2, "base_salary_cents": 10_000_000,
             "guaranteed_cents": 25_000_000, "signing_bonus_cents": 0,
             "incentive_cents": 0, "escalator_pct": 0},
            make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_escalator_above_max_returns_invalid_request(self, api):
        """PRD §3.4: "and the escalator must lie between zero and 0.15
        inclusive. Violations are rejected with `ERR_INVALID_REQUEST`."

        escalator_pct = 0.20 exceeds the 0.15 ceiling.

        Design: Corner/validations/escalator_above_max_returns_invalid_request
        """
        env = setup_negotiation_env(agency_name="EA")
        resp = api.create_contract(
            env["agency"]["id"], env["client"]["id"],
            {"team_id": env["team"]["id"], "cap_season_id": env["cap_season"]["id"],
             "start_season_year": 2026, "years": 2, "base_salary_cents": 10_000_000,
             "guaranteed_cents": 15_000_000, "signing_bonus_cents": 0,
             "incentive_cents": 0, "escalator_pct": 0.20},
            make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestContractUniqueness:
    def test_second_negotiating_contract_same_pair_rejected(self, api):
        """PRD §3.4: "Uniqueness is enforced per market as well: at most one
        contract in `NEGOTIATING` or `SIGNED` may exist for a given
        client-and-team pair, and a conflicting creation is rejected with
        `ERR_DUPLICATE_ACTIVE_CONTRACT`."

        Aggregate occupancy on the (client, team) pair: a second create while
        the first stands NEGOTIATING conflicts.

        Design: Difficulty/resource_temporal_overlap/duplicate_active_contract_temporal_aggregate
        """
        env = setup_negotiation_env(agency_name="DupAgency")
        first = create_contract(env, base_salary_cents=5_000_000,
                                guaranteed_cents=5_000_000)
        assert first["signing_status"] == "NEGOTIATING"
        resp = api.create_contract(
            env["agency"]["id"], env["client"]["id"],
            {"team_id": env["team"]["id"], "cap_season_id": env["cap_season"]["id"],
             "start_season_year": 2026, "years": 2, "base_salary_cents": 8_000_000,
             "guaranteed_cents": 12_000_000, "signing_bonus_cents": 0,
             "incentive_cents": 0, "escalator_pct": 0},
            make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CONTRACT,
                       expected_status=409)

    def test_signed_contract_blocks_and_voided_releases_the_pair(self, api):
        """PRD §3.4: "Uniqueness is enforced per market as well: at most one
        contract in `NEGOTIATING` or `SIGNED` may exist for a given
        client-and-team pair, and a conflicting creation is rejected with
        `ERR_DUPLICATE_ACTIVE_CONTRACT`."
        PRD §3.6: "A contract that is `VOIDED` with posting `REVERSED` is
        terminal on both dimensions."

        SIGNED occupancy also blocks; once the incumbent is VOIDED it no longer
        occupies the pair and a fresh create succeeds.

        Design: Difficulty/resource_temporal_overlap/duplicate_active_contract_temporal_aggregate
        """
        env = setup_negotiation_env(agency_name="DupAgency2")
        first = create_contract(env, base_salary_cents=5_000_000,
                                guaranteed_cents=5_000_000)
        env.setdefault("contract_clients", {})[first["id"]] = env["client"]["id"]
        proposal = create_draft_proposal(env, first["id"],
                                         proposed_aav_cents=5_000_000,
                                         proposed_guaranteed_cents=5_000_000)
        sign_contract_via_proposal(env, first["id"], proposal["id"])

        payload = {"team_id": env["team"]["id"],
                   "cap_season_id": env["cap_season"]["id"],
                   "start_season_year": 2026, "years": 2,
                   "base_salary_cents": 8_000_000, "guaranteed_cents": 12_000_000,
                   "signing_bonus_cents": 0, "incentive_cents": 0, "escalator_pct": 0}
        resp = api.create_contract(env["agency"]["id"], env["client"]["id"], payload,
                                   make_agent_headers(env["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CONTRACT,
                       expected_status=409)

        validate_success(api.void_contract(
            env["agency"]["id"], env["client"]["id"], first["id"],
            make_agency_manager_headers(env["manager"]["id"])))
        second = validate_success(
            api.create_contract(env["agency"]["id"], env["client"]["id"], payload,
                                make_agent_headers(env["agent"]["id"])), 201)
        assert second["signing_status"] == "NEGOTIATING"


class TestContractParallelDimensions:
    def test_void_signed_vs_void_negotiating_divergent_side_effects(self, api):
        """PRD §3.4: "A contract's life is tracked on two independent dimensions
        from birth — `signing_status` begins `NEGOTIATING` while
        `cap_posting_status` begins `UNPOSTED` — and contracts can be listed
        with filters on `signing_status` and `team_id`."
        PRD §3.6: "While the contract is still `NEGOTIATING`, voiding moves
        `signing_status` to `VOIDED` and flips the never-posted ledger dimension
        from `UNPOSTED` straight to `REVERSED`, withdrawing any open proposals
        and releasing their reservations."
        PRD §3.6: "Voiding a signed contract moves `cap_posting_status` from
        `POSTED` to `REVERSED`, subtracts the contract's `aav_cents` from the
        season's `committed_cents`, and voids every fee ledger entry for the
        contract still standing `ACCRUED`, moving each to `VOIDED`."

        Both voids land on the same state pair (VOIDED, REVERSED) but only the
        signed void debits committed_cents and voids the accrued fee.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_signing_x_cap_posting
        """
        env = setup_negotiation_env(agency_name="Dim Agency")
        manager_headers = make_agency_manager_headers(env["manager"]["id"])
        # Signed path: 30M posted to the season.
        c_signed = env["client"]
        con_signed = create_contract(env, base_salary_cents=30_000_000,
                                     guaranteed_cents=30_000_000)
        env.setdefault("contract_clients", {})[con_signed["id"]] = c_signed["id"]
        p_signed = create_draft_proposal(env, con_signed["id"],
                                         proposed_aav_cents=30_000_000,
                                         proposed_guaranteed_cents=30_000_000)
        sign_contract_via_proposal(env, con_signed["id"], p_signed["id"])
        assert fresh_cap_season(env)["committed_cents"] == 30_000_000
        # Negotiating path: never posted.
        c_neg = add_client(env, full_name="Neg Player", position="SF")
        con_neg = create_contract(env, client_id=c_neg["id"],
                                  base_salary_cents=20_000_000,
                                  guaranteed_cents=20_000_000)

        void_signed = validate_success(api.void_contract(
            env["agency"]["id"], c_signed["id"], con_signed["id"], manager_headers))
        void_neg = validate_success(api.void_contract(
            env["agency"]["id"], c_neg["id"], con_neg["id"], manager_headers))

        assert void_signed["signing_status"] == "VOIDED"
        assert void_signed["cap_posting_status"] == "REVERSED"
        assert void_neg["signing_status"] == "VOIDED"
        assert void_neg["cap_posting_status"] == "REVERSED"

        season = fresh_cap_season(env)
        assert season["committed_cents"] == 0, \
            "signed void debited the 30M it had posted; negotiating void debited nothing"

        signed_entries = fee_entries_for_contract(env["agency"]["id"], con_signed["id"])
        assert len(signed_entries) == 1
        assert signed_entries[0]["status"] == "VOIDED", \
            "accrued fee voided by the signed-contract void"
        assert fee_entries_for_contract(env["agency"]["id"], con_neg["id"]) == []

    def test_dimensions_at_birth_and_at_signature(self, api):
        """PRD §3.4: "A contract's life is tracked on two independent dimensions
        from birth — `signing_status` begins `NEGOTIATING` while
        `cap_posting_status` begins `UNPOSTED` — and contracts can be listed
        with filters on `signing_status` and `team_id`."
        PRD §3.6: "A successful signing moves `signing_status` from
        `NEGOTIATING` to `SIGNED` and, on the parallel ledger dimension,
        `cap_posting_status` from `UNPOSTED` to `POSTED`."

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_signing_x_cap_posting
        """
        env = setup_negotiation_env(agency_name="Dim Agency 2")
        contract = create_contract(env, base_salary_cents=12_000_000,
                                   guaranteed_cents=12_000_000)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        assert contract["signing_status"] == "NEGOTIATING"
        assert contract["cap_posting_status"] == "UNPOSTED"

        proposal = create_draft_proposal(env, contract["id"],
                                         proposed_aav_cents=12_000_000,
                                         proposed_guaranteed_cents=12_000_000)
        signed = sign_contract_via_proposal(env, contract["id"], proposal["id"])
        assert signed["signing_status"] == "SIGNED"
        assert signed["cap_posting_status"] == "POSTED"


class TestContractVoidCascade:
    def test_void_signed_contract_reverses_cap_and_voids_fee(self, api):
        """PRD §3.6: "Voiding a signed contract moves `cap_posting_status` from
        `POSTED` to `REVERSED`, subtracts the contract's `aav_cents` from the
        season's `committed_cents`, and voids every fee ledger entry for the
        contract still standing `ACCRUED`, moving each to `VOIDED`."

        Depth-2 cascade: signing_status -> VOIDED (level 1) causes the
        committed_cents debit and the ACCRUED fee -> VOIDED compensation
        (level 2).

        Design: Difficulty/transitive_cascade/contract_void_cascade_depth2_via_fee_reversal
        """
        env = setup_negotiation_env(agency_name="VoidAgency")
        contract = create_contract(env, base_salary_cents=40_000_000,
                                   guaranteed_cents=40_000_000)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        proposal = create_draft_proposal(env, contract["id"],
                                         proposed_aav_cents=40_000_000,
                                         proposed_guaranteed_cents=40_000_000)
        sign_contract_via_proposal(env, contract["id"], proposal["id"])
        assert fresh_cap_season(env)["committed_cents"] == 40_000_000

        voided = validate_success(api.void_contract(
            env["agency"]["id"], env["client"]["id"], contract["id"],
            make_agency_manager_headers(env["manager"]["id"])))
        assert voided["signing_status"] == "VOIDED"  # level 1
        assert voided["cap_posting_status"] == "REVERSED"

        season = fresh_cap_season(env)
        assert season["committed_cents"] == 0, "level 2: ledger sync reversed"
        entries = fee_entries_for_contract(env["agency"]["id"], contract["id"])
        assert len(entries) == 1
        assert entries[0]["status"] == "VOIDED", "level 2: compensation voids the fee"

    def test_void_signed_contract_leaves_sibling_commitments_intact(self, api):
        """PRD §3.6: "Voiding a signed contract moves `cap_posting_status` from
        `POSTED` to `REVERSED`, subtracts the contract's `aav_cents` from the
        season's `committed_cents`, and voids every fee ledger entry for the
        contract still standing `ACCRUED`, moving each to `VOIDED`."

        With two signed contracts (30M and 40M) on one season, voiding the 40M
        contract leaves the sibling's 30M commitment and its ACCRUED fee
        untouched.

        Design: Difficulty/transitive_cascade/contract_void_cascade_depth2_via_fee_reversal
        """
        env = setup_negotiation_env(agency_name="VoidAgency2")
        manager_headers = make_agency_manager_headers(env["manager"]["id"])
        con_a = create_contract(env, base_salary_cents=30_000_000,
                                guaranteed_cents=30_000_000)
        env.setdefault("contract_clients", {})[con_a["id"]] = env["client"]["id"]
        p_a = create_draft_proposal(env, con_a["id"], proposed_aav_cents=30_000_000,
                                    proposed_guaranteed_cents=30_000_000)
        sign_contract_via_proposal(env, con_a["id"], p_a["id"])

        c2 = add_client(env)
        con_b = create_contract(env, client_id=c2["id"], base_salary_cents=40_000_000,
                                guaranteed_cents=40_000_000)
        env["contract_clients"][con_b["id"]] = c2["id"]
        p_b = create_draft_proposal(env, con_b["id"], proposed_aav_cents=40_000_000,
                                    proposed_guaranteed_cents=40_000_000)
        sign_contract_via_proposal(env, con_b["id"], p_b["id"])
        assert fresh_cap_season(env)["committed_cents"] == 70_000_000

        validate_success(api.void_contract(env["agency"]["id"], c2["id"], con_b["id"],
                                           manager_headers))
        season = fresh_cap_season(env)
        assert season["committed_cents"] == 30_000_000, \
            "only the voided contract's aav is subtracted"
        b_entries = fee_entries_for_contract(env["agency"]["id"], con_b["id"])
        assert all(e["status"] == "VOIDED" for e in b_entries)
        a_entries = fee_entries_for_contract(env["agency"]["id"], con_a["id"])
        assert len(a_entries) == 1 and a_entries[0]["status"] == "ACCRUED", \
            "sibling contract's fee is unaffected"


class TestContractRBAC:
    def test_team_cannot_create_contract(self, api):
        """PRD §2.1: "When the role is recognized but is not among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_FORBIDDEN` (403)."
        PRD §4: "POST | `/agencies/{agencyId}/clients/{clientId}/contracts` |
        Create a Contract; valuation computed at creation | Agent".

        Design: Corner/rbac/team_cannot_create_contract
        """
        env = setup_negotiation_env(agency_name="RBA2")
        resp = api.create_contract(
            env["agency"]["id"], env["client"]["id"],
            {"team_id": env["team"]["id"], "cap_season_id": env["cap_season"]["id"],
             "start_season_year": 2026, "years": 1, "base_salary_cents": 1_000_000,
             "guaranteed_cents": 1_000_000, "signing_bonus_cents": 0,
             "incentive_cents": 0, "escalator_pct": 0},
            make_team_headers(env["team"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
