"""Intake questionnaire severity scoring: provisional vs reviewed variants, and the
multi-branch formula with clamps."""
from test_helpers import (
    TEST_USERS,
    create_case_payload,
    create_consultant,
    get_case,
    make_consultant_headers,
    make_parent_headers,
    open_case,
    register_family,
    review_questionnaire_payload,
    submit_questionnaire,
    submit_questionnaire_payload,
    validate_success,
)

ADMIN = TEST_USERS["practice_admin_headers"]


def test_provisional_severity_from_answers_alone(api):
    """PRD §3.2: "The provisional severity score, on a scale from 0 to 100, is
    computed from the answers alone. Start with ten points per night waking, add four
    points per night feed, add one point for each full three minutes of bedtime
    resistance (the minutes divided by three, rounded down), and add a nap-deficit
    term: the shortfall of the day's `nap_total_minutes` against a 150-minute
    baseline, divided by fifteen and rounded up, never less than zero. If
    `medical_flags` is set, subtract twenty points; if `preterm_birth` is set,
    subtract a further ten. The result is then clamped into the range from 0 to 100
    inclusive."

    answers = {night_wakings 4, night_feeds 2, bedtime_resistance_minutes 45,
    nap_total_minutes 60}: 40 + 8 + floor(45/3)=15 + ceil(90/15)=6 = 69.

    Design: Difficulty/dual_variant_calc/questionnaire_severity_provisional_vs_reviewed
    """
    consultant = create_consultant(certification_no="CERT-100")
    family = register_family(full_name="Fam Alpha", email="alpha@x.com")
    case = open_case(family, consultant, child_birth_date="2026-05-01")
    res = api.submit_questionnaire(
        case["id"],
        submit_questionnaire_payload(
            {
                "night_wakings": 4,
                "night_feeds": 2,
                "bedtime_resistance_minutes": 45,
                "nap_total_minutes": 60,
                "medical_flags": False,
                "preterm_birth": False,
            }
        ),
        make_parent_headers(family["id"]),
    )
    questionnaire = validate_success(res, 201)
    assert questionnaire["provisional_severity_score"] == 69, (
        f"expected provisional 69, got {questionnaire['provisional_severity_score']}"
    )
    # Not yet reviewed: consultant-supplied review fields remain null.
    assert questionnaire["status"] == "SUBMITTED"
    assert questionnaire["adjustment_points"] is None
    assert questionnaire["reviewed_severity_score"] is None


def test_reviewed_severity_adds_adjustment_and_band_modifier(api):
    """PRD §3.2: "The `reviewed_severity_score` is the provisional score plus
    `adjustment_points` plus an age-band modifier taken from the case's age band at
    review time — `NEWBORN` contributes −5, `INFANT` contributes 0, `TODDLER`
    contributes +5, and `PRESCHOOL` contributes +10 — with the total clamped into the
    range from 0 to 100 inclusive. Because of the adjustment and the modifier,
    identical questionnaire answers yield a different score once reviewed."
    PRD §3.2: "The review marks the questionnaire `REVIEWED`, records the score, and
    moves the case from `ASSESSMENT` to `PLANNING`, again incrementing the case
    `version`."

    Same answers as the provisional probe (score 69); the child is 3 months old at
    the default clock (NEWBORN, modifier −5): 69 + 12 − 5 = 76.

    Design: Difficulty/dual_variant_calc/questionnaire_severity_provisional_vs_reviewed
    """
    consultant = create_consultant(certification_no="CERT-100")
    family = register_family(full_name="Fam Alpha", email="alpha@x.com")
    case = open_case(family, consultant, child_birth_date="2026-05-01")
    questionnaire = submit_questionnaire(
        case,
        family,
        {
            "night_wakings": 4,
            "night_feeds": 2,
            "bedtime_resistance_minutes": 45,
            "nap_total_minutes": 60,
            "medical_flags": False,
            "preterm_birth": False,
        },
    )
    assert questionnaire["provisional_severity_score"] == 69
    res = api.review_questionnaire(
        questionnaire["id"],
        review_questionnaire_payload(12, review_note="colic suspected"),
        make_consultant_headers(consultant["id"]),
    )
    reviewed = validate_success(res, 200)
    assert reviewed["reviewed_severity_score"] == 76, (
        f"expected reviewed 76 (69 + 12 - 5), got {reviewed['reviewed_severity_score']}"
    )
    assert reviewed["reviewed_severity_score"] != reviewed["provisional_severity_score"]
    assert reviewed["status"] == "REVIEWED"
    assert get_case(case["id"])["status"] == "PLANNING"


