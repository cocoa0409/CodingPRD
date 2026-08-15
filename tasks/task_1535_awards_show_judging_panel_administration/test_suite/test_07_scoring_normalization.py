"""Ballot math, the two normalization variants, degenerate panels, ballot
completeness at close, and final-composite reconciliation (PRD §2.8, §3.6).
"""
from decimal import Decimal, ROUND_HALF_UP

from test_helpers import (
    ApiErrorId,
    assert_score_4dp,
    make_judge_headers,
    quantize_4dp,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]

# Expected normalized grid for the shared ballots (judges rows, entries
# columns), verified against the PRD §3.6 formulas.
Z_EXPECTED = {
    (0, 0): "58.0396", (0, 1): "2.4188", (0, 2): "96.9742",
    (1, 0): "52.4776", (1, 1): "100.0", (1, 2): "4.9551",
    (2, 0): "64.8252", (2, 1): "0.0", (2, 2): "92.6074",
}
Z_COMPOSITES = ["58.4475", "34.1396", "64.8456"]
R_EXPECTED = {
    (0, 0): "50.0", (0, 1): "0.0", (0, 2): "100.0",
    (1, 0): "50.0", (1, 1): "100.0", (1, 2): "0.0",
    (2, 0): "50.0", (2, 1): "0.0", (2, 2): "100.0",
}
R_COMPOSITES = ["50.0", "33.3333", "66.6667"]


def _scores_by_judge_entry(api, round_id, judges, entries):
    scores = fx.list_round_scores(round_id)
    grid = {}
    for score in scores:
        j_pos = next(i for i, j in enumerate(judges) if j["id"] == score["judge_id"])
        e_pos = next(i for i, e in enumerate(entries) if e["id"] == score["entry_id"])
        grid[(j_pos, e_pos)] = score
    return grid


