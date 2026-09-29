"""Two formulas whose combined inputs and rounding order decide the outcome.

The first is the batch data-quality score, which folds five weighted components
through a three-way mode switch where only `PENALIZED_WEIGHTED` distinguishes a
malformed value from an absent one — enough to move one batch across the feed's
completeness floor while its twin stays above it. The second is
`revenue_per_member_cents`, where summing first and rounding once at the very end
produces a different integer than rounding each share.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    approx2,
    approx4,
    assert_instant_equals,
    assert_whole_cents,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import ANALYST


def _mixed_quality_records():
    """Three records that exercise PASS, FAIL and ABSENT across the five components.

    The first record passes all five. The second has a malformed phone (present but
    unparseable) and an absent loyalty number. The third has an absent email and an
    absent postal code and nothing malformed at all.
    """
    return [
        f.raw_record("M1"),
        f.raw_record("M2", phone_raw="555-01", loyalty_number=None),
        f.raw_record("M3", email_raw=None, postal_code=None),
    ]


def _scored_batch(api, dq_scoring_mode):
    """One feed on the named scoring mode plus its validated mixed-quality batch."""
    env = fx.received_batch(
        api,
        _mixed_quality_records(),
        feed_overrides={
            "dq_scoring_mode": dq_scoring_mode,
            "pii_completeness_floor": 0.70,
        },
    )
    env["batch"] = fx.validate(api, env["batch"]["id"])
    env["feed"] = fx.reread_feed(api, env["feed"]["id"])
    return env


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/dq_score_penalized_weighted_branches_on_fail_vs_absent
# ---------------------------------------------------------------------------
def test_penalized_weighted_subtracts_a_penalty_per_malformed_component(api):
    """Under PENALIZED_WEIGHTED the malformed phone costs the second record a 0.10
    penalty on top of its missing weight, so the record scores 0.50 and the batch
    scores 0.68 — strictly below the 0.70 floor, which quarantines the batch.

    "It **passes** when its raw value is present and satisfies its format check; it **fails** when the raw value is present but malformed; and it is **absent** when the raw value is null or blank after trimming."
    "Under `PENALIZED_WEIGHTED`, the same weighted sum is computed first as a base, then a penalty of 0.10 is subtracted for each component that is present but malformed, and the result is floored at 0.00 so it can never go negative; this is the only mode in which failing and being absent diverge, on the principle that a malformed value actively poisons downstream matching whereas a missing one merely withholds evidence."
    "Whichever mode applies, the per-record score is rounded half up to two decimal places *before* it is compared to any threshold or fed into any average."
    "A record is **valid** when its score is at least 0.60 and **invalid** when its score is strictly below 0.60; the boundary is inclusive on the valid side, so a score of exactly 0.60 is valid."
    "The batch-level `dq_score` is the sum of the per-record scores over **all** records — invalid ones included — divided by `record_count`, rounded half up to two decimal places; it measures the feed, not the survivors."
    "Where the score is strictly below the floor, the batch moves `RECEIVED` → `QUARANTINED`, with `validated_at` stamped just the same."

    Design: Difficulty/combinatorial_formula/dq_score_penalized_weighted_branches_on_fail_vs_absent
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _scored_batch(api, "PENALIZED_WEIGHTED")
    batch = env["batch"]

    # 1.00, (0.30 + 0.15 + 0.15) - 0.10 = 0.50, and 0.20 + 0.20 + 0.15 = 0.55.
    # (1.00 + 0.50 + 0.55) / 3 = 0.6833... which rounds half up to 0.68.
    assert batch["dq_score"] == approx2(0.68)
    assert batch["valid_record_count"] == 1
    assert batch["invalid_record_count"] == 2
    assert batch["dq_failure_breakdown"] == {"phone_norm": 1}
    assert batch["status"] == "QUARANTINED"
    assert_instant_equals(batch["validated_at"], DEFAULT_CLOCK, "validated_at")


