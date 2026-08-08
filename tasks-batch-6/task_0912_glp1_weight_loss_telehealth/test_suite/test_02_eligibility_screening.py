"""Eligibility screening: the decision ladder, the re-screen loop and the two
readings of body-mass index."""

from test_helpers import (
    assert_screening,
    book_consult,
    close_consult,
    create_prescription_payload,
    enroll_patient,
    make_provider_headers,
    open_screening,
    platform_admin_headers,
    read_patient,
    register_clinician,
    set_clock,
    submit_screening,
    validate_success,
)


def test_screening_defers_on_stale_labs_then_requalifies_on_fresh_labs(api):
    """PRD §3.2: "A newly opened screening sits in `DRAFT` with `assessed_bmi`,
    `eligibility_band` and `decision_reason` all null, `submitted_at` null,
    `submit_count` at zero and `comorbidity_count` at zero."
    PRD §3.2: "If that age is 90 days or more, the screening lands in `DEFERRED`
    with `decision_reason` set to `STALE_LABS`. On this branch `assessed_bmi` and
    `eligibility_band` are both left null — no clinical reading is produced from
    evidence too old to trust — while `submitted_at` and `submit_count` are still
    updated."
    PRD §3.2: "If the resubmission supplies fresh labs and the renal and band
    tests pass, the screening advances `DEFERRED → ELIGIBLE`, freezing
    `assessed_bmi` and `eligibility_band` exactly as the first-time path does and
    incrementing `submit_count`."

    Design: Corner/state_machines/screening_starts_in_draft_and_defers_on_stale_labs_then_requalifies
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(email="sm1@example.com", full_name="Sm One", weight_kg=95.0)
    clinician = register_clinician()

    draft = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=95.0,
        egfr=88.0,
        lab_collected_at="2026-01-01T00:00:00Z",
    )
    assert draft["status"] == "DRAFT"
    assert draft["submit_count"] == 0

    deferred = validate_success(
        api.submit_screening(draft["id"], {}, make_provider_headers(clinician["id"]))
    )
    assert_screening(deferred)
    assert deferred["status"] == "DEFERRED"
    assert deferred["decision_reason"] == "STALE_LABS"
    assert deferred["assessed_bmi"] is None
    assert deferred["eligibility_band"] is None
    assert deferred["submit_count"] == 1
    assert read_patient(member["id"])["eligibility_status"] == "DEFERRED"

    requalified = validate_success(
        api.submit_screening(
            draft["id"],
            {
                "recorded_weight_kg": 95.0,
                "egfr": 88.0,
                "lab_collected_at": "2026-05-25T00:00:00Z",
            },
            make_provider_headers(clinician["id"]),
        )
    )
    assert requalified["status"] == "ELIGIBLE"
    assert requalified["decision_reason"] == "BMI_QUALIFIED"
    assert requalified["assessed_bmi"] == 32.9
    assert requalified["submit_count"] == 2
    assert read_patient(member["id"])["eligibility_status"] == "ELIGIBLE"


def test_renal_exclusion_pre_empts_a_qualifying_body_mass_index(api):
    """PRD §3.2: "**Renal exclusion.** Otherwise, if `egfr` is below 30.0, the
    screening lands in `INELIGIBLE` with `decision_reason` set to
    `RENAL_EXCLUSION`. Because this clause is evaluated *before* the body-mass
    tests, a member who fails both the renal panel and the weight bands reports
    `RENAL_EXCLUSION`, never `BMI_BELOW_BAND`."
    PRD §3.2: "On both `INELIGIBLE` branches — renal exclusion and below-band
    alike — `eligibility_band` is written as `NONE`."

    Design: Corner/calculations/renal_exclusion_evaluated_before_bmi_band
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(
        email="cal1@example.com",
        full_name="Cal One",
        weight_kg=95.0,
        comorbidity_codes=["TYPE_2_DIABETES"],
    )
    clinician = register_clinician()
    screening = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=95.0,
        egfr=25.0,
        a1c_pct=7.4,
        lab_collected_at="2026-05-20T00:00:00Z",
    )

    decided = validate_success(
        api.submit_screening(screening["id"], {}, make_provider_headers(clinician["id"]))
    )

    assert decided["assessed_bmi"] == 32.9
    assert decided["status"] == "INELIGIBLE"
    assert decided["decision_reason"] == "RENAL_EXCLUSION"
    assert decided["eligibility_band"] == "NONE"
    assert read_patient(member["id"])["eligibility_status"] == "INELIGIBLE"


