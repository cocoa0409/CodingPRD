"""The pellet ladder conversion and the laboratory's two rulers."""

from test_helpers import (
    new_patient,
    new_physician,
    record_consult,
    record_lab_panel,
    assert_consult,
    assert_lab_panel,
)


def test_testosterone_prescription_of_1150mg_resolves_to_five_large_and_two_small(api):
    """PRD §3.3: "The server divides the prescribed dose by the large strength and rounds
    that quotient **down** to a whole number, giving `planned_large_count`. It then subtracts
    the milligrams those large pellets supply from the prescribed dose, leaving a remainder.
    If the remainder is exactly zero, `planned_small_count` is zero; otherwise
    `planned_small_count` is the remainder divided by the small strength and rounded **up**
    to a whole number."
    PRD §3.3: "A testosterone prescription of 1150 mg therefore resolves to five 200 mg
    pellets covering 1000 mg, a remainder of 150 mg, two 100 mg pellets, seven pellets in all
    and a `planned_total_mg` of 1200."

    Design: Difficulty/combinatorial_formula/pellet_ladder_greedy_ceiling_mode_a
    """
    physician = new_physician(api)
    patient = new_patient(api, "Pat Four", "p4@example.com")

    consult = record_consult(
        api, patient["id"], physician["id"], "TESTOSTERONE",
        prescribed_dose_mg=1150, symptom_score=60, indication="Fatigue",
    )

    assert consult["planned_large_count"] == 5
    assert consult["planned_small_count"] == 2
    assert consult["planned_pellet_count"] == 7
    assert consult["planned_total_mg"] == 1200
    assert_consult(consult)


def test_estradiol_prescriptions_round_the_remainder_up_and_skip_it_when_exact(api):
    """PRD §3.3: "An estradiol prescription of 80 mg resolves to three 25 mg pellets covering
    75 mg, a remainder of 5 mg, one 10 mg pellet, four pellets and a planned total of 85."
    PRD §3.3: "An estradiol prescription of exactly 100 mg resolves to four 25 mg pellets, a
    remainder of zero, no small pellets at all, four pellets and a planned total of 100."

    Design: Difficulty/combinatorial_formula/pellet_ladder_greedy_ceiling_mode_a
    """
    physician = new_physician(api)
    patient = new_patient(api, "Pat Four", "p4@example.com")

    eighty = record_consult(
        api, patient["id"], physician["id"], "ESTRADIOL",
        prescribed_dose_mg=80, symptom_score=60, indication="Vasomotor",
    )
    assert eighty["planned_large_count"] == 3
    assert eighty["planned_small_count"] == 1
    assert eighty["planned_pellet_count"] == 4
    assert eighty["planned_total_mg"] == 85

    exact_hundred = record_consult(
        api, patient["id"], physician["id"], "ESTRADIOL",
        prescribed_dose_mg=100, symptom_score=60, indication="Vasomotor",
    )
    assert exact_hundred["planned_large_count"] == 4
    assert exact_hundred["planned_small_count"] == 0, (
        "A remainder of exactly zero takes no small pellet at all"
    )
    assert exact_hundred["planned_pellet_count"] == 4
    assert exact_hundred["planned_total_mg"] == 100


def test_laboratory_normal_testosterone_still_reads_below_the_clinic_optimum(api):
    """PRD §3.3: "The first ruler is the standard laboratory reference interval, recorded in
    `lab_reference_band`: the value is `BELOW_REF` when it falls strictly below the analyte's
    reference low, `ABOVE_REF` when it rises strictly above the analyte's reference high, and
    `IN_REF` in every other case, which includes sitting exactly on either bound."
    PRD §3.3: "The reference lows and highs are 264 and 916 ng/dL for `TOTAL_TESTOSTERONE`,
    30 and 400 pg/mL for `ESTRADIOL`, and 38.0 and 50.0 percent for `HEMATOCRIT`."
    PRD §3.3: "A total testosterone of 400 ng/dL is `IN_REF` — the laboratory would call that
    patient normal — yet it is `BELOW_OPTIMAL`, which is precisely the condition the re-dose
    gate is looking for."

    Design: Difficulty/dual_variant_calc/lab_value_lab_normal_but_below_clinic_optimal
    """
    physician = new_physician(api)
    patient = new_patient(api, "Pat Three", "p3@example.com", date_of_birth="1975-01-01")

    panel = record_lab_panel(
        api, patient["id"], physician["id"], analyte="TOTAL_TESTOSTERONE",
        value=400, drawn_at="2026-05-01T00:00:00Z", is_trough_draw=True,
    )

    assert panel["lab_reference_band"] == "IN_REF"
    assert panel["clinic_optimal_band"] == "BELOW_OPTIMAL", (
        "The same measurement reads differently against the clinic's narrower ruler"
    )
    assert panel["critical_flag"] is False
    assert panel["status"] == "RECORDED"
    assert panel["unit"] == "ng/dL"
    assert_lab_panel(panel)