def _composite(values):
    total = sum(Decimal(str(v)) for v in values)
    return (total / len(values)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


class TestScoringModeDivergence:
    def test_zscore_mode_normalized_values(self, api):
        """PRD §3.6: "Under `Z_SCORE`, the system computes each judge's mean and
        population standard deviation across that judge's `weighted_raw` values,
        writes each score's `z_intermediate` as its deviation from its judge's
        mean divided by its judge's standard deviation — zero when that standard
        deviation is zero — and then rescales across the whole round: the minimum
        and maximum `z_intermediate` over all scores define the range, and each
        `normalized_score` is its distance above the minimum, divided by that
        range, multiplied by 100, rounded half-up to four decimal places"
        PRD §3.6: "The intermediate fields are mode-exclusive: `z_intermediate`
        stays null under `RAW_RANK`, and `rank_among_judges_scores` stays null
        under `Z_SCORE`"
        PRD §3.6: "An entry's composite for the round is the mean of its
        `normalized_score` values across the panel, rounded half-up to four
        decimal places."

        Design: Difficulty/dual_variant_calc/score_normalization_mode_divergence
        """
        bundle = fx.setup_dual_mode_normalized("GALA-DUAL-Z")
        grid = _scores_by_judge_entry(
            api, bundle["round_z"]["id"], bundle["judges"], bundle["entries_z"]
        )
        assert len(grid) == 9
        for (j_pos, e_pos), expected in Z_EXPECTED.items():
            score = grid[(j_pos, e_pos)]
            assert_score_4dp(
                score["normalized_score"], expected,
                context=f"Z_SCORE judge {j_pos} entry {e_pos}",
            )
            assert score["z_intermediate"] is not None
            assert score.get("rank_among_judges_scores") is None, (
                "rank field stays null under Z_SCORE"
            )
        for e_pos, expected in enumerate(Z_COMPOSITES):
            comp = _composite(
                [grid[(j, e_pos)]["normalized_score"] for j in range(3)]
            )
            assert comp == Decimal(expected), (
                f"Z_SCORE composite entry {e_pos}: expected {expected}, got {comp}"
            )

    def test_raw_rank_mode_normalized_values(self, api):
        """PRD §3.6: "Under `RAW_RANK`, with N the count of distinct candidate
        entries in the round, each judge's locked scores are ranked by
        `weighted_raw` descending with ties sharing the average rank, the rank is
        stored as `rank_among_judges_scores`, and each `normalized_score` is N
        minus that rank, divided by N minus one, multiplied by 100, rounded
        half-up to four decimal places"
        PRD §3.6: "The two scoring modes diverge deliberately, so identical raw
        inputs yield different normalized values under each."

        Design: Difficulty/dual_variant_calc/score_normalization_mode_divergence
        """
        bundle = fx.setup_dual_mode_normalized("GALA-DUAL-R")
        grid = _scores_by_judge_entry(
            api, bundle["round_r"]["id"], bundle["judges"], bundle["entries_r"]
        )
        assert len(grid) == 9
        for (j_pos, e_pos), expected in R_EXPECTED.items():
            score = grid[(j_pos, e_pos)]
            assert_score_4dp(
                score["normalized_score"], expected,
                context=f"RAW_RANK judge {j_pos} entry {e_pos}",
            )
            assert score["rank_among_judges_scores"] is not None
            assert score.get("z_intermediate") is None, (
                "z field stays null under RAW_RANK"
            )
        for e_pos, expected in enumerate(R_COMPOSITES):
            comp = _composite(
                [grid[(j, e_pos)]["normalized_score"] for j in range(3)]
            )
            assert comp == Decimal(expected), (
                f"RAW_RANK composite entry {e_pos}: expected {expected}, got {comp}"
            )
        # Divergence on identical raw inputs: judge 0 / entry 0 differs by mode.
        z_grid = _scores_by_judge_entry(
            api, bundle["round_z"]["id"], bundle["judges"], bundle["entries_z"]
        )
        assert quantize_4dp(z_grid[(0, 0)]["normalized_score"]) != quantize_4dp(
            grid[(0, 0)]["normalized_score"]
        )


class TestCompositeRawRoundingOrder:
    def _setup_rounding_scenario(self, api, code: str):
        """One entry in a round whose rubric (P: 1000bp/max 3, Q: 9000bp/max 7)
        separates per-criterion-round-first from sum-then-round at the 4th
        decimal."""
        rubric = [
            {"criterion_code": "P", "weight_bp": 1000, "max_score": 3},
            {"criterion_code": "Q", "weight_bp": 9000, "max_score": 7},
        ]
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code=code, category_overrides={"scoring_rubric": rubric}
        )
        round_, judges, _ = fx.setup_locked_round(
            bundle["category"]["id"],
            round_index=1,
            scoring_mode="Z_SCORE",
            window=("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z"),
            advance_count=1,
        )
        fx.begin_judging(bundle["season"]["id"])
        fx.open_round(round_["id"])
        return bundle, round_, judges

    def test_weighted_raw_rounds_each_contribution_first(self, api):
        """PRD §3.6: "At submission the weighted raw composite is computed and
        stored as `weighted_raw`: for each criterion, the raw score is divided
        by the criterion's `max_score`, multiplied by the criterion's
        `weight_bp`, and divided by 100, and each such contribution is rounded
        half-up to four decimal places before any summation; `weighted_raw` is
        then the sum of those rounded contributions, itself rounded half-up to
        four decimal places, yielding a value between 0 and 100."

        Design: Difficulty/combinatorial_formula/composite_raw_rounding_order_pinned
        """
        bundle, round_, judges = self._setup_rounding_scenario(api, "GALA-RND")
        entry = bundle["entries"][0]
        for judge in judges:
            score = fx.post_score(
                round_["id"], entry["id"], judge["id"], {"P": 1, "Q": 1}
            )
            submitted = validate_success(
                api.submit_score(score["id"], make_judge_headers(judge["id"]))
            )
            assert quantize_4dp(submitted["weighted_raw"]) == Decimal("16.1904"), (
                "P contributes 3.3333 and Q 12.8571 after per-criterion rounding"
            )

    def test_weighted_raw_is_not_sum_then_round(self, api):
        """PRD §3.6: "each such contribution is rounded half-up to four decimal
        places before any summation; `weighted_raw` is then the sum of those
        rounded contributions, itself rounded half-up to four decimal places"
        (The alternative order — round once after summing — would yield
        16.1905 for the same ballot, not 16.1904.)

        Design: Difficulty/combinatorial_formula/composite_raw_rounding_order_pinned
        """
        bundle, round_, judges = self._setup_rounding_scenario(api, "GALA-RND2")
        entry = bundle["entries"][0]
        for judge in judges:
            score = fx.post_score(
                round_["id"], entry["id"], judge["id"], {"P": 1, "Q": 1}
            )
            fx.submit_score(score["id"], judge["id"])
        scores = fx.list_entry_scores(entry["id"])
        assert len(scores) == 3
        for score in scores:
            pinned = quantize_4dp(score["weighted_raw"])
            assert pinned == Decimal("16.1904")
            assert pinned != Decimal("16.1905")


