"""Four donor dimensions that move on their own, and the deferral repair loop."""
from test_helpers import (
    create_donor,
    determine_evaluation,
    get_donor,
    record_disclosure,
    setup_program_with_staff,
    submit_medical_evaluation,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId


def test_advocacy_moves_while_the_psychosocial_dimension_stays_untouched():
    """PRD §3.3: "The three input dimensions advance independently — a donor may be
    `ATTESTED` while medically `PENDING`, or medically `CLEARED` while advocacy is
    still `UNASSIGNED` — and none of them blocks another."
    PRD §3.4: "The **screening index**, stored in `screening_risk_index`, is
    recomputed after every determination and every resubmission. It is six tenths
    of `medical_risk_points` plus four tenths of `psychosocial_risk_points`, rounded
    half up to two decimal places once, applied to the whole weighted sum."
    PRD §3.4: "And `final_risk_index` stays null until the donor has both clinical
    dimensions `CLEARED` and `advocacy_status` `ATTESTED`."

    Design: Difficulty/non_linear_state_machine/donor_candidate_parallel_dimension_independence
    """
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)
    assert donor["advocacy_status"] == "ASSIGNED"

    medical = submit_medical_evaluation(env, donor["id"], bmi=31.0)
    determine_evaluation(env, medical["id"], "CLEARED", env["reviewer_med_headers"])

    disclosed = record_disclosure(env, donor["id"])

    assert disclosed["advocacy_status"] == "DISCLOSED"
    assert disclosed["medical_status"] == "CLEARED"
    assert disclosed["psychosocial_status"] == "PENDING", (
        "the psychosocial dimension has never been touched and is not dragged along"
    )
    assert disclosed["overall_status"] == "EVAL_IN_PROGRESS"
    assert disclosed["medical_risk_points"] == 2, "a bmi of 31.0 is a soft two-point finding"
    assert disclosed["psychosocial_risk_points"] == 0
    assert disclosed["screening_risk_index"] == 1.2, "0.6 * 2 + 0.4 * 0"
    assert disclosed["final_risk_index"] is None
    assert disclosed["disclosure_sequence"] == 1
    assert disclosed["cooling_off_ends_at"].startswith("2026-08-15T00:00:00"), (
        "a non-directed donor at the default seven-day base gets fourteen days"
    )


def test_medical_clearance_lands_while_advocacy_is_still_unassigned():
    """PRD §3.3: "The three input dimensions advance independently — a donor may be
    `ATTESTED` while medically `PENDING`, or medically `CLEARED` while advocacy is
    still `UNASSIGNED` — and none of them blocks another."
    PRD §3.4: "A `CLEARED` determination sets that donor dimension to `CLEARED`,
    copies the evaluation's `risk_points` into the donor's `medical_risk_points` or
    `psychosocial_risk_points` as the domain dictates, recomputes the donor's
    `screening_risk_index` and re-derives `overall_status`."
    PRD §3.3: "A `ProgramAdmin` assigns the advocate by supplying an
    `advocate_staff_id`, moving `advocacy_status` from `UNASSIGNED` to `ASSIGNED`
    and recording the staff member on the donor."

    Design: Difficulty/non_linear_state_machine/donor_candidate_parallel_dimension_independence
    """
    env = setup_program_with_staff()
    donor = create_donor(env, assign_advocate=False, mrn="D-001", age_years=41)
    assert donor["advocacy_status"] == "UNASSIGNED"
    assert donor["advocate_staff_id"] is None

    medical = submit_medical_evaluation(env, donor["id"], bmi=31.0)
    cleared = determine_evaluation(
        env, medical["id"], "CLEARED", env["reviewer_med_headers"]
    )
    assert cleared["status"] == "CLEARED"

    donor_after_clearance = get_donor(env, donor["id"])
    assert donor_after_clearance["medical_status"] == "CLEARED"
    assert donor_after_clearance["advocacy_status"] == "UNASSIGNED", (
        "clinical clearance does not drag the advocacy dimension forward"
    )
    assert donor_after_clearance["screening_risk_index"] == 1.2
    assert donor_after_clearance["overall_status"] == "EVAL_IN_PROGRESS"

    assigned = validate_success(
        api_client.assign_advocate(
            donor["id"],
            {"advocate_staff_id": env["advocate"]["id"]},
            env["admin_headers"],
        )
    )
    assert assigned["advocacy_status"] == "ASSIGNED", (
        "the advocacy dimension is still free to start from UNASSIGNED afterwards"
    )
    assert assigned["medical_status"] == "CLEARED"


