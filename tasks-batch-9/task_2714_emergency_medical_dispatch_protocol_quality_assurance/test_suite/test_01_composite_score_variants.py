"""Two views of the same evidence: the unweighted provisional composite a
reviewer sees versus the weighted accreditation composite that enters the
ledger, and the two aggregation variants of an accreditation report."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2
from test_helpers.test_users import OFFICER, SUPERVISOR

PROGRAM_THRESHOLDS = {
    "target_compliance_pct": 90.0,
    "watch_floor_pct": 80.0,
    "high_risk_target_pct": 85.0,
    "review_deadline_days": 30,
    "rebuttal_window_days": 14,
    "max_rebuttal_rounds": 2,
    "escalated_sample_floor": 25,
    "hours_owed_restriction_threshold": 6.0,
}

# Perfect on three sections, 18/30 on key questions: the one section whose
# weight (0.3500) differs most from the flat one-quarter of the provisional view.
WEAK_KEY_QUESTIONS_SHEET = {
    "case_entry": (20, 20),
    "key_questions": (18, 30),
    "pre_arrival": (10, 10),
    "final_coding": (5, 5),
}

REPORT_WINDOW = {"window_start": "2026-08-01T00:00:00Z", "window_end": "2026-09-01T00:00:00Z"}


def _weak_key_questions_env(api):
    """One CHEST_PAIN review dispatched and coded 10-C-4, scored 100/60/100/100."""
    return fx.scored_review_env(
        api,
        sections=WEAK_KEY_QUESTIONS_SHEET,
        reviewer_determinant_code="10-C-4",
        program_overrides=dict(PROGRAM_THRESHOLDS),
        call_overrides={"call_type": "CHEST_PAIN", "dispatched_determinant_code": "10-C-4"},
        period_overrides={"sampling_mode": "MIXED", "target_sample_count": 1},
    )


def test_provisional_composite_is_the_unweighted_mean_of_the_four_sections(api):
    """PRD 3.5: "Each is the points earned divided by the points possible,
    multiplied by one hundred, rounded half up to 2 decimal places."
    PRD 3.5: "The sheet's `provisional_composite_score` is then the arithmetic
    mean of those four already-rounded percentages, rounded half up to 1 decimal
    place — under this view each of the four sections contributes exactly one
    quarter, regardless of the weights on the pinned protocol version, and no
    determinant penalty is applied."

    Design: Difficulty/dual_variant_calc/review_provisional_unweighted_versus_final_weighted_composite
    """
    env = _weak_key_questions_env(api)
    sheet = env["sheet"]

    assert sheet["case_entry_pct"] == approx2(100.00)
    assert sheet["key_questions_pct"] == approx2(60.00)
    assert sheet["pre_arrival_pct"] == approx2(100.00)
    assert sheet["final_coding_pct"] == approx2(100.00)
    # (100.00 + 60.00 + 100.00 + 100.00) / 4 = 90.0, each section one quarter.
    assert sheet["provisional_composite_score"] == approx1(90.0), (
        f"expected an unweighted mean of 90.0, got {sheet['provisional_composite_score']}"
    )

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SCORED"
    assert review["provisional_composite_score"] == approx1(90.0)
    assert review["pre_penalty_composite_score"] is None, (
        "the weighted composite is only written at finalization"
    )


def test_finalization_reweights_the_same_sheet_with_the_pinned_section_weights(api):
    """PRD 3.7: "The four already-rounded section percentages of the **current**
    sheet — the one whose `sheet_round` equals the review's `current_sheet_round`,
    superseded sheets being excluded entirely — are each multiplied by the
    corresponding weight on the review's pinned protocol version, the four
    products are summed, and the total is rounded half up to 1 decimal place to
    give `pre_penalty_composite_score`."
    PRD 3.7: "`compliant` is true when `final_composite_score` is at or above the
    programme's `target_compliance_pct` and false otherwise."

    Design: Difficulty/dual_variant_calc/review_provisional_unweighted_versus_final_weighted_composite
    """
    env = _weak_key_questions_env(api)

    review = validate_success(
        api.finalize_review(env["review_id"], {"finalization_note": "concur"}, SUPERVISOR), 200
    )

    assert review["status"] == "FINALIZED"
    # The provisional figure the reviewer saw is untouched by finalization.
    assert review["provisional_composite_score"] == approx1(90.0)
    # 100.00*0.20 + 60.00*0.35 + 100.00*0.30 + 100.00*0.15 = 86.0
    assert review["pre_penalty_composite_score"] == approx1(86.0), (
        "the weighted view must differ from the unweighted mean of 90.0: got "
        f"{review['pre_penalty_composite_score']}"
    )
    assert review["determinant_accuracy"] == "ACCURATE"
    assert review["penalty_points"] == approx1(0.0)
    assert review["final_composite_score"] == approx1(86.0)
    assert review["compliant"] is False, "86.0 is below the target of 90.0"


def test_weighted_finalized_score_is_the_figure_that_enters_the_dispatcher_ledger(api):
    """PRD 3.7: "The dispatcher's compliance figures are recomputed from scratch
    over every review of theirs in `FINALIZED` — reviews in `SELECTED`, `SCORED`,
    `DISPUTED` or `VOIDED` contribute nothing: `reviewed_case_count` is the number
    of such reviews, `compliance_points_total` is the sum of their
    `final_composite_score` values rounded half up to 1 decimal place, and
    `compliance_pct` is that total divided by the count, rounded half up to 1
    decimal place."
    PRD 3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is
    at or above the programme's `target_compliance_pct`, `WATCH` when it is below
    that but at or above `watch_floor_pct`, and `PROBATION` when it is below the
    watch floor; a dispatcher with no finalized reviews is `UNRATED`."

    Design: Difficulty/dual_variant_calc/review_provisional_unweighted_versus_final_weighted_composite
    """
    env = _weak_key_questions_env(api)
    fx.finalize(api, env["review_id"], "concur")

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["reviewed_case_count"] == 1
    # The weighted 86.0 enters the ledger, not the provisional 90.0.
    assert dispatcher["compliance_points_total"] == approx1(86.0)
    assert dispatcher["compliance_pct"] == approx1(86.0)
    assert dispatcher["compliance_posture"] == "WATCH", (
        "86.0 is below the 90.0 target but at or above the 80.0 watch floor"
    )


def _three_finalized_reviews_env(api):
    """Dispatcher A with one compliant case; dispatcher B with one compliant and
    one failing case. Programme target 75.0, so the two variants disagree."""
    program = fx.new_program(
        api,
        accreditation_body="NAED_LOCAL",
        target_compliance_pct=75.0,
        watch_floor_pct=60.0,
        high_risk_target_pct=85.0,
    )
    fx.new_approved_version(api, program["id"])
    fx.set_clock(api, "2026-08-20T00:00:00Z")

    dispatcher_a = fx.new_dispatcher(api, program["id"])
    dispatcher_b = fx.new_dispatcher(api, program["id"])
    call_a1 = fx.ingest_call(api, dispatcher_a["id"], received_at="2026-08-05T09:00:00Z")
    call_b1 = fx.ingest_call(api, dispatcher_b["id"], received_at="2026-08-06T09:00:00Z")
    call_b2 = fx.ingest_call(api, dispatcher_b["id"], received_at="2026-08-07T09:00:00Z")

    period = fx.new_period(
        api, program["id"], sampling_mode="MIXED", target_sample_count=3
    )

    finalized = {}
    for key, call, earned, reason in (
        ("a1", call_a1, 23, "NEW_HIRE_AUDIT"),
        ("b1", call_b1, 22, "COMPLAINT"),
        ("b2", call_b2, 15, "COMPLAINT"),
    ):
        review = fx.target(api, period["id"], call["id"], reason)
        sections = {
            section: (earned, 25)
            for section in ("case_entry", "key_questions", "pre_arrival", "final_coding")
        }
        fx.score(
            api,
            review["id"],
            sections=sections,
            reviewer_determinant_code="10-C-4",
            expected_review_version=review["version"],
        )
        finalized[key] = fx.finalize(api, review["id"], "concur")

    return {
        "program_id": program["id"],
        "dispatcher_a_id": dispatcher_a["id"],
        "dispatcher_b_id": dispatcher_b["id"],
        "finalized": finalized,
    }


def test_case_weighted_report_counts_every_reviewed_case_once(api):
    """PRD 3.9: "From a non-empty pool, `review_count` is the size of the pool,
    `compliant_review_count` is how many of those reviews have `compliant` true,
    and `dispatcher_count` is the number of distinct dispatchers contributing at
    least one review to it."
    PRD 3.9: "Under the case-weighted variant every reviewed case counts once: the
    figure is one hundred multiplied by `compliant_review_count`, divided by
    `review_count`, rounded half up to 1 decimal place — so a dispatcher whose
    calls were sampled heavily dominates the programme number."

    Design: Difficulty/dual_variant_calc/accreditation_case_weighted_versus_dispatcher_equal_weight_inverts_threshold
    """
    env = _three_finalized_reviews_env(api)
    finalized = env["finalized"]

    # 23/25 = 92.00, 22/25 = 88.00 and 15/25 = 60.00 in all four sections, so the
    # weighted composite equals the flat section percentage in each case.
    assert finalized["a1"]["final_composite_score"] == approx1(92.0)
    assert finalized["a1"]["compliant"] is True
    assert finalized["b1"]["final_composite_score"] == approx1(88.0)
    assert finalized["b1"]["compliant"] is True
    assert finalized["b2"]["final_composite_score"] == approx1(60.0)
    assert finalized["b2"]["compliant"] is False

    report = validate_success(
        api.create_accreditation_report(
            env["program_id"], dict(REPORT_WINDOW, variant="CASE_WEIGHTED"), OFFICER
        ),
        201,
    )
    assert report["review_count"] == 3
    assert report["compliant_review_count"] == 2
    assert report["dispatcher_count"] == 2
    # 100 * 2 / 3 = 66.666... -> 66.7
    assert report["compliance_pct"] == approx1(66.7)
    assert report["threshold_met"] is False, "66.7 is below the 75.0 target"


def test_dispatcher_equal_weight_report_gives_every_dispatcher_one_vote(api):
    """PRD 3.9: "Under the dispatcher-equal-weight variant every dispatcher counts
    once regardless of how many of their calls were sampled: for each distinct
    dispatcher in the pool, that dispatcher's own compliant rate is their compliant
    in-window review count divided by their total in-window review count and is
    kept **unrounded**; those per-dispatcher rates are summed, the sum is divided
    by `dispatcher_count`, the result is multiplied by one hundred, and only that
    final programme mean is rounded half up to 1 decimal place."
    PRD 3.9: "`high_risk_compliance_pct` is one hundred multiplied by the pass
    count, divided by the high-risk count, rounded half up to 1 decimal place;
    when the high-risk count is 0 the field is null rather than 0.0, because a
    window containing no cardiac-arrest cases is not a window in which the centre
    failed them."

    Design: Difficulty/dual_variant_calc/accreditation_case_weighted_versus_dispatcher_equal_weight_inverts_threshold
    """
    env = _three_finalized_reviews_env(api)

    report = validate_success(
        api.create_accreditation_report(
            env["program_id"], dict(REPORT_WINDOW, variant="DISPATCHER_EQUAL_WEIGHT"), OFFICER
        ),
        201,
    )

    assert report["variant"] == "DISPATCHER_EQUAL_WEIGHT"
    assert report["review_count"] == 3
    assert report["dispatcher_count"] == 2
    # (1/1 + 1/2) / 2 * 100 = 75.0
    assert report["compliance_pct"] == approx1(75.0), (
        f"expected the mean of the per-dispatcher rates, got {report['compliance_pct']}"
    )
    assert report["high_risk_review_count"] == 0
    assert report["high_risk_compliance_pct"] is None
    assert report["status"] == "DRAFT"


def test_the_two_variants_disagree_about_the_accreditation_threshold(api):
    """PRD 3.9: "The two variants can disagree about the same data, and a heavily
    sampled weak dispatcher who sinks the case-weighted figure may leave the
    dispatcher-equal-weight figure comfortably above target — which is exactly why
    both are reported."
    PRD 3.9: "Finally `threshold_met` is true when `compliance_pct` is at or above
    the programme's `target_compliance_pct` **and** either
    `high_risk_compliance_pct` is null or it is at or above the programme's
    `high_risk_target_pct`."

    Design: Difficulty/dual_variant_calc/accreditation_case_weighted_versus_dispatcher_equal_weight_inverts_threshold
    """
    env = _three_finalized_reviews_env(api)

    case_weighted = fx.new_report(api, env["program_id"], variant="CASE_WEIGHTED", **REPORT_WINDOW)
    equal_weight = fx.new_report(
        api, env["program_id"], variant="DISPATCHER_EQUAL_WEIGHT", **REPORT_WINDOW
    )

    assert case_weighted["compliance_pct"] == approx1(66.7)
    assert case_weighted["threshold_met"] is False
    assert equal_weight["compliance_pct"] == approx1(75.0)
    assert equal_weight["threshold_met"] is True, (
        "75.0 is at the 75.0 target and the high-risk sub-figure is null"
    )
    assert case_weighted["review_count"] == equal_weight["review_count"] == 3, (
        "both variants aggregate exactly the same pool"
    )
