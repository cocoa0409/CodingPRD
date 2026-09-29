"""Branch order, per-unit rounding, constants and input-set filtering in the derived numbers."""
from test_helpers import (
    PATIENT_NAVIGATOR,
    REFERRAL_COORDINATOR,
    abort_exam,
    amend_report,
    api_client,
    apply_block_action,
    book_slot,
    check_in,
    claim_for_booking,
    complete_exam,
    confirm_prep,
    create_block,
    create_procedure_booking_payload,
    create_screening_episode_payload,
    finalize_report,
    lock_quality_period,
    move_clock,
    open_episode,
    open_quality_period,
    outreach_payload,
    read_claim,
    read_episode,
    read_referral,
    receive_report,
    record_outreach,
    register_endoscopist,
    register_patient,
    register_plan,
    specimen,
    start_exam,
    submit_referral,
    triage,
    triage_action_payload,
    validate_error,
    validate_success,
)


def test_the_ibd_branch_dominates_the_family_history_branch():
    """From those flags the server derives `risk_tier`, which is one of `AVERAGE`, `INCREASED`,
    or `HIGH`, using a strictly ordered three-branch rule that reads only the patient row being
    created and no other data. If either `ibd_diagnosis` or `prior_crc_history` is true, the
    tier is `HIGH`. Otherwise, if `family_history_crc` is true, the tier is `INCREASED`.
    Otherwise the tier is `AVERAGE`. Because the first branch dominates, a patient with
    inflammatory bowel disease *and* a family history is `HIGH`, not `INCREASED`.

    Design: Corner/calculations/risk_stratification_branch_order_puts_high_before_increased
    """
    plan = register_plan()

    both = register_patient(plan["id"], mrn="MRN-0001", ibd_diagnosis=True,
                            family_history_crc=True)
    family_only = register_patient(plan["id"], mrn="MRN-0002", family_history_crc=True)
    no_flags = register_patient(plan["id"], mrn="MRN-0003")
    prior_crc = register_patient(plan["id"], mrn="MRN-0004", prior_crc_history=True)

    assert both["risk_tier"] == "HIGH"
    assert family_only["risk_tier"] == "INCREASED"
    assert no_flags["risk_tier"] == "AVERAGE"
    assert prior_crc["risk_tier"] == "HIGH"