def test_deferred_evaluation_is_repaired_by_resubmission_and_then_cleared():
    """PRD §3.4: "The evaluation returns to `SUBMITTED`, `submission_count`
    increases by 1, `determined_at` is cleared to null, and `exclusion_codes`,
    `hard_exclusion_count` and `risk_points` are re-screened from the new findings.
    The donor's matching risk-points field and `screening_risk_index` are
    recomputed."
    PRD §3.4: "A dimension may move `PENDING` to `CLEARED`, `PENDING` to
    `DEFERRED`, `DEFERRED` to `CLEARED` after a resubmission, `PENDING` or
    `DEFERRED` to `EXCLUDED`, and — when a later determination defers a domain that
    had already been cleared — `CLEARED` back to `DEFERRED`, which also increments
    `deferral_count` and re-derives `overall_status` down to `EVAL_IN_PROGRESS`."
    PRD §3.4: "Critically, `deferral_count` is **not** reset — the resubmission
    repairs the findings but not the history."

    Design: Difficulty/non_linear_state_machine/donor_evaluation_deferral_resubmission_cycle
    """
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)

    medical = submit_medical_evaluation(env, donor["id"], bmi=36.0)
    assert medical["status"] == "SUBMITTED"
    assert medical["submission_count"] == 1
    assert medical["exclusion_codes"] == ["EX_BMI_TOO_HIGH"], (
        "a bmi strictly above 35.0 is a hard exclusion, not a soft finding"
    )
    assert medical["hard_exclusion_count"] == 1
    assert medical["risk_points"] == 0, (
        "a measurement that fires a hard code contributes no soft points"
    )

    deferred = determine_evaluation(
        env, medical["id"], "DEFERRED", env["reviewer_med_headers"]
    )
    assert deferred["status"] == "DEFERRED"
    donor_deferred = get_donor(env, donor["id"])
    assert donor_deferred["medical_status"] == "DEFERRED"
    assert donor_deferred["deferral_count"] == 1

    validate_success(
        api_client.resubmit_evaluation(
            medical["id"],
            {
                "bmi": 31.0,
                "egfr_ml_min": 100.0,
                "systolic_bp": 118,
                "hba1c": 5.0,
                "coercion_flag": False,
                "unmanaged_substance_use": False,
                "decisional_capacity_ok": True,
                "financial_hardship_score": 1,
                "social_support_score": 9,
            },
            env["reviewer_med_headers"],
        )
    )
    recleared = determine_evaluation(
        env, medical["id"], "CLEARED", env["reviewer_med_headers"]
    )

    assert recleared["status"] == "CLEARED"
    assert recleared["submission_count"] == 2
    assert recleared["exclusion_codes"] == []
    assert recleared["hard_exclusion_count"] == 0
    assert recleared["risk_points"] == 2, "the repaired bmi of 31.0 is a soft two-point finding"

    donor_after = get_donor(env, donor["id"])
    assert donor_after["medical_status"] == "CLEARED"
    assert donor_after["deferral_count"] == 1, "the deferral history survives the repair"
    assert donor_after["medical_risk_points"] == 2
    assert donor_after["screening_risk_index"] == 1.2
    assert donor_after["overall_status"] == "EVAL_IN_PROGRESS"


def test_resubmission_reopens_the_row_without_erasing_the_deferral_history():
    """PRD §3.4: "The evaluation returns to `SUBMITTED`, `submission_count`
    increases by 1, `determined_at` is cleared to null, and `exclusion_codes`,
    `hard_exclusion_count` and `risk_points` are re-screened from the new findings.
    The donor's matching risk-points field and `screening_risk_index` are
    recomputed."
    PRD §3.4: "Critically, `deferral_count` is **not** reset — the resubmission
    repairs the findings but not the history."
    PRD §3.4: "Every determination stamps `determined_at` with the current logical
    clock and increments the evaluation's `version` by 1."

    Design: Difficulty/non_linear_state_machine/donor_evaluation_deferral_resubmission_cycle
    """
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)

    medical = submit_medical_evaluation(env, donor["id"], bmi=36.0)
    deferred = determine_evaluation(
        env, medical["id"], "DEFERRED", env["reviewer_med_headers"]
    )
    assert deferred["determined_at"] is not None

    resubmitted = validate_success(
        api_client.resubmit_evaluation(
            medical["id"],
            {
                "bmi": 31.0,
                "egfr_ml_min": 100.0,
                "systolic_bp": 118,
                "hba1c": 5.0,
                "coercion_flag": False,
                "unmanaged_substance_use": False,
                "decisional_capacity_ok": True,
                "financial_hardship_score": 1,
                "social_support_score": 9,
            },
            env["reviewer_med_headers"],
        )
    )

    assert resubmitted["status"] == "SUBMITTED", "the row is reopened, not decided"
    assert resubmitted["submission_count"] == 2
    assert resubmitted["determined_at"] is None
    assert resubmitted["exclusion_codes"] == []
    assert resubmitted["hard_exclusion_count"] == 0
    assert resubmitted["risk_points"] == 2

    donor_mid_cycle = get_donor(env, donor["id"])
    assert donor_mid_cycle["deferral_count"] == 1
    assert donor_mid_cycle["medical_risk_points"] == 2, (
        "the donor's risk points are recomputed by the resubmission itself"
    )
    assert donor_mid_cycle["screening_risk_index"] == 1.2


def test_hard_finding_must_be_repaired_by_resubmission_not_cleared_over():
    """PRD §3.4: "A `CLEARED` outcome is refused with
    `ERR_HARD_EXCLUSION_PRESENT` while the evaluation's `hard_exclusion_count` is
    greater than 0 — a hard finding must be resolved by resubmission, not
    overridden."
    PRD §3.4: "`EX_BMI_TOO_HIGH` fires when `bmi` is strictly greater than 35.0."

    Design: Difficulty/non_linear_state_machine/donor_evaluation_deferral_resubmission_cycle
    """
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)
    medical = submit_medical_evaluation(env, donor["id"], bmi=36.0)
    assert medical["hard_exclusion_count"] == 1

    response = api_client.record_evaluation_determination(
        medical["id"], {"outcome": "CLEARED"}, env["reviewer_med_headers"]
    )
    validate_error(response, ApiErrorId.ERR_HARD_EXCLUSION_PRESENT.value)

    unchanged = validate_success(
        api_client.get_donor_evaluation(medical["id"], env["reviewer_med_headers"])
    )
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["determined_at"] is None
