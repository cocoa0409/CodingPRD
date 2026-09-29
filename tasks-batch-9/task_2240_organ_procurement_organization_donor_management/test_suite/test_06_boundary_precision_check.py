"""Inclusive thresholds, empty denominators and the exact minute of expiry."""

import pytest

from test_helpers import (
    BASIS_CLINICAL_TRIGGER,
    PARTNER_POSTURE_GOOD_STANDING,
    TIER_FAIL,
    TIER_INSUFFICIENT_DATA,
    TIMELINESS_TIMELY,
    TIMELINESS_UNTIMELY,
    advance_run,
    allocatable_organ,
    assert_instant_equals,
    assert_slot_conservation,
    assert_two_decimal_value,
    candidate_sequence,
    create_hospital,
    create_referral,
    list_offers,
    open_match_run,
    read_case,
    read_hospital,
    read_organ,
    read_performance,
    read_run,
)


# ---------------------------------------------------------------------------
# The timely-referral window is inclusive at its floor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "trigger_at,expected_lag,expected_flag",
    [
        ("2026-08-19T10:00:00Z", 60, TIMELINESS_TIMELY),
        ("2026-08-19T09:59:00Z", 61, TIMELINESS_UNTIMELY),
    ],
)
def test_window_equality_counts_as_timely_and_one_minute_past_does_not(
    env, trigger_at, expected_lag, expected_flag
):
    """A lag of exactly sixty is timely; sixty-one is not.

    PRD 3.1: "it is `TIMELY` when `referral_lag_minutes` is less than or equal
    to the hospital's `timely_referral_window_minutes`, with equality counting
    as timely, and `UNTIMELY` otherwise".
    PRD 2.6: "Every threshold comparison in this specification is inclusive at
    the stated floor unless the text says otherwise."

    Design: Difficulty/boundary_precision_check/referral_lag_inclusive_at_window_and_one_minute_past
    """
    env.set_clock("2026-08-19T11:00:00Z")
    hospital = create_hospital(env, timely_referral_window_minutes=60)

    referral = create_referral(env, hospital["id"], trigger_at)

    assert referral["referral_lag_minutes"] == expected_lag
    assert referral["timeliness_flag"] == expected_flag
    assert referral["audit_lag_minutes"] is None


def test_posture_holds_good_standing_below_the_minimum_sample(env):
    """A fifty-percent rate over two referrals still reads GOOD_STANDING.

    PRD 3.1: "if `referral_count` is below four the sample is too small to judge
    and the posture is `GOOD_STANDING` regardless of rate".
    PRD 3.1: "otherwise becomes one hundred multiplied by
    `timely_referral_count`, divided by `referral_count`, rounded half up to two
    decimal places".

    Design: Difficulty/boundary_precision_check/referral_lag_inclusive_at_window_and_one_minute_past
    """
    env.set_clock("2026-08-19T11:00:00Z")
    hospital = create_hospital(env, timely_referral_window_minutes=60)
    create_referral(env, hospital["id"], "2026-08-19T10:00:00Z", patient_mrn="MRN-8301")
    create_referral(env, hospital["id"], "2026-08-19T09:59:00Z", patient_mrn="MRN-8302")

    standing = read_hospital(env, hospital["id"])
    assert standing["referral_count"] == 2
    assert standing["timely_referral_count"] == 1
    assert standing["untimely_referral_count"] == 1
    assert_two_decimal_value(standing["timely_referral_rate"], 50.00)
    assert standing["partner_posture"] == PARTNER_POSTURE_GOOD_STANDING


# ---------------------------------------------------------------------------
# The expiry sweep is inclusive, and an empty pool exhausts the run
# ---------------------------------------------------------------------------
def _run_with_one_hour_offer(env):
    bundle = allocatable_organ(env, "LIVER", "2026-08-20T09:00:00Z")
    bundle.run = open_match_run(
        env,
        bundle.only_organ_id,
        candidate_sequence(1, 60),
        primary_offer_slots=2,
    )
    bundle.refresh_offers()
    return bundle


def test_expires_at_is_the_offered_instant_plus_the_candidates_own_clock(env):
    """A sixty-minute acceptance clock puts expiry exactly one hour out.

    PRD 3.6: "its status set to `PENDING`, its `offered_at` stamped from the
    logical clock, its `expires_at` set to that instant plus its own
    `acceptance_clock_minutes`".

    Design: Difficulty/boundary_precision_check/offer_expiry_inclusive_and_empty_candidate_pool_exhausts_run
    """
    bundle = _run_with_one_hour_offer(env)

    offer = bundle.offers[0]
    assert offer["status"] == "PENDING"
    assert_instant_equals(offer["offered_at"], "2026-08-20T09:00:00Z")
    assert_instant_equals(offer["expires_at"], "2026-08-20T10:00:00Z")

    run = read_run(env, bundle.run_id)
    assert run["pending_offer_count"] == 1
    assert run["slots_free"] == 1
    assert_slot_conservation(run)