def test_severity_nap_surplus_and_medical_penalty_clamp_to_zero(api):
    """PRD §3.2: "Start with ten points per night waking, add four points per night
    feed, add one point for each full three minutes of bedtime resistance (the
    minutes divided by three, rounded down), and add a nap-deficit term: the
    shortfall of the day's `nap_total_minutes` against a 150-minute baseline, divided
    by fifteen and rounded up, never less than zero. If `medical_flags` is set,
    subtract twenty points; if `preterm_birth` is set, subtract a further ten. The
    result is then clamped into the range from 0 to 100 inclusive."

    answers = {wakings 1, feeds 1, bedtime 10, nap 200, medical true}:
    10 + 4 + floor(10/3)=3 + max(0, ceil((150-200)/15))=0 - 20 = -3, clamped to 0.

    Design: Difficulty/combinatorial_formula/severity_score_multibranch_clamp
    """
    consultant = create_consultant(certification_no="CERT-102")
    family = register_family(full_name="Fam M", email="m@x.com")
    case = open_case(family, consultant, child_birth_date="2026-03-15")
    res = api.submit_questionnaire(
        case["id"],
        submit_questionnaire_payload(
            {
                "night_wakings": 1,
                "night_feeds": 1,
                "bedtime_resistance_minutes": 10,
                "nap_total_minutes": 200,
                "medical_flags": True,
                "preterm_birth": False,
            }
        ),
        make_parent_headers(family["id"]),
    )
    questionnaire = validate_success(res, 201)
    assert questionnaire["provisional_severity_score"] == 0, (
        f"raw score -3 must clamp up to the 0 floor, got {questionnaire['provisional_severity_score']}"
    )


def test_severity_nap_surplus_branch_without_medical_penalty(api):
    """PRD §3.2: "Start with ten points per night waking, add four points per night
    feed, add one point for each full three minutes of bedtime resistance (the
    minutes divided by three, rounded down), and add a nap-deficit term: the
    shortfall of the day's `nap_total_minutes` against a 150-minute baseline, divided
    by fifteen and rounded up, never less than zero. If `medical_flags` is set,
    subtract twenty points; if `preterm_birth` is set, subtract a further ten."

    Same answers as the clamp probe but with medical_flags false: the nap-surplus
    term contributes max(0, ceil((150-200)/15)) = 0 and no penalty applies, so the
    score is 10 + 4 + 3 + 0 = 17 — isolating the medical branch's −20 contribution.

    Design: Difficulty/combinatorial_formula/severity_score_multibranch_clamp
    """
    consultant = create_consultant(certification_no="CERT-102")
    family = register_family(full_name="Fam M", email="m@x.com")
    case = open_case(family, consultant, child_birth_date="2026-03-15")
    res = api.submit_questionnaire(
        case["id"],
        submit_questionnaire_payload(
            {
                "night_wakings": 1,
                "night_feeds": 1,
                "bedtime_resistance_minutes": 10,
                "nap_total_minutes": 200,
                "medical_flags": False,
                "preterm_birth": False,
            }
        ),
        make_parent_headers(family["id"]),
    )
    questionnaire = validate_success(res, 201)
    assert questionnaire["provisional_severity_score"] == 17, (
        f"expected 17 (no medical penalty, nap surplus clamped to 0), got "
        f"{questionnaire['provisional_severity_score']}"
    )


def test_age_band_boundary_exactly_four_months(api):
    """PRD §3.1: "`child_age_months` is the number of whole months between
    `child_birth_date` and the logical clock date: twelve times the difference in
    years plus the difference in months, minus one when the clock's day-of-month is
    earlier than the birth day-of-month, and never below zero. `age_band` is then
    `NEWBORN` at three months or younger, `INFANT` from four through eleven months,
    `TODDLER` from twelve through thirty-five months, and `PRESCHOOL` at thirty-six
    months or older; band boundaries are inclusive at the lower edge, so a child
    exactly four months old is `INFANT`."

    At the default clock 2026-08-01: birth 2026-04-01 is exactly 4 months (INFANT);
    birth 2026-04-02 is 3 months because clock day 1 < birth day 2 (NEWBORN).

    Design: Corner/calculations/age_band_boundary_exactly_four_months
    """
    consultant = create_consultant(max_active_cases=5, certification_no="CERT-217")
    family = register_family()
    case_a = validate_success(
        api.create_case(
            create_case_payload(family["id"], consultant["id"], child_birth_date="2026-04-01"),
            make_parent_headers(family["id"]),
        ),
        201,
    )
    case_b = validate_success(
        api.create_case(
            create_case_payload(family["id"], consultant["id"], child_birth_date="2026-04-02"),
            make_parent_headers(family["id"]),
        ),
        201,
    )
    assert case_a["child_age_months"] == 4 and case_a["age_band"] == "INFANT"
    assert case_b["child_age_months"] == 3 and case_b["age_band"] == "NEWBORN"
