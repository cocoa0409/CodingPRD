"""Consult intake, the two acuity variants and the priority-band boundary."""
from test_helpers import (
    as_instant,
    assert_band_matches_acuity,
    assert_consult_request,
    assert_one_decimal_place,
    assign_consult,
    create_candidate_nurse,
    create_certified_nurse,
    create_consult,
    create_patient,
    create_trainee_nurse,
    create_unit,
    get_success_data,
    read_patient_version,
    set_clock,
    triage_consult,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    make_director_headers,
    make_nurse_headers,
    make_unit_charge_headers,
)


DIRECTOR = make_director_headers()


def _ostomy_scenario(api):
    """Unit 7W, a certified nurse, an ostomy patient with two comorbidities and an
    `OSTOMY` consult whose ward-claimed stage is `STAGE_1`."""
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    nurse = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit,
        api=api,
        mrn="MRN-A01",
        admitted_at="2026-07-31T12:00:00Z",
        comorbidity_count=2,
        device_related_risk=False,
        ostomy_present=True,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="OSTOMY",
        reported_stage="STAGE_1",
        clinical_note="Peristomal skin breakdown, unit reports superficial redness.",
    )
    triage_consult(consult, nurse, api=api)
    assign_consult(consult, nurse, api=api)
    return unit, nurse, patient, consult


def test_intake_provisional_acuity_ignores_the_wound_area_entirely(api):
    """Triage scores the ward's claim alone, with the area term pinned to zero.

    PRD §3.4: "Under this variant the wound-area contribution is exactly 0, because
    the requesting unit supplies no measurement."
    PRD §3.4: "Those four contributions are summed and the sum is multiplied by a
    consult-type multiplier: 1.00 for a `WOUND` consult, 1.15 for an `OSTOMY`
    consult and 0.90 for an `INCONTINENCE` consult."
    PRD §3.4: "Triage sets `triaged_at` to the logical clock and derives
    `sla_due_at` as `triaged_at` plus the band's response allowance — 4 hours for
    `P1`, a full day for `P2`, and three days for `P3`."

    Design: Difficulty/dual_variant_calc/consult_acuity_provisional_vs_final_diverges
    """
    unit, nurse, _patient, consult = _ostomy_scenario(api)
    provisional = get_success_data(
        api.get_consult_request(consult["id"], make_nurse_headers(nurse["id"]))
    )
    assert provisional["acuity_score"] == 34.5, (
        "(STAGE_1 20 + min(25, 5 * 2) + 0 device + 0 area) * 1.15 = 34.5"
    )
    assert_one_decimal_place(provisional["acuity_score"])
    assert provisional["acuity_variant"] == "INTAKE_PROVISIONAL"
    assert provisional["priority_band"] == "P3", "34.5 sits below the 40.0 threshold"
    assert as_instant(provisional["triaged_at"]) == as_instant("2026-08-01T00:00:00Z")
    assert as_instant(provisional["sla_due_at"]) == as_instant("2026-08-04T00:00:00Z"), "three days for P3"
    assert_band_matches_acuity(provisional)
    assert_consult_request(provisional)
    assert unit["id"] == provisional["requesting_unit_id"]


