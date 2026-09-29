"""Two determinations that read the same rows under two named variants: the
measurable-skill-gain reading and the funding-allocation candidate filter.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import (
    assert_allocation_preview,
    assert_funding_pool_conserved,
    assert_skill_gain_read,
)
from test_helpers.test_users import make_state_authority_headers
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    MeasureType,
    MsgVariant,
    OutcomeStatus,
)

#: The learner's post-tests regress: 225 (level 4) on 2026-09-02 and then 208
#: (level 2) on 2026-09-05, so the two readings disagree about the gain.
BEST_POST_AT = "2026-09-02T10:00:00Z"
LATEST_POST_AT = "2026-09-05T10:00:00Z"


def _setup_regressed_post_tests():
    """A placed learner with 40.00 hours and two scored post-tests, the later lower."""
    period = fixtures.create_funding_period(rate_cents_per_weight=10000, total_cents=100000)
    context = fixtures.setup_enrollment_with_hours(
        total_hours=40.00,
        scale_score=205,
        first_date="2026-08-03",
        self_pay_authorized=True,
    )
    student_id = context["student_id"]
    enrollment_id = context["enrollment"]["id"]
    fixtures.score_post_test(student_id, enrollment_id, BEST_POST_AT, 225)
    fixtures.score_post_test(student_id, enrollment_id, LATEST_POST_AT, 208)
    outcome = fixtures.record_outcome(
        student_id,
        period["id"],
        measure_type=MeasureType.EFL_GAIN,
        evidence_ref="NRS-EFL-0001",
    )
    return {
        "period_id": period["id"],
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "outcome_id": outcome["id"],
    }


def _setup_mixed_review_states():
    """One CERTIFIED employment claim and one merely RECORDED postsecondary claim."""
    period = fixtures.create_funding_period(rate_cents_per_weight=10000, total_cents=100000)
    placed = fixtures.create_placed_student()
    employment = fixtures.certified_outcome(
        placed["student_id"],
        period["id"],
        measure_type=MeasureType.EMPLOYMENT_Q2,
        evidence_ref="WAGE-Q2-0001",
    )
    postsecondary = fixtures.record_outcome(
        placed["student_id"],
        period["id"],
        measure_type=MeasureType.POSTSECONDARY_ENROLLMENT,
        evidence_ref="NSC-0001",
    )
    return {
        "period_id": period["id"],
        "employment_id": employment["id"],
        "postsecondary_id": postsecondary["id"],
    }


def test_01_best_post_reading_reports_the_highest_post_test():
    """"The **`BEST_POST`** reading selects the post-test with the highest `efl_level`,
    breaking ties by `test_date` ascending and then `created_at` ascending. Because
    it takes the learner's best showing, a later regression is ignored and a gain
    can be reported."

    Design: Difficulty/dual_variant_calc/msg_variant_best_post_vs_latest_post_diverges
    """
    context = _setup_regressed_post_tests()

    reading = fixtures.read_skill_gain(
        context["student_id"],
        variant=MsgVariant.BEST_POST,
        funding_period_id=context["period_id"],
    )
    assert_skill_gain_read(reading)

    assert reading["variant"] == MsgVariant.BEST_POST
    assert reading["entry_efl_level"] == 2
    assert reading["post_efl_level"] == 4
    assert reading["best_post_scale_score"] == 225
    assert reading["levels_gained"] == 2
    assert reading["msg_achieved"] is True


def test_02_latest_post_reading_reports_the_chronologically_last_post_test():
    """"The **`LATEST_POST`** reading selects the chronologically last post-test, ordering
    by `test_date` descending and breaking ties by `created_at` descending. Because
    the most recent result governs, the same learner and the same events can yield no
    gain when a later post-test came in lower."

    Design: Difficulty/dual_variant_calc/msg_variant_best_post_vs_latest_post_diverges
    """
    context = _setup_regressed_post_tests()

    reading = fixtures.read_skill_gain(
        context["student_id"],
        variant=MsgVariant.LATEST_POST,
        funding_period_id=context["period_id"],
    )
    assert_skill_gain_read(reading)

    assert reading["variant"] == MsgVariant.LATEST_POST
    assert reading["entry_efl_level"] == 2
    assert reading["post_efl_level"] == 2
    assert reading["latest_post_scale_score"] == 208
    assert reading["levels_gained"] == 0
    assert reading["msg_achieved"] is False


def test_03_efl_gain_certification_follows_the_audited_latest_post_reading():
    """"a `CERTIFY` decision on an `EFL_GAIN` claim additionally requires the audited
    `LATEST_POST` reading of the skill-gain determination described in §3.3 to report
    a gain, and is refused with `ERR_MSG_NOT_SUPPORTED` when it does not — which is
    why a learner whose `BEST_POST` preview looked positive can still fail
    certification if their most recent post-test regressed."

    Design: Difficulty/dual_variant_calc/msg_variant_best_post_vs_latest_post_diverges
    """
    context = _setup_regressed_post_tests()

    response = api_client.decide_outcome_certification(
        context["outcome_id"],
        factories.outcome_certification_payload(),
        headers=make_state_authority_headers(),
    )
    validate_error(response, ApiErrorId.MSG_NOT_SUPPORTED, expected_status=409)

    refused = fixtures.read_outcome(context["outcome_id"])
    assert refused["status"] == OutcomeStatus.RECORDED
    assert refused["certified_by_user_id"] is None
    assert refused["allocation_status"] == AllocationStatus.UNALLOCATED


def test_04_provisional_preview_admits_recorded_and_certified_claims():
    """"The **`PROVISIONAL`** variant admits claims whose `status` is `RECORDED` or
    `CERTIFIED`. It is the mid-year forecast, and because it counts claims nobody has
    yet blessed, its `committed_cents` figure can exceed the final one on the same
    records."

    Design: Difficulty/dual_variant_calc/funding_allocation_provisional_vs_final_diverges
    """
    context = _setup_mixed_review_states()

    preview = fixtures.read_allocation_preview(
        context["period_id"], variant=AllocationVariant.PROVISIONAL
    )
    assert_allocation_preview(preview)

    assert preview["variant"] == AllocationVariant.PROVISIONAL
    assert preview["line_count"] == 2
    assert float(preview["total_weight"]) == 2.65
    assert preview["projected_committed_cents"] == 26500
    assert preview["projected_available_cents"] == 73500
    assert preview["deferred_line_count"] == 0

    # The preview writes nothing at all.
    period = fixtures.read_funding_period(context["period_id"])
    assert period["committed_cents"] == 0
    assert period["available_cents"] == 100000
    assert period["allocation_run_count"] == 0


def test_05_final_preview_admits_only_certified_claims():
    """"The **`FINAL`** variant admits only claims whose `status` is `CERTIFIED`. It is
    the period-close settlement, and a merely `RECORDED` claim contributes nothing to
    it."

    Design: Difficulty/dual_variant_calc/funding_allocation_provisional_vs_final_diverges
    """
    context = _setup_mixed_review_states()

    preview = fixtures.read_allocation_preview(
        context["period_id"], variant=AllocationVariant.FINAL
    )
    assert_allocation_preview(preview)

    assert preview["variant"] == AllocationVariant.FINAL
    assert preview["line_count"] == 1
    assert float(preview["total_weight"]) == 1.25
    assert preview["projected_committed_cents"] == 12500
    assert preview["projected_available_cents"] == 87500
    assert preview["deferred_line_count"] == 0


def test_06_final_run_commits_only_the_certified_line():
    """"When the walk finishes, the period's `committed_cents` rises by the exact
    integer sum of the committed line amounts, each already rounded, and
    `available_cents` is recomputed as `total_cents` less `committed_cents`." and "The
    run also increments `allocation_run_count` by one, stamps `last_allocation_run_at`
    from the logical clock, and records the applied variant as
    `last_allocation_variant`."

    Design: Difficulty/dual_variant_calc/funding_allocation_provisional_vs_final_diverges
    """
    context = _setup_mixed_review_states()

    period = fixtures.run_allocation(context["period_id"], variant=AllocationVariant.FINAL)
    assert_funding_pool_conserved(period)

    assert period["committed_cents"] == 12500
    assert period["available_cents"] == 87500
    assert period["allocation_run_count"] == 1
    assert period["last_allocation_variant"] == AllocationVariant.FINAL
    assert period["last_allocation_run_at"] is not None

    employment = fixtures.read_outcome(context["employment_id"])
    assert employment["allocated_cents"] == 12500
    assert employment["allocation_status"] == AllocationStatus.COMMITTED

    postsecondary = fixtures.read_outcome(context["postsecondary_id"])
    assert postsecondary["allocated_cents"] == 0
    assert postsecondary["allocation_status"] == AllocationStatus.UNALLOCATED


def test_07_preview_default_variant_is_the_final_settlement_view():
    """"A side-effect-free preview of the same computation is available to a
    `StateAuthority` or `ProgramCoordinator`, taking an optional `variant` that
    defaults to `FINAL`."

    Design: Difficulty/dual_variant_calc/funding_allocation_provisional_vs_final_diverges
    """
    context = _setup_mixed_review_states()

    response = api_client.get_allocation_preview(
        context["period_id"], headers=make_state_authority_headers()
    )
    defaulted = validate_success(response)
    assert_allocation_preview(defaulted)

    assert defaulted["variant"] == AllocationVariant.FINAL
    assert defaulted["line_count"] == 1
    assert defaulted["projected_committed_cents"] == 12500
