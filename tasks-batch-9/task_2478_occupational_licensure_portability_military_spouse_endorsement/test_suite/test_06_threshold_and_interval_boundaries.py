"""Two boundaries where one unit decides the outcome: a score sitting exactly on the
published waiver threshold versus a hundredth below it, and a permit starting exactly
when the incumbent expires versus one second earlier."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    ENTRY_EXAM_FEE_REVERSAL,
    PERMIT_ACTIVE,
    SCOPE_EQUIVALENT,
    ApiErrorId,
    assert_application_fields,
    assert_evaluation_fields,
    assert_instant_equals,
    assert_permit_fields,
    temporary_permit_payload,
    validate_error,
    validate_success,
)

RD_PROFESSION = {
    "profession_code": "RD",
    "title": "Registered Dietitian",
    "required_scope_elements": ["ASSESS", "TREAT", "PRESCRIBE", "SUPERVISE"],
    "critical_scope_elements": [],
    "required_practice_hours": 2000,
    "requirement_hours_total": 100.0,
    "exam_waiver_min_score": 70.00,
    "jurisprudence_exam_required": False,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 90,
    "base_fee_cents": 20000,
    "endorsement_fee_cents": 6000,
    "exam_fee_cents": 6000,
    "jurisprudence_fee_cents": 0,
    "permit_fee_cents": 5000,
    "expedite_surcharge_pct": 0.10,
}


@pytest.fixture
def one_hour_apart(setup):
    """Two dietitian files identical but for a single documented practice hour, both
    reviewed EQUIVALENT and CLEAR and waiting only for finalisation."""
    profession = setup.profession(**RD_PROFESSION)
    arms = {}
    for key, name, license_number, hours in (
        ("x", "Omar Vidal", "OK-99001", 800),
        ("y", "Pia Groen", "OK-99002", 799),
    ):
        applicant = setup.applicant(full_name=name, state_code="TX", residency_months=24)
        credential = setup.credential(
            applicant["id"],
            license_number=license_number,
            scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
            practice_hours=hours,
            issued_at="2022-02-01T00:00:00Z",
        )
        application = setup.application(applicant["id"], profession["id"], credential["id"])
        setup.submit(application["id"], applicant["id"])
        evaluation = setup.evaluation(application["id"], credential["id"])
        setup.scope_review(evaluation["id"], SCOPE_EQUIVALENT)
        arms[key] = {
            "ap_id": applicant["id"],
            "app_id": application["id"],
            "eval_id": evaluation["id"],
        }

    evaluator = setup.evaluator(full_name="Ines Falk", profession_code="RD")
    setup.review_assignment(
        evaluator["id"], arms["x"]["app_id"], "2026-08-02T00:00:00Z", "2026-08-09T00:00:00Z"
    )
    setup.review_assignment(
        evaluator["id"], arms["y"]["app_id"], "2026-08-11T00:00:00Z", "2026-08-14T00:00:00Z"
    )
    for key in ("x", "y"):
        setup.discipline_finding(arms[key]["eval_id"], evaluator["id"])
    return arms


@pytest.fixture
def permit_expiring_end_of_october(setup):
    """A settled endorsement file under review holding a permit whose window runs to
    exactly 2026-10-30T00:00:00Z, with the application version captured once."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Cyrus Bell", state_code="TX", residency_months=24)
    credential = setup.credential(
        applicant["id"], license_number="OK-70061", scope_elements=["ASSESS", "TREAT", "SUPERVISE"]
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.pay(application["id"], applicant["id"], 48000)
    setup.evaluation(application["id"], credential["id"])
    permit = setup.permit(application["id"], "2026-08-01T00:00:00Z")
    setup.pay(application["id"], applicant["id"], 6000)
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "permit": permit,
        "app_version": setup.application_version(application["id"]),
    }