class TestDegenerateZScore:
    def _setup_degenerate_round(self, api, code: str):
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code=code
        )
        round_, judges, _ = fx.setup_locked_round(
            bundle["category"]["id"],
            round_index=1,
            scoring_mode="Z_SCORE",
            window=("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z"),
            advance_count=1,
        )
        fx.begin_judging(bundle["season"]["id"])
        fx.open_round(round_["id"])
        entry = bundle["entries"][0]
        identical = {"CRAFT": 8, "IMPACT": 4}  # weighted_raw 80.0 everywhere
        for judge in judges:
            score = fx.post_score(round_["id"], entry["id"], judge["id"], identical)
            fx.submit_score(score["id"], judge["id"])
        fx.close_round(round_["id"])
        fx.normalize_round(round_["id"])
        return bundle, round_, judges, entry

    def test_zero_stddev_scores_normalize_to_fifty(self, api):
        """PRD §3.6: "Under `Z_SCORE`, the system computes each judge's mean and
        population standard deviation across that judge's `weighted_raw` values,
        writes each score's `z_intermediate` as its deviation from its judge's
        mean divided by its judge's standard deviation — zero when that standard
        deviation is zero — and then rescales across the whole round: the minimum
        and maximum `z_intermediate` over all scores define the range, and each
        `normalized_score` is its distance above the minimum, divided by that
        range, multiplied by 100, rounded half-up to four decimal places; if the
        maximum equals the minimum, every score normalizes to exactly 50."

        Design: Difficulty/boundary_precision_check/zscore_degenerate_zero_stddev
        """
        _, round_, _, _ = self._setup_degenerate_round(api, "GALA-BND2")
        scores = fx.list_round_scores(round_["id"])
        assert len(scores) == 3
        for score in scores:
            assert_score_4dp(score["normalized_score"], "50.0", context="degenerate z")
            assert_score_4dp(score["z_intermediate"], "0", context="zero stddev")

    def test_zero_stddev_entry_composite_is_fifty(self, api):
        """PRD §3.6: "An entry's composite for the round is the mean of its
        `normalized_score` values across the panel, rounded half-up to four
        decimal places."

        Design: Difficulty/boundary_precision_check/zscore_degenerate_zero_stddev
        """
        _, round_, _, entry = self._setup_degenerate_round(api, "GALA-BND2B")
        scores = fx.list_entry_scores(entry["id"])
        assert len(scores) == 3
        comp = _composite([s["normalized_score"] for s in scores])
        assert comp == Decimal("50.0")


