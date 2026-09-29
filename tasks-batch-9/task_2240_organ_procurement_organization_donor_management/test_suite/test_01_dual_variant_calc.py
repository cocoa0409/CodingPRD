"""One input, two scoring bases: lag bases, risk variants and rate denominators."""

from test_helpers import (
    BASIS_CLINICAL_TRIGGER,
    BASIS_DEATH_NOTE,
    PARTNER_POSTURE_GOOD_STANDING,
    RISK_TIER_INCREASED,
    RISK_TIER_STANDARD,
    TIER_FAIL,
    TIER_PROBATION,
    TIMELINESS_TIMELY,
    TIMELINESS_UNTIMELY,
    VARIANT_INTERVIEW_BASED,
    VARIANT_RECORDS_ONLY,
    assert_two_decimal_value,
    create_hospital,
    create_referral,
    open_screening,
    read_hospital,
    read_performance,
    submit_assessment,
)


# ---------------------------------------------------------------------------
# Referral lag on the clinical-trigger basis versus the death-note basis
# ---------------------------------------------------------------------------
def test_one_referral_stores_both_lag_bases_independently(env):
    """A single intake stores a clinical-trigger lag and a death-note lag.

    PRD 3.1: "For each basis, the lag is the number of whole minutes from the
    basis instant to `referred_at`".
    PRD 3.1: "Under the clinical-trigger basis the basis instant is
    `trigger_event_at`, and the resulting value is stored as
    `referral_lag_minutes`".
    PRD 3.1: "Under the death-note basis the basis instant is
    `death_pronounced_at`, and the resulting value is stored as
    `audit_lag_minutes`".

    Design: Difficulty/dual_variant_calc/referral_lag_clinical_trigger_versus_death_note_basis
    """
    env.set_clock("2026-08-10T11:00:00Z")
    hospital = create_hospital(
        env,
        name="Mercy General",
        referral_trigger_policy="VENTILATED_NEURO_INJURY",
        timely_referral_window_minutes=60,
    )
    referral = create_referral(
        env,
        hospital["id"],
        "2026-08-10T09:45:00Z",
        patient_mrn="MRN-7001",
        age_years=52,
        ventilated=True,
        gcs_score=3,
        cause_of_death_category="ANOXIA",
        death_pronounced_at="2026-08-10T10:30:00Z",
    )

    assert referral["referral_lag_minutes"] == 75
    assert referral["audit_lag_minutes"] == 30


def test_only_the_clinical_trigger_basis_sets_the_persisted_flag(env):
    """The stored flag follows the trigger lag even when the death-note lag is timely.

    PRD 3.1: "Only the clinical-trigger basis sets the persisted
    `timeliness_flag`: it is `TIMELY` when `referral_lag_minutes` is less than
    or equal to the hospital's `timely_referral_window_minutes`".
    PRD 3.1: "`untimely_referral_count` increases by one when the flag is
    `UNTIMELY`".

    Design: Difficulty/dual_variant_calc/referral_lag_clinical_trigger_versus_death_note_basis
    """
    env.set_clock("2026-08-10T11:00:00Z")
    hospital = create_hospital(
        env, name="Mercy General", timely_referral_window_minutes=60
    )
    referral = create_referral(
        env,
        hospital["id"],
        "2026-08-10T09:45:00Z",
        patient_mrn="MRN-7001",
        age_years=52,
        death_pronounced_at="2026-08-10T10:30:00Z",
    )

    assert referral["timeliness_flag"] == TIMELINESS_UNTIMELY

    standing = read_hospital(env, hospital["id"])
    assert standing["referral_count"] == 1
    assert standing["untimely_referral_count"] == 1
    assert standing["timely_referral_count"] == 0
    assert_two_decimal_value(standing["timely_referral_rate"], 0.00)


