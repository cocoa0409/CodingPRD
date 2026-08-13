"""Weighted tabulation: per-instruction rounding, vote standards, abstain
filtering, and the UNOFFICIAL/CERTIFIED variant flip (PRD §2.8, §2.9, §3.4)."""
from test_helpers import (
    validate_success,
    assert_tabulation_read,
    setup_voting_open, setup_meeting_in_progress,
    cast_vote,
    make_inspector_headers,
)


class TestUnofficialVsCertifiedOutcomeFlip:
    """On identical raw data, the CERTIFIED lens excludes OPEN-challenged votes
    and can flip the projected outcome."""

    def _setup_flip(self, api):
        """600 FOR / 2500 AGAINST / 2000 FOR-with-OPEN-challenge, all COMMON,
        on a MAJORITY_OF_VOTES_CAST proposal; meeting convened."""
        ctx = setup_meeting_in_progress(
            account_specs=[{"shares_held": 600}, {"shares_held": 2500}, {"shares_held": 2000}],
            vote_specs=[
                {"account": 0, "choice": "FOR"},
                {"account": 1, "choice": "AGAINST"},
                {"account": 2, "choice": "FOR"},
            ],
        )
        m_id = ctx["meeting"]["id"]
        challenged_vote = ctx["votes"][2]
        resp = api.create_vote_challenge(
            {
                "meeting_id": m_id,
                "vote_instruction_id": challenged_vote["id"],
                "reason": "Solicitation defect alleged",
            },
            make_inspector_headers("insp-1"),
        )
        validate_success(resp, 201)
        return ctx["proposals"][0]["id"]

    def test_unofficial_tabulation_includes_challenged_vote(self, api, inspector_headers):
        """PRD §3.4: "the `CERTIFIED` variant additionally excludes any
        instruction with an `OPEN` challenge, while `UNOFFICIAL` includes
        them".
        PRD §3.4: "under `MAJORITY_OF_VOTES_CAST` the outcome is `PASS` when at
        least one vote has been cast and twice `for_votes` exceeds
        `votes_cast`, otherwise `FAIL`"

        Design: Difficulty/dual_variant_calc/tabulation_unofficial_vs_certified_outcome_flip
        """
        p_id = self._setup_flip(api)
        data = validate_success(api.get_tabulation(p_id, inspector_headers, variant="UNOFFICIAL"), 200)
        assert_tabulation_read(data)
        assert data["variant"] == "UNOFFICIAL"
        assert data["for_votes"] == 2600, f"600 + 2000 challenged-but-valid: {data['for_votes']}"
        assert data["against_votes"] == 2500
        assert data["votes_cast"] == 5100
        assert data["projected_outcome"] == "PASS", "2600*2 = 5200 > 5100 must project PASS"

    def test_certified_tabulation_excludes_challenged_vote_and_flips(self, api, inspector_headers):
        """PRD §2.8: "The `CERTIFIED` variant excludes votes with an open
        challenge, so it can reach a different outcome than `UNOFFICIAL` on
        identical raw data."

        Design: Difficulty/dual_variant_calc/tabulation_unofficial_vs_certified_outcome_flip
        """
        p_id = self._setup_flip(api)
        certified = validate_success(api.get_tabulation(p_id, inspector_headers, variant="CERTIFIED"), 200)
        assert_tabulation_read(certified)
        assert certified["variant"] == "CERTIFIED"
        assert certified["for_votes"] == 600, (
            f"CERTIFIED excludes the OPEN-challenged 2000: {certified['for_votes']}"
        )
        assert certified["against_votes"] == 2500
        assert certified["votes_cast"] == 3100
        assert certified["projected_outcome"] == "FAIL", "600*2 = 1200 < 3100 must project FAIL"
        unofficial = validate_success(api.get_tabulation(p_id, inspector_headers, variant="UNOFFICIAL"), 200)
        assert unofficial["projected_outcome"] != certified["projected_outcome"], (
            "identical raw data must produce opposite outcomes across the two lenses"
        )


