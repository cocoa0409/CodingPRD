"""Quorum computation: dual variants, contested floor, basis-point boundary,
walk-in shares, and input-set filtering (PRD §2.8, §2.9, §3.7)."""
from test_helpers import (
    validate_success,
    assert_quorum_read,
    setup_voting_open, setup_meeting_in_progress,
    cast_vote,
    make_inspector_headers,
)


class TestProvisionalVsFinalWithOpenChallenge:
    """Identical raw vote data must read differently through the two quorum
    lenses when a VALIDATED vote carries an OPEN challenge."""

    def _setup_challenged_quorum(self, api):
        """4500 + 1500 COMMON voted FOR; the 1500-share vote carries an OPEN
        challenge; meeting convened. Returns (meeting_id, challenged_vote_id)."""
        ctx = setup_meeting_in_progress(
            account_specs=[{"shares_held": 4500}, {"shares_held": 1500}],
            vote_specs=[{"account": 0, "choice": "FOR"}, {"account": 1, "choice": "FOR"}],
        )
        m_id = ctx["meeting"]["id"]
        challenged_vote = ctx["votes"][1]
        resp = api.create_vote_challenge(
            {
                "meeting_id": m_id,
                "vote_instruction_id": challenged_vote["id"],
                "reason": "Beneficial ownership dispute",
            },
            make_inspector_headers("insp-1"),
        )
        validate_success(resp, 201)
        return m_id, challenged_vote["id"]

    def test_provisional_quorum_includes_open_challenged_votes(self, api, inspector_headers):
        """PRD §3.7: "For the `PROVISIONAL` variant, shares present are the sum
        of `shares_voted` across the meeting's `VALIDATED` instructions,
        including any that carry an open challenge."
        PRD §3.7: "`quorum_met` is true exactly when `quorum_pct_bp` is at
        least `threshold_bp`."

        Design: Difficulty/dual_variant_calc/quorum_provisional_includes_open_challenged_final_excludes
        """
        m_id, _ = self._setup_challenged_quorum(api)
        resp = api.get_quorum(m_id, inspector_headers, variant="PROVISIONAL")
        data = validate_success(resp, 200)
        assert_quorum_read(data)
        assert data["variant"] == "PROVISIONAL"
        assert data["shares_present"] == 6000, (
            f"PROVISIONAL counts the challenged-but-valid vote: {data['shares_present']}"
        )
        assert data["quorum_pct_bp"] == 6000
        assert data["threshold_bp"] == 5000
        assert data["quorum_met"] is True, "6000bp >= 5000bp must satisfy quorum"

    def test_final_quorum_excludes_open_challenged_votes(self, api, inspector_headers):
        """PRD §2.8: "The `FINAL` variant excludes votes that are under an
        open challenge and adds shares physically present at the meeting
        without a voted proxy; the `PROVISIONAL` variant includes
        challenged-but-still-valid votes and never counts walk-in shares."

        Design: Difficulty/dual_variant_calc/quorum_provisional_includes_open_challenged_final_excludes
        """
        m_id, _ = self._setup_challenged_quorum(api)
        resp = api.get_quorum(m_id, inspector_headers, variant="FINAL")
        data = validate_success(resp, 200)
        assert_quorum_read(data)
        assert data["variant"] == "FINAL"
        assert data["shares_present"] == 4500, (
            f"FINAL excludes the OPEN-challenged 1500-share vote: {data['shares_present']}"
        )
        assert data["quorum_pct_bp"] == 4500
        assert data["threshold_bp"] == 5000
        assert data["quorum_met"] is False, "4500bp < 5000bp must fail quorum"
        # The divergence between the two lenses is exactly the challenged vote.
        prov = validate_success(api.get_quorum(m_id, inspector_headers, variant="PROVISIONAL"), 200)
        assert prov["shares_present"] - data["shares_present"] == 1500


