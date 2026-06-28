"""Readiness scoring, mastery, mock/practice arithmetic, and the dual-variant divergence.

Covers difficulty queue (A): dual_variant_calc, combinatorial_formula (readiness blend),
boundary_precision_check (readiness threshold), and corner queue (B) calculation instances
for mock scaling, practice batch precision, overage threshold, and immediate consistency.
"""
import pytest

from test_helpers import (
    validate_success,
    setup_active_enrollment,
    create_published_program, create_plan, create_learner, create_enrollment,
    activate, get_enrollment, set_clock,
    make_learner_headers,
    create_practice_session_payload, create_mock_exam_payload,
)


# ==========================================================================
# dual_variant_calc / readiness_conservative_vs_projected_diverges_on_enrollment
# ==========================================================================
def test_conservative_uses_latest_mock_projected_uses_average(api):
    """Conservative readiness uses only the latest mock while projected averages all mocks.

    PRD §3.4: "The conservative, gating `readiness_score` blends 0.60 of that weighted
    domain mastery with 0.40 of the single latest mock's `scaled_score`, the final blend
    rounded half up to an integer; the "latest mock" is the `COMPLETED` mock with the
    greatest `completed_at`, breaking ties by earliest `created_at` and then by creation
    order, and the mock component is zero when no completed mock exists."
    PRD §3.4: "the two diverge whenever the latest mock differs from the running mean."

    Design: Difficulty/dual_variant_calc/readiness_conservative_vs_projected_diverges_on_enrollment
    """
    ctx = setup_active_enrollment(
        license_code="CPA-FAR",
        domain_weights=[{"domain_code": "A", "weight": 0.50},
                        {"domain_code": "B", "weight": 0.30},
                        {"domain_code": "C", "weight": 0.20}],
        plan_overrides={"tier": "BASIC", "total_price_cents": 50000, "included_mock_credits": 5},
        learner_email="dv1@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])

    set_clock("2026-05-01T09:00:00Z")
    validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=70, item_count=100), lh), 201)
    set_clock("2026-05-02T09:00:00Z")
    validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=90, item_count=100), lh), 201)

    data = validate_success(api.get_enrollment_analytics(enr["id"], lh))
    # weighted_domain_mastery = 0.5*50+0.3*50+0.2*50 = 50
    # conservative: round(0.6*50 + 0.4*90) = round(66.0) = 66
    # projected: avg(70,90)=80 -> round(0.6*50 + 0.4*80) = round(62.0) = 62
    assert data["readiness_score"] == 66, f"expected conservative 66, got {data['readiness_score']}"
    assert data["projected_readiness_score"] == 62, \
        f"expected projected 62, got {data['projected_readiness_score']}"
    assert data["readiness_score"] != data["projected_readiness_score"]


def test_projected_diverges_from_conservative_when_latest_below_mean(api):
    """When the latest mock is lower than the mean, projected exceeds conservative.

    PRD §3.4: "The optimistic `projected_readiness_score` instead blends the same 0.60 of
    weighted domain mastery with 0.40 of the average mock score, where the average is the
    mean of `scaled_score` across *all* completed mocks, that mean itself rounded half up
    to an integer before blending, and zero when there are no mocks; the final projected
    blend is likewise rounded half up."
    PRD §3.4: "the two diverge whenever the latest mock differs from the running mean."

    Design: Difficulty/dual_variant_calc/readiness_conservative_vs_projected_diverges_on_enrollment
    """
    ctx = setup_active_enrollment(
        license_code="DV2-PROG",
        domain_weights=[{"domain_code": "A", "weight": 1.00}],
        plan_overrides={"tier": "BASIC", "total_price_cents": 50000, "included_mock_credits": 5},
        learner_email="dv2@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])

    set_clock("2026-05-01T09:00:00Z")
    validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=90, item_count=100), lh), 201)
    set_clock("2026-05-02T09:00:00Z")
    validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=70, item_count=100), lh), 201)

    data = validate_success(api.get_enrollment_analytics(enr["id"], lh))
    # masteries all 50, single domain weight 1.0 -> weighted = 50
    # conservative: latest mock = 70 -> round(0.6*50 + 0.4*70) = round(58.0) = 58
    # projected: mean(90,70)=80 -> round(0.6*50 + 0.4*80) = round(62.0) = 62
    assert data["readiness_score"] == 58, f"expected conservative 58, got {data['readiness_score']}"
    assert data["projected_readiness_score"] == 62, \
        f"expected projected 62, got {data['projected_readiness_score']}"
    assert data["readiness_score"] != data["projected_readiness_score"]


