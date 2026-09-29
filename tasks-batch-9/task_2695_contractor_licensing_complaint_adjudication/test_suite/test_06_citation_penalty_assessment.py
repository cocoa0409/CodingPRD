"""One penalty formula, two variants, and the statutory ceiling that caps it.

The same citation is priced twice: once at issuance, where no order of correction
can yet have been verified, and once again when a hearing affirms it and the
mitigation credit becomes available. A separate sting citation drives the factor
product past the ceiling so the terminal clamp can be seen on its own.
"""

from test_helpers import (
    LICENSING_ANALYST_HEADERS,
    CitationStatus,
    ComplaintStatus,
    HearingDecision,
    HearingStatus,
    InvestigationOrigin,
    PenaltyVariant,
    Severity,
    SubjectType,
    assert_citation,
    assert_fields,
    assert_penalty_within_statutory_maximum,
    constants as K,
    fixtures as FX,
    validate_success,
)


def _serious_tier_three_citation(api):
    """A SERIOUS citation against a licensed tier-three electrician, no priors."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = FX.mint_active_license(api)
    consumer = FX.register_consumer(
        api, full_name="Pat Ratepayer", contact_email="pat@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    complaint, _investigation, citation = FX.substantiated_citation(
        api,
        ctx,
        consumer["id"],
        severity=Severity.SERIOUS,
        violation_code="B-7110",
        correction_due_date="2026-09-30",
    )
    return ctx, complaint, citation


def test_01_the_issuance_variant_prices_the_citation_without_any_credit(api):
    """At issuance the mitigation multiplier is always one, giving 375,000 cents.

    PRD: "The `INITIAL_ASSESSMENT` variant runs at issuance: it evaluates
    `prior_final_citation_count` as of the issuance moment, and its mitigation
    multiplier is always one, because no order of correction can possibly have been
    verified before the citation that orders it exists."

    Design: Difficulty/dual_variant_calc/citation_penalty_initial_assessment_vs_post_hearing_mitigation
    """
    _ctx, _complaint, citation = _serious_tier_three_citation(api)

    assert_citation(
        citation,
        civil_penalty_cents=375000,
        penalty_variant=PenaltyVariant.INITIAL_ASSESSMENT,
        prior_final_citation_count=0,
        penalty_paid_cents=0,
        severity=Severity.SERIOUS,
        subject_type=SubjectType.LICENSED,
        status=CitationStatus.ISSUED,
    )


def test_02_affirming_with_a_verified_correction_reprices_the_same_row(api):
    """The post-hearing variant earns the quarter credit and drops to 281,250.

    PRD: "it earns the twenty-five percent mitigation credit when the deciding
    request supplies a `correction_verified_on` date and that date is on or before
    the citation's `correction_due_date`."

    Design: Difficulty/dual_variant_calc/citation_penalty_initial_assessment_vs_post_hearing_mitigation
    """
    ctx, _complaint, citation = _serious_tier_three_citation(api)
    hearing = FX.appealed_citation_with_hearing(
        api,
        citation["id"],
        ctx.licensee_id,
        "2026-09-10T14:00:00Z",
        "2026-09-10T16:00:00Z",
    )
    FX.set_clock(api, "2026-09-10T14:00:00Z")

    decided = FX.decide_hearing(
        api,
        hearing["id"],
        HearingDecision.AFFIRM,
        findings_summary="Violation proven; correction verified before the ordered date",
        correction_verified_on="2026-09-08",
    )

    assert_fields(decided, {"status": HearingStatus.DECIDED})
    repriced = validate_success(
        api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS)
    )
    assert_citation(
        repriced,
        civil_penalty_cents=281250,
        penalty_variant=PenaltyVariant.POST_HEARING_RECALCULATION,
        correction_completed_on="2026-09-08",
        prior_final_citation_count=0,
        status=CitationStatus.AFFIRMED,
    )
    assert citation["civil_penalty_cents"] - repriced["civil_penalty_cents"] == 93750, (
        "the credit must move the same row by exactly a quarter of the assessment"
    )


def test_03_the_recalculated_figure_is_what_becomes_collectable(api):
    """Exposure and the complaint's closure both follow the affirmed figure.

    PRD: "the licensee's `unpaid_penalty_cents` rises by the recalculated
    `civil_penalty_cents` less `penalty_paid_cents`, and the sanction ladder is
    graded."

    Design: Difficulty/dual_variant_calc/citation_penalty_initial_assessment_vs_post_hearing_mitigation
    """
    ctx, complaint, citation = _serious_tier_three_citation(api)
    hearing = FX.appealed_citation_with_hearing(
        api,
        citation["id"],
        ctx.licensee_id,
        "2026-09-10T14:00:00Z",
        "2026-09-10T16:00:00Z",
    )
    FX.set_clock(api, "2026-09-10T14:00:00Z")

    FX.decide_hearing(
        api,
        hearing["id"],
        HearingDecision.AFFIRM,
        findings_summary="Violation proven; correction verified before the ordered date",
        correction_verified_on="2026-09-08",
    )

    assert_fields(
        validate_success(
            api.get_licensee(ctx.licensee_id, LICENSING_ANALYST_HEADERS)
        ),
        {"unpaid_penalty_cents": 281250},
    )
    assert_fields(
        validate_success(
            api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": ComplaintStatus.CLOSED_SANCTIONED},
    )


def _egregious_sting_citation(api):
    """A board sting against an unlicensed operator in a tier-three trade."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    classification = FX.create_c10_classification(api)
    case = FX.open_investigation(
        api,
        origin=InvestigationOrigin.STING,
        subject_business_name="Bolt Sparks Handyman",
    )
    FX.substantiate(
        api,
        case["id"],
        severity=Severity.EGREGIOUS,
        evidence_summary="Undercover buy: live 200A service installed without any licence",
    )
    citation = FX.issue_citation(
        api,
        case["id"],
        classification["id"],
        violation_code="B-7028",
        correction_due_date="2026-09-15",
    )
    return classification, case, citation


