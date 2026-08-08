"""Readiness scoring, the PASS threshold, and activation gating."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_pending_enrollment,
)
from test_helpers import factories as F

CM = TEST_USERS["case_manager_headers"]


def test_readiness_score_heavy_smoker_tiered(api):
    """PRD §3.3: "Start from the sum of `motivation_score` and `confidence_score`.
    Add a prior-attempts bonus: zero when `prior_quit_attempts` is 0, one when it
    is 1 or 2, and two when it is 3 or more. Then subtract a dependence penalty
    based on the snapshotted `cigarettes_per_day`: zero when it is 10 or fewer, one
    when it is between 11 and 20 inclusive, and two when it is 21 or more."
    PRD §3.3: "The assessment's `result` is `PASS` when the resulting
    `readiness_score` is at least `READINESS_PASS_THRESHOLD` (12), and `FAIL` otherwise."

    Design: Difficulty/combinatorial_formula/readiness_score_tiered_nonlinear
    """
    ctx = setup_pending_enrollment(api, cpd=25)
    resp = api.create_readiness_assessment(
        ctx["enrollment_id"],
        F.create_readiness_assessment_payload(
            motivation_score=8, confidence_score=8, prior_quit_attempts=3
        ),
        CM,
    )
    data = validate_success(resp, 201)
    # 8 + 8 + prior_bonus(3->2) - penalty(cpd25->2) == 16
    assert data["readiness_score"] == 16, f"expected 16, got {data['readiness_score']}"
    assert data["result"] == "PASS"


def test_readiness_score_mirrors_onto_enrollment(api):
    """PRD §3.3: "Each new assessment refreshes the enrollment's `readiness_score`
    and `readiness_result` to mirror the latest one."

    Design: Difficulty/combinatorial_formula/readiness_score_tiered_nonlinear
    """
    ctx = setup_pending_enrollment(api, cpd=25)
    api.create_readiness_assessment(
        ctx["enrollment_id"],
        F.create_readiness_assessment_payload(
            motivation_score=8, confidence_score=8, prior_quit_attempts=3
        ),
        CM,
    )
    enr = validate_success(api.get_enrollment(ctx["enrollment_id"], CM))
    assert enr["readiness_score"] == 16
    assert enr["readiness_result"] == "PASS"


def test_readiness_threshold_exactly_twelve_passes(api):
    """PRD §3.3: "The assessment's `result` is `PASS` when the resulting
    `readiness_score` is at least `READINESS_PASS_THRESHOLD` (12), and `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/readiness_threshold_exactly_12_passes
    """
    ctx = setup_pending_enrollment(api, cpd=10)
    # cpd 10 -> penalty 0; 6 + 6 + 0 - 0 == 12 (exactly the threshold)
    data = validate_success(
        api.create_readiness_assessment(
            ctx["enrollment_id"],
            F.create_readiness_assessment_payload(
                motivation_score=6, confidence_score=6, prior_quit_attempts=0
            ),
            CM,
        ),
        201,
    )
    assert data["readiness_score"] == 12
    assert data["result"] == "PASS"


def test_readiness_threshold_eleven_fails(api):
    """PRD §3.3: "The assessment's `result` is `PASS` when the resulting
    `readiness_score` is at least `READINESS_PASS_THRESHOLD` (12), and `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/readiness_threshold_exactly_12_passes
    """
    ctx = setup_pending_enrollment(api, cpd=10)
    # 6 + 5 + 0 - 0 == 11 (one below threshold)
    data = validate_success(
        api.create_readiness_assessment(
            ctx["enrollment_id"],
            F.create_readiness_assessment_payload(
                motivation_score=6, confidence_score=5, prior_quit_attempts=0
            ),
            CM,
        ),
        201,
    )
    assert data["readiness_score"] == 11
    assert data["result"] == "FAIL"


def test_readiness_score_light_smoker_no_penalty(api):
    """PRD §3.3: "Add a prior-attempts bonus: zero when `prior_quit_attempts` is 0,
    one when it is 1 or 2, and two when it is 3 or more. Then subtract a dependence
    penalty based on the snapshotted `cigarettes_per_day`: zero when it is 10 or
    fewer, one when it is between 11 and 20 inclusive, and two when it is 21 or more."

    Design: Corner/calculations/readiness_score_light_smoker_no_penalty
    """
    ctx = setup_pending_enrollment(api, cpd=8)
    # 5 + 5 + prior_bonus(1->1) - penalty(cpd8->0) == 11 -> FAIL
    data = validate_success(
        api.create_readiness_assessment(
            ctx["enrollment_id"],
            F.create_readiness_assessment_payload(
                motivation_score=5, confidence_score=5, prior_quit_attempts=1
            ),
            CM,
        ),
        201,
    )
    assert data["readiness_score"] == 11
    assert data["result"] == "FAIL"


def test_activate_without_pass_returns_readiness_not_met(api):
    """PRD §3.3: "activating while the latest result is `FAIL` (or while none exists)
    is rejected with `ERR_READINESS_NOT_MET`."

    Design: Corner/state_machines/activate_without_pass_returns_readiness_not_met
    """
    ctx = setup_pending_enrollment(api, cpd=10)
    # 6 + 5, cpd10 -> score 11 -> FAIL
    api.create_readiness_assessment(
        ctx["enrollment_id"],
        F.create_readiness_assessment_payload(
            motivation_score=6, confidence_score=5, prior_quit_attempts=0
        ),
        CM,
    )
    resp = api.activate_enrollment(ctx["enrollment_id"], CM)
    validate_error(resp, ApiErrorId.ERR_READINESS_NOT_MET.value)
    enr = validate_success(api.get_enrollment(ctx["enrollment_id"], CM))
    assert enr["status"] == "PENDING_ASSESSMENT"