def test_body_mass_index_of_exactly_twenty_seven_qualifies_with_one_comorbidity(api):
    """PRD §3.2: "**Comorbid band.** Otherwise, if the frozen `assessed_bmi` is at
    least 27.0 *and* `comorbidity_count` is at least 1, the screening lands in
    `ELIGIBLE` with `eligibility_band` set to `COMORBID` and `decision_reason` set
    to `COMORBID_QUALIFIED`."
    PRD §2.9: "Body-mass index is the one non-monetary quantity that carries a
    rounding rule: it is rounded to exactly one decimal place, again half-up, and
    every threshold comparison is made against the *rounded* value rather than the
    raw quotient."
    PRD §3.2: "It also counts the entries currently in the member's
    `comorbidity_codes` and writes that count into `comorbidity_count`, sets
    `submitted_at` to the clock, and increments `submit_count` by one."

    Design: Difficulty/boundary_precision_check/bmi_exactly_twenty_seven_with_one_comorbidity_qualifies
    """
    set_clock("2026-06-01T00:00:00Z")
    clinician = register_clinician()
    member = enroll_patient(
        email="rae@example.com",
        full_name="Rae Idris",
        weight_kg=78.03,
        comorbidity_codes=["TYPE_2_DIABETES"],
    )
    screening = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=78.03,
        egfr=88.0,
        lab_collected_at="2026-05-20T00:00:00Z",
    )

    decided = validate_success(
        api.submit_screening(screening["id"], {}, make_provider_headers(clinician["id"]))
    )

    assert decided["assessed_bmi"] == 27.0, (
        f"78.03 kg at 170 cm rounds to exactly 27.0, got {decided['assessed_bmi']}"
    )
    assert decided["comorbidity_count"] == 1
    assert decided["status"] == "ELIGIBLE"
    assert decided["eligibility_band"] == "COMORBID"
    assert decided["decision_reason"] == "COMORBID_QUALIFIED"
    assert read_patient(member["id"])["eligibility_status"] == "ELIGIBLE"


def test_body_mass_index_of_exactly_twenty_seven_fails_without_a_comorbidity(api):
    """PRD §3.2: "**Below band.** Otherwise the screening lands in `INELIGIBLE`
    with `decision_reason` set to `BMI_BELOW_BAND`."
    PRD §3.2: "On both `INELIGIBLE` branches — renal exclusion and below-band
    alike — `eligibility_band` is written as `NONE`."
    PRD §3.1: "An optional `comorbidity_codes` array may be supplied; when omitted
    it defaults to the empty list."

    Design: Difficulty/boundary_precision_check/bmi_exactly_twenty_seven_with_one_comorbidity_qualifies
    """
    set_clock("2026-06-01T00:00:00Z")
    clinician = register_clinician()
    member = enroll_patient(
        email="sol@example.com",
        full_name="Sol Vera",
        weight_kg=78.03,
        comorbidity_codes=[],
    )
    screening = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=78.03,
        egfr=88.0,
        lab_collected_at="2026-05-20T00:00:00Z",
    )

    decided = validate_success(
        api.submit_screening(screening["id"], {}, make_provider_headers(clinician["id"]))
    )

    assert decided["assessed_bmi"] == 27.0
    assert decided["comorbidity_count"] == 0
    assert decided["status"] == "INELIGIBLE"
    assert decided["eligibility_band"] == "NONE"
    assert decided["decision_reason"] == "BMI_BELOW_BAND"
    assert read_patient(member["id"])["eligibility_status"] == "INELIGIBLE"


