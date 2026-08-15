"""Bracket seeding, funding gates, validation priority, and bracket OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_slot,
    advance_tournament,
    api_client,
    create_player,
    create_registration,
    create_tournament,
    fund_tournament,
    generate_bracket,
    get_matches,
    get_registration,
    get_tournament,
    get_tournament_version,
    make_player_headers,
    make_team_manager_headers,
    review_registration,
    set_clock,
    setup_locked_tournament,
    setup_registration_open_tournament,
    setup_seeded_tournament,
    submit_registration,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["organizer_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestFundingGate:

    def test_funding_exact_equality_passes_and_seeds(self):
        """PRD §3.3: "the funded pool must be at least the advertised target —
        `funded_pool_cents` must be greater than or equal to
        `prize_pool_target_cents`, with exact equality allowed (else
        `ERR_PRIZE_POOL_UNDERFUNDED`)"
        PRD §3.3: "the platform first computes `seed_score` for each `LOCKED`
        registration: half of `region_rank_points`, plus three-tenths of
        `prior_event_points`, plus one-fifth of `qualifier_wins` multiplied by
        10, with the final score rounded half-up to 3 decimal places."

        Design: Difficulty/boundary_precision_check/funding_exact_equality_passes
        """
        ctx = setup_locked_tournament(
            "Exact Cup", prize_pool_target_cents=500000,
            fund_amounts=(200000, 300000))
        tournament_id = ctx["tournament"]["id"]
        r1, r2 = ctx["registrations"]

        resp = api_client.generate_bracket(
            tournament_id,
            {"expected_tournament_version":
             get_tournament_version(tournament_id)},
            TD)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SEEDED"
        assert data["bracket_version"] == 1

        reg1 = get_registration(r1["id"])
        reg2 = get_registration(r2["id"])
        assert float(reg1["seed_score"]) == 50.0, \
            f"0.5*100 expected 50.0, got {reg1['seed_score']}"
        assert reg1["seed_position"] == 1
        assert float(reg2["seed_score"]) == 40.0
        assert reg2["seed_position"] == 2

        matches = get_matches(tournament_id)
        assert len(matches) == 1, "2-team bracket has exactly one match"
        assert matches[0]["home_registration_id"] == r1["id"]
        assert matches[0]["away_registration_id"] == r2["id"]

    def test_fund_accumulates_across_deposits_to_exact_equality(self):
        """PRD §3.1: "The prize pool is topped up by the same
        `OrganizerAdmin` calling the funding capability with an
        `amount_cents`, which adds the amount to `funded_pool_cents` and bumps
        the tournament's `version`."
        PRD §3.3: "`funded_pool_cents` must be greater than or equal to
        `prize_pool_target_cents`, with exact equality allowed"

        Design: Difficulty/boundary_precision_check/funding_exact_equality_passes
        """
        ctx = setup_registration_open_tournament(
            "Accum Cup", prize_pool_target_cents=500000)
        tournament_id = ctx["tournament"]["id"]
        fund_tournament(tournament_id, 200000)
        mid = get_tournament(tournament_id)
        assert mid["funded_pool_cents"] == 200000
        fund_tournament(tournament_id, 300000)
        topped = get_tournament(tournament_id)
        assert topped["funded_pool_cents"] == 500000, \
            "deposits must accumulate onto funded_pool_cents"
        assert topped["version"] == mid["version"] + 1

        set_clock("2026-08-10T00:00:00Z")
        advance_tournament(tournament_id, "REGISTRATION_LOCKED")
        seeded = generate_bracket(tournament_id)
        assert seeded["status"] == "SEEDED"
        assert seeded["bracket_version"] == 1

    def test_funding_one_cent_short_fails(self):
        """PRD §3.3: "the funded pool must be at least the advertised target
        — `funded_pool_cents` must be greater than or equal to
        `prize_pool_target_cents`, with exact equality allowed (else
        `ERR_PRIZE_POOL_UNDERFUNDED`)"

        Design: Corner/validations/funding_one_cent_short_fails
        """
        ctx = setup_locked_tournament(
            "Short Cup", prize_pool_target_cents=500000,
            fund_amounts=(499999,))
        tournament_id = ctx["tournament"]["id"]
        resp = api_client.generate_bracket(
            tournament_id,
            {"expected_tournament_version":
             get_tournament_version(tournament_id)},
            TD)
        validate_error(resp, ApiErrorId.ERR_PRIZE_POOL_UNDERFUNDED)
        tournament = get_tournament(tournament_id)
        assert tournament["status"] == "REGISTRATION_LOCKED"
        assert tournament["bracket_version"] == 0

    def test_insufficient_field_with_single_locked_registration(self):
        """PRD §3.3: "The gates are: at least 2 registrations must be in
        `LOCKED` (else `ERR_INSUFFICIENT_FIELD`)"
        PRD §3.3: "The advance cascades: every registration in `APPROVED`
        moves to `LOCKED`, and every registration still in `SUBMITTED` or
        `APPEALED` moves to `REJECTED` as unreviewed at lock."

        Design: Corner/validations/insufficient_field_with_single_locked_registration
        """
        specs = [
            {"handle": "p1", "dob": "2000-01-01", "team_name": "Alpha",
             "rank": 100},
            {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta",
             "rank": 80, "submit": False},
        ]
        ctx = setup_locked_tournament("Thin Cup", team_specs=specs)
        tournament_id = ctx["tournament"]["id"]
        resp = api_client.generate_bracket(
            tournament_id,
            {"expected_tournament_version":
             get_tournament_version(tournament_id)},
            TD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FIELD)
        assert get_registration(ctx["registrations"][1]["id"])[
            "status"] == "DRAFT", \
            "the lock cascade leaves DRAFT registrations untouched"


class TestSeedScoreSelector:

    def _locked_two_team(self, name, spec_a, spec_b):
        return setup_locked_tournament(name, team_specs=[spec_a, spec_b])

    def test_seed_score_tiebreak_by_qualifier_wins(self):
        """PRD §3.3: "the platform first computes `seed_score` for each
        `LOCKED` registration: half of `region_rank_points`, plus
        three-tenths of `prior_event_points`, plus one-fifth of
        `qualifier_wins` multiplied by 10, with the final score rounded
        half-up to 3 decimal places."
        PRD §3.3: "`seed_position` is then assigned by a selector policy that
        filters to `LOCKED` registrations, ranks by `seed_score` descending,
        breaks ties on `qualifier_wins` descending, then on the
        registration's `created_at` ascending, and finally on `team_name`
        ascending — never on `id`."

        Design: Corner/calculations/seed_score_tiebreak_by_qualifier_wins
        """
        ctx = self._locked_two_team(
            "Tie Cup",
            {"handle": "pa", "dob": "2000-01-01", "team_name": "TieA",
             "rank": 40, "prior": 20, "qwins": 4},
            {"handle": "pb", "dob": "2000-02-02", "team_name": "TieB",
             "rank": 50, "prior": 10, "qwins": 3})
        tournament_id = ctx["tournament"]["id"]
        generate_bracket(tournament_id)
        ra = get_registration(ctx["registrations"][0]["id"])
        rb = get_registration(ctx["registrations"][1]["id"])
        # 0.5*40 + 0.3*20 + 0.2*40 == 34.0 == 0.5*50 + 0.3*10 + 0.2*30
        assert float(ra["seed_score"]) == 34.0
        assert float(rb["seed_score"]) == 34.0
        assert ra["seed_position"] == 1, \
            "the 4-qualifier-win registration wins the tie-break over 3"
        assert rb["seed_position"] == 2

    def test_seed_score_full_tie_falls_to_created_at(self):
        """PRD §3.3: "`seed_position` is then assigned by a selector policy
        that filters to `LOCKED` registrations, ranks by `seed_score`
        descending, breaks ties on `qualifier_wins` descending, then on the
        registration's `created_at` ascending, and finally on `team_name`
        ascending — never on `id`."

        Design: Corner/calculations/seed_score_full_tie_falls_to_created_at
        """
        tournament = create_tournament("Tie2 Cup")
        advance_tournament(tournament["id"], "REGISTRATION_OPEN")
        pa = create_player("pa", "2000-01-01", "NA")
        pb = create_player("pb", "2000-02-02", "NA")
        # created_at ascending is ranked before team_name ascending; naming
        # the earlier registration "Zulu" makes the ordering load-bearing.
        set_clock("2026-08-01T00:00:00Z")
        ra = create_registration(tournament["id"], "Zulu", pa["id"],
                                 rank=50, prior=10, qwins=3)
        set_clock("2026-08-01T00:00:01Z")
        rb = create_registration(tournament["id"], "Alpha", pb["id"],
                                 rank=50, prior=10, qwins=3)
        for reg, player in ((ra, pa), (rb, pb)):
            add_roster_slot(reg["id"], player["id"], "STARTER")
            submit_registration(reg["id"])
            review_registration(reg["id"], "APPROVE")
        fund_tournament(tournament["id"], 100000)
        set_clock("2026-08-10T00:00:00Z")
        advance_tournament(tournament["id"], "REGISTRATION_LOCKED")

        generate_bracket(tournament["id"])
        ra_after = get_registration(ra["id"])
        rb_after = get_registration(rb["id"])
        assert float(ra_after["seed_score"]) == 34.0
        assert float(rb_after["seed_score"]) == 34.0
        assert ra_after["qualifier_wins"] == rb_after["qualifier_wins"] == 3
        assert ra_after["seed_position"] == 1, \
            "earlier created_at takes the higher seed (team_name is the later tie-break)"
        assert rb_after["seed_position"] == 2


class TestBracketConstruction:

    def test_bye_walkover_auto_advances_top_seed(self):
        """PRD §3.3: "Seeds greater than `n` do not exist; a round-1 match
        whose away seed exceeds `n` is a walkover, created directly in
        `FORFEIT` status with the home seed as winner, and the winner
        propagates immediately to the next match's empty slot (home slot
        first, then away)."
        PRD §3.3: "Each match's `next_match_id` points at round `r+1` slot
        equal to the ceiling of `k` divided by 2; the final's `next_match_id`
        is null. A match created with both participants null stays `PENDING`
        (TBD)."

        Design: Corner/calculations/bye_walkover_auto_advances_top_seed
        """
        ctx = setup_seeded_tournament("Bye Cup", team_count=3)
        r1, r2, r3 = ctx["registrations"]
        matches = ctx["matches"]
        assert len(matches) == 3, "3 LOCKED registrations pad to a size-4 bracket"
        m1, m2, mf = matches
        assert (m1["bracket_round"], m1["bracket_slot"]) == (1, 1)
        assert m1["status"] == "FORFEIT"
        assert m1["winner_registration_id"] == r1["id"]
        assert m1["away_registration_id"] is None
        assert (m2["bracket_round"], m2["bracket_slot"]) == (1, 2)
        assert m2["status"] == "PENDING"
        assert m2["home_registration_id"] == r2["id"]
        assert m2["away_registration_id"] == r3["id"]
        assert mf["bracket_round"] == 2
        assert mf["status"] == "PENDING"
        assert mf["home_registration_id"] == r1["id"], \
            "the walkover winner propagates into the final's home slot"
        assert mf["away_registration_id"] is None
        assert mf["next_match_id"] is None
        assert m1["next_match_id"] == mf["id"]
        assert m2["next_match_id"] == mf["id"]


class TestGenerateBracketErrors:

    def test_state_error_beats_funding_error_on_generate(self):
        """PRD §2.9: "Then come per-entity state-machine from-state checks."
        PRD §2.9: "Business-fiscal rules (bracket field size, prize-pool
        funding, open integrity cases, payout-final) come after temporal."
        PRD §3.3: "Bracket generation is allowed from `REGISTRATION_LOCKED`
        (initial build) and from `SEEDED` (regeneration, which supersedes the
        prior bracket)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bracket_gate
        """
        ctx = setup_registration_open_tournament(
            "Priority Cup", prize_pool_target_cents=500000)
        tournament_id = ctx["tournament"]["id"]
        # funded_pool_cents is 0 against a 500000 target AND the tournament
        # is in REGISTRATION_OPEN: the state error must surface.
        resp = api_client.generate_bracket(
            tournament_id,
            {"expected_tournament_version":
             get_tournament_version(tournament_id)},
            TD)
        validate_error(resp, ApiErrorId.ERR_INVALID_TOURNAMENT_STATUS)
        tournament = get_tournament(tournament_id)
        assert tournament["status"] == "REGISTRATION_OPEN"
        assert tournament["bracket_version"] == 0

    def test_state_error_on_generate_from_draft(self):
        """PRD §3.3: "Bracket generation is allowed from
        `REGISTRATION_LOCKED` (initial build) and from `SEEDED`
        (regeneration, which supersedes the prior bracket)."
        PRD §2.7: "requesting a transition from a state that does not permit
        it is rejected with the machine's specific invalid-status error
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bracket_gate
        """
        tournament = create_tournament("DraftGate Cup",
                                       prize_pool_target_cents=500000)
        resp = api_client.generate_bracket(
            tournament["id"],
            {"expected_tournament_version":
             get_tournament_version(tournament["id"])},
            TD)
        validate_error(resp, ApiErrorId.ERR_INVALID_TOURNAMENT_STATUS)
        after = get_tournament(tournament["id"])
        assert after["status"] == "DRAFT"
        assert after["bracket_version"] == 0

    def test_player_cannot_generate_bracket_returns_forbidden(self):
        """PRD §2.1: "A request whose role is recognized but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)
        per the endpoint's authorized role list in §4."
        PRD §4: "| POST | /api/tournaments/{id}/generate-bracket | Seed
        LOCKED registrations and build the match tree; regeneration
        supersedes (OCC-guarded) | TournamentDirector |"

        Design: Corner/rbac/player_cannot_generate_bracket_returns_forbidden
        """
        tournament = create_tournament("RBAC Cup")
        player = create_player("p1", "2000-01-01", "NA")
        resp = api_client.generate_bracket(
            tournament["id"],
            {"expected_tournament_version": tournament["version"]},
            make_player_headers(player["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_tournament(tournament["id"])["status"] == "DRAFT"


class TestBracketOptimisticConcurrency:

    def test_occ_stale_version_on_generate_bracket(self):
        """PRD §2.6: "Two write endpoints are guarded by optimistic
        concurrency control: bracket generation (initial and regeneration)
        and payout computation."
        PRD §2.6: "If the tournament's current `version` has advanced since
        the client last read it — for example because another operator just
        funded the pool or locked the roster — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and no state change occurs."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_generate_bracket
        """
        ctx = setup_locked_tournament("OCC Cup", fund_amounts=(60000,))
        tournament_id = ctx["tournament"]["id"]
        stale_version = get_tournament_version(tournament_id)
        fund_tournament(tournament_id, 40000)

        resp = api_client.generate_bracket(
            tournament_id, {"expected_tournament_version": stale_version}, TD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_tournament(tournament_id)["bracket_version"] == 0

        fresh = get_tournament_version(tournament_id)
        seeded = generate_bracket(tournament_id, fresh)
        assert seeded["status"] == "SEEDED"
        assert seeded["bracket_version"] == 1