def test_the_assessed_final_variant_moves_the_deadline_sixty_eight_hours_earlier(api):
    """The nurse's own staging plus a live area term flips P3 to P1 on one row.

    PRD §3.5: "The stage weight is read from the WOC nurse's own `observed_stage`
    rather than from the ward's `reported_stage`."
    PRD §3.5: "And the wound-area contribution is no longer zero: it awards 5 points
    for each whole 10 square centimetres of `measured_area_cm2`, discarding any
    remainder, capped at 15 points."
    PRD §3.5: "Because the two variants can differ substantially, the same wound
    routinely lands in a different `priority_band` after assessment than it did at
    triage, and `sla_due_at` is re-derived from the unchanged `triaged_at`
    accordingly."

    Design: Difficulty/dual_variant_calc/consult_acuity_provisional_vs_final_diverges
    """
    _unit, nurse, patient, consult = _ostomy_scenario(api)
    nurse_headers = make_nurse_headers(nurse["id"])
    before = get_success_data(api.get_consult_request(consult["id"], nurse_headers))
    assert before["acuity_score"] == 34.5
    assert as_instant(before["sla_due_at"]) == as_instant("2026-08-04T00:00:00Z")

    assessment = validate_success(
        api.create_skin_assessment(
            {
                "consult_request_id": consult["id"],
                "patient_id": patient["id"],
                "anatomic_location": "OTHER",
                "observed_stage": "STAGE_3",
                "measured_area_cm2": 24,
                "observed_at": "2026-08-01T00:00:00Z",
                "expected_patient_version": read_patient_version(patient["id"], api=api),
            },
            nurse_headers,
        ),
        expected_status=201,
    )
    assert assessment["staged_by_nurse_id"] == nurse["id"]
    assert assessment["validation_status"] == "PENDING_VALIDATION"

    after = get_success_data(api.get_consult_request(consult["id"], nurse_headers))
    assert after["acuity_score"] == 92.0, (
        "(STAGE_3 60 + min(25, 5 * 2) + 0 + min(15, floor(24 / 10) * 5)) * 1.15 = 92.0"
    )
    assert after["priority_band"] == "P1"
    assert after["acuity_variant"] == "ASSESSED_FINAL"
    assert as_instant(after["sla_due_at"]) == as_instant("2026-08-01T04:00:00Z"), "four hours from the same triaged_at"
    assert after["status"] == "ASSESSED"
    assert round(after["acuity_score"] - before["acuity_score"], 1) == 57.5
    assert after["sla_due_at"] < before["sla_due_at"], (
        "the deadline moves 68 hours earlier, not later"
    )


def _wound_stage3_consult(api, comorbidity_count, mrn, note):
    """A `WOUND` consult claiming `STAGE_3` on a patient with the given comorbidities."""
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    nurse = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit,
        api=api,
        mrn=mrn,
        admitted_at="2026-07-30T00:00:00Z",
        comorbidity_count=comorbidity_count,
        device_related_risk=False,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_3",
        clinical_note=note,
    )
    return unit, nurse, patient, consult


def test_an_acuity_of_exactly_seventy_lands_in_p1(api):
    """The band comparison is inclusive, so 70.0 itself is the top band.

    PRD §3.4: "The resulting `acuity_score` selects the `priority_band`: `P1` when
    the score is 70.0 or higher, otherwise `P2` when it is 40.0 or higher, otherwise
    `P3`."
    PRD §3.4: "To that is added a comorbidity contribution of 5 points for each of
    the patient's `comorbidity_count`, capped at 25 points, so a patient with 5 or
    more comorbidities contributes the same 25."

    Design: Difficulty/boundary_precision_check/acuity_exactly_seventy_maps_to_p1
    """
    _unit, nurse, _patient, consult = _wound_stage3_consult(
        api, 2, "MRN-T2", "Full thickness sacral loss, two comorbidities."
    )
    data = validate_success(
        api.triage_consult_request(consult["id"], make_nurse_headers(nurse["id"]))
    )
    assert data["acuity_score"] == 70.0, "(STAGE_3 60 + min(25, 5 * 2)) * 1.00 = 70.0"
    assert_one_decimal_place(data["acuity_score"])
    assert data["priority_band"] == "P1", "the comparison is score >= 70.0, not score > 70.0"
    assert as_instant(data["sla_due_at"]) == as_instant("2026-08-01T04:00:00Z"), "four hours for P1"
    assert as_instant(data["triaged_at"]) == as_instant("2026-08-01T00:00:00Z")
    assert data["acuity_variant"] == "INTAKE_PROVISIONAL"
    assert data["status"] == "TRIAGED"