def test_screening_freezes_body_mass_index_while_the_live_reading_drifts(api):
    """PRD §3.2: "The service then freezes a body-mass index into `assessed_bmi`
    using the **screening-snapshot** reading: the same centimetres-to-metres
    conversion, square, divide and round-half-up-to-one-decimal-place arithmetic
    as §3.1, but computed from `recorded_weight_kg` and `recorded_height_cm`
    rather than from the live chart. Once frozen it is never recomputed by a later
    weigh-in."
    PRD §3.1: "This is the **current-recheck** reading of body-mass index: it
    always reads the member's live `height_cm` and `weight_kg`, so it drifts as the
    member's weight changes."
    PRD §3.2: "**Obesity band.** Otherwise, if the frozen `assessed_bmi` is at
    least 30.0, the screening lands in `ELIGIBLE` with `eligibility_band` set to
    `OBESITY` and `decision_reason` set to `BMI_QUALIFIED`."

    Design: Difficulty/dual_variant_calc/frozen_screening_bmi_versus_live_patient_bmi
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(
        email="ava@example.com", full_name="Ava Reed", weight_kg=86.7, payment_mode="CASH"
    )
    clinician = register_clinician(full_name="Dr Nia Cole")
    screening = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=86.7,
        egfr=92.0,
        lab_collected_at="2026-05-20T00:00:00Z",
    )
    screening = submit_screening(screening["id"], clinician["id"])

    api.update_patient_vitals(
        member["id"], {"weight_kg": 77.0}, make_provider_headers(clinician["id"])
    )

    frozen = validate_success(
        api.get_screening(screening["id"], platform_admin_headers())
    )
    live = read_patient(member["id"])

    assert frozen["assessed_bmi"] == 30.0
    assert frozen["eligibility_band"] == "OBESITY"
    assert frozen["decision_reason"] == "BMI_QUALIFIED"
    assert live["current_bmi"] == 26.6, (
        f"77.0 kg at 170 cm rounds to 26.6, got {live['current_bmi']}"
    )
    assert live["eligibility_status"] == "ELIGIBLE"


def test_prescription_gate_reads_the_frozen_band_not_the_live_reading(api):
    """PRD §3.4: "The eligibility gate reads the *frozen* screening, never the
    live chart."
    PRD §3.4: "This is the reason §3.1 insists that `current_bmi` gates nothing: a
    member who has since lost enough weight to drop below 27.0 still holds a valid
    frozen band and may still be prescribed."
    PRD §3.4: "Its `dose_level` is 1 and its `dose_mg` is rung 1 of the ladder for
    the chosen `drug_family`, taken from the table in §3.5."

    Design: Difficulty/dual_variant_calc/frozen_screening_bmi_versus_live_patient_bmi
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(
        email="ava2@example.com", full_name="Ava Reed", weight_kg=86.7, payment_mode="CASH"
    )
    clinician = register_clinician()
    screening = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=86.7,
        egfr=92.0,
        lab_collected_at="2026-05-20T00:00:00Z",
    )
    screening = submit_screening(screening["id"], clinician["id"])
    consult = book_consult(member["id"], clinician["id"])
    close_consult(consult["id"], clinician["id"], "PRESCRIBE")
    api.update_patient_vitals(
        member["id"], {"weight_kg": 77.0}, make_provider_headers(clinician["id"])
    )

    live = read_patient(member["id"])
    assert live["current_bmi"] == 26.6

    response = api.create_prescription(
        create_prescription_payload(
            member["id"],
            consult["id"],
            clinician["id"],
            screening["id"],
            live["version"],
            drug_family="SEMAGLUTIDE",
            units_per_cycle=2,
        ),
        make_provider_headers(clinician["id"]),
    )
    prescription = validate_success(response, 201)

    assert prescription["screening_id"] == screening["id"]
    assert prescription["dose_level"] == 1
    assert prescription["dose_mg"] == 0.25


def test_member_version_advances_on_vitals_and_on_the_screening_decision(api):
    """PRD §2.5: "`version` (integer): a counter that begins at 1 and increments by
    1 on every mutation of the row."
    PRD §3.2: "Every submission mirrors its outcome onto the member:
    `eligibility_status` on the Patient row is set to `ELIGIBLE`, `INELIGIBLE` or
    `DEFERRED` to match, and the member's `version` is incremented by one."
    PRD §3.2: "At the moment the screening row is created the service snapshots
    the member's `height_cm` into `recorded_height_cm`; that snapshot never moves
    again, no matter what later weigh-ins do to the chart."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_patient_mutation
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(email="occ3@example.com", full_name="Occ Three", weight_kg=95.0)
    assert member["version"] == 1
    clinician = register_clinician()
    screening = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=95.0,
        egfr=88.0,
        lab_collected_at="2026-05-20T00:00:00Z",
    )

    after_vitals = validate_success(
        api.update_patient_vitals(
            member["id"], {"weight_kg": 93.0}, make_provider_headers(clinician["id"])
        )
    )
    assert after_vitals["version"] == 2
    assert after_vitals["current_bmi"] == 32.2

    decided = submit_screening(screening["id"], clinician["id"])
    after_decision = read_patient(member["id"])

    assert after_decision["version"] == 3
    assert after_decision["eligibility_status"] == "ELIGIBLE"
    assert decided["assessed_bmi"] == 32.9, (
        "the screening freezes its own recorded weight, not the later weigh-in"
    )