def test_each_touchpoint_is_rounded_before_it_joins_the_running_total():
    """The decay is computed by taking the elapsed time from the entry's `occurred_at` to the
    logical clock's current instant, converting it to whole days by discarding any partial day,
    subtracting 0.05 from 1.00 for each of those whole days, then raising the result to a floor
    of 0.25 if it fell below that and lowering it to a ceiling of 1.00 if it somehow exceeded
    it. The three factors multiplied together are **rounded half-up to two decimal places once,
    per touchpoint**, and only then added to the running raw total; summing first and rounding
    at the end is a different number and is wrong. Recording outreach compares the freshly
    recomputed score against 3.00: at 3.00 or above the episode advances `NOT_STARTED →
    OUTREACH_ACTIVE` (or holds/returns to `OUTREACH_ACTIVE` from `PREP_AT_RISK`), and below
    3.00 it moves to `PREP_AT_RISK` — from `NOT_STARTED → PREP_AT_RISK` on a first weak
    touchpoint, or `OUTREACH_ACTIVE → PREP_AT_RISK` when decay has eroded a previously adequate
    score.

    Design: Corner/calculations/prep_score_rounds_per_touchpoint_and_honours_the_decay_floor
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"])
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")

    first = record_outreach(episode["id"], "PORTAL", True)
    assert first["prep_adherence_score"] == 1.50
    assert first["navigation_status"] == "PREP_AT_RISK"

    second = record_outreach(episode["id"], "PORTAL", True)
    assert second["prep_adherence_score"] == 3.00
    assert second["navigation_status"] == "OUTREACH_ACTIVE"

    move_clock("2026-09-16T00:00:00Z")
    third = validate_success(
        api_client.record_outreach(episode["id"], outreach_payload("MAIL", False),
                                   PATIENT_NAVIGATOR))
    assert third["prep_adherence_score"] == 1.16
    assert third["prep_adherence_score"] != 1.15
    assert third["navigation_status"] == "PREP_AT_RISK"
    assert len(third["outreach_log"]) == 3
    assert third["prep_attestation"] == "NONE"


def test_the_complexity_tier_stays_where_the_base_put_it_after_the_addon_lands():
    """Step three selects `complexity_tier` **from `base_allowed_cents` alone**: `TIER_3` when
    the base is 250000 cents or more, `TIER_2` when it is 150000 cents or more but below that,
    and `TIER_1` otherwise. The tier is **never re-selected from `allowed_amount_cents`**: a
    base of 247250 cents stays `TIER_2` even though its adjusted total of 255750 cents sits
    above the tier-three floor.

    The `FACILITY` line is allowed 78000 cents plus 950 cents for each scheduled minute in
    `duration_minutes`. The `PROFESSIONAL` line is allowed 41500 cents plus 13750 cents for each
    polyp in the polyp count.

    Design: Corner/calculations/complexity_tier_is_never_rederived_from_the_adjusted_total
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(deductible_cents=150000, diagnostic_coinsurance_pct=0.20)
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=120)

    provisional = claim_for_booking(booking["id"])
    assert provisional["base_allowed_cents"] == 233500
    assert provisional["complexity_tier"] == "TIER_2"
    assert provisional["allowed_amount_cents"] == 242000

    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    complete_exam(booking["id"], endoscopist["id"], prep_quality_bbps=8,
                  polyps_removed_count=1, largest_polyp_mm=7, specimen_count=1)
    report = receive_report(booking["id"], [specimen("A", "TUBULAR_ADENOMA", 7)])
    finalize_report(report["id"])

    final = read_claim(provisional["id"])
    assert final["base_allowed_cents"] == 247250
    assert final["complexity_tier"] == "TIER_2"
    assert final["allowed_amount_cents"] == 255750
    assert final["classification"] == "DIAGNOSTIC"
    assert final["deductible_applied_cents"] == 150000
    assert final["coinsurance_cents"] == 21150
    assert final["patient_responsibility_cents"] == 171150
    assert final["plan_paid_cents"] == 84600
    assert final["line_items"][0]["code"] == "FACILITY"
    assert final["line_items"][0]["allowed_cents"] == 200500