def test_five_acuity_points_below_the_boundary_costs_twenty_hours(api):
    """One comorbidity fewer scores 65.0, drops to P2 and buys a full day.

    PRD §3.4: "The resulting `acuity_score` selects the `priority_band`: `P1` when
    the score is 70.0 or higher, otherwise `P2` when it is 40.0 or higher, otherwise
    `P3`."
    PRD §3.4: "Triage sets `triaged_at` to the logical clock and derives
    `sla_due_at` as `triaged_at` plus the band's response allowance — 4 hours for
    `P1`, a full day for `P2`, and three days for `P3`."

    Design: Difficulty/boundary_precision_check/acuity_exactly_seventy_maps_to_p1
    """
    unit, nurse, _patient_lo, consult_lo = _wound_stage3_consult(
        api, 1, "MRN-T1", "Full thickness sacral loss, one comorbidity."
    )
    nurse_headers = make_nurse_headers(nurse["id"])
    low = validate_success(api.triage_consult_request(consult_lo["id"], nurse_headers))
    assert low["acuity_score"] == 65.0, "(STAGE_3 60 + min(25, 5 * 1)) * 1.00 = 65.0"
    assert low["priority_band"] == "P2"
    assert as_instant(low["sla_due_at"]) == as_instant("2026-08-02T00:00:00Z"), "a full day for P2"
    assert low["acuity_variant"] == "INTAKE_PROVISIONAL"

    patient_hi = create_patient(
        unit,
        api=api,
        mrn="MRN-T2",
        admitted_at="2026-07-30T00:00:00Z",
        comorbidity_count=2,
        device_related_risk=False,
    )
    consult_hi = create_consult(
        unit,
        patient_hi,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_3",
        clinical_note="Full thickness sacral loss, two comorbidities.",
    )
    high = validate_success(api.triage_consult_request(consult_hi["id"], nurse_headers))
    assert high["acuity_score"] == 70.0
    assert high["priority_band"] == "P1"
    assert as_instant(high["sla_due_at"]) == as_instant("2026-08-01T04:00:00Z")
    assert round(high["acuity_score"] - low["acuity_score"], 1) == 5.0
    assert high["triaged_at"] == low["triaged_at"], "both were triaged at the same instant"
    assert high["sla_due_at"] < low["sla_due_at"], (
        "5.0 acuity points move the deadline 20 hours earlier"
    )