def test_weighted_components_treats_the_malformed_phone_as_merely_absent(api):
    """The identical three records scored under WEIGHTED_COMPONENTS carry no penalty,
    so the second record holds its 0.60 and stays valid and the batch scores 0.72 —
    at or above the same 0.70 floor, which validates the batch.

    "Under `WEIGHTED_COMPONENTS`, the score is the sum of the weights of the passing components, over a weight base that is always the full 1.00: an email that passes contributes 0.30, a phone 0.20, a loyalty number 0.20, a name pair 0.15 and a postal code 0.15 — the five weights summing to exactly 1.00, so email is worth twice postal code — and failing is again indistinguishable from being absent."
    "A record is **valid** when its score is at least 0.60 and **invalid** when its score is strictly below 0.60; the boundary is inclusive on the valid side, so a score of exactly 0.60 is valid."
    "The batch-level `dq_score` is the sum of the per-record scores over **all** records — invalid ones included — divided by `record_count`, rounded half up to two decimal places; it measures the feed, not the survivors."
    "Where the computed `dq_score` is at least the feed's `pii_completeness_floor` — inclusive at equality — the batch moves `RECEIVED` → `VALIDATED` and `validated_at` is stamped at the logical clock now."
    "Alongside it, `dq_failure_breakdown` is written as a map from component name to the count of records in which that component was present but malformed; components that were merely absent never appear in those counts."

    Design: Difficulty/combinatorial_formula/dq_score_penalized_weighted_branches_on_fail_vs_absent
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _scored_batch(api, "WEIGHTED_COMPONENTS")
    batch = env["batch"]

    # 1.00, 0.30 + 0.15 + 0.15 = 0.60, and 0.20 + 0.20 + 0.15 = 0.55.
    # (1.00 + 0.60 + 0.55) / 3 = 0.7166... which rounds half up to 0.72.
    assert batch["dq_score"] == approx2(0.72)
    assert batch["valid_record_count"] == 2
    assert batch["invalid_record_count"] == 1
    assert batch["dq_failure_breakdown"] == {"phone_norm": 1}
    assert batch["status"] == "VALIDATED"
    assert_instant_equals(batch["validated_at"], DEFAULT_CLOCK, "validated_at")


def test_unweighted_mean_ignores_the_weight_table_entirely(api):
    """Scored under UNWEIGHTED_MEAN the same three records are graded on how many of
    the five components pass rather than on their weights, so both sparse records reach
    exactly 0.60 and stay valid while the batch scores 0.73.

    "Under `UNWEIGHTED_MEAN`, the score is the number of passing components divided by five; the weight table is ignored entirely, so a record missing only its email scores exactly the same as a record missing only its postal code, and failing is indistinguishable from being absent."
    "A record is **valid** when its score is at least 0.60 and **invalid** when its score is strictly below 0.60; the boundary is inclusive on the valid side, so a score of exactly 0.60 is valid."
    "The batch-level `dq_score` is the sum of the per-record scores over **all** records — invalid ones included — divided by `record_count`, rounded half up to two decimal places; it measures the feed, not the survivors."
    "Alongside it, `dq_failure_breakdown` is written as a map from component name to the count of records in which that component was present but malformed; components that were merely absent never appear in those counts."

    Design: Difficulty/combinatorial_formula/dq_score_penalized_weighted_branches_on_fail_vs_absent
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _scored_batch(api, "UNWEIGHTED_MEAN")
    batch = env["batch"]

    # 5/5 = 1.00, 3/5 = 0.60 and 3/5 = 0.60; (1.00 + 0.60 + 0.60) / 3 = 0.7333...
    assert batch["dq_score"] == approx2(0.73)
    assert batch["valid_record_count"] == 3
    assert batch["invalid_record_count"] == 0
    assert batch["dq_failure_breakdown"] == {"phone_norm": 1}
    assert batch["status"] == "VALIDATED"

    feed = env["feed"]
    assert feed["submitted_record_total"] == 3
    assert feed["valid_record_total"] == 3
    assert feed["dq_pass_rate"] == approx4(1.0000)


