"""Match-scoring variant divergence and fee-estimate rounding order."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_engagement_letter_payload,
    create_party,
    get_success_data,
    list_hits_for_check,
    make_responsible_attorney_headers,
    run_conflict_check,
    set_clock,
    setup_basic_matter,
    TEST_USERS,
    validate_success,
)
from test_helpers import (
    add_roster_party,
    create_attorney,
    create_matter,
    get_deposit,
    issue_letter,
    record_credit_assessment,
)

INTAKE = TEST_USERS["intake_specialist_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestDualVariantStrictVsPhoneticHitSet:
    def test_strict_check_ignores_phonetic_channel(self):
        """PRD §3.4: "Under the `STRICT` variant the base score is simply the
        higher of the direct and alias channels; the phonetic channel is ignored,
        so names that sound alike but share no tokens — "Smyth" versus "Smith" —
        score 0 and produce no hit."

        Design: Difficulty/dual_variant_calc/dual_variant_strict_vs_phonetic_hit_set
        """
        p_smyth = create_party("Smyth & Co")
        p_smith = create_party("Smith Company")
        atty = create_attorney()
        create_matter(p_smyth["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_smith["id"], atty["id"], matter_title="M1")

        check = run_conflict_check(m1["id"], "STRICT")
        assert check["hit_count"] == 0, (
            f"STRICT must ignore the phonetic channel: 'smith' vs 'smyth' share "
            f"no tokens; got hit_count={check['hit_count']}"
        )

    def test_phonetic_check_adds_soundex_channel_hit(self):
        """PRD §3.4: "Under the `PHONETIC` variant a third channel contributes 70
        whenever the query string's Soundex key equals the candidate's
        `phonetic_key`, and the base score is the best of the three channels —
        identical inputs can therefore yield different hit sets under the two
        variants."

        Design: Difficulty/dual_variant_calc/dual_variant_strict_vs_phonetic_hit_set
        """
        p_smyth = create_party("Smyth & Co")
        p_smith = create_party("Smith Company")
        atty = create_attorney()
        m0 = create_matter(p_smyth["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_smith["id"], atty["id"], matter_title="M1")

        check = run_conflict_check(m1["id"], "PHONETIC")
        assert check["hit_count"] == 1, (
            f"PHONETIC must add the soundex channel (70 >= default threshold 60); "
            f"got hit_count={check['hit_count']}"
        )
        hits = list_hits_for_check(check["id"])
        assert hits[0]["match_score"] == 70, (
            f"phonetic channel scores 70, got {hits[0]['match_score']}"
        )
        assert hits[0]["matched_party_id"] == p_smyth["id"]
        assert hits[0]["matched_matter_id"] == m0["id"]


class TestDualVariantRecentVsBestBandRetainer:
    def test_retainer_uses_latest_valid_assessment_band_not_best(self):
        """PRD §3.8: "The governing band is the band of the valid assessment
        with the latest `assessed_at`, with a tie on `assessed_at` broken in
        favor of the later `created_at`; when no valid assessment exists, the
        band defaults conservatively to `SUBPRIME`. The rejected alternative —
        picking the client-favorable best band among the valid assessments — is
        not permitted: with an older `PRIME` assessment and a newer `STANDARD`
        assessment both inside their validity windows, the requirement follows
        the newer assessment's band and multiplies by two, not one."

        Design: Difficulty/dual_variant_calc/dual_variant_recent_vs_best_band_retainer
        """
        set_clock("2026-08-01T00:00:00Z")
        party = create_party("Retainer Client Corp")
        atty = create_attorney()
        matter = create_matter(party["id"], atty["id"], matter_title="M")

        resp = api_create_credit(matter["id"], 800)
        assert resp["band"] == "PRIME"
        set_clock("2026-08-11T00:00:00Z")
        resp2 = api_create_credit(matter["id"], 700)
        assert resp2["band"] == "STANDARD"
        set_clock("2026-08-21T00:00:00Z")

        from test_helpers import create_letter, issue_letter

        letter = create_letter(matter, atty)
        assert letter["fee_estimate_cents"] == 2000000, (
            f"100.0 hours x 20000 cents = 2,000,000; got "
            f"{letter['fee_estimate_cents']}"
        )
        issue_letter(letter["id"], atty)
        deposit = get_deposit(matter["id"])
        assert deposit["required_cents"] == 4000000, (
            f"V_RECENT pins the latest valid assessment's band (STANDARD x2): "
            f"2,000,000 x 2 = 4,000,000; a V_BEST implementation would wrongly "
            f"produce 2,000,000; got {deposit['required_cents']}"
        )
        assert deposit["status"] == "PENDING"

    def test_retainer_band_bands_recorded_on_assessments(self):
        """PRD §3.8: "The server stamps `assessed_at` from the logical clock and
        derives the `band`: `PRIME` when the score is at least 740, `STANDARD`
        from 670 through 739, and `SUBPRIME` below 670 — so 740 is `PRIME`, 739
        is `STANDARD`, 670 is `STANDARD`, and 669 is `SUBPRIME`."

        Design: Difficulty/dual_variant_calc/dual_variant_recent_vs_best_band_retainer
        """
        set_clock("2026-08-01T00:00:00Z")
        party = create_party("Band Recording Corp")
        atty = create_attorney()
        matter = create_matter(party["id"], atty["id"], matter_title="M")
        first = api_create_credit(matter["id"], 800)
        set_clock("2026-08-11T00:00:00Z")
        second = api_create_credit(matter["id"], 700)
        assert first["band"] == "PRIME"
        assert second["band"] == "STANDARD"


def api_create_credit(matter_id: str, score: int) -> dict:
    return record_credit_assessment(matter_id, score)


class TestCombinatorialAffiliateChannelMax:
    def test_affiliate_depth_discount_feeds_threshold_comparison(self):
        """PRD §3.4: "Each descendant party reachable by following
        `affiliate_of_id` links downward from the candidate, at a depth of one
        to three levels, is emitted as an additional hit candidate whose score
        is the base score discounted by ten points per level of depth; when
        several paths reach the same descendant, only the highest score is
        kept. A candidate becomes a hit exactly when its score is greater than
        or equal to the `match_threshold` — the boundary is inclusive."

        Design: Difficulty/combinatorial_formula/combinatorial_affiliate_channel_max
        """
        p_x = create_party("Umbrella Industries")
        p_p = create_party("Globex Corporation")
        p_c = create_party("Globex Subsidiary Holdings", affiliate_of_id=p_p["id"])
        p_g = create_party("Globex Sub Sub", affiliate_of_id=p_c["id"])
        p_q = create_party("Globex Corp")
        atty = create_attorney()
        m0 = create_matter(p_x["id"], atty["id"], matter_title="M0")
        add_roster_party(m0["id"], p_p["id"], "RELATED")
        add_roster_party(m0["id"], p_c["id"], "RELATED")
        add_roster_party(m0["id"], p_g["id"], "RELATED")
        m1 = create_matter(p_q["id"], atty["id"], matter_title="M1")

        check = run_conflict_check(m1["id"], "STRICT", match_threshold=85)
        assert check["hit_count"] == 2, (
            f"P direct 100 and C affiliate 90 both >= 85, G affiliate 80 < 85: "
            f"expected 2 hits, got {check['hit_count']}"
        )
        hits = list_hits_for_check(check["id"])
        assert hits[0]["match_score"] == 100
        assert hits[0]["matched_party_id"] == p_p["id"]
        assert hits[0]["matched_via"] == "DIRECT"
        assert hits[1]["match_score"] == 90
        assert hits[1]["matched_party_id"] == p_c["id"]
        assert hits[1]["matched_via"] == "AFFILIATE"

    def test_affiliate_hit_never_references_depth_two_descendant_below_threshold(self):
        """PRD §3.4: "A candidate becomes a hit exactly when its score is greater
        than or equal to the `match_threshold` — the boundary is inclusive."

        Design: Difficulty/combinatorial_formula/combinatorial_affiliate_channel_max
        """
        p_x = create_party("Umbrella Industries")
        p_p = create_party("Globex Corporation")
        p_c = create_party("Globex Subsidiary Holdings", affiliate_of_id=p_p["id"])
        p_g = create_party("Globex Sub Sub", affiliate_of_id=p_c["id"])
        p_q = create_party("Globex Corp")
        atty = create_attorney()
        m0 = create_matter(p_x["id"], atty["id"], matter_title="M0")
        add_roster_party(m0["id"], p_p["id"], "RELATED")
        add_roster_party(m0["id"], p_c["id"], "RELATED")
        add_roster_party(m0["id"], p_g["id"], "RELATED")
        m1 = create_matter(p_q["id"], atty["id"], matter_title="M1")

        check = run_conflict_check(m1["id"], "STRICT", match_threshold=85)
        hits = list_hits_for_check(check["id"])
        hit_party_ids = {h["matched_party_id"] for h in hits}
        assert p_g["id"] not in hit_party_ids, (
            "grand-affiliate G at depth 2 scores 100 - 2*10 = 80 < 85 and must "
            "not appear as a hit"
        )


class TestCombinatorialPerLineRoundingOrder:
    def test_fee_estimate_rounds_per_line_then_sums(self):
        """PRD §2.7: "A letter's `fee_estimate_cents` is computed by multiplying
        each fee line's `hours` by its `rate_cents`, rounding each line's
        product half up to a whole cent first, and only then summing the
        per-line amounts — the order is pinned, per line before summation. The
        rejected reading (sum first, round once) diverges: two lines of 0.5
        hours at 101 cents produce 51 + 51 = 102 cents under the pinned order
        but 101 under sum-then-round."

        Design: Difficulty/combinatorial_formula/combinatorial_per_line_rounding_order
        """
        party, atty, matter = setup_basic_matter("Rounding Client Inc")
        from test_helpers import api_client

        resp = api_client.create_engagement_letter(
            matter["id"],
            create_engagement_letter_payload(
                matter["version"],
                fee_lines=[
                    {"description": "a", "hours": 0.5, "rate_cents": 101},
                    {"description": "b", "hours": 0.5, "rate_cents": 101},
                ],
            ),
            make_responsible_attorney_headers(atty["id"]),
        )
        letter = validate_success(resp, 201)
        assert letter["fee_estimate_cents"] == 102, (
            f"round_half_up(50.5)=51 per line, then 51+51=102; sum-then-round "
            f"implementations return 101 and are wrong; got "
            f"{letter['fee_estimate_cents']}"
        )

    def test_fee_estimate_single_line_exact(self):
        """PRD §2.7: "A letter's `fee_estimate_cents` is computed by multiplying
        each fee line's `hours` by its `rate_cents`, rounding each line's
        product half up to a whole cent first, and only then summing the
        per-line amounts — the order is pinned, per line before summation."

        Design: Difficulty/combinatorial_formula/combinatorial_per_line_rounding_order
        """
        party, atty, matter = setup_basic_matter("Fee Client Corp")
        from test_helpers import api_client

        resp = api_client.create_engagement_letter(
            matter["id"],
            create_engagement_letter_payload(
                matter["version"],
                fee_lines=[{"description": "fees", "hours": 100.0, "rate_cents": 20000}],
            ),
            make_responsible_attorney_headers(atty["id"]),
        )
        letter = validate_success(resp, 201)
        assert letter["fee_estimate_cents"] == 2000000, (
            f"100.0 x 20000 = 2,000,000; got {letter['fee_estimate_cents']}"
        )