def test_an_aborted_exam_and_an_amended_report_both_drop_out_of_the_measure():
    """Bookings in `BOOKED`, `CHECKED_IN`, `IN_PROGRESS`, `ABORTED_INADEQUATE_PREP`, or
    `CANCELLED` never enter either the numerator or the denominator, and surveillance or
    diagnostic-followup indications are outside the measure entirely. For each candidate, the
    reports consulted are only those pathology reports on that booking whose `status` is
    `FINALIZED`; a report sitting in `AMENDED` is invisible both to the numerator and to
    finalization-date attribution.

    `benchmark_result` is then `INSUFFICIENT_VOLUME` when `screening_colonoscopy_count` is below
    the minimum measurable volume of one exam — that is, when it is zero — otherwise `MET` when
    `adr_pct` is at or above `benchmark_pct`, and otherwise `MISSED`.

    Design: Corner/calculations/adr_denominator_excludes_aborted_bookings_and_amended_reports
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist(adr_benchmark_pct=0.25)
    patient_a = register_patient(plan["id"], mrn="MRN-0001")
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1972-06-22")
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")

    episode_a = open_episode(patient_a["id"], "SCREENING_AVERAGE_RISK")
    booking_a = book_slot(block["id"], episode_a["id"], endoscopist["id"],
                          slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    episode_b = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")
    booking_b = book_slot(block["id"], episode_b["id"], endoscopist["id"],
                          slot_start_utc="2026-09-15T14:00:00Z", duration_minutes=45)

    confirm_prep(episode_a["id"], patient_a["id"])
    confirm_prep(episode_b["id"], patient_b["id"])

    check_in(booking_a["id"])
    start_exam(booking_a["id"], endoscopist["id"])
    complete_exam(booking_a["id"], endoscopist["id"], prep_quality_bbps=8,
                  polyps_removed_count=1, largest_polyp_mm=7, specimen_count=1)
    report = receive_report(booking_a["id"], [specimen("A", "TUBULAR_ADENOMA", 7)])
    finalize_report(report["id"])

    check_in(booking_b["id"])
    start_exam(booking_b["id"], endoscopist["id"])
    abort_exam(booking_b["id"], endoscopist["id"], prep_quality_bbps=2,
               cancellation_reason="INADEQUATE_PREP")

    amended = amend_report(report["id"], [specimen("A", "TUBULAR_ADENOMA", 9)],
                           amendment_reason="SIZE_CORRECTION")
    assert amended["status"] == "AMENDED"

    move_clock("2026-09-30T00:00:00Z")
    period = open_quality_period(endoscopist["id"], "2026-09-01", "2026-09-30",
                                 attribution_basis="PROCEDURE_DATE")

    locked = lock_quality_period(period["id"])
    assert locked["status"] == "LOCKED"
    assert locked["screening_colonoscopy_count"] == 1
    assert locked["adenoma_positive_count"] == 0
    assert locked["adr_pct"] == 0.0
    assert locked["benchmark_pct"] == 0.25
    assert locked["benchmark_result"] == "MISSED"
    assert locked["remediation_required"] is True


def test_the_diagnostic_window_is_ninety_days_where_the_standard_window_is_a_hundred_and_eighty():
    """The `due_date` is computed at creation in `YYYY-MM-DD` form by adding a whole number of
    calendar days to `index_date`. A `DIAGNOSTIC_FOLLOWUP` episode is due in 90 days; every
    other indication is due in 180 days. Outside the cascade this second branch never runs,
    because `navigation_priority` is read before any episode exists.

    The episode's `index_date` is the calendar date of the logical clock at creation, in
    `YYYY-MM-DD` form, and it anchors both the age calculation and the due date.

    Design: Corner/calculations/diagnostic_followup_due_date_uses_the_ninety_day_constant
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient_a = register_patient(plan["id"], mrn="MRN-0001")
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1972-06-22")

    diagnostic = open_episode(patient_a["id"], "DIAGNOSTIC_FOLLOWUP")
    standard = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")

    assert diagnostic["index_date"] == "2026-09-01"
    assert diagnostic["due_date"] == "2026-11-30"
    assert standard["due_date"] == "2027-02-28"
    assert diagnostic["origin"] == "DIRECT"
    assert standard["origin"] == "DIRECT"
    assert read_episode(diagnostic["id"])["assigned_interval_months"] is None
    assert read_episode(standard["id"])["assigned_interval_months"] is None


