"""Arithmetic the specification pins to the cent, the tenth of an hour and the
hundredth of a point: the equivalency score's half-up rounding, the per-category
military conversion factors rounded record by record, and the decay floor under the
disciplinary risk index."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CATEGORY_FIELD_EXPERIENCE,
    CATEGORY_MOS_TRAINING,
    DISCIPLINE_CLEAR,
    MILITARY_VETERAN,
    SCOPE_EQUIVALENT,
    SEVERITY_ADVISORY,
    ApiErrorId,
    assert_application_fields,
    assert_evaluation_fields,
    assert_hours_conserved,
    credit_award_payload,
    disciplinary_record_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

OCCUPATIONAL_THERAPIST = {
    "profession_code": "OT",
    "title": "Occupational Therapist",
    "required_scope_elements": ["EVAL", "TREAT"],
    "critical_scope_elements": [],
    "required_practice_hours": 1000,
    "requirement_hours_total": 60.0,
    "exam_waiver_min_score": 99.00,
    "jurisprudence_exam_required": False,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 90,
    "base_fee_cents": 18000,
    "endorsement_fee_cents": 5000,
    "exam_fee_cents": 4000,
    "jurisprudence_fee_cents": 0,
    "permit_fee_cents": 3000,
    "expedite_surcharge_pct": 0.10,
}

PHYSICAL_THERAPIST = {
    **OCCUPATIONAL_THERAPIST,
    "profession_code": "PT",
    "title": "Physical Therapist",
    "requirement_hours_total": 400.0,
}


@pytest.fixture
def therapist_evaluation_ready_to_finalize(setup):
    """An occupational therapist endorsement whose credential matches the full scope but
    documents 865 of the 1000 required practice hours, with both review dimensions
    resolved and only finalisation outstanding."""
    profession = setup.profession(**OCCUPATIONAL_THERAPIST)
    applicant = setup.applicant(full_name="Uma Sethi")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-13001",
        scope_elements=["EVAL", "TREAT"],
        practice_hours=865,
        issued_at="2021-01-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    setup.scope_review(evaluation["id"], SCOPE_EQUIVALENT)
    evaluator = setup.evaluator(full_name="Vera Klein", profession_code="OT")
    setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    setup.discipline_finding(evaluation["id"], evaluator["id"], DISCIPLINE_CLEAR)
    return {"app_id": application["id"], "eval_id": evaluation["id"]}


@pytest.fixture
def veteran_with_three_service_records(setup):
    """A veteran's submitted physical-therapy file with three 133-hour service records —
    two of MOS training and one of field experience — the first two already credited."""
    profession = setup.profession(**PHYSICAL_THERAPIST)
    applicant = setup.applicant(full_name="Wes Adeyemi", military_status=MILITARY_VETERAN)
    credential = setup.credential(
        applicant["id"],
        license_number="OK-13002",
        scope_elements=["EVAL", "TREAT"],
        practice_hours=400,
        issued_at="2021-01-01T00:00:00Z",
    )
    first = setup.training_record(
        applicant["id"], documented_hours=133, source_document="JST-A-133"
    )
    second = setup.training_record(
        applicant["id"], documented_hours=133, source_document="JST-B-133"
    )
    third = setup.training_record(
        applicant["id"],
        category=CATEGORY_FIELD_EXPERIENCE,
        documented_hours=133,
        source_document="JST-C-133",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    return {
        "app_id": application["id"],
        "aw_a": setup.credit_award(application["id"], first["id"])["id"],
        "aw_b": setup.credit_award(application["id"], second["id"])["id"],
        "tr_c": third["id"],
    }


@pytest.fixture
def veteran_with_an_unverified_transcript(setup):
    """A veteran's submitted physical-therapy file whose only service record is still
    unverified."""
    profession = setup.profession(**PHYSICAL_THERAPIST)
    applicant = setup.applicant(full_name="Xan Petrov", military_status=MILITARY_VETERAN)
    credential = setup.credential(
        applicant["id"],
        license_number="OK-13003",
        scope_elements=["EVAL", "TREAT"],
        practice_hours=400,
        issued_at="2021-01-01T00:00:00Z",
    )
    record = setup.training_record(
        applicant["id"],
        category=CATEGORY_MOS_TRAINING,
        documented_hours=200,
        source_document="JST-UNVERIFIED",
        verified=False,
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    return {"app_id": application["id"], "tr_id": record["id"]}


class TestEquivalencyScorePrecision:
    def test_a_score_landing_on_a_half_cent_of_a_point_rounds_upward(
        self, api, therapist_evaluation_ready_to_finalize
    ):
        """PRD §3.5: "The raw figure is the scope ratio weighted at 0.60, plus the hours
        ratio weighted at 0.25, plus the standing term weighted at 0.15."  PRD §3.5:
        "Finally, multiply the raw figure by 100, subtract the penalty, round the result
        half up to two decimal places, and clamp it into the closed range from 0.00
        through 100.00 — the clamp is applied after the penalty, so a heavily penalised
        score floors at 0.00 rather than going negative."  PRD §2.5: "The
        substantial-equivalency score and both disciplinary risk indexes are carried to
        exactly two decimal places, rounded half up, and are constrained to the closed
        range from 0.00 through 100.00."

        Design: Corner/calculations/equivalency_score_precision_is_two_decimals_round_half_up
        """
        env = therapist_evaluation_ready_to_finalize
        evaluation = validate_success(
            api.finalize_evaluation(env["eval_id"], {}, ANALYST_HEADERS), 200
        )

        assert_evaluation_fields(
            evaluation,
            equivalency_score=96.63,
            matched_scope_elements=["EVAL", "TREAT"],
            missing_scope_elements=[],
        )

    def test_a_score_below_the_published_threshold_wins_no_seat_fee_back(
        self, api, therapist_evaluation_ready_to_finalize, setup
    ):
        """PRD §3.5: "`exam_waiver_granted` is true when the computed `equivalency_score`
        is at or above the profession's `exam_waiver_min_score` — the threshold itself
        grants the waiver — **or** when an unexpired reciprocal agreement exists for this
        profession whose `partner_state` equals the applicant's `state_code` and whose
        `exam_waiver_allowed` is true, in which case the compact grants the waiver
        irrespective of the score."  PRD §3.5: "When and only when the waiver is granted,
        the seat fee the applicant was assessed at submission must come back."

        Design: Corner/calculations/equivalency_score_precision_is_two_decimals_round_half_up
        """
        env = therapist_evaluation_ready_to_finalize
        evaluation = validate_success(
            api.finalize_evaluation(env["eval_id"], {}, ANALYST_HEADERS), 200
        )

        assert_evaluation_fields(evaluation, exam_waiver_granted=False)
        assert_application_fields(
            setup.read_application(env["app_id"]), fee_balance_cents=27000
        )
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2


class TestMilitaryCreditHourConversion:
    def test_each_category_converts_at_its_own_factor_and_rounds_before_summing(
        self, api, veteran_with_three_service_records, setup
    ):
        """PRD §3.7: "Each award's `awarded_hours` is the training record's
        `documented_hours` multiplied by the factor for its `category` — 0.75 for
        `MOS_TRAINING`, 0.40 for `FIELD_EXPERIENCE`, and 0.90 for
        `JOINT_SERVICE_TRANSCRIPT` — with the product rounded half up to one decimal
        place, and that already-rounded value is what the award stores."  PRD §3.7: "The
        application's `requirement_hours_satisfied` is then recomputed by adding together
        the already-rounded `awarded_hours` of every credit award of this application
        whose `status` is `AWARDED`, taken in `created_at` ascending order, rounding that
        sum half up to one decimal place, and capping the result at the profession's
        `requirement_hours_total` so credit can never overshoot the requirement."  PRD
        §3.7: "Summing the raw unrounded products and rounding once at the end is a
        different answer and is not permitted."

        Design: Corner/calculations/military_credit_hours_conversion_factor_differs_by_category
        """
        env = veteran_with_three_service_records
        third_award = validate_success(
            api.create_credit_award(
                credit_award_payload(env["app_id"], env["tr_c"]), ANALYST_HEADERS
            ),
            201,
        )

        assert setup.read_credit_award(env["aw_a"])["awarded_hours"] == 99.8
        assert setup.read_credit_award(env["aw_b"])["awarded_hours"] == 99.8
        assert third_award["awarded_hours"] == 53.2

        application = setup.read_application(env["app_id"])
        assert_application_fields(
            application,
            requirement_hours_satisfied=252.8,
            requirement_hours_remaining=147.2,
        )
        assert_hours_conserved(application, 400.0)

    def test_an_unverified_transcript_never_reaches_the_hours_arithmetic(
        self, api, veteran_with_an_unverified_transcript, setup
    ):
        """PRD §3.7: "Because the unverified check bites at award time, an unverified
        transcript can never enter the hours arithmetic at all."  PRD §2.8:
        "Training-record verification — the training record's `verified` flag is true.
        `ERR_TRAINING_RECORD_UNVERIFIED`, 422. Applies to awarding credit."

        Design: Corner/calculations/credit_award_excludes_unverified_training_record
        """
        env = veteran_with_an_unverified_transcript
        response = api.create_credit_award(
            credit_award_payload(env["app_id"], env["tr_id"]), ANALYST_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_TRAINING_RECORD_UNVERIFIED.value, 422)

        _rows, meta = validate_paginated(
            api.list_credit_awards(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 0
        assert_application_fields(
            setup.read_application(env["app_id"]),
            requirement_hours_satisfied=0.0,
            requirement_hours_remaining=400.0,
        )


class TestDisciplinaryRiskDecay:
    def test_a_sixteen_year_old_advisory_decays_only_to_the_floor(self, api, setup):
        """PRD §3.3: "For each row, measure its age as the number of whole 365-day blocks
        that have elapsed from the variant's timestamp to the logical clock, discarding
        any partial block."  PRD §3.3: "Derive a decay factor by subtracting, from 1.0,
        the product of 0.20 and that whole-year age, but never let the factor fall below
        a floor of 0.20 no matter how old the action is."  PRD §3.3: "Multiply the row's
        severity point value — 5 for `ADVISORY`, 15 for `PROBATION`, 30 for `SUSPENSION`,
        60 for `REVOCATION` — by that factor, and round the product half up to two
        decimal places to obtain the row's contribution."  PRD §3.3: "Good standing is a
        conjunction of two independent conditions, and both must hold for
        `good_standing_flag` to be true: the applicant must have no unresolved
        disciplinary record whose `severity` is `SUSPENSION` or `REVOCATION`, and
        `disciplinary_risk_index_reported` must be strictly below the good-standing
        ceiling of 25.00."

        Design: Corner/calculations/risk_index_decay_floor_clamps_at_twenty_percent
        """
        applicant = setup.applicant(full_name="Yara Bello")

        record = validate_success(
            api.create_disciplinary_record(
                disciplinary_record_payload(
                    applicant["id"],
                    severity=SEVERITY_ADVISORY,
                    action_effective_at="2010-01-01T00:00:00Z",
                    reported_at="2010-01-01T00:00:00Z",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert record["resolved"] is False

        refreshed = setup.read_applicant(applicant["id"])
        assert refreshed["disciplinary_risk_index_reported"] == 1.00
        assert refreshed["disciplinary_risk_index_effective"] == 1.00
        assert refreshed["good_standing_flag"] is True