class TestExamWaiverThreshold:
    def test_a_score_at_exactly_the_published_minimum_grants_the_waiver(
        self, one_hour_apart, setup
    ):
        """PRD §3.5: "`exam_waiver_granted` is true when the computed
        `equivalency_score` is at or above the profession's `exam_waiver_min_score` —
        the threshold itself grants the waiver — **or** when an unexpired reciprocal
        agreement exists for this profession whose `partner_state` equals the
        applicant's `state_code` and whose `exam_waiver_allowed` is true, in which
        case the compact grants the waiver irrespective of the score."

        Design: Difficulty/boundary_precision_check/exam_waiver_threshold_at_exactly_min_score_vs_one_hundredth_below
        """
        setup.finalize(one_hour_apart["x"]["eval_id"])
        setup.finalize(one_hour_apart["y"]["eval_id"])

        at_threshold = setup.read_evaluation(one_hour_apart["x"]["eval_id"])
        below = setup.read_evaluation(one_hour_apart["y"]["eval_id"])
        assert_evaluation_fields(at_threshold, equivalency_score=70.00, exam_waiver_granted=True)
        assert_evaluation_fields(below, equivalency_score=69.99, exam_waiver_granted=False)

    def test_one_documented_hour_moves_the_score_by_a_single_hundredth(
        self, one_hour_apart, setup
    ):
        """PRD §3.5: "The hours ratio is the credential's `practice_hours` divided by
        the profession's `required_practice_hours`, capped at 1.0 so that surplus
        hours never earn extra credit; under the `UNIVERSAL_RECOGNITION` variant only,
        if the applicant's `residency_months` is at least the profession's
        `universal_recognition_min_residency_months` then the hours ratio is lifted to
        exactly 1.0 outright, because residency substitutes for documented hours on
        that pathway."

        Design: Difficulty/boundary_precision_check/exam_waiver_threshold_at_exactly_min_score_vs_one_hundredth_below
        """
        setup.finalize(one_hour_apart["x"]["eval_id"])
        setup.finalize(one_hour_apart["y"]["eval_id"])

        at_threshold = setup.read_evaluation(one_hour_apart["x"]["eval_id"])
        below = setup.read_evaluation(one_hour_apart["y"]["eval_id"])
        assert round(at_threshold["equivalency_score"] - below["equivalency_score"], 2) == 0.01, (
            "800 of 2000 hours weighs 0.100000 and 799 weighs 0.099875 against the "
            "identical 0.45 scope term and 0.15 standing term"
        )

    def test_an_empty_critical_element_list_lets_a_missing_element_cost_nothing(
        self, one_hour_apart, setup
    ):
        """PRD §3.5: "Count how many members of `missing_scope_elements` also appear
        in the profession's `critical_scope_elements`; under the `STRICT_SCOPE` variant
        the penalty is 10.0 points for each such critical miss, and under the
        `UNIVERSAL_RECOGNITION` variant the penalty is zero and critical misses are
        ignored entirely."

        Design: Difficulty/boundary_precision_check/exam_waiver_threshold_at_exactly_min_score_vs_one_hundredth_below
        """
        setup.finalize(one_hour_apart["x"]["eval_id"])

        at_threshold = setup.read_evaluation(one_hour_apart["x"]["eval_id"])
        assert_evaluation_fields(
            at_threshold,
            scope_review_status=SCOPE_EQUIVALENT,
            missing_scope_elements=["PRESCRIBE"],
            equivalency_score=70.00,
        )

    def test_only_the_waived_arm_gets_its_seat_fee_back(self, one_hour_apart, setup):
        """PRD §3.5: "When and only when the waiver is granted, the seat fee the
        applicant was assessed at submission must come back."

        Design: Difficulty/boundary_precision_check/exam_waiver_threshold_at_exactly_min_score_vs_one_hundredth_below
        """
        setup.finalize(one_hour_apart["x"]["eval_id"])
        setup.finalize(one_hour_apart["y"]["eval_id"])

        waived_ledger = setup.read_ledger(one_hour_apart["x"]["app_id"])
        reversals = [row for row in waived_ledger if row["entry_type"] == ENTRY_EXAM_FEE_REVERSAL]
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == -6000
        assert_application_fields(
            setup.read_application(one_hour_apart["x"]["app_id"]), fee_balance_cents=26000
        )

        unwaived_ledger = setup.read_ledger(one_hour_apart["y"]["app_id"])
        assert ENTRY_EXAM_FEE_REVERSAL not in [row["entry_type"] for row in unwaived_ledger]
        assert_application_fields(
            setup.read_application(one_hour_apart["y"]["app_id"]), fee_balance_cents=32000
        )


