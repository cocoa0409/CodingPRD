"""Calculations: the eight-step charge, the PPS rate, the aggregations and the sweep."""

import pytest

from test_helpers import (
    ADMIN,
    BILLER,
    OFFICER,
    api_client,
    advance_clock,
    bill_encounter,
    compute_uds_report,
    create_encounter_payload,
    record_payment_payload,
    refresh_encounter,
    refresh_fee_schedule,
    refresh_finding,
    refresh_health_center,
    refresh_patient,
    same_instant,
    setup_boot_core,
    setup_boot_pt,
    setup_draft_uds_report,
    setup_encounter,
    setup_open_finding,
    setup_patient,
    setup_quality_measure,
    validate_success,
    void_encounter_payload,
)


def _measure(measure_id):
    return validate_success(api_client.get_quality_measure_result(measure_id, OFFICER))


def _mco_encounter(ctx, *, encounter_date, claim_reference, mco_paid_cents):
    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date=encounter_date,
        payer_type="MEDICAID_MCO",
        gross_charge_cents=8000,
    )
    bill_encounter(encounter, claim_reference)
    return validate_success(
        api_client.record_encounter_payment(
            encounter["id"], record_payment_payload(mco_paid_cents), BILLER
        )
    )


def test_a_nominal_band_charges_the_flat_fee_not_a_fraction_of_the_gross():
    """The nominal kind returns the schedule's fee outright and the cap leaves it alone.

    PRD 3.5: "Step four converts the gross charge into a raw amount according to the
    tier's `discount_kind`. When the kind is `NOMINAL`, the raw amount is the pinned
    schedule's `nominal_fee_cents`." and "Step five caps the raw amount at the gross
    charge: the patient may never owe more than the undiscounted charge."

    Design: Corner/calculations/patient_charge_on_a_nominal_tier_correct_result
    """
    ctx = setup_boot_pt()

    response = api_client.create_encounter(
        create_encounter_payload(
            ctx["patient_id"],
            ctx["site_id"],
            ctx["service_id"],
            encounter_date="2026-03-15T00:00:00Z",
            payer_type="SELF_PAY",
            gross_charge_cents=8000,
        ),
        BILLER,
    )
    encounter = validate_success(response, 201)

    assert encounter["patient_charge_cents"] == 2500, (
        "the flat nominal fee is charged rather than a percentage of the 8000 gross, "
        f"got {encounter['patient_charge_cents']}"
    )
    assert encounter["charge_basis"] == "SLIDING_FEE_TIER"
    assert encounter["sliding_fee_applied"] is True
    assert encounter["pinned_discount_tier_id"] == ctx["tiers_by_label"]["NOMINAL_FULL"]["id"]
    assert encounter["income_verification_id"] == ctx["income_verification_id"]
    assert encounter["fee_schedule_id"] == ctx["fee_schedule_id"]
    assert encounter["pps_encounter_rate_cents"] == 20000, (
        "a required primary service at a service-delivery site takes the unmultiplied "
        f"base rate, got {encounter['pps_encounter_rate_cents']}"
    )
    assert encounter["wraparound_due_cents"] == 0
    assert encounter["wraparound_status"] == "NOT_APPLICABLE"
    assert encounter["charge_adjustment_cents"] == 0
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500


def test_a_medicare_encounter_is_clamped_to_the_ceiling_and_charges_the_patient_nothing():
    """Two declared constants act independently on the same row.

    PRD 3.5: "Finally, if `payer_type` is `MEDICARE`, the rate is reduced to the
    grantee's `medicare_upper_limit_cents` when it exceeds that ceiling. The Medicare
    clamp is applied *after* the rounding, to the rounded integer." and "Step one
    handles third-party payers. If `payer_type` is `MEDICARE`, `MEDICAID_FFS` or
    `PRIVATE`, then `sliding_fee_applied` is false, `charge_basis` is `THIRD_PARTY`,
    `pinned_discount_tier_id` is null, and `patient_charge_cents` is 0."

    Design: Corner/calculations/pps_rate_medicare_upper_limit_constant_clamps_the_rate
    """
    ctx = setup_boot_pt()

    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-20T00:00:00Z",
        payer_type="MEDICARE",
        gross_charge_cents=30000,
    )

    assert encounter["pps_encounter_rate_cents"] == 15000, (
        "the 20000 base rate is reduced to the 15000 ceiling, got "
        f"{encounter['pps_encounter_rate_cents']}"
    )
    assert encounter["patient_charge_cents"] == 0, (
        "no sliding fee logic runs for a third-party payer, even for a verified patient"
    )
    assert encounter["charge_basis"] == "THIRD_PARTY"
    assert encounter["sliding_fee_applied"] is False
    assert encounter["pinned_discount_tier_id"] is None
    assert encounter["wraparound_status"] == "NOT_APPLICABLE"
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 0


