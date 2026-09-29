"""Two numbers for the same facts: provisional versus final claim pricing, and
adenoma detection rates that differ by attribution basis."""
from test_helpers import (
    assert_claim_money_identity,
    claim_for_booking,
    complete_exam,
    confirm_prep,
    check_in,
    create_block,
    apply_block_action,
    finalize_report,
    lock_quality_period,
    move_clock,
    open_episode,
    open_quality_period,
    read_booking,
    read_claim,
    receive_report,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    specimen,
    staff_block,
    start_exam,
    book_slot,
)

PLAN_P1 = {
    "plan_code": "P1",
    "payer_name": "Meridian Health",
    "preventive_coverage_pct": 1.00,
    "diagnostic_coinsurance_pct": 0.20,
    "deductible_cents": 150000,
    "out_of_pocket_max_cents": 400000,
    "polypectomy_carveout": "DIAGNOSTIC_CONVERTED",
    "anesthesia_bundled": False,
}


def _mac_colonoscopy_with_two_adenomas():
    """Book a 45-minute MAC colonoscopy, capture the provisional claim, then run the
    exam to completion and finalize a two-adenoma pathology report."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**PLAN_P1)
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician()
    patient = register_patient(plan["id"], birth_date="1975-04-10")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")
    staff_block(block["id"], anesthetist["id"])
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    provisional_claim = claim_for_booking(booking["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    complete_exam(booking["id"], endoscopist["id"], prep_quality_bbps=7,
                  polyps_removed_count=2, largest_polyp_mm=6, specimen_count=2)
    report = receive_report(booking["id"], [
        specimen("A", "TUBULAR_ADENOMA", 6),
        specimen("B", "TUBULAR_ADENOMA", 4),
    ])
    finalize_report(report["id"])
    return {
        "booking_id": booking["id"],
        "claim_id": provisional_claim["id"],
        "provisional_claim": provisional_claim,
    }


def test_provisional_pass_forces_a_zero_polyp_count_and_bills_only_the_anesthesia_line():
    """A polyp count feeds this step, and it is where the two variants first diverge:
    under the provisional pass the polyp count is forced to zero, while under the
    final pass it is the booking's recorded `polyps_removed_count`.

    For each line, under a `SCREENING_PREVENTIVE` classification no deductible is
    applied to that line at all, and the line's coinsurance is the line's
    `allowed_cents` multiplied by one minus the plan's `preventive_coverage_pct`,
    rounded half-up to whole cents — except that an `ANESTHESIA` line on a plan
    whose `anesthesia_bundled` is false is instead charged the line's
    `allowed_cents` multiplied by the plan's `diagnostic_coinsurance_pct`, rounded
    the same way.

    Design: Difficulty/dual_variant_calc/claim_provisional_versus_final_patient_share_diverges
    """
    scenario = _mac_colonoscopy_with_two_adenomas()
    provisional = scenario["provisional_claim"]

    assert provisional["variant"] == "PROVISIONAL"
    assert provisional["status"] == "PROVISIONAL_PRICED"
    assert provisional["classification"] == "SCREENING_PREVENTIVE"
    assert provisional["allowed_amount_cents"] == 211200
    assert provisional["patient_responsibility_cents"] == 8090
    assert provisional["deductible_applied_cents"] == 0
    assert provisional["reprice_count"] == 0
    assert_claim_money_identity(provisional)


def test_final_pass_reprices_the_claim_through_the_diagnostic_deductible_waterfall():
    """Under a `DIAGNOSTIC` classification, the line first absorbs deductible equal to
    the smaller of the line's `allowed_cents` and the deductible remaining, the
    remaining figure is reduced by that amount before the next line is considered,
    and the line's coinsurance is the line's `allowed_cents` less the deductible it
    absorbed, multiplied by the plan's `diagnostic_coinsurance_pct`, rounded half-up
    to whole cents.

    `line_items`, `base_allowed_cents`, `complexity_tier`, `allowed_amount_cents`,
    `deductible_applied_cents`, `coinsurance_cents`, `patient_responsibility_cents`,
    and `plan_paid_cents` are all replaced, `variant` becomes `FINAL`, `reprice_count`
    increases by 1, and the booking's `final_classification` is set from the claim's
    `classification`.

    Design: Difficulty/dual_variant_calc/claim_provisional_versus_final_patient_share_diverges
    """
    scenario = _mac_colonoscopy_with_two_adenomas()
    claim = read_claim(scenario["claim_id"])

    assert claim["variant"] == "FINAL"
    assert claim["status"] == "REPRICED"
    assert claim["reprice_count"] == 1
    assert claim["classification"] == "DIAGNOSTIC"
    assert claim["complexity_tier"] == "TIER_2"
    assert claim["base_allowed_cents"] == 230200
    assert claim["allowed_amount_cents"] == 238700
    assert claim["deductible_applied_cents"] == 150000
    assert claim["coinsurance_cents"] == 17740
    assert claim["patient_responsibility_cents"] == 167740
    assert claim["plan_paid_cents"] == 70960
    assert_claim_money_identity(claim)


def test_booking_retains_the_preventive_plan_and_the_diagnostic_outcome_side_by_side():
    """The provisional pass runs at booking creation, when `polyps_removed_count` is
    not yet known, and writes its classification to the booking's
    `planned_classification`.

    Under the final pass on a non-aborted booking, the polypectomy carveout gets a
    chance to flip it: if the booking's `polyps_removed_count` is 1 or more and the
    plan's `polypectomy_carveout` is `DIAGNOSTIC_CONVERTED`, the classification
    becomes `DIAGNOSTIC`.

    Design: Difficulty/dual_variant_calc/claim_provisional_versus_final_patient_share_diverges
    """
    scenario = _mac_colonoscopy_with_two_adenomas()
    booking = read_booking(scenario["booking_id"])

    assert booking["planned_classification"] == "SCREENING_PREVENTIVE"
    assert booking["final_classification"] == "DIAGNOSTIC"


def _two_exams_finalized_in_different_months():
    """One moderate-sedation block hosts two screening colonoscopies; the adenoma
    report is finalized inside September and the normal report only in October."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient_a = register_patient(plan["id"], mrn="MRN-0001", birth_date="1975-04-10")
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1972-06-22")
    episode_a = open_episode(patient_a["id"], "SCREENING_AVERAGE_RISK")
    episode_b = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    booking_a = book_slot(block["id"], episode_a["id"], endoscopist["id"],
                          slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    booking_b = book_slot(block["id"], episode_b["id"], endoscopist["id"],
                          slot_start_utc="2026-09-15T15:00:00Z", duration_minutes=45)
    for episode, patient, booking in (
        (episode_a, patient_a, booking_a),
        (episode_b, patient_b, booking_b),
    ):
        confirm_prep(episode["id"], patient["id"])
        check_in(booking["id"])
        start_exam(booking["id"], endoscopist["id"])
        complete_exam(booking["id"], endoscopist["id"], prep_quality_bbps=8,
                      polyps_removed_count=1, largest_polyp_mm=6, specimen_count=1)
    report_a = receive_report(booking_a["id"], [specimen("A", "TUBULAR_ADENOMA", 6)],
                              accession_number="ACC-0001")
    report_b = receive_report(booking_b["id"], [specimen("B", "NORMAL_MUCOSA", 0)],
                              accession_number="ACC-0002")
    move_clock("2026-09-20T00:00:00Z")
    finalize_report(report_a["id"])
    move_clock("2026-10-05T00:00:00Z")
    finalize_report(report_b["id"])
    move_clock("2026-10-06T00:00:00Z")
    return {"endoscopist_id": endoscopist["id"]}


def test_procedure_date_attribution_keeps_the_late_finalized_exam_in_the_denominator():
    """Under `PROCEDURE_DATE` the attribution date is the calendar date of the booking's
    `slot_start_utc`, so a completed exam whose pathology is finalized after
    `period_end_date` still counts in the denominator, and counts in the numerator
    only if a finalized report with an adenoma exists at lock time.

    When the denominator is zero, `adr_pct` is `null` rather than 0.0000; otherwise
    it is the numerator divided by the denominator, rounded half-up to four decimal
    places.

    Design: Difficulty/dual_variant_calc/adr_diverges_by_attribution_basis
    """
    scenario = _two_exams_finalized_in_different_months()
    period = open_quality_period(scenario["endoscopist_id"], "2026-09-01", "2026-09-30",
                                attribution_basis="PROCEDURE_DATE")
    locked = lock_quality_period(period["id"])

    assert locked["status"] == "LOCKED"
    assert locked["screening_colonoscopy_count"] == 2
    assert locked["adenoma_positive_count"] == 1
    assert locked["adr_pct"] == 0.5000
    assert locked["benchmark_pct"] == 0.25
    assert locked["benchmark_result"] == "MET"
    assert locked["remediation_required"] is False


def test_pathology_finalization_date_attribution_drops_the_exam_finalized_in_october():
    """Under `PATHOLOGY_FINALIZATION_DATE` a booking with no finalized report is dropped
    from the denominator altogether, and for the rest the attribution date is the
    earliest `finalized_at` among that booking's finalized reports — the aggregate is
    order-free and needs no tie-break.

    A candidate joins the denominator when its attribution date falls on or after
    `period_start_date` and on or before `period_end_date`; **both endpoints are
    inclusive**.

    Design: Difficulty/dual_variant_calc/adr_diverges_by_attribution_basis
    """
    scenario = _two_exams_finalized_in_different_months()
    period = open_quality_period(scenario["endoscopist_id"], "2026-09-01", "2026-09-30",
                                attribution_basis="PATHOLOGY_FINALIZATION_DATE")
    locked = lock_quality_period(period["id"])

    assert locked["status"] == "LOCKED"
    assert locked["screening_colonoscopy_count"] == 1
    assert locked["adenoma_positive_count"] == 1
    assert locked["adr_pct"] == 1.0000
    assert locked["benchmark_pct"] == 0.25
    assert locked["benchmark_result"] == "MET"


def test_the_same_exams_measured_both_ways_yield_two_retained_rates():
    """The financial and quality surfaces of this practice share one property: each
    computes the same quantity two ways, and both answers are legitimate and must be
    retained.

    Windows that differ in `attribution_basis` may overlap freely — indeed, measuring
    the same calendar month both ways is the point.

    Design: Difficulty/dual_variant_calc/adr_diverges_by_attribution_basis
    """
    scenario = _two_exams_finalized_in_different_months()
    by_procedure = open_quality_period(scenario["endoscopist_id"], "2026-09-01",
                                       "2026-09-30",
                                       attribution_basis="PROCEDURE_DATE")
    by_pathology = open_quality_period(scenario["endoscopist_id"], "2026-09-01",
                                       "2026-09-30",
                                       attribution_basis="PATHOLOGY_FINALIZATION_DATE")
    locked_procedure = lock_quality_period(by_procedure["id"])
    locked_pathology = lock_quality_period(by_pathology["id"])

    assert locked_procedure["adr_pct"] == 0.5000
    assert locked_pathology["adr_pct"] == 1.0000
    assert locked_procedure["screening_colonoscopy_count"] == 2
    assert locked_pathology["screening_colonoscopy_count"] == 1
    assert locked_procedure["adr_pct"] != locked_pathology["adr_pct"]