class TestPermitHalfOpenBoundary:
    def test_touching_windows_are_admitted_while_a_single_second_of_overlap_collides(
        self, api, permit_expiring_end_of_october
    ):
        """PRD §3.8: "Because both comparisons are strict, two windows that merely
        touch — a new permit starting at precisely the instant an existing permit
        expires — do **not** collide, and no buffer of any kind is applied."

        Design: Difficulty/boundary_precision_check/permit_half_open_boundary_touching_start_admitted_one_second_earlier_collides
        """
        env = permit_expiring_end_of_october
        assert_permit_fields(env["permit"], expires_at="2026-10-30T00:00:00Z")

        one_second_early = api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-10-29T23:59:59Z", env["app_version"]),
            ANALYST_HEADERS,
        )
        validate_error(one_second_early, ApiErrorId.ERR_PERMIT_WINDOW_OVERLAP.value, 409)

        touching = api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-10-30T00:00:00Z", env["app_version"]),
            ANALYST_HEADERS,
        )
        admitted = validate_success(touching, 201)
        assert_instant_equals(
            admitted["effective_at"], "2026-10-30T00:00:00Z", "permit.effective_at"
        )

    def test_the_grace_allowance_caps_the_touching_permit_before_its_pathway_maximum(
        self, api, permit_expiring_end_of_october, setup
    ):
        """PRD §3.8: "The other candidate end is the application's
        `review_deadline_at` advanced by a grace allowance of 30 whole days. The
        permit's `expires_at` is whichever of those two candidates is earlier, so a
        permit can never outlive the review it bridges by more than the grace
        allowance, and can never exceed its pathway's statutory maximum either."

        Design: Difficulty/boundary_precision_check/permit_half_open_boundary_touching_start_admitted_one_second_earlier_collides
        """
        env = permit_expiring_end_of_october
        second = validate_success(
            api.create_temporary_permit(
                temporary_permit_payload(env["app_id"], "2026-10-30T00:00:00Z", env["app_version"]),
                ANALYST_HEADERS,
            ),
            201,
        )

        assert_permit_fields(
            second,
            effective_at="2026-10-30T00:00:00Z",
            expires_at="2026-11-29T00:00:00Z",
            permit_max_days=90,
            permit_fee_cents=6000,
        )
        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=6000)

    def test_a_refused_issuance_leaves_the_incumbent_permit_alone(
        self, api, permit_expiring_end_of_october, setup
    ):
        """PRD §3.8: "Issuance is refused when any temporary permit whose `status` is
        `ACTIVE` or `CONVERTED`, and whose own application shares both the same
        applicant and the same profession as this application, satisfies both of the
        following: the new permit's `effective_at` is strictly before that permit's
        `expires_at`, and that permit's `effective_at` is strictly before the new
        permit's `expires_at`."

        Design: Difficulty/boundary_precision_check/permit_half_open_boundary_touching_start_admitted_one_second_earlier_collides
        """
        env = permit_expiring_end_of_october
        api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-10-29T23:59:59Z", env["app_version"]),
            ANALYST_HEADERS,
        )

        permits = setup.read_permits(env["app_id"])
        assert len(permits) == 1, "the collision created nothing"
        assert_permit_fields(
            permits[0],
            status=PERMIT_ACTIVE,
            effective_at="2026-08-01T00:00:00Z",
            expires_at="2026-10-30T00:00:00Z",
        )
