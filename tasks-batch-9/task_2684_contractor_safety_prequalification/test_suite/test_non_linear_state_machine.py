"""Difficulty rule: non_linear_state_machine.

Rows that leave a state and come back: a conditional prequalification that
re-enters review and is graded a second time, and a certificate whose two
independent dimensions advance in different directions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import validate_success  # noqa: E402

from test_helpers.assertions import (  # noqa: E402
    assert_certificate_state,
    assert_contractor_posture,
    assert_effective_thresholds,
    assert_instant_equals,
    assert_prequalification_state,
    reconcile_open_deficiency_count,
)
from test_helpers.constants import ANALYST_INSURANCE, INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import (  # noqa: E402
    certificate_decision_payload,
    certificate_payload,
    improvement_plan_decision_payload,
    improvement_plan_payload,
    improvement_plan_submit_payload,
    variance_decision_payload,
    variance_payload,
)
from test_helpers.test_users import make_analyst_headers  # noqa: E402

_SOFT_EMR_STATISTIC = {"emr": 1.01}


def test_soft_emr_breach_grades_conditional_at_77_89(build, api):
    """An EMR of 1.01 inside the 1.2000 tolerance band is a soft breach.

    PRD Section 3.6: "A metric is a **soft breach** when its value exceeds its
    effective ceiling but does not exceed its tolerance ceiling."

    Design: Difficulty/non_linear_state_machine/conditional_prequalification_reenters_under_review_and_regrades_approved_after_variance
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides=_SOFT_EMR_STATISTIC)

    graded = scenario["prequalification"]
    assert_prequalification_state(
        graded,
        status="CONDITIONAL",
        grade="B",
        deficiency_codes=["EMR"],
        final_composite_score=77.89,
    )
    assert_instant_equals(graded["conditional_expires_at"], "2026-10-30T00:00:00Z")
    assert_instant_equals(graded["expires_at"], "2027-08-01T00:00:00Z")

    contractor = build.read_contractor(scenario["contractor_id"])
    assert_contractor_posture(contractor, open_deficiency_count=1)