def test_recert_basis_switch_flips_the_windowed_timeliness_verdict(env):
    """The same referral reads FAIL on the trigger basis and PROBATION on the death note.

    PRD 3.8: "On the `CLINICAL_TRIGGER` basis, timeliness is read from each
    referral's stored `timeliness_flag`."
    PRD 3.8: "On the `DEATH_NOTE` basis, timeliness is instead re-derived from
    `audit_lag_minutes` against the hospital's window".
    PRD 3.8: "if the windowed `timely_referral_rate` is at least 60.00, the tier
    is `PROBATION`".

    Design: Difficulty/dual_variant_calc/referral_lag_clinical_trigger_versus_death_note_basis
    """
    env.set_clock("2026-08-10T11:00:00Z")
    hospital = create_hospital(
        env, name="Mercy General", timely_referral_window_minutes=60
    )
    create_referral(
        env,
        hospital["id"],
        "2026-08-10T09:45:00Z",
        patient_mrn="MRN-7001",
        age_years=52,
        ventilated=True,
        death_pronounced_at="2026-08-10T10:30:00Z",
    )
    # PRD 3.8: "`window_end` is the current logical clock instant and is
    # **exclusive**" -- the clock must move past `referred_at` for the referral
    # to be "strictly before `window_end`" and therefore in scope.
    env.set_clock("2026-08-10T11:05:00Z")

    on_trigger = read_performance(
        env, hospital["id"], window_days=365, basis=BASIS_CLINICAL_TRIGGER
    )
    assert on_trigger["eligible_referral_count"] == 1
    assert on_trigger["timely_referral_count"] == 0
    assert_two_decimal_value(on_trigger["timely_referral_rate"], 0.00)
    assert on_trigger["recertification_tier"] == TIER_FAIL

    on_death_note = read_performance(
        env, hospital["id"], window_days=365, basis=BASIS_DEATH_NOTE
    )
    assert on_death_note["eligible_referral_count"] == 1
    assert on_death_note["timely_referral_count"] == 1
    assert_two_decimal_value(on_death_note["timely_referral_rate"], 100.00)
    assert on_death_note["recertification_tier"] == TIER_PROBATION


# ---------------------------------------------------------------------------
# Behavioral risk: interview-based versus records-only
# ---------------------------------------------------------------------------
def _pending_screening(env, mrn):
    hospital = create_hospital(env, timely_referral_window_minutes=60)
    referral = create_referral(
        env,
        hospital["id"],
        "2026-08-10T10:30:00Z",
        patient_mrn=mrn,
        age_years=44,
    )
    return open_screening(env, referral["id"])


def test_interview_based_variant_ignores_unresolved_factors(env):
    """A primary-informant assessment scores the reported factors only.

    PRD 3.2: "the unresolved factors are ignored entirely and
    `risk_variant_applied` is set to `INTERVIEW_BASED`".
    PRD 3.2: "each one contributes its weight multiplied by the reliability
    multiplier, that product rounded half up to two decimal places".

    Design: Difficulty/dual_variant_calc/behavioral_risk_interview_versus_records_only_variant
    """
    env.set_clock("2026-08-10T11:00:00Z")
    screening = _pending_screening(env, "MRN-7002")

    scored = submit_assessment(
        env,
        screening["id"],
        screening["version"],
        risk_factors=["IV_DRUG_USE_12MO"],
        informant_reliability="PRIMARY_NEXT_OF_KIN",
        unresolved_factors=[
            "INCARCERATION_72H_12MO",
            "NEW_SEX_PARTNER_HIGH_RISK_12MO",
            "HEMODIALYSIS_12MO",
        ],
    )

    assert_two_decimal_value(scored["risk_score"], 6.50)
    assert scored["risk_tier"] == RISK_TIER_STANDARD
    assert scored["risk_variant_applied"] == VARIANT_INTERVIEW_BASED


