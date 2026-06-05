"""The matching engine and its dual evaluation times: the frozen screening
snapshot versus the live re-evaluation at enrollment, plus the weighted
match-score formula (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    screen_participant_payload, create_enrollment_payload, update_participant_payload,
    assert_screening,
    set_clock, create_trial, add_criterion, create_participant,
    screen_participant, create_enrollment,
    TEST_USERS,
)


# ─── Difficulty: dual_variant_calc / eligibility drift ──────────────


def test_enrollment_rejected_when_age_drifts_below_inclusion(api):
    """PRD §3.4: "If the participant's fields have changed since screening so
    that the live evaluation now yields `INELIGIBLE` even though the stored
    screening said `ELIGIBLE`, the enrollment is rejected with
    `ERR_ELIGIBILITY_DRIFTED` (HTTP 409) — the frozen snapshot and the live
    value have diverged."

    Design: Difficulty/dual_variant_calc/dvc_eligibility_snapshot_vs_revalidation_drift
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    add_criterion(trial["id"], kind="INCLUSION", attribute="age_years", comparator="GE", threshold=18)
    participant = create_participant(full_name="P Drift", age_years=20, weight_kg=70, hba1c=6.0)

    screening = screen_participant(trial["id"], participant["id"])
    assert screening["match_result"] == "ELIGIBLE", "the frozen snapshot screened ELIGIBLE"

    # Drift the participant below the inclusion threshold before enrolling.
    validate_success(api.update_participant(
        participant["id"], update_participant_payload(age_years=17),
        TEST_USERS["coordinator_headers"],
    ), 200)

    res = api.create_enrollment(
        create_enrollment_payload(screening["id"]), TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ELIGIBILITY_DRIFTED.value, 409)


def test_screening_snapshot_frozen_eligible_despite_later_drift(api):
    """PRD §3.3: "the server creates a **Screening** that records the
    `trial_id` and `participant_id` and freezes three computed outcomes:
    `match_result`, `failed_criteria_count`, and `match_score`."

    Design: Difficulty/dual_variant_calc/dvc_eligibility_snapshot_vs_revalidation_drift
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    add_criterion(trial["id"], kind="INCLUSION", attribute="age_years", comparator="GE", threshold=18)
    participant = create_participant(full_name="P Frozen", age_years=20, weight_kg=70, hba1c=6.0)
    screening = screen_participant(trial["id"], participant["id"])

    # The participant drifts, but the already-frozen Screening row is unchanged.
    validate_success(api.update_participant(
        participant["id"], update_participant_payload(age_years=17),
        TEST_USERS["coordinator_headers"],
    ), 200)

    res = api.get_screening(screening["id"], TEST_USERS["coordinator_headers"])
    data = validate_success(res, 200)
    assert_screening(data)
    assert data["match_result"] == "ELIGIBLE", "the frozen snapshot stays ELIGIBLE after the drift"


# ─── Difficulty: combinatorial_formula / match_score mode (a) ───────


def test_match_score_weighted_inclusion_and_exclusion(api):
    """PRD §3.3: "When both sets are non-empty, the raw score is the inclusion
    pass fraction weighted by 0.6 plus the exclusion clear fraction weighted
    by 0.4."
    PRD §3.3: "The `match_result` is `ELIGIBLE` when the failure count is
    exactly 0, and `INELIGIBLE` otherwise."

    Design: Difficulty/combinatorial_formula/cf_match_score_weighted_mode_a
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    # 2 inclusion (one passes, one fails) + 1 exclusion (cleared).
    add_criterion(trial["id"], kind="INCLUSION", attribute="age_years", comparator="GE", threshold=18)
    add_criterion(trial["id"], kind="INCLUSION", attribute="hba1c", comparator="GE", threshold=7.0)
    add_criterion(trial["id"], kind="EXCLUSION", attribute="prior_trials_count", comparator="GE", threshold=3)
    participant = create_participant(
        full_name="P Score", age_years=20, weight_kg=70, hba1c=6.0, prior_trials_count=0,
    )

    res = api.screen_participant(
        trial["id"], screen_participant_payload(participant["id"]),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 201)
    assert_screening(data)
    # 0.6*(1/2) + 0.4*(1/1) = 0.3 + 0.4 = 0.7
    assert data["match_score"] == pytest.approx(0.7, abs=1e-4), \
        f"weighted score must be 0.7000, got {data['match_score']}"
    assert data["failed_criteria_count"] == 1, "one inclusion fails (hba1c 6.0 < 7.0)"
    assert data["match_result"] == "INELIGIBLE", "one failure => INELIGIBLE"


def test_match_score_clamped_lone_inclusion_full_weight(api):
    """PRD §3.3: "When only the inclusion set is non-empty, the raw score is
    the inclusion pass fraction alone (the lone present category takes full
    weight)"
    PRD §3.3: "The stored `match_score` is the raw score clamped to a maximum
    of 1.0 and then rounded to four decimal places using round-half-up"

    Design: Difficulty/combinatorial_formula/cf_match_score_weighted_mode_a
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    add_criterion(trial["id"], kind="INCLUSION", attribute="age_years", comparator="GE", threshold=18)
    participant = create_participant(full_name="P Lone", age_years=40, weight_kg=70, hba1c=6.0)

    res = api.screen_participant(
        trial["id"], screen_participant_payload(participant["id"]),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 201)
    assert data["match_score"] == pytest.approx(1.0, abs=1e-4), \
        f"lone passed inclusion folds to 1.0, got {data['match_score']}"
    assert data["match_result"] == "ELIGIBLE"


# ─── Corner: validations / enrollment from ineligible screening ─────


def test_enrollment_from_ineligible_screening_rejected(api):
    """PRD §3.4: "The referenced screening must have `match_result` of
    `ELIGIBLE` for the trial in question; otherwise the creation is rejected
    with `ERR_SCREENING_NOT_ELIGIBLE` (HTTP 409)."

    Design: Corner/validations/enrollment_from_ineligible_screening_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    add_criterion(trial["id"], kind="INCLUSION", attribute="age_years", comparator="GE", threshold=18)
    participant = create_participant(full_name="P Young", age_years=16, weight_kg=60, hba1c=5.5)
    screening = screen_participant(trial["id"], participant["id"])
    assert screening["match_result"] == "INELIGIBLE", "age 16 < 18 fails the inclusion"

    res = api.create_enrollment(
        create_enrollment_payload(screening["id"]), TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_SCREENING_NOT_ELIGIBLE.value, 409)