class TestPerInstructionRounding:
    """Nested rounding: round half up per instruction BEFORE summation."""

    def _setup_preferred_pair(self):
        ctx = setup_voting_open(
            account_specs=[
                {"account_number": "P-1001", "share_class": "PREFERRED", "shares_held": 1001},
                {"account_number": "P-1002", "share_class": "PREFERRED", "shares_held": 1001},
            ],
            proposal_specs=[{"title": "Ratify auditor", "proposal_type": "RATIFICATION"}],
        )
        m_id = ctx["meeting"]["id"]
        p_id = ctx["proposals"][0]["id"]
        cast_vote(m_id, p_id, ctx["accounts"][0], choice="FOR")
        cast_vote(m_id, p_id, ctx["accounts"][1], choice="FOR")
        return p_id

    def test_per_instruction_rounding_then_sum(self, api, proxy_admin_headers):
        """PRD §2.9: "All tabulation arithmetic converts each vote instruction
        to a whole number of weighted votes by multiplying its `shares_voted`
        by the weight of its account's class and rounding the product half up
        to an integer; this per-instruction rounding happens **before** any
        summation, and that order is pinned — summing first and rounding the
        total is not an acceptable substitute."

        Design: Difficulty/combinatorial_formula/weighted_tabulation_per_instruction_rounding_order
        """
        p_id = self._setup_preferred_pair()
        data = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert_tabulation_read(data)
        assert data["for_votes"] == 1002, (
            f"round_half_up(1001*0.5)=501 per instruction; 501+501=1002, got {data['for_votes']}"
        )

    def test_per_instruction_rounding_rejects_sum_then_round(self, api, proxy_admin_headers):
        """PRD §2.9: "this per-instruction rounding happens **before** any
        summation, and that order is pinned — summing first and rounding the
        total is not an acceptable substitute."

        Design: Difficulty/combinatorial_formula/weighted_tabulation_per_instruction_rounding_order
        """
        p_id = self._setup_preferred_pair()
        data = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert data["votes_cast"] == 1002, (
            f"votes_cast sums the per-instruction rounded weights: {data['votes_cast']}"
        )
        assert data["for_votes"] != 1001, (
            "sum-then-round would yield round(2002*0.5)=1001 — the pinned order forbids it"
        )