def test_an_offer_whose_expiry_equals_the_clock_is_swept(env):
    """Advancing at exactly the expiry instant expires the offer.

    PRD 3.6: "The boundary is inclusive — an offer whose `expires_at` equals the
    current clock instant **is** swept — and each sweep decrements the run's
    `pending_offer_count` by one and increments its `slots_free` by one."

    Design: Difficulty/boundary_precision_check/offer_expiry_inclusive_and_empty_candidate_pool_exhausts_run
    """
    bundle = _run_with_one_hour_offer(env)
    env.set_clock("2026-08-20T10:00:00Z")

    advance_run(env, bundle.run_id)

    offers = list_offers(env, bundle.run_id)
    assert offers[0]["status"] == "EXPIRED"

    run = read_run(env, bundle.run_id)
    assert run["pending_offer_count"] == 0
    assert run["slots_free"] == 2
    assert_slot_conservation(run)


def test_an_empty_candidate_pool_exhausts_the_run_and_returns_the_organ(env):
    """With nothing left queued, the run exhausts and the organ is re-listable.

    PRD 3.6: "if the pool was empty **and** the run's `pending_offer_count` is
    zero after the sweep, the run moves `OPEN → EXHAUSTED` with `closed_reason`
    `CANDIDATES_EXHAUSTED`, the organ returns `OFFERING → ALLOCATABLE`, the case
    returns `allocation_status` `OFFERS_IN_FLIGHT → MATCH_RUN_OPEN`".

    Design: Difficulty/boundary_precision_check/offer_expiry_inclusive_and_empty_candidate_pool_exhausts_run
    """
    bundle = _run_with_one_hour_offer(env)
    env.set_clock("2026-08-20T10:00:00Z")

    advanced = advance_run(env, bundle.run_id)
    assert advanced["status"] == "EXHAUSTED"
    assert advanced["closed_reason"] == "CANDIDATES_EXHAUSTED"

    assert read_organ(env, bundle.only_organ_id)["status"] == "ALLOCATABLE"
    assert read_case(env, bundle.case_id)["allocation_status"] == "MATCH_RUN_OPEN"


# ---------------------------------------------------------------------------
# A zero ventilated denominator yields nulls, not zeros
# ---------------------------------------------------------------------------
def _harborview_with_one_unventilated_referral(env):
    env.set_clock("2026-08-21T11:00:00Z")
    hospital = create_hospital(
        env, name="Harborview", timely_referral_window_minutes=60
    )
    referral = create_referral(
        env,
        hospital["id"],
        "2026-08-21T10:30:00Z",
        patient_mrn="MRN-8501",
        age_years=70,
        ventilated=False,
        gcs_score=8,
        cause_of_death_category="OTHER",
    )
    return hospital, referral


def test_zero_eligible_referrals_leaves_every_ratio_null(env):
    """No ventilated referral means the three ratios are null rather than zero.

    PRD 3.8: "The report's `timely_referral_rate` is null when
    `eligible_referral_count` is zero".
    PRD 3.8: "The `conversion_rate` is null when `cleared_referral_count` is
    zero".
    PRD 3.8: "The `organs_per_donor` figure is null when
    `converted_referral_count` is zero".

    Design: Difficulty/boundary_precision_check/performance_zero_ventilated_denominator_yields_null_rate
    """
    hospital, _referral = _harborview_with_one_unventilated_referral(env)

    report = read_performance(
        env, hospital["id"], window_days=365, basis=BASIS_CLINICAL_TRIGGER
    )
    assert report["eligible_referral_count"] == 0
    assert report["timely_referral_rate"] is None
    assert report["conversion_rate"] is None
    assert report["organs_per_donor"] is None


def test_zero_eligible_referrals_reads_insufficient_data_not_fail(env):
    """The tier ladder short-circuits before the failure band is reached.

    PRD 3.8: "If `eligible_referral_count` is zero, the tier is
    `INSUFFICIENT_DATA`."

    Design: Difficulty/boundary_precision_check/performance_zero_ventilated_denominator_yields_null_rate
    """
    hospital, _referral = _harborview_with_one_unventilated_referral(env)

    report = read_performance(
        env, hospital["id"], window_days=365, basis=BASIS_CLINICAL_TRIGGER
    )
    assert report["recertification_tier"] == TIER_INSUFFICIENT_DATA
    assert report["recertification_tier"] != TIER_FAIL


def test_the_excluded_referral_still_scores_timely_on_the_lifetime_ledger(env):
    """The same referral is out of the windowed denominator but inside the lifetime one.

    PRD 3.1: "This lifetime denominator counts **every** referral the hospital
    has ever placed — ventilated or not, ruled out or not".

    Design: Difficulty/boundary_precision_check/performance_zero_ventilated_denominator_yields_null_rate
    """
    hospital, referral = _harborview_with_one_unventilated_referral(env)

    assert referral["timeliness_flag"] == TIMELINESS_TIMELY
    standing = read_hospital(env, hospital["id"])
    assert standing["referral_count"] == 1
    assert_two_decimal_value(standing["timely_referral_rate"], 100.00)
