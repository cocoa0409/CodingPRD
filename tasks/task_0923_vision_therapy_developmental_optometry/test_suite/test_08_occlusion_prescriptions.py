"""Patching: the age-band x severity dose ladder, adherence and the taper gate."""

from test_helpers import (
    ApiErrorId,
    assert_pct,
    log_adherence,
    read_prescription,
    setup_occlusion_scenario,
    taper,
    validate_error,
    validate_success,
)


def test_the_taper_self_loop_steps_the_dose_down_to_zero_and_completes(api):
    """PRD §3.8: "When the gate passes, `current_daily_hours` is reduced by 2 hours
    but never below zero, `taper_step_count` increments by 1, and the prescription's
    `version` is bumped."
    PRD §3.8: "A prescription in `ACTIVE` or `TAPERED` whose reduced dose is still
    strictly above zero lands in `TAPERED` — from `ACTIVE` that is the transition
    `ACTIVE → TAPERED`, and from `TAPERED` it is a self-loop that can be walked down
    repeatedly for as long as the gate keeps passing."
    PRD §3.8: "A prescription in `ACTIVE` or `TAPERED` whose reduced dose would reach
    zero or below instead has `current_daily_hours` set to exactly 0 and moves to
    `COMPLETED`, which is terminal."

    Design: Corner/state_machines/occlusion_taper_self_loop_reaches_completed_at_zero_hours
    """
    scn, prescription = setup_occlusion_scenario(
        severity="MODERATE", baseline_acuity_logmar=0.40
    )
    assert prescription["age_band"] == "OLDER"
    assert prescription["prescribed_daily_hours"] == 5

    adherence = log_adherence(scn, prescription["id"], 10, 8)
    assert_pct(adherence["adherence_pct"], 80.00, "adherence_pct")

    first = taper(scn, prescription["id"], 0.18)
    assert first["current_daily_hours"] == 3
    assert first["status"] == "TAPERED"

    second = taper(scn, prescription["id"], 0.18)
    assert second["current_daily_hours"] == 1
    assert second["status"] == "TAPERED"

    third = validate_success(
        api.taper_occlusion(
            prescription["id"], {"current_acuity_logmar": 0.18}, scn["hdr_od1"]
        ),
        200,
    )
    assert third["current_daily_hours"] == 0
    assert third["status"] == "COMPLETED"
    assert third["taper_step_count"] == 3

    fourth = api.taper_occlusion(
        prescription["id"], {"current_acuity_logmar": 0.18}, scn["hdr_od1"]
    )
    validate_error(fourth, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_the_most_aggressive_dose_cell_is_capped_at_seven_hours(api):
    """PRD §3.8: "An `OLDER` child is prescribed 3 hours when `MILD`, 5 when
    `MODERATE` and 8 when `SEVERE`."
    PRD §3.8: "Whatever the ladder yields is then capped at a maximum of 7 hours a
    day, which is why the single most aggressive cell — an older child with severe
    amblyopia, whose ladder value is 8 — is actually prescribed 7."
    PRD §3.8: "The capped figure is written to both `prescribed_daily_hours` and
    `current_daily_hours`, in whole hours. A new prescription opens in `status`
    `ACTIVE` with `taper_step_count` 0, `logged_days` 0, `adherent_days` 0 and
    `adherence_pct` `0.00`."
    PRD §3.8: "The first axis is an `age_band` derived from the source battery's
    `patient_age_years`: `YOUNG` when the child is under 4 years old, `SCHOOL` when
    the age is 4 through 7 inclusive, and `OLDER` from 8 years upward."

    Design: Corner/calculations/occlusion_dose_older_severe_is_capped_at_max_daily_hours
    """
    scn, prescription = setup_occlusion_scenario(
        severity="SEVERE", baseline_acuity_logmar=0.50
    )

    assert prescription["age_band"] == "OLDER"
    assert prescription["prescribed_daily_hours"] == 7
    assert prescription["current_daily_hours"] == 7
    assert prescription["status"] == "ACTIVE"
    assert prescription["taper_step_count"] == 0


def test_adherence_reads_zero_percent_before_any_day_is_logged(api):
    """PRD §3.8: "A `PatientUser` supplies two non-negative whole numbers,
    `logged_days_delta` and `adherent_days_delta`, which are added to `logged_days`
    and `adherent_days` respectively."
    PRD §3.8: "`adherence_pct` is then `adherent_days` divided by `logged_days`,
    multiplied by 100 and rounded half-up to two decimal places; when `logged_days` is
    0 the result is `0.00` rather than an error or a null."
    PRD §3.8: "An `OLDER` child is prescribed 3 hours when `MILD`, 5 when `MODERATE`
    and 8 when `SEVERE`."

    Design: Corner/calculations/occlusion_adherence_zero_denominator_yields_zero_percent
    """
    scn, prescription = setup_occlusion_scenario(
        severity="MILD", baseline_acuity_logmar=0.30
    )
    assert_pct(prescription["adherence_pct"], 0.00, "adherence_pct at creation")
    assert prescription["prescribed_daily_hours"] == 3

    data = validate_success(
        api.log_adherence(
            prescription["id"],
            {"logged_days_delta": 3, "adherent_days_delta": 2},
            scn["hdr_patient"],
        ),
        200,
    )

    assert data["logged_days"] == 3
    assert data["adherent_days"] == 2
    assert_pct(data["adherence_pct"], 66.67, "adherence_pct")


def test_the_taper_gate_refuses_a_prescription_below_the_adherence_threshold(api):
    """PRD §3.8: "Two conditions form a single gate. Adherence must be at least 70.0
    percent, and the acuity gain — the prescription's `baseline_acuity_logmar` less
    `current_acuity_logmar`, rounded half-up to two decimal places — must be at least
    0.20 logMAR. If either half fails, the taper is refused with
    `ERR_TAPER_GATE_NOT_MET`; both halves are reported through that one error."

    Design: Corner/errors/occlusion_taper_gate_blocks_low_adherence
    """
    scn, prescription = setup_occlusion_scenario(
        severity="MODERATE", baseline_acuity_logmar=0.40
    )
    adherence = log_adherence(scn, prescription["id"], 10, 5)
    assert_pct(adherence["adherence_pct"], 50.00, "adherence_pct")

    response = api.taper_occlusion(
        prescription["id"], {"current_acuity_logmar": 0.18}, scn["hdr_od1"]
    )

    validate_error(response, ApiErrorId.ERR_TAPER_GATE_NOT_MET.value, 422)
    stored = read_prescription(prescription["id"])
    assert stored["current_daily_hours"] == 5
    assert stored["taper_step_count"] == 0
    assert stored["status"] == "ACTIVE"
