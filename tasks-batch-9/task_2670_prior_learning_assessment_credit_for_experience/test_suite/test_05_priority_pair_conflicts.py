"""Requests that break two ladder rungs at once.

The contract fixes which of the two answers comes back, so each scenario is
arranged so that both rungs are genuinely live and then the losing rung is
cleared to prove it was.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_claim_dimensions, assert_fields_equal, assert_ledger
from test_helpers.test_users import (
    COORDINATOR,
    OFFICER_APPROVER,
    OFFICER_REVIEWER,
    make_student_headers,
)
from test_helpers.types import (
    AssessmentStatus,
    CourseLevel,
    PaymentMethod,
    Recommendation,
    RuleStatus,
    SourceType,
    SuspendReason,
)


@pytest.fixture
def scored_claim_over_a_suspended_rule_and_a_shrunken_cap(client):
    """A SCORED exam claim whose crosswalk is suspended and whose cap is now 3.

    Suspension deliberately leaves a `SCORED` claim alone, so the claim survives
    into the award decision carrying both defects at once.
    """
    program = fx.new_program(
        client,
        program_code="BSCS",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
        allowed_source_types=[SourceType.CREDIT_BY_EXAM, SourceType.PORTFOLIO],
    )
    course = fx.new_course(
        client,
        course_code="CS150",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=[
            f.outcome_payload("OC1", 8000, mastery_threshold_bp=7000),
            f.outcome_payload("OC2", 2000, mastery_threshold_bp=7000),
        ],
    )
    outcomes = fx.outcomes_of(client, course["id"])
    student = fx.new_student(
        client, program["id"], transfer_credits_accepted=0, institutional_credits_earned=60
    )
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    recommendation = fx.published_recommendation(
        client,
        credential_code="CLEP-CS",
        source_type=SourceType.CREDIT_BY_EXAM,
        recommended_credits=6,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-01-01T00:00:00Z",
    )
    rule = fx.approved_rule(
        client,
        recommendation["id"],
        course["id"],
        awarded_credits=6,
        effective_from="2026-01-01T00:00:00Z",
    )
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.CREDIT_BY_EXAM,
        credits_requested=6,
        articulation_rule_id=rule["id"],
        attempt_date="2026-06-15T00:00:00Z",
    )
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.pay_invoice(
            invoice["id"],
            f.payment_payload(19000, PaymentMethod.CARD),
            headers=make_student_headers(student["id"]),
        )
    )
    # OC1 at 4 of 4 and OC2 at 3 of 4 weight to 9500 basis points, which is a PASS.
    scored = fx.scored_claim(
        client, claim["id"], assessor["id"], outcomes, [4, 3], Recommendation.PASS
    )
    get_success_data(
        client.suspend_rule(
            rule["id"], {"suspend_reason": SuspendReason.MANUAL_REVIEW}, headers=OFFICER_APPROVER
        )
    )
    shrunken = get_success_data(
        client.patch_program(program["id"], {"pla_max_credits": 3}, headers=COORDINATOR)
    )
    return {
        "program": shrunken,
        "student": student,
        "rule": rule,
        "claim": scored,
    }


def test_suspended_crosswalk_outranks_the_shrunken_programme_cap_at_award(
    client, scored_claim_over_a_suspended_rule_and_a_shrunken_cap
):
    """Rung 21 answers even though rung 39 is violated in the same request.

    PRD: "a caller who violates two rules at once must receive the error belonging
    to the *lower-numbered* rung". Rung 21: "**Crosswalk still approved.** The
    claim's pinned crosswalk rule is `APPROVED` and its parent recommendation is
    `PUBLISHED`. Failure: `ERR_ARTICULATION_NOT_APPROVED` (409). Applies to awarding
    a claim and posting to the transcript." Rung 39: "At award, `credits_awarded` is
    at most the reserved-inclusive remaining capacity measured with this claim's own
    reservation released".

    Design: Difficulty/priority_pair_validation_conflict/articulation_not_approved_priority21_beats_pla_cap_exceeded_priority39
    """
    scenario = scored_claim_over_a_suspended_rule_and_a_shrunken_cap
    assert_claim_dimensions(scenario["claim"], assessment_status=AssessmentStatus.SCORED)
    assert_fields_equal(scenario["claim"], verified_coverage_bp=9500)
    rule = get_success_data(client.get_rule(scenario["rule"]["id"], headers=OFFICER_APPROVER))
    assert_fields_equal(rule, status=RuleStatus.SUSPENDED)
    assert_fields_equal(scenario["program"], effective_pla_cap_credits=3)

    student_before = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    # Reserved-inclusive headroom with this claim's own 6 credits released is 3,
    # so an award of 6 credits also breaches rung 39.
    assert_ledger(student_before, reserved=6, awarded=0, posted=0)

    response = client.award_claim(
        scenario["claim"]["id"],
        {"expected_student_version": student_before["version"], "credits_awarded": 6},
        headers=COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_ARTICULATION_NOT_APPROVED, 409)

    unchanged = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(unchanged, assessment_status=AssessmentStatus.SCORED)
    assert unchanged["credits_awarded"] is None, (
        "a rejected award must not record credits_awarded, got %r" % (unchanged["credits_awarded"],)
    )

    student_after = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert student_after["version"] == student_before["version"], (
        "a rejected award performs no ledger write, so version must not move"
    )
    assert_ledger(student_after, reserved=6, awarded=0, posted=0)


def test_reinstating_the_crosswalk_exposes_the_cap_breach_underneath(
    client, scored_claim_over_a_suspended_rule_and_a_shrunken_cap
):
    """With rung 21 satisfied the same award now reports the cap.

    PRD: "Reinstating a `SUSPENDED` rule reverses the institutional hold. It
    advances `SUSPENDED → APPROVED`". Rung 39: "**Programme credit cap.** At award,
    `credits_awarded` is at most the reserved-inclusive remaining capacity measured
    with this claim's own reservation released; at posting, `posted_credits` is at
    most the posted-only remaining capacity. Failure: `ERR_PLA_CAP_EXCEEDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/articulation_not_approved_priority21_beats_pla_cap_exceeded_priority39
    """
    scenario = scored_claim_over_a_suspended_rule_and_a_shrunken_cap
    reinstated = validate_success(
        client.reinstate_rule(scenario["rule"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(reinstated, status=RuleStatus.APPROVED, suspend_reason=None)

    student = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    response = client.award_claim(
        scenario["claim"]["id"],
        {"expected_student_version": student["version"], "credits_awarded": 6},
        headers=COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_PLA_CAP_EXCEEDED, 409)

    unchanged = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(unchanged, assessment_status=AssessmentStatus.SCORED)
    assert unchanged["credits_awarded"] is None


@pytest.fixture
def second_rule_under_review_behind_an_amendment(client):
    """Two rules on one recommendation-and-course pair, with a stale read in hand.

    R1 is already `APPROVED` over an open-ended window from 2026-01-01, and R2 sits
    in `UNDER_REVIEW` over an overlapping open-ended window from 2026-06-01. The
    approver reads the recommendation version and only then is the recommendation
    amended, so the token they hold is one behind.
    """
    course = fx.new_course(
        client,
        course_code="CS150",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=[f.outcome_payload("OC1", 10000, mastery_threshold_bp=7000)],
    )
    recommendation = fx.published_recommendation(
        client,
        credential_code="CLEP-CS",
        source_type=SourceType.CREDIT_BY_EXAM,
        recommended_credits=6,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-01-01T00:00:00Z",
    )
    rule_one = fx.approved_rule(
        client,
        recommendation["id"],
        course["id"],
        awarded_credits=6,
        effective_from="2026-01-01T00:00:00Z",
    )
    rule_two = get_success_data(
        client.create_rule(
            f.rule_payload(
                recommendation["id"],
                course["id"],
                awarded_credits=5,
                effective_from="2026-06-01T00:00:00Z",
            ),
            headers=OFFICER_REVIEWER,
        )
    )
    get_success_data(client.submit_rule_for_review(rule_two["id"], headers=OFFICER_REVIEWER))
    stale_read = get_success_data(
        client.get_recommendation(recommendation["id"], headers=OFFICER_APPROVER)
    )
    amended = get_success_data(
        client.patch_recommendation(
            recommendation["id"], {"recommended_credits": 5}, headers=OFFICER_REVIEWER
        )
    )
    return {
        "recommendation": recommendation,
        "rule_one": rule_one,
        "rule_two": rule_two,
        "stale_read": stale_read,
        "amended": amended,
    }


def test_stale_recommendation_version_outranks_the_window_overlap(
    client, second_rule_under_review_behind_an_amendment
):
    """Rung 13 answers with 412 even though the overlap at rung 29 is unconditional.

    PRD: "**Recommendation concurrency.** `expected_recommendation_version` equals
    the current `CredentialRecommendation` `version`. Failure:
    `ERR_STALE_RECOMMENDATION_VERSION` (412). Applies to approving a crosswalk
    rule." "Amending a recommendation is the only operation that moves
    `terms_version`: it accepts any of `recommended_credits`, `recommended_level`,
    `title` and `effective_to`, increments `terms_version` by one **and** increments
    `version` by one."

    Design: Difficulty/priority_pair_validation_conflict/stale_recommendation_version_412_beats_articulation_window_overlap_409
    """
    scenario = second_rule_under_review_behind_an_amendment
    assert scenario["amended"]["version"] == scenario["stale_read"]["version"] + 1
    assert scenario["amended"]["terms_version"] == scenario["stale_read"]["terms_version"] + 1

    response = client.approve_rule(
        scenario["rule_two"]["id"],
        {"expected_recommendation_version": scenario["stale_read"]["version"]},
        headers=OFFICER_APPROVER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_RECOMMENDATION_VERSION, 412)

    rule_two = get_success_data(
        client.get_rule(scenario["rule_two"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(rule_two, status=RuleStatus.UNDER_REVIEW, pinned_recommendation_version=None)

    rule_one = get_success_data(
        client.get_rule(scenario["rule_one"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(rule_one, status=RuleStatus.APPROVED)

    recommendation = get_success_data(
        client.get_recommendation(scenario["recommendation"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(recommendation, approved_rule_count=1)


def test_a_fresh_token_then_reveals_the_overlapping_window(
    client, second_rule_under_review_behind_an_amendment
):
    """With rung 13 satisfied the same approval reports the overlap at 409.

    PRD: "Two rules conflict when they share both `recommendation_id` and
    `course_id`, the other rule's `status` is `APPROVED`, and their validity windows
    overlap under **half-open** semantics: each window includes its `effective_from`
    and excludes its `effective_to`, and a null `effective_to` extends to positive
    infinity."

    Design: Difficulty/priority_pair_validation_conflict/stale_recommendation_version_412_beats_articulation_window_overlap_409
    """
    scenario = second_rule_under_review_behind_an_amendment
    current = get_success_data(
        client.get_recommendation(scenario["recommendation"]["id"], headers=OFFICER_APPROVER)
    )
    response = client.approve_rule(
        scenario["rule_two"]["id"],
        {"expected_recommendation_version": current["version"]},
        headers=OFFICER_APPROVER,
    )
    validate_error(response, ApiErrorId.ERR_ARTICULATION_WINDOW_OVERLAP, 409)

    rule_two = get_success_data(
        client.get_rule(scenario["rule_two"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(rule_two, status=RuleStatus.UNDER_REVIEW, pinned_recommendation_version=None)

    after = get_success_data(
        client.get_recommendation(scenario["recommendation"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(after, approved_rule_count=1)