def test_04_an_unlicensed_egregious_citation_is_clamped_to_the_statutory_ceiling(api):
    """Four factors compose to 2,250,000 and the ceiling cuts it to 1,500,000.

    PRD: "An `EGREGIOUS`, `UNLICENSED` citation in a tier-3 trade with no priors
    computes 750,000 times two times one and a half, or 2,250,000, and is clamped
    down to 1,500,000."

    Design: Difficulty/combinatorial_formula/unlicensed_sting_egregious_penalty_clamped_at_statutory_maximum
    """
    _classification, _case, citation = _egregious_sting_citation(api)

    assert_citation(
        citation,
        civil_penalty_cents=K.STATUTORY_MAX_PENALTY_CENTS,
        severity=Severity.EGREGIOUS,
        subject_type=SubjectType.UNLICENSED,
        license_id=None,
        prior_final_citation_count=0,
    )
    assert_penalty_within_statutory_maximum(citation, K.STATUTORY_MAX_PENALTY_CENTS)


def test_05_the_clamped_sting_citation_is_still_stamped_as_an_initial_assessment(api):
    """The clamp is terminal, not a different variant, and issuance stamping stands.

    PRD: "`subject_type` is `LICENSED` when a `license_id` was copied and
    `UNLICENSED` when none was: an unlicensed operator both doubles the penalty base
    and adds sanction points."

    Design: Difficulty/combinatorial_formula/unlicensed_sting_egregious_penalty_clamped_at_statutory_maximum
    """
    _classification, _case, citation = _egregious_sting_citation(api)

    stored = validate_success(api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS))
    assert_citation(
        stored,
        status=CitationStatus.ISSUED,
        issued_on="2026-08-01",
        appeal_deadline="2026-08-16",
        penalty_variant=PenaltyVariant.INITIAL_ASSESSMENT,
        civil_penalty_cents=K.STATUTORY_MAX_PENALTY_CENTS,
        subject_type=SubjectType.UNLICENSED,
    )