def test_critical_estradiol_reads_above_both_rulers_and_diverts_to_critical_flagged(api):
    """PRD §3.3: "The second ruler is the clinic's own, narrower therapeutic target, recorded
    in `clinic_optimal_band`: the value is `BELOW_OPTIMAL` when it falls strictly below the
    optimal low, `ABOVE_OPTIMAL` when it rises strictly above the optimal high, and
    `IN_OPTIMAL` in every other case including the bounds themselves."
    PRD §3.3: "Those optimal lows and highs are 600 and 900 ng/dL for `TOTAL_TESTOSTERONE`,
    80 and 200 pg/mL for `ESTRADIOL`, and 40.0 and 46.0 percent for `HEMATOCRIT`."
    PRD §3.3: "`critical_flag` is set true when the value rises **strictly above** the
    analyte's critical ceiling — 1500 ng/dL for `TOTAL_TESTOSTERONE`, 500 pg/mL for
    `ESTRADIOL`, 54.0 percent for `HEMATOCRIT` — and false otherwise. A panel's `status`
    starts at `RECORDED`, and a panel whose `critical_flag` is true is diverted
    `RECORDED → CRITICAL_FLAGGED` within the very request that creates it, so it is never
    observable at rest in `RECORDED`."

    Design: Difficulty/dual_variant_calc/lab_value_lab_normal_but_below_clinic_optimal
    """
    physician = new_physician(api)
    patient = new_patient(api, "Pat Three", "p3@example.com", date_of_birth="1975-01-01")

    panel = record_lab_panel(
        api, patient["id"], physician["id"], analyte="ESTRADIOL",
        value=950, drawn_at="2026-05-01T00:00:00Z", is_trough_draw=False,
    )

    assert panel["lab_reference_band"] == "ABOVE_REF"
    assert panel["clinic_optimal_band"] == "ABOVE_OPTIMAL"
    assert panel["critical_flag"] is True
    assert panel["status"] == "CRITICAL_FLAGGED", (
        "A critical value is diverted inside the request that records it"
    )
    assert panel["unit"] == "pg/mL"
    assert_lab_panel(panel)


def test_is_trough_draw_omitted_records_as_false(api):
    """PRD §3.3: "Laboratory results are recorded by a `Physician` or a `NurseInjector`, who
    supply the `patient_id`, the `ordered_by_provider_id` of whoever ordered the draw, an
    `analyte` of `TOTAL_TESTOSTERONE`, `ESTRADIOL` or `HEMATOCRIT`, the measured `value`, the
    instant `drawn_at` at which the specimen was taken, and an optional `is_trough_draw` flag
    that defaults to false."
    PRD §3.3: "The server derives the `unit` from the analyte — `ng/dL` for
    `TOTAL_TESTOSTERONE`, `pg/mL` for `ESTRADIOL`, `percent` for `HEMATOCRIT` — and stamps
    `resulted_at` from the logical clock."

    Design: Corner/entities/lab_panel_is_trough_draw_defaults_to_false
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner Four", "c4@example.com")

    panel = record_lab_panel(
        api, patient["id"], physician["id"], analyte="HEMATOCRIT",
        value=44.0, drawn_at="2026-05-01T00:00:00Z",
    )

    assert panel["is_trough_draw"] is False
    assert panel["unit"] == "percent"
    assert panel["lab_reference_band"] == "IN_REF"
    assert panel["clinic_optimal_band"] == "IN_OPTIMAL"
    assert panel["critical_flag"] is False
    assert panel["status"] == "RECORDED"
    assert_lab_panel(panel)