def test_approved_variance_and_accepted_plan_regrade_the_row_to_78_49(build, api):
    """The re-entered row is graded against the variance-loosened EMR ceiling.

    PRD Section 3.6: "Every variance on this prequalification whose `status` is
    `APPROVED`, whose `expires_at` is strictly after the logical clock, and
    whose `requirement_code` is one of `TRIR`, `DART`, `EMR` or
    `CITATION_POINTS` relaxes the matching effective ceiling: that ceiling
    becomes the greater of its already-tightened value and the variance's
    `requested_value` rounded half-up to four decimal places."

    Design: Difficulty/non_linear_state_machine/conditional_prequalification_reenters_under_review_and_regrades_approved_after_variance
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides=_SOFT_EMR_STATISTIC)
    pq_id = scenario["prequalification_id"]

    variance = validate_success(
        api.create_variance(
            pq_id,
            variance_payload(
                requirement_code="EMR",
                requested_value=1.05,
                justification=(
                    "Carrier recalculated the modifier after a disputed claim "
                    "was withdrawn"
                ),
            ),
            scenario["contractor_headers"],
        ),
        201,
    )
    decided = validate_success(
        api.decide_variance(
            variance["id"],
            variance_decision_payload("APPROVE", expires_at="2027-01-01T00:00:00Z"),
            scenario["manager_headers"],
        )
    )
    assert decided["status"] == "APPROVED"

    current = build.read_prequalification(pq_id)
    plan = validate_success(
        api.create_improvement_plan(
            pq_id,
            improvement_plan_payload(
                expected_prequalification_version=current["version"],
                due_date="2026-09-30T00:00:00Z",
                milestone_count=3,
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    validate_success(
        api.submit_improvement_plan(
            plan["id"],
            improvement_plan_submit_payload("EVID-EMR-REMEDIATION-1"),
            scenario["contractor_headers"],
        )
    )
    validate_success(
        api.decide_improvement_plan(
            plan["id"],
            improvement_plan_decision_payload("ACCEPT"),
            scenario["manager_headers"],
        )
    )

    reopened = build.read_prequalification(pq_id)
    assert_prequalification_state(reopened, status="UNDER_REVIEW", grade=None)

    regraded = build.grade_prequalification(pq_id, scenario["client_id"])
    assert_prequalification_state(
        regraded,
        status="APPROVED",
        grade="B",
        deficiency_codes=[],
        final_composite_score=78.49,
    )
    assert_effective_thresholds(
        regraded["effective_thresholds"],
        max_trir=3.0000,
        max_dart_rate=1.5000,
        max_emr=1.0500,
        max_citation_points=6.0000,
        tightening=1.00,
        hazard_tier=1,
    )
    assert regraded["conditional_expires_at"] is None
    assert_instant_equals(regraded["expires_at"], "2027-08-01T00:00:00Z")

    assert (
        reconcile_open_deficiency_count(
            api, scenario["admin_headers"], scenario["contractor_id"]
        )
        == 0
    )


def _short_dated_certificate(build, api):
    """A GL certificate filed 14 complete days before it expires."""
    build.set_clock(INITIAL_CLOCK)
    contractor = build.create_contractor()
    certificate = validate_success(
        api.create_certificate(
            contractor["id"],
            certificate_payload(
                "GL",
                each_occurrence_limit=1000000,
                aggregate_limit=2000000,
                effective_date="2026-07-01T00:00:00Z",
                expiration_date="2026-08-15T00:00:00Z",
            ),
            build.contractor_headers(contractor["id"]),
        ),
        201,
    )
    return contractor, certificate


def test_certificate_filed_inside_thirty_days_materializes_expiring_soon(build, api):
    """14 complete days remaining reads EXPIRING_SOON while still PENDING.

    PRD Section 3.5: "Otherwise the number of complete days remaining is taken
    as the whole number of 86,400-second days between the clock and the
    `expiration_date`, discarding any partial day; thirty or fewer complete days
    remaining gives `EXPIRING_SOON`, and the boundary is inclusive so exactly
    thirty days out already reads `EXPIRING_SOON`."

    Design: Difficulty/non_linear_state_machine/certificate_lapses_in_lifecycle_dimension_while_verification_dimension_still_pending
    """
    contractor, certificate = _short_dated_certificate(build, api)

    assert_certificate_state(
        certificate,
        verification_status="PENDING",
        lifecycle_status="EXPIRING_SOON",
    )
    assert_contractor_posture(
        build.read_contractor(contractor["id"]), verified_coverage_types=[]
    )


def test_verification_succeeds_on_a_certificate_that_has_already_lapsed(build, api):
    """The two dimensions move independently: VERIFIED and LAPSED together.

    PRD Section 3.5: "A still-unverified certificate can perfectly well reach
    `LAPSED`, and a verified certificate remains `VERIFIED` after it lapses —
    the two dimensions simply describe different facts."

    Design: Difficulty/non_linear_state_machine/certificate_lapses_in_lifecycle_dimension_while_verification_dimension_still_pending
    """
    contractor, certificate = _short_dated_certificate(build, api)

    # A bare clock advance past the expiration date, with no other write.
    build.set_clock("2026-08-20T00:00:00Z")

    verified = validate_success(
        api.verify_certificate(
            certificate["id"],
            certificate_decision_payload("VERIFY"),
            make_analyst_headers(ANALYST_INSURANCE),
        ),
        200,
    )
    assert_certificate_state(
        verified, verification_status="VERIFIED", lifecycle_status="LAPSED"
    )
    assert verified["verified_by_user_id"] == ANALYST_INSURANCE, (
        f"expected verified_by_user_id {ANALYST_INSURANCE!r}, "
        f"got {verified['verified_by_user_id']!r}"
    )

    # A lapsed certificate drops its coverage type out of the array.
    assert_contractor_posture(
        build.read_contractor(contractor["id"]), verified_coverage_types=[]
    )