def test_the_comorbidity_cap_the_device_bonus_and_the_type_multiplier_all_bite(api):
    """Eight comorbidities still contribute 25, and 0.90 scales the whole sum down.

    PRD §3.4: "To that is added a comorbidity contribution of 5 points for each of
    the patient's `comorbidity_count`, capped at 25 points, so a patient with 5 or
    more comorbidities contributes the same 25."
    PRD §3.4: "A further 10 points are added when the patient's
    `device_related_risk` is true, and nothing when it is false."
    PRD §3.4: "Those four contributions are summed and the sum is multiplied by a
    consult-type multiplier: 1.00 for a `WOUND` consult, 1.15 for an `OSTOMY`
    consult and 0.90 for an `INCONTINENCE` consult."

    Design: Corner/calculations/acuity_type_multiplier_and_comorbidity_cap_applied
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nurse = create_trainee_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit,
        api=api,
        mrn="MRN-J1",
        admitted_at="2026-07-31T00:00:00Z",
        comorbidity_count=8,
        device_related_risk=True,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="INCONTINENCE",
        reported_stage="STAGE_3",
        clinical_note="Deep IAD with a rectal tube in place.",
    )
    data = validate_success(
        api.triage_consult_request(consult["id"], make_nurse_headers(nurse["id"]))
    )
    assert data["acuity_score"] == 85.5, (
        "(60 + min(25, 5 * 8) + 10 + 0) = 95, times 0.90 = 85.5; the uncapped "
        "comorbidity term would have produced 99.0 instead"
    )
    assert data["acuity_variant"] == "INTAKE_PROVISIONAL"
    assert data["priority_band"] == "P1"
    assert as_instant(data["triaged_at"]) == as_instant("2026-08-01T00:00:00Z")
    assert as_instant(data["sla_due_at"]) == as_instant("2026-08-01T04:00:00Z")
    assert data["status"] == "TRIAGED"
    assert data["version"] == 2


def test_acuity_rounds_half_up_at_the_first_decimal(api):
    """17.25 must round up to 17.3, not to 17.2.

    PRD §3.4: "The product is then rounded half up to one decimal place, and only
    after that rounding is the result capped at 100 — rounding first and capping
    second is mandatory, and doing it the other way round is a defect."
    PRD §2.8: "Four precision rules govern the calculations described in §3, and
    each names both a scale and a rounding method. Consult acuity is carried to
    **1 decimal place**, rounded half up."

    Design: Corner/calculations/acuity_round_half_up_at_one_decimal_boundary
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nurse = create_trainee_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit,
        api=api,
        mrn="MRN-J2",
        admitted_at="2026-07-31T00:00:00Z",
        ostomy_present=True,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="OSTOMY",
        reported_stage="MUCOSAL",
        clinical_note="Mucocutaneous separation, no peristomal breakdown.",
    )
    data = validate_success(
        api.triage_consult_request(consult["id"], make_nurse_headers(nurse["id"]))
    )
    assert data["acuity_score"] == 17.3, (
        "MUCOSAL 15 * 1.15 = 17.25, and half-up rounding to one decimal gives 17.3; "
        "half-even rounding and truncation would both give 17.2"
    )
    assert_one_decimal_place(data["acuity_score"])
    assert data["priority_band"] == "P3", "17.3 is below the 40.0 threshold"
    assert as_instant(data["sla_due_at"]) == as_instant("2026-08-04T00:00:00Z")
    assert data["acuity_variant"] == "INTAKE_PROVISIONAL"