def test_the_reported_patient_set_dedupes_visits_and_drops_a_voided_only_patient():
    """The distinct-patient set over non-void encounters decides who is reported.

    PRD 3.9: "The **income distribution** aggregation first determines the reported
    patient set: the distinct `patient_id` values over encounters whose service site
    belongs to the report's grantee, whose `pps_claim_status` is anything other than
    `VOID`, and whose `encounter_date` falls in the report's `reporting_year`.
    `total_patient_count` is the size of that set."

    Design: Corner/calculations/uds_income_distribution_excludes_void_encounters_and_dedupes_patients
    """
    ctx = setup_boot_pt()
    setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-15T00:00:00Z",
        gross_charge_cents=8000,
    )
    setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-04-01T00:00:00Z",
        gross_charge_cents=8000,
    )
    undocumented = setup_patient(mrn="MRN-C03", full_name="Rue Marsh", household_size=1)
    setup_encounter(
        ctx,
        undocumented["id"],
        encounter_date="2026-05-01T00:00:00Z",
        gross_charge_cents=8000,
    )
    voided_only = setup_patient(mrn="MRN-C04", full_name="Sol Vega", household_size=1)
    voided = setup_encounter(
        ctx,
        voided_only["id"],
        encounter_date="2026-06-01T00:00:00Z",
        gross_charge_cents=8000,
    )
    validate_success(
        api_client.void_encounter(
            voided["id"], void_encounter_payload("DUPLICATE"), BILLER
        )
    )
    report = setup_draft_uds_report(ctx, reporting_year=2026)

    computed = compute_uds_report(report)

    assert computed["total_patient_count"] == 2, (
        "two visits by one patient count her once and the voided-only patient is "
        f"excluded entirely, got {computed['total_patient_count']}"
    )
    assert computed["patients_at_or_below_100_count"] == 1
    assert computed["patients_101_to_150_count"] == 0
    assert computed["patients_151_to_200_count"] == 0
    assert computed["patients_over_200_count"] == 0
    assert computed["unverified_patient_count"] == 1, (
        "the patient with no verification at all lands in the unverified tally"
    )
    assert computed["included_measure_count"] == 0
    assert computed["composite_quality_rate_pct"] is None
    assert same_instant(computed["computed_at"]) == "2026-08-01T00:00:00Z"
    assert refresh_encounter(voided["id"])["pps_claim_status"] == "VOID"


def test_both_measures_land_on_a_half_boundary_and_round_upward():
    """Half-up is the declared mode, so neither rate rounds down to an even digit.

    PRD 2.7: "A quality measure's `rate_pct` and a report's
    `composite_quality_rate_pct` are each rounded half up to **1 decimal place**."

    PRD 3.9: "Otherwise `composite_quality_rate_pct` is the sum of the included
    measures' `rate_pct` values divided by `included_measure_count`, rounded half up to
    one decimal place."

    Design: Corner/calculations/quality_measure_rate_uses_round_half_up_not_bankers_rounding
    """
    ctx = setup_boot_core()
    report = setup_draft_uds_report(ctx, reporting_year=2026)
    blood_pressure = setup_quality_measure(
        report,
        measure_code="CMS165_BP_CONTROL",
        numerator=5,
        denominator=16,
        benchmark_pct=31.3,
    )
    glycemic = setup_quality_measure(
        report,
        measure_code="CMS122_HBA1C",
        numerator=1,
        denominator=16,
        benchmark_pct=6.4,
    )

    computed = compute_uds_report(report)

    first = _measure(blood_pressure["id"])
    assert first["rate_pct"] == pytest.approx(31.3, abs=0.01), (
        f"5 of 16 is exactly 31.25, which rounds up to 31.3, got {first['rate_pct']}"
    )
    assert first["inclusion_status"] == "INCLUDED"
    assert first["meets_benchmark"] is True

    second = _measure(glycemic["id"])
    assert second["rate_pct"] == pytest.approx(6.3, abs=0.01), (
        f"1 of 16 is exactly 6.25, which rounds up to 6.3, got {second['rate_pct']}"
    )
    assert second["inclusion_status"] == "INCLUDED"
    assert second["meets_benchmark"] is False

    assert computed["included_measure_count"] == 2
    assert computed["composite_quality_rate_pct"] == pytest.approx(18.8, abs=0.01), (
        "the mean of the already-rounded 31.3 and 6.3 is 18.8, got "
        f"{computed['composite_quality_rate_pct']}"
    )