class TestContestedFloor:
    """A contested meeting's effective threshold is max(threshold_pct, 1/2)."""

    def test_contested_threshold_floor_applies(self, api, proxy_admin_headers):
        """PRD §3.7: "In both variants the effective threshold fraction is the
        meeting's `quorum_threshold_pct` — except that for a `CONTESTED`
        meeting the effective threshold is the greater of
        `quorum_threshold_pct` and one half."

        Design: Difficulty/combinatorial_formula/quorum_contested_floor_max_branch
        """
        ctx = setup_voting_open(
            account_specs=[{"shares_held": 4000}],
            proposal_specs=[{"title": "Director election", "proposal_type": "DIRECTOR_ELECTION",
                             "vote_standard": "PLURALITY"}],
            meeting_type="CONTESTED", meeting_mode="HYBRID", quorum_threshold_pct=0.3,
        )
        m_id = ctx["meeting"]["id"]
        cast_vote(m_id, ctx["proposals"][0]["id"], ctx["accounts"][0], choice="FOR")
        data = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="PROVISIONAL"), 200)
        assert_quorum_read(data)
        assert data["threshold_bp"] == 5000, (
            f"max(0.30, 0.50) floor applies for CONTESTED: {data['threshold_bp']}"
        )
        assert data["quorum_pct_bp"] == 4000

    def test_contested_floor_flips_quorum_met_vs_annual(self, api, proxy_admin_headers):
        """PRD §3.7: "for a `CONTESTED` meeting the effective threshold is the
        greater of `quorum_threshold_pct` and one half"; "`quorum_met` is true
        exactly when `quorum_pct_bp` is at least `threshold_bp`."

        Design: Difficulty/combinatorial_formula/quorum_contested_floor_max_branch
        """
        ctx = setup_voting_open(
            account_specs=[{"shares_held": 4000}],
            proposal_specs=[{"title": "Director election", "proposal_type": "DIRECTOR_ELECTION",
                             "vote_standard": "PLURALITY"}],
            meeting_type="CONTESTED", meeting_mode="HYBRID", quorum_threshold_pct=0.3,
        )
        contested_id = ctx["meeting"]["id"]
        cast_vote(contested_id, ctx["proposals"][0]["id"], ctx["accounts"][0], choice="FOR")
        contested = validate_success(
            api.get_quorum(contested_id, proxy_admin_headers, variant="PROVISIONAL"), 200
        )
        assert contested["quorum_met"] is False, "4000bp < 5000bp floored threshold"

        # Identical numbers on an ANNUAL meeting: no floor applies.
        ctx2 = setup_voting_open(
            account_specs=[{"shares_held": 4000}],
            proposal_specs=[{"title": "Say on pay"}],
            meeting_type="ANNUAL", quorum_threshold_pct=0.3,
        )
        annual_id = ctx2["meeting"]["id"]
        cast_vote(annual_id, ctx2["proposals"][0]["id"], ctx2["accounts"][0], choice="FOR")
        annual = validate_success(
            api.get_quorum(annual_id, proxy_admin_headers, variant="PROVISIONAL"), 200
        )
        assert annual["threshold_bp"] == 3000, "ANNUAL uses the configured 0.30 threshold"
        assert annual["quorum_met"] is True, "4000bp >= 3000bp must satisfy quorum"


class TestThresholdBoundary:
    """The quorum comparison is inclusive: pct_bp >= threshold_bp."""

    def _setup_exact_boundary(self):
        return setup_meeting_in_progress(
            account_specs=[{"shares_held": 5000}],
            vote_specs=[{"account": 0, "choice": "FOR"}],
        )

    def test_quorum_exactly_at_threshold_is_met(self, api, proxy_admin_headers):
        """PRD §3.7: "`quorum_met` is true exactly when `quorum_pct_bp` is at
        least `threshold_bp`."

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_threshold_is_met
        """
        ctx = self._setup_exact_boundary()
        m_id = ctx["meeting"]["id"]
        data = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="FINAL"), 200)
        assert_quorum_read(data)
        assert data["quorum_pct_bp"] == 5000
        assert data["threshold_bp"] == 5000
        assert data["quorum_met"] is True, "the boundary comparison is inclusive (>=)"

    def test_conclude_succeeds_at_exact_quorum_boundary(self, api, proxy_admin_headers):
        """PRD §3.7: "the `FINAL` quorum variant — walk-ins included — must be
        met at that moment, or the conclusion is rejected with
        `ERR_QUORUM_NOT_MET` and the meeting stays in progress. A successful
        conclusion moves the meeting `MEETING_IN_PROGRESS → MEETING_HELD`".

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_threshold_is_met
        """
        ctx = self._setup_exact_boundary()
        m_id = ctx["meeting"]["id"]
        concluded = api.conclude(m_id, proxy_admin_headers, {})
        data = validate_success(concluded, 200)
        assert data["status"] == "MEETING_HELD", (
            f"conclude at the exact 5000bp boundary must succeed, got {data['status']}"
        )