def test_acuity_is_capped_at_one_hundred_after_rounding(api):
    """A raw 132.25 rounds to 132.3 and only then is clamped to 100.0.

    PRD §3.4: "The product is then rounded half up to one decimal place, and only
    after that rounding is the result capped at 100 — rounding first and capping
    second is mandatory, and doing it the other way round is a defect."
    PRD §3.4: "The resulting `acuity_score` selects the `priority_band`: `P1` when
    the score is 70.0 or higher, otherwise `P2` when it is 40.0 or higher, otherwise
    `P3`."

    Design: Corner/calculations/acuity_clamped_to_acuity_max_when_raw_exceeds_one_hundred
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nurse = create_trainee_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit,
        api=api,
        mrn="MRN-J3",
        admitted_at="2026-07-31T00:00:00Z",
        comorbidity_count=6,
        device_related_risk=True,
        ostomy_present=True,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="OSTOMY",
        reported_stage="STAGE_4",
        clinical_note="Full-thickness peristomal ulceration with exposed fascia.",
    )
    data = validate_success(
        api.triage_consult_request(consult["id"], make_nurse_headers(nurse["id"]))
    )
    assert data["acuity_score"] == 100.0, (
        "(80 + min(25, 5 * 6) + 10 + 0) = 115, times 1.15 = 132.25, rounded to "
        "132.3 and then capped at 100.0"
    )
    assert_one_decimal_place(data["acuity_score"])
    assert data["priority_band"] == "P1"
    assert as_instant(data["sla_due_at"]) == as_instant("2026-08-01T04:00:00Z")


def test_the_endpoint_not_the_payload_chooses_the_acuity_variant(api):
    """Triage runs the provisional variant; the first filing runs the final one.

    PRD §3.4: "It computes the **intake-provisional acuity**, the first of the two
    acuity variants this service maintains, and records `acuity_variant` as
    `INTAKE_PROVISIONAL`."
    PRD §3.5: "Filing an assessment recomputes the consult's `acuity_score` under
    the second variant, setting `acuity_variant` to `ASSESSED_FINAL`."
    PRD §3.5: "So a wound of 9.9 square centimetres earns nothing, 10.0 earns 5,
    29.9 earns 10, and anything from 30.0 upward earns the full 15."

    Design: Corner/calculations/acuity_variant_switches_from_intake_provisional_to_assessed_final
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nurse = create_candidate_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    nurse_headers = make_nurse_headers(nurse["id"])
    patient = create_patient(unit, api=api, mrn="MRN-J4", admitted_at="2026-07-31T00:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_1",
        clinical_note="Non-blanchable erythema reported by the charge nurse.",
    )
    triaged = triage_consult(consult, nurse, api=api)
    assert triaged["acuity_variant"] == "INTAKE_PROVISIONAL"
    assert triaged["acuity_score"] == 20.0, "STAGE_1 20 * 1.00 with the area term forced to 0"
    assert triaged["priority_band"] == "P3"
    assert as_instant(triaged["sla_due_at"]) == as_instant("2026-08-04T00:00:00Z")
    assign_consult(consult, nurse, api=api)

    validate_success(
        api.create_skin_assessment(
            {
                "consult_request_id": consult["id"],
                "patient_id": patient["id"],
                "anatomic_location": "SACRUM",
                "observed_stage": "STAGE_4",
                "measured_area_cm2": 30,
                "observed_at": "2026-08-01T00:00:00Z",
                "expected_patient_version": read_patient_version(patient["id"], api=api),
            },
            nurse_headers,
        ),
        expected_status=201,
    )
    assert get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))["certification_status"] == (
        "CANDIDATE"
    )
    assert get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))["max_consult_load"] == 3

    after = get_success_data(api.get_consult_request(consult["id"], nurse_headers))
    assert after["acuity_variant"] == "ASSESSED_FINAL"
    assert after["acuity_score"] == 95.0, (
        "STAGE_4 80 + min(15, floor(30 / 10) * 5) = 15, all times 1.00; re-running "
        "the provisional variant would have produced 80.0"
    )
    assert after["priority_band"] == "P1"
    assert after["status"] == "ASSESSED"