# ==========================================================================
# combinatorial_formula / readiness_weighted_blend_conditional_latest_mock_mode_a
# ==========================================================================
def test_readiness_weighted_blend_over_three_domains_and_latest_mock(api):
    """Readiness blends a 3-domain weighted mastery with the latest mock score.

    PRD §3.4: "First, the weighted domain mastery is the sum, over every study-plan domain
    of the enrollment, of that domain's `weight` multiplied by its `mastery`."
    PRD §3.4: "The conservative, gating `readiness_score` blends 0.60 of that weighted
    domain mastery with 0.40 of the single latest mock's `scaled_score`, the final blend
    rounded half up to an integer; the "latest mock" is the `COMPLETED` mock with the
    greatest `completed_at`, breaking ties by earliest `created_at` and then by creation
    order, and the mock component is zero when no completed mock exists."
    PRD §3.4: "The new mastery is the smoothing coefficient of 0.40 multiplied by the batch
    percentage, plus the complement 0.60 multiplied by the domain's prior mastery, the
    whole sum rounded half up to an integer and then clamped to the range 0 through 100."

    Design: Difficulty/combinatorial_formula/readiness_weighted_blend_conditional_latest_mock_mode_a
    """
    ctx = setup_active_enrollment(
        license_code="CPA-AUD",
        domain_weights=[{"domain_code": "A", "weight": 0.50},
                        {"domain_code": "B", "weight": 0.30},
                        {"domain_code": "C", "weight": 0.20}],
        plan_overrides={"tier": "BASIC", "total_price_cents": 40000, "included_mock_credits": 5},
        learner_email="blend@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])

    # Two practice sessions on A: 50 -> round(0.4*100+0.6*50)=70 -> round(0.4*95+0.6*70)=80
    validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=100, correct_count=100), lh), 201)
    validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=100, correct_count=95), lh), 201)
    set_clock("2026-05-05T09:00:00Z")
    validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=60, item_count=100), lh), 201)
    set_clock("2026-05-06T09:00:00Z")
    validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=90, item_count=100), lh), 201)

    domains = validate_success(api.list_domains(enr["id"], lh))
    by_code = {d["domain_code"]: d for d in domains}
    assert by_code["A"]["mastery"] == 80, f"A mastery expected 80, got {by_code['A']['mastery']}"
    assert by_code["B"]["mastery"] == 50 and by_code["C"]["mastery"] == 50

    data = validate_success(api.get_enrollment_analytics(enr["id"], lh))
    # weighted = 0.5*80 + 0.3*50 + 0.2*50 = 65; latest mock 90 -> round(0.6*65 + 0.4*90) = round(75.0) = 75
    assert data["readiness_score"] == 75, f"expected readiness 75, got {data['readiness_score']}"