def test_the_scoring_mode_alone_straddles_the_completeness_floor(api):
    """Two feeds with the same 0.70 floor receive the same three records and differ only
    in `dq_scoring_mode`: the penalized feed's batch quarantines on 0.68 while the
    weighted feed's batch validates on 0.72, and each feed's rolling rate follows.

    "Under `PENALIZED_WEIGHTED`, the same weighted sum is computed first as a base, then a penalty of 0.10 is subtracted for each component that is present but malformed, and the result is floored at 0.00 so it can never go negative; this is the only mode in which failing and being absent diverge, on the principle that a malformed value actively poisons downstream matching whereas a missing one merely withholds evidence."
    "`submitted_record_total` is the sum of `record_count` over the feed's in-window batches, and `valid_record_total` is the sum of their `valid_record_count`."
    "`dq_pass_rate` is then the valid total divided by the submitted total, rounded half up to four decimal places, except that when the submitted total is 0 the rate is exactly 1.0000, because a feed with no evidence is presumed clean."
    "A feed is driven to `QUARANTINED` when, after a recomputation, its `submitted_record_total` has reached at least five records **and** its `dq_pass_rate` is strictly below its own `pii_completeness_floor`."

    Design: Difficulty/combinatorial_formula/dq_score_penalized_weighted_branches_on_fail_vs_absent
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    penalized = _scored_batch(api, "PENALIZED_WEIGHTED")
    weighted = _scored_batch(api, "WEIGHTED_COMPONENTS")

    assert penalized["batch"]["dq_score"] == approx2(0.68)
    assert weighted["batch"]["dq_score"] == approx2(0.72)
    assert penalized["batch"]["status"] == "QUARANTINED"
    assert weighted["batch"]["status"] == "VALIDATED"

    # 1 of 3 valid against 2 of 3 valid, on identical raw input.
    assert penalized["feed"]["submitted_record_total"] == 3
    assert penalized["feed"]["valid_record_total"] == 1
    assert penalized["feed"]["dq_pass_rate"] == approx4(0.3333)
    assert weighted["feed"]["submitted_record_total"] == 3
    assert weighted["feed"]["valid_record_total"] == 2
    assert weighted["feed"]["dq_pass_rate"] == approx4(0.6667)

    # Three in-window records is short of the five-record evidence threshold, so
    # neither feed is quarantined however low its rate has fallen.
    assert penalized["feed"]["status"] == "REGISTERED"
    assert weighted["feed"]["status"] == "REGISTERED"
    assert penalized["feed"]["quarantine_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/revenue_per_member_rounds_once_after_summation
# ---------------------------------------------------------------------------
def _performance(api, segment_id, attribution_basis):
    """The computed attribution read under one basis."""
    return validate_success(
        api.get_segment_performance(
            segment_id, ANALYST, {"attribution_basis": attribution_basis}
        ),
        200,
    )


def _repeat_purchase_environment(api):
    """Three members and four conversions of 100 cents, one member buying twice.

    Every conversion is dated after the segment's approval instant, so all four
    qualify, and the repeat purchase is the only difference between the two bases.
    """
    env = fx.delivering_activation_environment(api, 3)
    first, second, third = env["profiles"][0], env["profiles"][1], env["profiles"][2]
    env["repeat_buyer"] = first
    env["conversions"] = [
        f.conversion(first["id"], "2026-08-02T01:00:00Z", 100),
        f.conversion(first["id"], "2026-08-02T01:30:00Z", 100),
        f.conversion(second["id"], "2026-08-02T01:05:00Z", 100),
        f.conversion(third["id"], "2026-08-02T01:10:00Z", 100),
    ]
    env["activation"] = fx.report_match(
        api,
        env["activation"]["id"],
        env["destination"]["id"],
        3,
        0,
        env["conversions"],
    )
    return env


def test_revenue_per_member_divides_the_summed_total_once(api):
    """Three conversions of 100 cents against three members give 300 cents summed and
    exactly 100 cents per member, which is the figure only a single division of the
    already-summed total produces.

    "`revenue_per_member_cents` is 0 where `member_count` is 0, and otherwise the `attributed_revenue_cents` figure divided by `member_count`, rounded half up to whole cents."
    "**The order of operations is pinned:** sum first, divide once, round exactly once at the very end."
    "The tempting alternative — dividing each conversion's `revenue_cents` by `member_count`, rounding each share, and then summing those shares — is explicitly not the rule and produces a different integer."
    "With a `member_count` of 3 and three conversions of 100 cents each, the pinned order yields 100 while the per-conversion order would yield 99; implementations must reproduce 100."
    "Under `TOTAL`, the default, `conversion_count` is the number of qualifying conversions and `attributed_revenue_cents` is the sum of their `revenue_cents` — every repeat purchase by the same person counts again."

    Design: Difficulty/combinatorial_formula/revenue_per_member_rounds_once_after_summation
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = fx.attribution_environment(
        api, member_count=3, revenue_cents=100, conversions_per_member=1
    )

    report = _performance(api, env["segment"]["id"], "TOTAL")

    assert report["member_count"] == 3
    assert report["conversion_count"] == 3
    assert report["unique_converter_count"] == 3
    assert report["attributed_revenue_cents"] == 300
    assert_whole_cents(report["revenue_per_member_cents"], "revenue_per_member_cents")
    assert report["revenue_per_member_cents"] == 100
    assert report["revenue_per_member_cents"] != 99, (
        "rounding each conversion's share before summing yields 99, which the PRD "
        "explicitly rejects"
    )

    for profile in env["profiles"]:
        assert fx.reread_profile(api, profile["id"])["lifetime_value_cents"] == 100
    activation = fx.reread_activation(api, env["activation"]["id"])
    assert activation["attributed_conversion_count"] == 3
    assert activation["gross_match_rate"] == approx4(1.0000)
    assert activation["status"] == "ACTIVE"