class TestFinalVariantWalkInsAndDefaults:
    def test_final_quorum_includes_walk_in_shares_at_conclude(self, api, proxy_admin_headers):
        """PRD §3.7: "For the `FINAL` variant, instructions with an `OPEN`
        challenge are excluded and the meeting's `walk_in_shares` are added to
        the sum."
        PRD §3.7: "The administrator concludes with an optional
        `walk_in_shares` figure (defaulting to zero), which is stored on the
        meeting".

        Design: Corner/calculations/final_quorum_includes_walk_in_shares_at_conclude
        """
        ctx = setup_meeting_in_progress(
            account_specs=[{"shares_held": 4500}],
            vote_specs=[{"account": 0, "choice": "FOR"}],
            meeting_mode="HYBRID",
        )
        m_id = ctx["meeting"]["id"]
        # 4500 voted alone would be 4500bp < 5000bp; 500 walk-ins close the gap.
        concluded = api.conclude(m_id, proxy_admin_headers, {"walk_in_shares": 500})
        data = validate_success(concluded, 200)
        assert data["status"] == "MEETING_HELD"
        assert data["walk_in_shares"] == 500, "walk_in_shares is stored on the meeting"
        quorum = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="FINAL"), 200)
        assert quorum["shares_present"] == 5000, (
            f"FINAL adds walk-ins: 4500 + 500 = {quorum['shares_present']}"
        )
        assert quorum["quorum_met"] is True

    def test_quorum_default_variant_is_provisional(self, api, proxy_admin_headers):
        """PRD §2.8: "Quorum is computed as `PROVISIONAL` (the default read
        variant while voting is in progress)"; "Both computed reads accept a
        `variant` query parameter selecting the lens; omitting it yields the
        default variant named above."

        Design: Corner/calculations/quorum_default_variant_is_provisional
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        cast_vote(m_id, ctx["proposals"][0]["id"], ctx["accounts"][0], choice="FOR")
        data = validate_success(api.get_quorum(m_id, proxy_admin_headers), 200)
        assert_quorum_read(data)
        assert data["variant"] == "PROVISIONAL", "omitted variant must default to PROVISIONAL"
        assert data["shares_present"] == 6000

    def test_superseded_vote_does_not_double_count_quorum(self, api, proxy_admin_headers):
        """PRD §3.4: "If a newer valid instruction arrives for the same account
        and proposal, the older one transitions `VALIDATED → SUPERSEDED`
        automatically, so at most one instruction per account-and-proposal is
        live."
        PRD §3.7: "For the `PROVISIONAL` variant, shares present are the sum of
        `shares_voted` across the meeting's `VALIDATED` instructions".

        Design: Corner/calculations/superseded_vote_does_not_double_count_quorum
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        cast_vote(m_id, proposal["id"], account, choice="FOR", channel="INTERNET")
        cast_vote(m_id, proposal["id"], account, choice="AGAINST", channel="MAIL")
        quorum = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="PROVISIONAL"), 200)
        assert quorum["shares_present"] == 6000, (
            f"superseded instruction must not double-count: {quorum['shares_present']}"
        )
        tab = validate_success(api.get_tabulation(proposal["id"], proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert tab["for_votes"] == 0 and tab["against_votes"] == 6000, (
            "latest valid vote wins: the AGAINST re-vote is the only live instruction"
        )