def test_mastery_ewma_order_dependent_two_sessions(api):
    """EWMA mastery folds each batch into the running value in record order.

    PRD §3.4: "The new mastery is the smoothing coefficient of 0.40 multiplied by the batch
    percentage, plus the complement 0.60 multiplied by the domain's prior mastery, the
    whole sum rounded half up to an integer and then clamped to the range 0 through 100."

    Design: Difficulty/combinatorial_formula/readiness_weighted_blend_conditional_latest_mock_mode_a
    """
    ctx = setup_active_enrollment(
        license_code="EWMA-PROG",
        domain_weights=[{"domain_code": "A", "weight": 1.00}],
        learner_email="ewma@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])

    validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=100, correct_count=100), lh), 201)
    validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=100, correct_count=95), lh), 201)

    domains = validate_success(api.list_domains(enr["id"], lh))
    a = next(d for d in domains if d["domain_code"] == "A")
    # 50 -> round(0.4*100 + 0.6*50) = 70 -> round(0.4*95 + 0.6*70) = round(80.0) = 80
    assert a["mastery"] == 80, f"expected EWMA mastery 80, got {a['mastery']}"


# ==========================================================================
# boundary_precision_check / readiness_threshold_inclusive_75_qualifies_74_does_not
# (the >= boundary itself, via the readiness metric)
# ==========================================================================
def test_readiness_score_at_threshold_boundary_75(api):
    """Mastery 70 + latest mock 82 yields conservative readiness exactly 75.

    PRD §3.4: "The conservative, gating `readiness_score` blends 0.60 of that weighted
    domain mastery with 0.40 of the single latest mock's `scaled_score`, the final blend
    rounded half up to an integer; the "latest mock" is the `COMPLETED` mock with the
    greatest `completed_at`, breaking ties by earliest `created_at` and then by creation
    order, and the mock component is zero when no completed mock exists."

    Design: Difficulty/boundary_precision_check/readiness_threshold_inclusive_75_qualifies_74_does_not
    """
    ctx = setup_active_enrollment(
        license_code="BND-75",
        domain_weights=[{"domain_code": "A", "weight": 1.00}],
        plan_overrides={"tier": "BASIC", "total_price_cents": 30000, "included_mock_credits": 5},
        learner_email="b75@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    # practice 10/10: 50 -> round(0.4*100 + 0.6*50) = 70
    validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=10, correct_count=10), lh), 201)
    data = validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=82, item_count=100), lh), 201)
    enr = get_enrollment(enr["id"], learner["id"])
    # round(0.6*70 + 0.4*82) = round(75.0) = 75
    assert enr["readiness_score"] == 75, f"expected readiness 75, got {enr['readiness_score']}"


def test_readiness_score_just_below_threshold_74(api):
    """Mastery 70 + latest mock 81 yields conservative readiness 74 (below the 75 boundary).

    PRD §3.4: "The conservative, gating `readiness_score` blends 0.60 of that weighted
    domain mastery with 0.40 of the single latest mock's `scaled_score`, the final blend
    rounded half up to an integer; the "latest mock" is the `COMPLETED` mock with the
    greatest `completed_at`, breaking ties by earliest `created_at` and then by creation
    order, and the mock component is zero when no completed mock exists."

    Design: Difficulty/boundary_precision_check/readiness_threshold_inclusive_75_qualifies_74_does_not
    """
    ctx = setup_active_enrollment(
        license_code="BND-74",
        domain_weights=[{"domain_code": "A", "weight": 1.00}],
        plan_overrides={"tier": "BASIC", "total_price_cents": 30000, "included_mock_credits": 5},
        learner_email="b74@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=10, correct_count=10), lh), 201)
    validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=81, item_count=100), lh), 201)
    enr = get_enrollment(enr["id"], learner["id"])
    # round(0.6*70 + 0.4*81) = round(74.4) = 74
    assert enr["readiness_score"] == 74, f"expected readiness 74, got {enr['readiness_score']}"