def test_the_grantee_receivable_is_recounted_from_the_surviving_encounters():
    """Voiding one encounter removes its residual from the base rather than adjusting it.

    PRD 2.8: "`wraparound_receivable_cents` equals the sum of `wraparound_due_cents`
    over the grantee's encounters whose `wraparound_status` is `PENDING`, `CLAIMED` or
    `REBILL_REQUIRED`. An encounter whose wraparound has reached `RECEIVED`, or which is
    `NOT_APPLICABLE`, contributes nothing to the receivable."

    Design: Corner/calculations/wraparound_receivable_aggregation_after_payment_and_after_void
    """
    ctx = setup_boot_pt()
    first = _mco_encounter(
        ctx,
        encounter_date="2026-03-15T00:00:00Z",
        claim_reference="CLM-M1",
        mco_paid_cents=14000,
    )
    second = _mco_encounter(
        ctx,
        encounter_date="2026-04-01T00:00:00Z",
        claim_reference="CLM-M2",
        mco_paid_cents=15000,
    )
    assert first["patient_charge_cents"] == 2500, (
        "the managed-care clamp holds the patient at the nominal fee"
    )
    assert first["wraparound_due_cents"] == 3500, (
        "20000 less the 14000 payment less the 2500 counted patient portion is 3500, "
        f"got {first['wraparound_due_cents']}"
    )
    assert first["wraparound_status"] == "PENDING"
    assert second["wraparound_due_cents"] == 2500
    assert second["wraparound_status"] == "PENDING"
    assert refresh_health_center(ctx["health_center_id"])[
        "wraparound_receivable_cents"
    ] == 6000

    validate_success(
        api_client.void_encounter(
            first["id"], void_encounter_payload("CODING_ERROR"), BILLER
        )
    )

    voided = refresh_encounter(first["id"])
    assert voided["pps_claim_status"] == "VOID"
    assert voided["wraparound_status"] == "NOT_APPLICABLE"
    assert voided["charge_adjustment_cents"] == -2500
    assert refresh_health_center(ctx["health_center_id"])[
        "wraparound_receivable_cents"
    ] == 2500, "the surviving encounter's 2500 is all that remains in the base"
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500


def test_one_sweep_runs_all_four_steps_in_order_and_a_second_changes_nothing():
    """Escalation in step two is visible in the posture step four recomputes.

    PRD 3.9: "The step order is itself load-bearing: because escalations in step two
    freeze scope *before* step four recomputes posture, one sweep can both escalate a
    finding and report the resulting frozen posture in the same pass. The sweep is
    global across all grantees and idempotent at a fixed clock value — running it twice
    without moving the clock changes nothing the second time."

    Design: Corner/calculations/compliance_sweep_step_order_and_second_run_idempotence
    """
    ctx = setup_boot_pt()
    finding = setup_open_finding(
        ctx,
        requirement_code="REQ_BOARD_AUTHORITY_19",
        severity="CONDITION",
        cap_due_days=30,
        service_site_id=ctx["site_id"],
        finding_summary="Governing board lacks patient-majority composition",
    )
    advance_clock("2027-03-01T00:00:00Z")

    first_sweep = validate_success(api_client.run_compliance_sweep(ADMIN))

    assert first_sweep["expired_verification_count"] == 1
    assert first_sweep["escalated_finding_count"] == 1
    assert first_sweep["expired_fee_schedule_count"] == 1
    assert first_sweep["recomputed_health_center_count"] == 1
    verification = validate_success(
        api_client.get_income_verification(ctx["income_verification_id"], OFFICER)
    )
    assert verification["status"] == "EXPIRED"
    assert refresh_patient(ctx["patient_id"])["sliding_fee_status"] == "EXPIRED"
    escalated = refresh_finding(finding["id"])
    assert escalated["status"] == "ESCALATED"
    assert same_instant(escalated["escalated_at"]) == "2027-03-01T00:00:00Z"
    schedule = refresh_fee_schedule(ctx["fee_schedule_id"])
    assert schedule["status"] == "EXPIRED"
    assert schedule["review_status"] == "CURRENT", (
        "the schedule's own guideline year is still the latest published one and only "
        f"212 days have elapsed, got {schedule['review_status']}"
    )
    frozen = refresh_health_center(ctx["health_center_id"])
    assert frozen["open_condition_count"] == 1
    assert frozen["operational_status"] == "CONDITIONS_IMPOSED"
    assert frozen["scope_posture"] == "CHANGE_FROZEN", (
        "step two froze scope before step four recomputed the posture"
    )

    second_sweep = validate_success(api_client.run_compliance_sweep(ADMIN))

    assert second_sweep["expired_verification_count"] == 0
    assert second_sweep["escalated_finding_count"] == 0
    assert second_sweep["expired_fee_schedule_count"] == 0
    assert (
        validate_success(
            api_client.get_income_verification(ctx["income_verification_id"], OFFICER)
        )["status"]
        == "EXPIRED"
    )
    assert refresh_finding(finding["id"])["status"] == "ESCALATED"
    assert refresh_fee_schedule(ctx["fee_schedule_id"])["status"] == "EXPIRED"
    assert refresh_health_center(ctx["health_center_id"])["open_condition_count"] == 1
