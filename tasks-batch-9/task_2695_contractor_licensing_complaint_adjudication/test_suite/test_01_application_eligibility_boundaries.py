"""Eligibility boundaries and the decision outcomes of the application pipeline.

The submission battery is where a licence is won or lost: credited experience is
weighed against the classification's statutory minimum, examination currency is
re-proved, and the analyst's decision either opens a cure round, denies, or fires
the four-hop minting cascade.
"""

from test_helpers import (
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    ApplicationDecision,
    ApplicationStatus,
    CompliancePosture,
    EducationCredential,
    ExamType,
    LicenseStatus,
    RelationshipType,
    assert_exam_result,
    assert_fields,
    assert_license,
    assert_qualification_count,
    assert_qualifier_assignment,
    constants as K,
    factories as F,
    fixtures as FX,
    get_success_data,
    validate_error,
    validate_success,
)


def _c10_world(api):
    """Clock at the design date plus the tier-3 electrical classification."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    return FX.create_c10_classification(api)


def _draft_application(
    api,
    classification,
    *,
    legal_name,
    contact_email,
    full_name,
    verified_experience_months,
    education_credential=EducationCredential.FOUR_YEAR_DEGREE,
    declared_net_worth_cents=250000,
    trade_score=78,
    law_score=82,
    record_trade_exam=True,
):
    """A licensee, an examined qualifier and one DRAFT application over them."""
    licensee = FX.register_licensee(
        api, legal_name=legal_name, contact_email=contact_email
    )
    individual = FX.register_qualifying_individual(
        api,
        full_name=full_name,
        verified_experience_months=verified_experience_months,
    )
    FX.record_exam(
        api,
        individual["id"],
        ExamType.LAW_AND_BUSINESS,
        score=law_score,
        taken_on="2025-03-01",
    )
    if record_trade_exam:
        FX.record_exam(
            api,
            individual["id"],
            ExamType.TRADE,
            trade_code=classification["code"],
            score=trade_score,
            taken_on="2025-03-01",
        )
    application = FX.open_application(
        api,
        licensee["id"],
        classification["id"],
        individual["id"],
        declared_net_worth_cents=declared_net_worth_cents,
        education_credential=education_credential,
    )
    return licensee, individual, application


def test_01_credited_experience_at_exactly_the_minimum_clears_submission(api):
    """Twenty-four verified months plus a clipped four-year degree reaches 48.

    PRD: "Worth noting the shape of this: a classification demanding forty-eight
    months caps educational substitution at twenty-four, so a four-year degree
    worth thirty-six months is clipped to twenty-four, and an applicant with
    twenty-four verified months exactly reaches forty-eight and passes while one
    with twenty-three reaches forty-seven and does not."

    Design: Difficulty/boundary_precision_check/credited_experience_exactly_at_minimum_versus_one_month_short
    """
    classification = _c10_world(api)
    licensee, _individual, application = _draft_application(
        api,
        classification,
        legal_name="Alpha Electric LLC",
        contact_email="a@alpha.test",
        full_name="Quinn FortyEight",
        verified_experience_months=24,
    )

    submitted = validate_success(
        api.submit_application(
            application["id"], FX.make_licensee_headers(licensee["id"])
        )
    )

    assert_fields(
        submitted,
        {
            "credited_experience_months": 48,
            "status": ApplicationStatus.SUBMITTED,
        },
    )
    assert submitted["submitted_at"] is not None


def test_02_credited_experience_one_month_short_is_refused(api):
    """Twenty-three verified months reaches only forty-seven and is refused.

    PRD: "The applicant is eligible when credited experience is greater than or
    equal to `min_experience_months`, so exact equality passes; falling short
    draws `ERR_EXPERIENCE_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/credited_experience_exactly_at_minimum_versus_one_month_short
    """
    classification = _c10_world(api)
    licensee, _individual, application = _draft_application(
        api,
        classification,
        legal_name="Beta Electric LLC",
        contact_email="b@beta.test",
        full_name="Quinn FortySeven",
        verified_experience_months=23,
        law_score=84,
        trade_score=79,
    )
    licensee_headers = FX.make_licensee_headers(licensee["id"])

    validate_error(
        api.submit_application(application["id"], licensee_headers),
        ApiErrorId.EXPERIENCE_INSUFFICIENT,
    )

    stored = validate_success(api.get_application(application["id"], licensee_headers))
    assert_fields(
        stored, {"status": ApplicationStatus.DRAFT, "submitted_at": None}
    )


def test_03_exam_score_at_the_pass_mark_clears_submission(api):
    """A trade sitting scored exactly seventy is stamped passed and lets the file move.

    PRD: "`passed` is true when the `score` is at least 70; a score of exactly 70
    passes. `expires_on` is the `taken_on` date advanced by forty-eight months —
    four years — and a passed examination stops satisfying any eligibility
    requirement once the clock date is strictly past that `expires_on`."

    Design: Difficulty/boundary_precision_check/exam_score_exactly_at_pass_mark_versus_one_point_below
    """
    classification = _c10_world(api)
    licensee, individual, application = _draft_application(
        api,
        classification,
        legal_name="Seventy Electric LLC",
        contact_email="s70@x.test",
        full_name="Sev Enty",
        verified_experience_months=60,
        education_credential=EducationCredential.NONE,
        declared_net_worth_cents=300000,
        record_trade_exam=False,
    )

    sitting = FX.record_exam(
        api,
        individual["id"],
        ExamType.TRADE,
        trade_code=classification["code"],
        score=K.EXAM_PASS_SCORE,
        taken_on="2025-03-01",
    )

    assert_exam_result(sitting, passed=True, expires_on="2029-03-01", score=70)
    submitted = validate_success(
        api.submit_application(
            application["id"], FX.make_licensee_headers(licensee["id"])
        )
    )
    assert_fields(submitted, {"status": ApplicationStatus.SUBMITTED})


def test_04_exam_score_one_point_below_the_pass_mark_blocks_submission(api):
    """Sixty-nine is stamped failed even though its validity dating is identical.

    PRD: "A missing sitting, a failed sitting, a trade sitting for the wrong code,
    or a sitting whose validity has run out all draw
    `ERR_EXAM_REQUIREMENT_UNMET`."

    Design: Difficulty/boundary_precision_check/exam_score_exactly_at_pass_mark_versus_one_point_below
    """
    classification = _c10_world(api)
    licensee, individual, application = _draft_application(
        api,
        classification,
        legal_name="Sixtynine Electric LLC",
        contact_email="s69@x.test",
        full_name="Six Tynine",
        verified_experience_months=60,
        education_credential=EducationCredential.NONE,
        declared_net_worth_cents=300000,
        record_trade_exam=False,
    )
    licensee_headers = FX.make_licensee_headers(licensee["id"])

    sitting = FX.record_exam(
        api,
        individual["id"],
        ExamType.TRADE,
        trade_code=classification["code"],
        score=K.EXAM_PASS_SCORE - 1,
        taken_on="2025-03-01",
    )

    assert_exam_result(sitting, passed=False, expires_on="2029-03-01", score=69)
    validate_error(
        api.submit_application(application["id"], licensee_headers),
        ApiErrorId.EXAM_REQUIREMENT_UNMET,
    )
    stored = validate_success(api.get_application(application["id"], licensee_headers))
    assert_fields(stored, {"status": ApplicationStatus.DRAFT})


def test_05_first_two_deficiency_findings_each_open_a_cure_round(api):
    """Two findings count up to two and each one is curable back to SUBMITTED.

    PRD: "An outcome of `DEFICIENT` opens a cure round: the application moves
    `SUBMITTED → DEFICIENT`, `deficiency_round_count` rises by one, and the
    supplied `deficiency_reason` is stored as the last deficiency narrative."

    Design: Difficulty/non_linear_state_machine/application_deficiency_cure_loop_denies_on_third_finding
    """
    classification = _c10_world(api)
    licensee, _individual, application = _draft_application(
        api,
        classification,
        legal_name="Volt Works LLC",
        contact_email="ops@voltworks.test",
        full_name="Dana Volt",
        verified_experience_months=24,
    )
    licensee_headers = FX.make_licensee_headers(licensee["id"])
    validate_success(api.submit_application(application["id"], licensee_headers))

    first = validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(
                ApplicationDecision.DEFICIENT,
                deficiency_reason="Financial statement unsigned",
            ),
            LICENSING_ANALYST_HEADERS,
        )
    )
    assert_fields(
        first,
        {
            "status": ApplicationStatus.DEFICIENT,
            "deficiency_round_count": 1,
            "deficiency_reason": "Financial statement unsigned",
        },
    )

    cured = validate_success(
        api.cure_application(
            application["id"],
            {"declared_net_worth_cents": 250000},
            licensee_headers,
        )
    )
    assert_fields(cured, {"status": ApplicationStatus.SUBMITTED})

    second = validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(
                ApplicationDecision.DEFICIENT,
                deficiency_reason="Experience affidavit missing notary",
            ),
            LICENSING_ANALYST_HEADERS,
        )
    )
    assert_fields(
        second,
        {
            "status": ApplicationStatus.DEFICIENT,
            "deficiency_round_count": 2,
        },
    )


def test_06_third_deficiency_finding_denies_the_application_instead(api):
    """The same request body that opened round two denies the file at round three.

    PRD: "When a deficiency outcome arrives on an application whose
    `deficiency_round_count` already stands at 2, the very same request body
    instead drives the application `SUBMITTED → DENIED`: `deficiency_round_count`
    is set to 3, the supplied `deficiency_reason` is still stored, and
    `denial_reason` is stamped automatically as `EXCESSIVE_DEFICIENCY_ROUNDS`."

    Design: Difficulty/non_linear_state_machine/application_deficiency_cure_loop_denies_on_third_finding
    """
    classification = _c10_world(api)
    licensee, individual, application = _draft_application(
        api,
        classification,
        legal_name="Volt Works LLC",
        contact_email="ops@voltworks.test",
        full_name="Dana Volt",
        verified_experience_months=24,
    )
    licensee_headers = FX.make_licensee_headers(licensee["id"])
    validate_success(api.submit_application(application["id"], licensee_headers))
    for reason in ("Financial statement unsigned", "Experience affidavit missing notary"):
        validate_success(
            api.decide_application(
                application["id"],
                F.decision_payload(
                    ApplicationDecision.DEFICIENT, deficiency_reason=reason
                ),
                LICENSING_ANALYST_HEADERS,
            )
        )
        validate_success(
            api.cure_application(
                application["id"],
                {"declared_net_worth_cents": 250000},
                licensee_headers,
            )
        )

    denied = validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(
                ApplicationDecision.DEFICIENT,
                deficiency_reason="Bond commitment letter still absent",
            ),
            LICENSING_ANALYST_HEADERS,
        )
    )

    assert_fields(
        denied,
        {
            "status": ApplicationStatus.DENIED,
            "deficiency_round_count": 3,
            "denial_reason": K.AUTO_DENIAL_REASON,
            "deficiency_reason": "Bond commitment letter still absent",
        },
    )
    minted = get_success_data(
        api.list_licenses(
            LICENSING_ANALYST_HEADERS, {"application_id": application["id"]}
        )
    )
    assert minted == [], "a denied application must not mint a licence"
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(individual["id"], LICENSING_ANALYST_HEADERS)
        ),
        0,
    )


def test_07_approval_mints_a_licence_and_designates_its_qualifier(api):
    """Approval creates the licence and, because it exists, its designation.

    PRD: "**Second**, *because* a licence now exists with no qualifier of record, a
    designation is created for it: it names the new licence and the application's
    `qualifying_individual_id`, takes a `relationship_type` of
    `RESPONSIBLE_MANAGING_EMPLOYEE`, an `ownership_pct` of 0, an `effective_from`
    equal to the licence's `issued_on`, a null `effective_to` (open-ended), and
    `ACTIVE` status — and the licence's `qualifying_individual_id` is pointed at
    that person."

    Design: Difficulty/transitive_cascade/application_approval_cascade_mints_license_designation_and_qualifier_count
    """
    classification = _c10_world(api)
    licensee, individual, application = _draft_application(
        api,
        classification,
        legal_name="Volt Works LLC",
        contact_email="ops@voltworks.test",
        full_name="Dana Volt",
        verified_experience_months=24,
    )
    licensee_headers = FX.make_licensee_headers(licensee["id"])
    submitted = validate_success(
        api.submit_application(application["id"], licensee_headers)
    )
    assert_fields(submitted, {"credited_experience_months": 48})

    approved = validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(ApplicationDecision.APPROVED),
            LICENSING_ANALYST_HEADERS,
        )
    )

    assert_fields(approved, {"status": ApplicationStatus.APPROVED})
    minted = get_success_data(
        api.list_licenses(
            LICENSING_ANALYST_HEADERS, {"application_id": application["id"]}
        )
    )
    assert len(minted) == 1, "exactly one licence is minted by the approval"
    license_row = minted[0]
    assert_license(
        license_row,
        status=LicenseStatus.ACTIVE,
        issued_on="2026-08-01",
        expires_on="2028-08-01",
        application_id=application["id"],
        qualifying_individual_id=individual["id"],
        ce_hours_completed=0,
    )
    assignment = FX.find_assignment_for_license(api, license_row["id"])
    assert assignment is not None, "the licence must carry a qualifier of record"
    assert_qualifier_assignment(
        assignment,
        status="ACTIVE",
        relationship_type=RelationshipType.RESPONSIBLE_MANAGING_EMPLOYEE,
        effective_from="2026-08-01",
        effective_to=None,
        ownership_pct=0,
        qualifying_individual_id=individual["id"],
    )


def test_08_minted_licence_raises_the_qualifier_count_and_is_born_non_compliant(api):
    """The designation lifts the count to one and the bondless licence is NON_COMPLIANT.

    PRD: "A brand-new licence is thus simultaneously `ACTIVE` and
    `NON_COMPLIANT`, and it will stay that way until a bond is verified against
    it."

    Design: Difficulty/transitive_cascade/application_approval_cascade_mints_license_designation_and_qualifier_count
    """
    classification = _c10_world(api)
    licensee, individual, application = _draft_application(
        api,
        classification,
        legal_name="Volt Works LLC",
        contact_email="ops@voltworks.test",
        full_name="Dana Volt",
        verified_experience_months=24,
    )
    licensee_headers = FX.make_licensee_headers(licensee["id"])
    validate_success(api.submit_application(application["id"], licensee_headers))

    validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(ApplicationDecision.APPROVED),
            LICENSING_ANALYST_HEADERS,
        )
    )

    license_row = FX.find_license_for_application(api, application["id"])
    assert_fields(
        license_row,
        {
            "status": LicenseStatus.ACTIVE,
            "compliance_posture": CompliancePosture.NON_COMPLIANT,
        },
    )
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(individual["id"], LICENSING_ANALYST_HEADERS)
        ),
        1,
    )