# ==========================================================================
# Corner / calculations / mock_scaled_score_rounds_half_up
# ==========================================================================
def test_mock_scaled_score_rounds_half_up(api):
    """A mock raw 5 of 8 scales to round_half_up(62.5) = 63.

    PRD §3.4: "`scaled_score` is one hundred times the raw score divided by the item count,
    rounded half up to an integer on a 0-to-100 scale, and `completed_at` is stamped with
    the current logical-clock time so the latest attempt can later be identified."

    Design: Corner/calculations/mock_scaled_score_rounds_half_up
    """
    ctx = setup_active_enrollment(license_code="MSC", learner_email="msc@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    data = validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=5, item_count=8), lh), 201)
    assert data["scaled_score"] == 63, f"expected scaled_score 63, got {data['scaled_score']}"


# ==========================================================================
# Corner / calculations / practice_batch_pct_precision
# ==========================================================================
def test_practice_batch_pct_and_mastery_precision(api):
    """answered 3 correct 2 -> batch_pct 67 and EWMA mastery from 50 -> 57.

    PRD §3.4: "the system computes the batch percentage `batch_pct` as one hundred times
    the correct count divided by the answered count, rounded half up to an integer."
    PRD §3.4: "The new mastery is the smoothing coefficient of 0.40 multiplied by the batch
    percentage, plus the complement 0.60 multiplied by the domain's prior mastery, the
    whole sum rounded half up to an integer and then clamped to the range 0 through 100."

    Design: Corner/calculations/practice_batch_pct_precision
    """
    ctx = setup_active_enrollment(license_code="PBP", learner_email="pbp@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    data = validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=3, correct_count=2), lh), 201)
    assert data["batch_pct"] == 67, f"expected batch_pct 67, got {data['batch_pct']}"

    domains = validate_success(api.list_domains(enr["id"], lh))
    a = next(d for d in domains if d["domain_code"] == "A")
    # round(0.4*67 + 0.6*50) = round(56.8) = 57
    assert a["mastery"] == 57, f"expected mastery 57, got {a['mastery']}"


# ==========================================================================
# Corner / calculations / mock_overage_threshold_boundary
# ==========================================================================
def test_mock_overage_threshold_boundary(api):
    """With included_mock_credits=1, the first mock is not overage and the second is.

    PRD §3.4: "The system also marks `is_overage`: counting the mock exams already in
    `COMPLETED` status for the enrollment *before* this attempt, the attempt is an overage
    when that prior count is greater than or equal to the plan's `included_mock_credits`."
    PRD §3.4: "In other words, with N included credits, attempts 1 through N are included
    and attempt N+1 is the first overage."

    Design: Corner/calculations/mock_overage_threshold_boundary
    """
    ctx = setup_active_enrollment(
        license_code="OVG",
        plan_overrides={"tier": "BASIC", "total_price_cents": 30000, "included_mock_credits": 1},
        learner_email="ovg@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    set_clock("2026-05-20T09:00:00Z")
    first = validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=50, item_count=100), lh), 201)
    set_clock("2026-05-21T09:00:00Z")
    second = validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=60, item_count=100), lh), 201)
    assert first["is_overage"] is False, "first attempt (within credit) must not be overage"
    assert second["is_overage"] is True, "second attempt (credit+1) must be overage"


# ==========================================================================
# Corner / consistency_model / immediate_consistency_readiness_visible_same_response
# ==========================================================================
def test_readiness_visible_immediately_after_mock(api):
    """A posted mock's readiness recompute is visible in the very next GET.

    PRD §3.4: "Recording a mock increases the enrollment's `completed_mock_count`,
    recomputes readiness, and re-versions the enrollment."
    PRD §3.4: "The conservative figure is the one used for every gating decision and for
    readiness display; the projected figure is the forward-looking analytics view, and the
    two diverge whenever the latest mock differs from the running mean."

    Design: Corner/consistency_model/immediate_consistency_readiness_visible_same_response
    """
    ctx = setup_active_enrollment(license_code="IMM", learner_email="imm@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    validate_success(api.create_mock_exam(enr["id"], create_mock_exam_payload(raw_score=90, item_count=100), lh), 201)
    data = validate_success(api.get_enrollment(enr["id"], lh))
    # masteries 50, single domain -> round(0.6*50 + 0.4*90) = round(66.0) = 66
    assert data["readiness_score"] == 66, f"expected readiness 66, got {data['readiness_score']}"
    assert data["completed_mock_count"] == 1
