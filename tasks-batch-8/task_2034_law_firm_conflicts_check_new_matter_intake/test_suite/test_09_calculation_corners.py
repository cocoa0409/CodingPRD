"""Calculation corners: the 670 credit-band boundary, the retainer floor clamp
under the default SUBPRIME band, and the inclusive match threshold."""
from test_helpers import (
    TEST_USERS,
    add_roster_party,
    api_client,
    create_attorney,
    create_letter,
    create_matter,
    create_party,
    get_deposit,
    issue_letter,
    record_credit_assessment,
    run_conflict_check,
    setup_basic_matter,
    validate_success,
)

INTAKE = TEST_USERS["intake_specialist_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestCreditBandStandardBoundary670:
    def test_score_670_is_standard(self):
        """PRD §3.8: "The server stamps `assessed_at` from the logical clock and
        derives the `band`: `PRIME` when the score is at least 740, `STANDARD`
        from 670 through 739, and `SUBPRIME` below 670 — so 740 is `PRIME`, 739
        is `STANDARD`, 670 is `STANDARD`, and 669 is `SUBPRIME`."

        Design: Corner/calculations/c_credit_band_standard_boundary_670
        """
        _, _, matter = setup_basic_matter("Band Client Inc")
        assessment = record_credit_assessment(matter["id"], 670)
        assert assessment["band"] == "STANDARD"

    def test_score_669_is_subprime(self):
        """PRD §2.7: "Credit bands use inclusive lower bounds: 740 is `PRIME`,
        739 is `STANDARD`, 670 is `STANDARD`, 669 is `SUBPRIME`."

        Design: Corner/calculations/c_credit_band_standard_boundary_670
        """
        _, _, matter = setup_basic_matter("Band Client Inc")
        assessment = record_credit_assessment(matter["id"], 669)
        assert assessment["band"] == "SUBPRIME"


class TestRetainerFloorClampDefaultBand:
    def test_no_assessment_defaults_subprime_and_floor_clamps(self):
        """PRD §3.8: "The governing band is the band of the valid assessment
        with the latest `assessed_at`, with a tie on `assessed_at` broken in
        favor of the later `created_at`; when no valid assessment exists, the
        band defaults conservatively to `SUBPRIME`."
        PRD §3.8: "The raw requirement is the fee base multiplied by the band's
        months multiplier — one for `PRIME`, two for `STANDARD`, three for
        `SUBPRIME` — and the stored `required_cents` is that raw value clamped
        to a floor of 50000 cents and a ceiling of 10000000 cents."

        Design: Corner/calculations/c_retainer_floor_clamp_default_band
        """
        party, atty, matter = setup_basic_matter("Floor Client Inc")
        letter = create_letter(
            matter,
            atty,
            fee_lines=[{"description": "f", "hours": 1.0, "rate_cents": 100}],
        )
        assert letter["fee_estimate_cents"] == 100
        issue_letter(letter["id"], atty)
        deposit = get_deposit(matter["id"])
        assert deposit["required_cents"] == 50000, (
            f"raw 100 x 3 = 300 clamped up to the 50000 floor; band defaulted "
            f"to SUBPRIME without any assessment; got {deposit['required_cents']}"
        )
        assert deposit["status"] == "PENDING"


class TestMatchThresholdInclusiveBoundary:
    def _setup_token_overlap_80(self):
        """Query 'Alpha Beta Gamma Delta' (4 tokens) vs candidate 'Alpha Beta
        Gamma Delta Eps' (5 tokens): floor(100*4/5) = 80."""
        p_o = create_party("Orion Client LLC")
        p5 = create_party("Alpha Beta Gamma Delta Eps")
        p4 = create_party("Alpha Beta Gamma Delta")
        atty = create_attorney()
        m0 = create_matter(p_o["id"], atty["id"], matter_title="M0")
        add_roster_party(m0["id"], p5["id"], "RELATED")
        m1 = create_matter(p4["id"], atty["id"], matter_title="M1")
        return m1

    def test_score_80_meets_threshold_80_inclusive(self):
        """PRD §3.4: "Token overlap between two names is the floored integer of
        one hundred times the number of tokens shared by both names divided by
        the larger of the two token counts, and it is counted only when that
        value is at least 80 — below that floor it contributes 0."
        PRD §3.4: "A candidate becomes a hit exactly when its score is greater
        than or equal to the `match_threshold` — the boundary is inclusive."

        Design: Corner/calculations/c_match_threshold_inclusive_boundary
        """
        m1 = self._setup_token_overlap_80()
        check = run_conflict_check(m1["id"], "STRICT", match_threshold=80)
        assert check["hit_count"] == 1, (
            f"score 80 >= threshold 80 (inclusive); got {check['hit_count']}"
        )

    def test_score_80_below_threshold_81_produces_no_hit(self):
        """PRD §3.4: "A candidate becomes a hit exactly when its score is
        greater than or equal to the `match_threshold` — the boundary is
        inclusive."

        Design: Corner/calculations/c_match_threshold_inclusive_boundary
        """
        m1 = self._setup_token_overlap_80()
        check = run_conflict_check(m1["id"], "STRICT", match_threshold=81)
        assert check["hit_count"] == 0, (
            f"score 80 < threshold 81; got {check['hit_count']}"
        )