class TestBallotCompleteness:
    def test_close_with_missing_ballot_rejected(self, api):
        """PRD §3.6: "Closing the round is allowed only on a complete ballot:
        every `ACTIVE` panelist must hold a `SUBMITTED` or `LOCKED` score for
        every candidate entry, otherwise the close is refused with
        `ERR_INCOMPLETE_BALLOT`."

        Design: Corner/validations/incomplete_ballot_blocks_close
        """
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code="GALA-BAL"
        )
        round_, judges, _ = fx.setup_locked_round(
            bundle["category"]["id"],
            round_index=1,
            scoring_mode="RAW_RANK",
            window=("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z"),
            advance_count=1,
        )
        fx.begin_judging(bundle["season"]["id"])
        fx.open_round(round_["id"])
        entry = bundle["entries"][0]
        for judge in judges[:2]:  # the third judge never submits
            score = fx.post_score(
                round_["id"], entry["id"], judge["id"], {"CRAFT": 8, "IMPACT": 4}
            )
            fx.submit_score(score["id"], judge["id"])
        resp = api.close_round(round_["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_BALLOT)
        fetched = validate_success(api.get_round(round_["id"], ADMIN))
        assert fetched["status"] == "OPEN"


class TestFinalCompositeReconciliation:
    def test_final_fields_null_until_final_normalize_then_populated(self, api):
        """PRD §3.2: "New entries are `DRAFT` with `payment_status` `UNPAID`,
        `revision_count` zero, `fee_waived` false, `fee_tier_applied` null, and
        `final_composite_score` and `final_rank` not yet computed."
        PRD §3.6: "The final composite blends the entry's per-round composites
        with base weights of 0.20 for `SCREENING`, 0.30 for `SEMIFINAL`, and
        0.50 for `FINAL`; when a category ran fewer than three rounds, the
        missing rounds' weights redistribute proportionally, each present
        non-`VOIDED` round's effective weight being its base weight divided by
        the sum of the base weights of the present rounds — a `FINAL`-only
        category therefore gives the `FINAL` round an effective weight of 1.0,
        and a category that ran only `SCREENING` and `FINAL` uses 0.20 divided
        by 0.70 and 0.50 divided by 0.70."
        PRD §3.6: "The entry's `final_composite_score` is the sum over present
        rounds of each effective weight multiplied by the entry's composite in
        that round, rounded half-up to four decimal places, and `final_rank`
        orders entries by that composite descending, breaking ties by the
        `FINAL`-round composite descending and then by entry `created_at`
        ascending."

        Design: Corner/complexity_layers/derived_field_reconciliation_final_composite
        """
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=2, code="GALA-DFR"
        )
        e1, e2 = bundle["entries"]
        round_, judges, _ = fx.setup_locked_round(
            bundle["category"]["id"],
            round_index=3,
            scoring_mode="RAW_RANK",
            window=("2026-09-12T00:00:00Z", "2026-09-14T00:00:00Z"),
            advance_count=None,
        )
        fx.begin_judging(bundle["season"]["id"])
        fx.open_round(round_["id"])

        before = fx.get_entry(e1["id"])
        assert before.get("final_composite_score") is None
        assert before.get("final_rank") is None

        # Judge-uniform ballots: E1 strictly outranks E2 for every judge.
        matrix = {
            (j, 0): {"CRAFT": 8, "IMPACT": 4} for j in range(3)
        }
        matrix.update({(j, 1): {"CRAFT": 6, "IMPACT": 3} for j in range(3)})
        fx.score_entries(round_["id"], [e1, e2], judges, matrix)
        fx.close_round(round_["id"])
        fx.normalize_round(round_["id"])

        after1 = fx.get_entry(e1["id"])
        after2 = fx.get_entry(e2["id"])
        assert_score_4dp(after1["final_composite_score"], "100.0", context="E1 final")
        assert after1["final_rank"] == 1
        assert_score_4dp(after2["final_composite_score"], "0.0", context="E2 final")
        assert after2["final_rank"] == 2