def test_a_non_exact_division_still_rounds_only_at_the_very_end(api):
    """Four conversions of 100 cents against three members sum to 400 and divide to
    133.33, which rounds half up once to 133; rounding each of the four shares first
    would sum to 132 instead.

    "**The order of operations is pinned:** sum first, divide once, round exactly once at the very end."
    "The tempting alternative — dividing each conversion's `revenue_cents` by `member_count`, rounding each share, and then summing those shares — is explicitly not the rule and produces a different integer."
    "Where a monetary computation involves division, the division is applied to the already-summed total and the result is rounded half up exactly once at the very end, as spelled out for `revenue_per_member_cents` in §3.10."
    "Under `TOTAL`, the default, `conversion_count` is the number of qualifying conversions and `attributed_revenue_cents` is the sum of their `revenue_cents` — every repeat purchase by the same person counts again."
    "Two outputs are identical under both bases: `unique_converter_count` is the number of distinct `profile_id` values across the qualifying conversions, and `member_count` is the segment's member-set size at read time."

    Design: Difficulty/combinatorial_formula/revenue_per_member_rounds_once_after_summation
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _repeat_purchase_environment(api)

    report = _performance(api, env["segment"]["id"], "TOTAL")

    assert report["member_count"] == 3
    assert report["conversion_count"] == 4
    assert report["unique_converter_count"] == 3
    assert report["attributed_revenue_cents"] == 400
    assert_whole_cents(report["revenue_per_member_cents"], "revenue_per_member_cents")
    assert report["revenue_per_member_cents"] == 133
    assert report["revenue_per_member_cents"] != 132, (
        "four shares of round_half_up(100 / 3) sum to 132, which is not the rule"
    )
    assert (
        fx.reread_profile(api, env["repeat_buyer"]["id"])["lifetime_value_cents"] == 200
    )


def test_incremental_basis_credits_only_the_first_touch_before_dividing(api):
    """Read on the INCREMENTAL basis the same four conversions credit only each buyer's
    chronologically first purchase, so 300 cents is summed over three members and the
    single division yields exactly 100 rather than the total basis's 133.

    "Under `INCREMENTAL`, only each distinct `profile_id`'s **chronologically first** conversion in the window is credited, so `conversion_count` is the number of distinct first touches and `attributed_revenue_cents` sums only those; a repeat purchase inside the window is treated as retained rather than incremental revenue."
    "Two outputs are identical under both bases: `unique_converter_count` is the number of distinct `profile_id` values across the qualifying conversions, and `member_count` is the segment's member-set size at read time."
    "`revenue_per_member_cents` is 0 where `member_count` is 0, and otherwise the `attributed_revenue_cents` figure divided by `member_count`, rounded half up to whole cents."
    "**The order of operations is pinned:** sum first, divide once, round exactly once at the very end."

    Design: Difficulty/combinatorial_formula/revenue_per_member_rounds_once_after_summation
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _repeat_purchase_environment(api)

    incremental = _performance(api, env["segment"]["id"], "INCREMENTAL")
    total = _performance(api, env["segment"]["id"], "TOTAL")

    assert incremental["conversion_count"] == 3
    assert incremental["attributed_revenue_cents"] == 300
    assert incremental["revenue_per_member_cents"] == 100
    assert incremental["unique_converter_count"] == total["unique_converter_count"] == 3
    assert incremental["member_count"] == total["member_count"] == 3
    assert total["revenue_per_member_cents"] == 133


def test_revenue_per_member_is_zero_when_the_member_set_has_emptied(api):
    """After every member is suppressed the segment's live member set is empty, so the
    per-member figure is pinned at 0 even though the three qualifying conversions still
    sum to 300 cents.

    "`revenue_per_member_cents` is 0 where `member_count` is 0, and otherwise the `attributed_revenue_cents` figure divided by `member_count`, rounded half up to whole cents."
    "The eligible population is narrower still: only profiles whose `resolution_status` is not `MERGED_AWAY` and whose `privacy_status` is exactly `NORMAL` are considered."
    "Its input set is every activation of the segment whose `status` is not `DRAFT` — a draft activation has never delivered — and, within those, every element of `attributed_conversions` whose `converted_at` is at or after the segment's `approved_at`."

    Design: Difficulty/combinatorial_formula/revenue_per_member_rounds_once_after_summation
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = fx.attribution_environment(
        api, member_count=3, revenue_cents=100, conversions_per_member=1
    )
    for profile in env["profiles"]:
        fx.add_suppression(
            api,
            profile["id"],
            entry_type="GLOBAL_OPT_OUT",
            reason_code="SUBJECT_REQUEST",
        )
        assert fx.reread_profile(api, profile["id"])["privacy_status"] == "SUPPRESSED"

    report = _performance(api, env["segment"]["id"], "TOTAL")

    assert report["member_count"] == 0
    assert report["conversion_count"] == 3
    assert report["attributed_revenue_cents"] == 300
    assert_whole_cents(report["revenue_per_member_cents"], "revenue_per_member_cents")
    assert report["revenue_per_member_cents"] == 0