def test_the_age_gate_and_the_tier_gate_are_checked_in_that_order():
    """Otherwise, for `SCREENING_HIGH_RISK`, the status is `INELIGIBLE_AGE` when age is below 40;
    if the age passes but the patient's `risk_tier` is neither `INCREASED` nor `HIGH`, the status
    is `INELIGIBLE_RISK_MISMATCH`; otherwise `ELIGIBLE`. Creation succeeds regardless of the
    outcome; ineligibility only bites later, when someone tries to book a room.

    The episode's `clinical_status` must be `OPEN`, else `ERR_INVALID_EPISODE_STATE`, and its
    `eligibility_status` must be `ELIGIBLE`, else `ERR_EPISODE_NOT_ELIGIBLE` (HTTP 422) — this
    is where an ineligible episode finally stops being bookable.

    Design: Corner/calculations/high_risk_indication_needs_both_the_age_floor_and_the_risk_tier
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    average = register_patient(plan["id"], mrn="MRN-0001", birth_date="1984-01-15")
    increased = register_patient(plan["id"], mrn="MRN-0002", birth_date="1984-01-15",
                                 family_history_crc=True)
    block = create_block(endoscopist["id"])
    published = apply_block_action(block["id"], "PUBLISH")

    mismatch = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(average["id"], "SCREENING_HIGH_RISK"),
            REFERRAL_COORDINATOR),
        201)
    eligible = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(increased["id"], "SCREENING_HIGH_RISK"),
            REFERRAL_COORDINATOR),
        201)
    too_young = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(increased["id"], "SCREENING_AVERAGE_RISK"),
            REFERRAL_COORDINATOR),
        201)

    assert mismatch["eligibility_status"] == "INELIGIBLE_RISK_MISMATCH"
    assert mismatch["risk_tier_snapshot"] == "AVERAGE"
    assert eligible["eligibility_status"] == "ELIGIBLE"
    assert eligible["risk_tier_snapshot"] == "INCREASED"
    assert too_young["eligibility_status"] == "INELIGIBLE_AGE"
    assert read_episode(too_young["id"])["due_date"] == "2027-02-28"

    validate_error(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                mismatch["id"], endoscopist["id"], published["version"],
                "2026-09-15T13:00:00Z", 45),
            REFERRAL_COORDINATOR),
        "ERR_EPISODE_NOT_ELIGIBLE")


def test_a_bleeding_complaint_fails_the_screen_that_an_asa_three_referral_passes():
    """That screen writes `risk_screen_result` as one of `PENDING`, `CLEARED_OPEN_ACCESS`, or
    `OFFICE_VISIT_REQUIRED`, and it reads only three values on the referral itself, as most
    recently revised: the result is `CLEARED_OPEN_ACCESS` when `asa_class_reported` is at most
    3 **and** `anticoagulant_reported` is false **and** `reason` is anything other than
    `SYMPTOMATIC_BLEEDING`; in every other case the result is `OFFICE_VISIT_REQUIRED`. An ASA
    class of 4 or 5, a patient on anticoagulants, or a bleeding complaint each independently
    forces a clinic visit. `ACCEPT_OPEN_ACCESS` moves `UNDER_TRIAGE → ACCEPTED_OPEN_ACCESS`,
    but only if the recomputed `risk_screen_result` is `CLEARED_OPEN_ACCESS`; if it is
    `OFFICE_VISIT_REQUIRED`, the acceptance is rejected with
    `ERR_OPEN_ACCESS_RISK_SCREEN_FAILED` (HTTP 422). `ACCEPT_OFFICE_VISIT` moves `UNDER_TRIAGE
    → ACCEPTED_OFFICE_VISIT` and is always permitted from `UNDER_TRIAGE` — it is the deliberate
    fallback when the open-access screen fails.

    Design: Corner/calculations/symptomatic_bleeding_referral_cannot_clear_open_access
    """
    plan = register_plan()
    patient = register_patient(plan["id"])
    bleeding = submit_referral(patient["id"], referring_provider_npi="3000000001",
                              reason="SYMPTOMATIC_BLEEDING", asa_class_reported=2)
    asa_three = submit_referral(patient["id"], referring_provider_npi="3000000002",
                               reason="FAMILY_HISTORY", asa_class_reported=3)

    triaged = triage(bleeding["id"], "BEGIN_TRIAGE")
    assert triaged["status"] == "UNDER_TRIAGE"
    assert triaged["risk_screen_result"] == "OFFICE_VISIT_REQUIRED"

    validate_error(
        api_client.referral_triage_action(
            bleeding["id"], triage_action_payload("ACCEPT_OPEN_ACCESS"), REFERRAL_COORDINATOR),
        "ERR_OPEN_ACCESS_RISK_SCREEN_FAILED")
    assert read_referral(bleeding["id"])["status"] == "UNDER_TRIAGE"

    accepted_in_clinic = triage(bleeding["id"], "ACCEPT_OFFICE_VISIT",
                               note="COLONOSCOPY_AFTER_OFFICE_EVALUATION")
    assert accepted_in_clinic["status"] == "ACCEPTED_OFFICE_VISIT"
    assert accepted_in_clinic["triage_decision_note"] == "COLONOSCOPY_AFTER_OFFICE_EVALUATION"

    cleared = triage(asa_three["id"], "BEGIN_TRIAGE")
    assert cleared["risk_screen_result"] == "CLEARED_OPEN_ACCESS"
    accepted_open = triage(asa_three["id"], "ACCEPT_OPEN_ACCESS")
    assert accepted_open["status"] == "ACCEPTED_OPEN_ACCESS"

    assert read_referral(bleeding["id"])["info_request_rounds"] == 0
    assert read_referral(asa_three["id"])["info_request_rounds"] == 0