def test_records_only_variant_imputes_unresolved_factors_at_half_weight(env):
    """A records-only assessment adds each unresolved factor at half its weight.

    PRD 3.2: "the unresolved factors are then de-duplicated, walked in the same
    canonical order, and each one contributes its weight multiplied by one half
    and then by the reliability multiplier, that product likewise rounded half
    up to two decimal places".
    PRD 3.2: "Finally `risk_tier` becomes `INCREASED_RISK` when `risk_score` is
    at least 12.00 and `STANDARD` otherwise."

    Design: Difficulty/dual_variant_calc/behavioral_risk_interview_versus_records_only_variant
    """
    env.set_clock("2026-08-10T11:00:00Z")
    screening = _pending_screening(env, "MRN-7003")

    scored = submit_assessment(
        env,
        screening["id"],
        screening["version"],
        risk_factors=["IV_DRUG_USE_12MO"],
        informant_reliability="MEDICAL_RECORD_ONLY",
        unresolved_factors=[
            "INCARCERATION_72H_12MO",
            "NEW_SEX_PARTNER_HIGH_RISK_12MO",
            "HEMODIALYSIS_12MO",
        ],
    )

    # 8.45 reported plus 2.76, 2.44 and 1.63 imputed.
    assert_two_decimal_value(scored["risk_score"], 15.28)
    assert scored["risk_tier"] == RISK_TIER_INCREASED
    assert scored["risk_variant_applied"] == VARIANT_RECORDS_ONLY


def test_records_only_variant_scores_strictly_higher_on_the_same_history(env):
    """Two screenings with identical reported factors diverge by the variant alone.

    PRD 3.2: "The same reported factor list therefore scores strictly higher
    under the records-only variant whenever any unresolved factor is present."

    Design: Difficulty/dual_variant_calc/behavioral_risk_interview_versus_records_only_variant
    """
    env.set_clock("2026-08-10T11:00:00Z")
    unresolved = [
        "INCARCERATION_72H_12MO",
        "NEW_SEX_PARTNER_HIGH_RISK_12MO",
        "HEMODIALYSIS_12MO",
    ]

    interview = _pending_screening(env, "MRN-7002")
    records = _pending_screening(env, "MRN-7003")

    interview_scored = submit_assessment(
        env,
        interview["id"],
        interview["version"],
        risk_factors=["IV_DRUG_USE_12MO"],
        informant_reliability="PRIMARY_NEXT_OF_KIN",
        unresolved_factors=list(unresolved),
    )
    records_scored = submit_assessment(
        env,
        records["id"],
        records["version"],
        risk_factors=["IV_DRUG_USE_12MO"],
        informant_reliability="MEDICAL_RECORD_ONLY",
        unresolved_factors=list(unresolved),
    )

    assert float(records_scored["risk_score"]) > float(interview_scored["risk_score"])
    assert_two_decimal_value(
        float(records_scored["risk_score"]) - float(interview_scored["risk_score"]),
        8.78,
    )
    assert interview_scored["risk_tier"] == RISK_TIER_STANDARD
    assert records_scored["risk_tier"] == RISK_TIER_INCREASED


# ---------------------------------------------------------------------------
# Lifetime standing versus the windowed recertification denominator
# ---------------------------------------------------------------------------
def _hospital_with_three_timely_unventilated_and_one_untimely_ventilated(env):
    hospital = create_hospital(
        env,
        name="Lakeside Regional",
        referral_trigger_policy="ALL_VENTILATED_DEATHS",
        timely_referral_window_minutes=60,
    )
    for mrn in ("MRN-8001", "MRN-8002", "MRN-8003"):
        create_referral(
            env,
            hospital["id"],
            "2026-08-10T10:30:00Z",
            as_clerk=True,
            patient_mrn=mrn,
            age_years=61,
            ventilated=False,
            gcs_score=6,
            cause_of_death_category="CVA_STROKE",
        )
    create_referral(
        env,
        hospital["id"],
        "2026-08-10T09:00:00Z",
        patient_mrn="MRN-8004",
        age_years=58,
        ventilated=True,
        gcs_score=3,
        cause_of_death_category="HEAD_TRAUMA",
    )
    return hospital