def test_the_recomputed_deadline_re_anchors_on_the_original_triage_instant(api):
    """A day passes between triage and staging; the new SLA still counts from triage.

    PRD §3.4: "Whenever `priority_band` later changes, `sla_due_at` is re-derived
    from the same `triaged_at` with the new band's allowance; `triaged_at` itself is
    not moved by a recompute."
    PRD §3.5: "Because the two variants can differ substantially, the same wound
    routinely lands in a different `priority_band` after assessment than it did at
    triage, and `sla_due_at` is re-derived from the unchanged `triaged_at`
    accordingly."

    Design: Corner/calculations/acuity_variant_switch_reanchors_sla_on_original_triaged_at
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nurse = create_candidate_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    nurse_headers = make_nurse_headers(nurse["id"])
    patient = create_patient(unit, api=api, mrn="MRN-J5", admitted_at="2026-07-31T00:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_1",
        clinical_note="Blanchable redness reported overnight.",
    )
    triaged = triage_consult(consult, nurse, api=api)
    assert triaged["acuity_score"] == 20.0
    assert triaged["priority_band"] == "P3"
    assert as_instant(triaged["triaged_at"]) == as_instant("2026-08-01T00:00:00Z")
    assert as_instant(triaged["sla_due_at"]) == as_instant("2026-08-04T00:00:00Z")
    assign_consult(consult, nurse, api=api)
    set_clock("2026-08-02T00:00:00Z", api=api)

    validate_success(
        api.create_skin_assessment(
            {
                "consult_request_id": consult["id"],
                "patient_id": patient["id"],
                "anatomic_location": "SACRUM",
                "observed_stage": "STAGE_3",
                "measured_area_cm2": 12,
                "observed_at": "2026-08-02T00:00:00Z",
                "expected_patient_version": read_patient_version(patient["id"], api=api),
            },
            nurse_headers,
        ),
        expected_status=201,
    )
    after = get_success_data(api.get_consult_request(consult["id"], nurse_headers))
    assert after["acuity_score"] == 65.0, "60 + min(15, floor(12 / 10) * 5) = 5, times 1.00"
    assert after["priority_band"] == "P2"
    assert as_instant(after["triaged_at"]) == as_instant("2026-08-01T00:00:00Z"), "staging must not restamp triaged_at"
    assert as_instant(after["sla_due_at"]) == as_instant("2026-08-02T00:00:00Z"), "triaged_at plus the P2 allowance"
    assert as_instant(after["sla_due_at"]) != as_instant("2026-08-03T00:00:00Z"), (
        "anchoring on the current clock instead of triaged_at is a defect"
    )
    assert after["acuity_variant"] == "ASSESSED_FINAL"
    assert after["status"] == "ASSESSED"


def test_a_new_consult_carries_no_scoring_at_all(api):
    """Every scoring field is null on a `REQUESTED` row even though the inputs exist.

    PRD §3.4: "A new consult starts with `status` `REQUESTED`, `revision_count` 0,
    `escalation_count` 0 and `protocol_hold` false; `acuity_score`,
    `acuity_variant`, `priority_band`, `triaged_at`, `sla_due_at`,
    `assigned_nurse_id` and `closing_summary` are all null."

    Design: Corner/state_machines/consult_request_initial_state_is_requested_with_null_scoring
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    patient = create_patient(
        unit,
        api=api,
        mrn="MRN-G2",
        admitted_at="2026-07-31T00:00:00Z",
        comorbidity_count=4,
        device_related_risk=True,
    )
    data = validate_success(
        api.create_consult_request(
            {
                "patient_id": patient["id"],
                "requesting_unit_id": unit["id"],
                "consult_type": "INCONTINENCE",
                "reported_stage": "STAGE_2",
                "clinical_note": "IAD over the buttocks.",
            },
            make_unit_charge_headers(unit["id"]),
        ),
        expected_status=201,
    )
    assert data["status"] == "REQUESTED"
    assert data["acuity_score"] is None
    assert data["acuity_variant"] is None
    assert data["priority_band"] is None
    assert data["triaged_at"] is None
    assert data["sla_due_at"] is None
    assert data["assigned_nurse_id"] is None
    assert data["revision_count"] == 0
    assert data["escalation_count"] == 0
    assert data["protocol_hold"] is False
    assert data["closing_summary"] is None
    assert data["version"] == 1