class TestVoteStandards:
    def test_majority_of_votes_cast_exact_tie_fails(self, api, proxy_admin_headers):
        """PRD §3.4: "under `MAJORITY_OF_VOTES_CAST` the outcome is `PASS` when
        at least one vote has been cast and twice `for_votes` exceeds
        `votes_cast`, otherwise `FAIL`"

        Design: Corner/calculations/majority_of_votes_cast_exact_tie_fails
        """
        ctx = setup_voting_open(account_specs=[{"shares_held": 2500}, {"shares_held": 2500}])
        m_id = ctx["meeting"]["id"]
        p_id = ctx["proposals"][0]["id"]
        cast_vote(m_id, p_id, ctx["accounts"][0], choice="FOR")
        cast_vote(m_id, p_id, ctx["accounts"][1], choice="AGAINST")
        data = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert_tabulation_read(data)
        assert data["votes_cast"] == 5000
        assert data["projected_outcome"] == "FAIL", (
            "an exact tie (2500*2 == 5000) is not strictly greater — FAIL"
        )

    def test_abstain_excluded_from_votes_cast(self, api, proxy_admin_headers):
        """PRD §3.4: "The totals reported are `for_votes`, `against_votes`,
        `abstain_votes`, and `withhold_votes`, plus `votes_cast`, which counts
        only `FOR` and `AGAINST` votes — abstentions and withholds are not
        votes cast."

        Design: Corner/calculations/abstain_excluded_from_votes_cast
        """
        ctx = setup_voting_open(account_specs=[
            {"shares_held": 100}, {"shares_held": 900}, {"shares_held": 50},
        ])
        m_id = ctx["meeting"]["id"]
        p_id = ctx["proposals"][0]["id"]
        cast_vote(m_id, p_id, ctx["accounts"][0], choice="FOR")
        cast_vote(m_id, p_id, ctx["accounts"][1], choice="ABSTAIN")
        cast_vote(m_id, p_id, ctx["accounts"][2], choice="AGAINST")
        data = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert_tabulation_read(data)
        assert data["votes_cast"] == 150, f"abstain excluded from cast: {data['votes_cast']}"
        assert data["abstain_votes"] == 900
        assert data["projected_outcome"] == "PASS", "100*2 = 200 > 150 must project PASS"

    def test_majority_of_outstanding_strict_half_boundary(self, api, proxy_admin_headers):
        """PRD §3.4: "under `MAJORITY_OF_OUTSTANDING` it is `PASS` when twice
        `for_votes` exceeds the meeting's `outstanding_shares`, otherwise
        `FAIL`"

        Design: Corner/calculations/majority_of_outstanding_strict_half_boundary
        """
        ctx = setup_voting_open(
            account_specs=[{"shares_held": 5000}, {"shares_held": 1}],
            proposal_specs=[{"title": "Bylaw amendment",
                             "proposal_type": "SHAREHOLDER_PROPOSAL",
                             "vote_standard": "MAJORITY_OF_OUTSTANDING"}],
        )
        m_id = ctx["meeting"]["id"]
        p_id = ctx["proposals"][0]["id"]
        cast_vote(m_id, p_id, ctx["accounts"][0], choice="FOR")
        half = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert half["for_votes"] == 5000
        assert half["projected_outcome"] == "FAIL", (
            "exactly half: 5000*2 > 10000 is false — FAIL"
        )
        cast_vote(m_id, p_id, ctx["accounts"][1], choice="FOR")
        over = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert over["for_votes"] == 5001
        assert over["projected_outcome"] == "PASS", "5001*2 = 10002 > 10000 — PASS"

    def test_plurality_compares_for_against_withhold(self, api, proxy_admin_headers):
        """PRD §3.4: "under `PLURALITY` it is `PASS` when `for_votes` exceeds
        `withhold_votes`, otherwise `FAIL`."

        Design: Corner/calculations/plurality_compares_for_against_withhold
        """
        ctx = setup_voting_open(
            account_specs=[{"shares_held": 100}, {"shares_held": 101}],
            proposal_specs=[{"title": "Elect director J. Doe",
                             "proposal_type": "DIRECTOR_ELECTION",
                             "vote_standard": "PLURALITY"}],
        )
        m_id = ctx["meeting"]["id"]
        p_id = ctx["proposals"][0]["id"]
        cast_vote(m_id, p_id, ctx["accounts"][0], choice="FOR")
        cast_vote(m_id, p_id, ctx["accounts"][1], choice="WITHHOLD")
        data = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert_tabulation_read(data)
        assert data["withhold_votes"] == 101
        assert data["votes_cast"] == 100, "withhold is not a vote cast"
        assert data["projected_outcome"] == "FAIL", "for 100 not > withhold 101 — FAIL"


class TestZeroVotesCast:
    """An empty vote set must resolve to FAIL via the zero-guard."""

    def _setup_no_votes(self):
        return setup_voting_open()

    def test_zero_votes_cast_reports_zero_totals(self, api, proxy_admin_headers):
        """PRD §3.4: "`votes_cast`, which counts only `FOR` and `AGAINST`
        votes — abstentions and withholds are not votes cast."

        Design: Difficulty/boundary_precision_check/zero_votes_cast_proposal_fails_without_division
        """
        ctx = self._setup_no_votes()
        p_id = ctx["proposals"][0]["id"]
        data = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert_tabulation_read(data)
        assert data["votes_cast"] == 0
        assert data["for_votes"] == 0
        assert data["against_votes"] == 0

    def test_zero_votes_cast_outcome_is_fail(self, api, proxy_admin_headers):
        """PRD §3.4: "under `MAJORITY_OF_VOTES_CAST` the outcome is `PASS` when
        at least one vote has been cast and twice `for_votes` exceeds
        `votes_cast`, otherwise `FAIL`"

        Design: Difficulty/boundary_precision_check/zero_votes_cast_proposal_fails_without_division
        """
        ctx = self._setup_no_votes()
        p_id = ctx["proposals"][0]["id"]
        data = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert data["projected_outcome"] == "FAIL", (
            "a majority of an empty cast is not attainable — the zero-guard yields FAIL"
        )