def test_lifetime_standing_counts_every_referral_ever_placed(env):
    """The persisted rate uses all four referrals, ventilated or not.

    PRD 3.1: "This lifetime denominator counts **every** referral the hospital
    has ever placed — ventilated or not, ruled out or not — and its numerator
    uses each referral's stored flag."
    PRD 3.1: "otherwise, a rate of at least 75.00 gives `GOOD_STANDING`, a rate
    of at least 60.00 gives `WATCH`, and anything lower gives `PROBATION`".

    Design: Difficulty/dual_variant_calc/hospital_lifetime_rate_versus_windowed_recert_denominator
    """
    env.set_clock("2026-08-10T11:00:00Z")
    hospital = _hospital_with_three_timely_unventilated_and_one_untimely_ventilated(env)

    standing = read_hospital(env, hospital["id"])
    assert standing["referral_count"] == 4
    assert standing["timely_referral_count"] == 3
    assert standing["untimely_referral_count"] == 1
    assert_two_decimal_value(standing["timely_referral_rate"], 75.00)
    assert standing["partner_posture"] == PARTNER_POSTURE_GOOD_STANDING


def test_windowed_denominator_counts_only_ventilated_referrals(env):
    """The recertification read narrows to the ventilated subset and reads FAIL.

    PRD 3.8: "an `eligible_referral_count`, being the number of in-scope
    referrals whose `ventilated` is true, which is the imminent-death
    denominator".
    PRD 3.8: "the same hospital can quite legitimately carry a
    `partner_posture` of `GOOD_STANDING` while its `recertification_tier` reads
    `FAIL`".

    Design: Difficulty/dual_variant_calc/hospital_lifetime_rate_versus_windowed_recert_denominator
    """
    env.set_clock("2026-08-10T11:00:00Z")
    hospital = _hospital_with_three_timely_unventilated_and_one_untimely_ventilated(env)
    # PRD 3.8: "`window_end` is the current logical clock instant and is
    # **exclusive**" -- the clock must move past `referred_at` for the referrals
    # to be "strictly before `window_end`" and therefore in scope.
    env.set_clock("2026-08-10T11:05:00Z")

    report = read_performance(
        env, hospital["id"], window_days=365, basis=BASIS_CLINICAL_TRIGGER
    )
    assert report["eligible_referral_count"] == 1
    assert report["timely_referral_count"] == 0
    assert_two_decimal_value(report["timely_referral_rate"], 0.00)
    assert report["recertification_tier"] == TIER_FAIL

    standing = read_hospital(env, hospital["id"])
    assert standing["partner_posture"] == PARTNER_POSTURE_GOOD_STANDING
    assert_two_decimal_value(standing["timely_referral_rate"], 75.00)


def test_unventilated_referrals_still_carry_a_timely_flag_of_their_own(env):
    """A referral excluded from the windowed denominator still scores its own lag.

    PRD 3.1: "The window is pinned from the hospital row as it stands at
    intake; a later edit to the hospital's window never restates a referral
    already stored."
    PRD 3.1: "it is `TIMELY` when `referral_lag_minutes` is less than or equal
    to the hospital's `timely_referral_window_minutes`, with equality counting
    as timely, and `UNTIMELY` otherwise".

    Design: Difficulty/dual_variant_calc/hospital_lifetime_rate_versus_windowed_recert_denominator
    """
    env.set_clock("2026-08-10T11:00:00Z")
    hospital = create_hospital(
        env,
        name="Lakeside Regional",
        referral_trigger_policy="ALL_VENTILATED_DEATHS",
        timely_referral_window_minutes=60,
    )
    unventilated = create_referral(
        env,
        hospital["id"],
        "2026-08-10T10:30:00Z",
        as_clerk=True,
        patient_mrn="MRN-8001",
        ventilated=False,
        gcs_score=6,
    )

    assert unventilated["referral_lag_minutes"] == 30
    assert unventilated["timeliness_flag"] == TIMELINESS_TIMELY
    assert unventilated["audit_lag_minutes"] is None