def test_a_reported_stage_outside_the_vocabulary_is_refused(api):
    """`reported_stage` is a closed set and an unknown member never reaches triage.

    PRD §3.4: "The `reported_stage` is what the requesting unit *claims* to be
    seeing and is drawn from a wider vocabulary than a WOC nurse's own staging,
    because a bedside unit is allowed to say there is nothing to stage: it takes one
    of `NONE`, `MUCOSAL`, `STAGE_1`, `STAGE_2`, `STAGE_3`, `STAGE_4`, `DTI` or
    `UNSTAGEABLE`."
    PRD §2.10 rung 3: "Request-body and query-string schema conformance: every
    required field present, every type correct, every enum member legal, every
    numeric range and string length honored, `limit` within 1 through 100 and
    `offset` at least 0 — `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/consult_request_invalid_reported_stage_enum_rejected
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    charge = make_unit_charge_headers(unit["id"])
    patient = create_patient(unit, api=api, mrn="MRN-E1", admitted_at="2026-07-31T00:00:00Z")
    validate_error(
        api.create_consult_request(
            {
                "patient_id": patient["id"],
                "requesting_unit_id": unit["id"],
                "consult_type": "WOUND",
                "reported_stage": "STAGE_9",
                "clinical_note": "Unstageable per bedside RN.",
            },
            charge,
        ),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )
    _, meta = validate_paginated(
        api.list_consult_requests(charge, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0

    validate_error(
        api.create_consult_request(
            {
                "patient_id": patient["id"],
                "requesting_unit_id": unit["id"],
                "consult_type": "PRESSURE",
                "reported_stage": "STAGE_2",
                "clinical_note": "Unstageable per bedside RN.",
            },
            charge,
        ),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )


def test_a_consult_raised_by_the_wrong_ward_is_a_link_mismatch(api):
    """Both ids resolve, so only the field-agreement rule can catch this.

    PRD §3.4: "The `requesting_unit_id` must be the unit the patient is actually on,
    and a mismatch is an `ERR_ENTITY_LINK_MISMATCH`."
    PRD §2.10 rung 6: "Cross-entity field agreement as enumerated in §2.5 —
    `ERR_ENTITY_LINK_MISMATCH` (422), on `POST /consult-requests`,
    `POST /skin-assessments`, `POST /support-surface-orders`,
    `POST /survey-observations` and `POST /ostomy-education-plans`."

    Design: Corner/entities/consult_request_requesting_unit_mismatch_rejected
    """
    home = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    other = create_unit(
        api,
        unit_code="4W",
        name="Four West",
        bed_count=12,
        rental_budget_cap_cents=250000,
    )
    patient = create_patient(home, api=api, mrn="MRN-M9", admitted_at="2026-07-31T00:00:00Z")
    payload = {
        "patient_id": patient["id"],
        "requesting_unit_id": other["id"],
        "consult_type": "WOUND",
        "reported_stage": "STAGE_2",
        "clinical_note": "Filed by the wrong unit's charge nurse.",
    }
    validate_error(
        api.create_consult_request(payload, make_unit_charge_headers(other["id"])),
        "ERR_ENTITY_LINK_MISMATCH",
        expected_status=422,
    )
    _, meta = validate_paginated(
        api.list_consult_requests(DIRECTOR, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "the refused consult inserted no row"

    validate_success(
        api.create_consult_request(
            dict(payload, requesting_unit_id=home["id"]),
            make_unit_charge_headers(home["id"]),
        ),
        expected_status=201,
    )


def test_the_consult_listing_counts_the_whole_filtered_set(api):
    """Three consults over a page size of two: the count stays 3 and `has_more` flips.

    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as
    they were resolved for that request, `total_count` as the number of rows matching
    the supplied filters before pagination is applied, and `has_more` as a boolean
    that is true exactly when `offset` plus the number of returned rows is less than
    `total_count`."

    Design: Corner/entities/consult_request_list_paginates_with_total_count_and_has_more
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    notes = ("Sacral erythema.", "Heel erythema.", "Coccyx erythema.")
    expected_ids = set()
    for index, note in enumerate(notes, start=1):
        patient = create_patient(
            unit, api=api, mrn=f"MRN-L{index}", admitted_at="2026-07-31T00:00:00Z"
        )
        consult = create_consult(
            unit,
            patient,
            api=api,
            consult_type="WOUND",
            reported_stage="STAGE_1",
            clinical_note=note,
        )
        expected_ids.add(consult["id"])

    response = api.list_consult_requests(
        DIRECTOR, {"requesting_unit_id": unit["id"], "limit": 2, "offset": 0}
    )
    page1, meta1 = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_consult_requests(
            DIRECTOR, {"requesting_unit_id": unit["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["limit"] == 2
    assert meta2["offset"] == 2
    assert page1[0]["id"] != page2[0]["id"], "the two pages are disjoint"
    assert {row["id"] for row in page1} | {page2[0]["id"]} == expected_ids
