"""Charges, the sliding fee scale, the encounter nominal-fee floor and the
sponsor-hospital claim cycle."""

import pytest

from test_helpers import (
    BILLING,
    REGISTRAR,
    ApiErrorId,
    assert_charge,
    assert_fpl_precision,
    assert_visit_buckets,
    charge_of_category,
    charges_for_visit,
    complete_visit,
    create_student,
    get_charge,
    get_visit,
    record_dose,
    set_clock,
    set_financial_profile,
    setup_enrolled_student,
    setup_pending_charge,
    setup_private_insurance_pending_charge,
    setup_visit_in_progress,
    submit_claim,
    validate_error,
    validate_success,
)


def _self_pay_encounter_with_an_immunization_dose():
    """A TIER_A self-pay family, an ACUTE encounter IN_PROGRESS and one VALID
    HEPB dose recorded against that encounter."""
    ctx = setup_visit_in_progress(
        setup_enrolled_student(
            financial={
                "household_income_annual_cents": 3_000_000,
                "household_size": 4,
                "payer_route": "SELF_PAY",
            }
        )
    )
    ctx["dose"] = record_dose(
        ctx["student"]["id"],
        ctx["clinician"]["id"],
        "HEPB",
        1,
        "2026-05-04",
        visit_id=ctx["visit"]["id"],
    )
    return ctx


def test_provisional_responsibility_takes_its_base_gross_first(api):
    """PRD §3.10: "The **provisional** variant runs at charge creation, before any
    payer has been heard from, and it takes its base gross-first: the base is 0 for
    a no-charge service category, 0 when the snapshotted payer route is `MEDICAID`,
    a flat 2,500 cents when it is `PRIVATE_INSURANCE`, and the full
    `gross_amount_cents` when it is `SELF_PAY`. The result is stored as
    `provisional_patient_responsibility_cents`."
    PRD §3.2: "Each tier carries a discount fraction used later by the billing
    rules: 1.00 for `TIER_A`, 0.80 for `TIER_B`, 0.60 for `TIER_C`, 0.40 for
    `TIER_D` and 0.00 for `TIER_E`."

    Design: Difficulty/dual_variant_calc/charge_responsibility_provisional_gross_first_vs_final_net_of_payer
    """
    ctx = setup_private_insurance_pending_charge()

    student = validate_success(api.get_student(ctx["student"]["id"], REGISTRAR))
    assert float(student["fpl_percent"]) == pytest.approx(151.66, abs=0.001)
    assert_fpl_precision(student["fpl_percent"])
    assert student["discount_tier"] == "TIER_C"

    charge = get_charge(ctx["charge"]["id"])
    assert_charge(charge)
    assert charge["gross_amount_cents"] == 12_000
    # base 2500 (private insurance) x (1 - 0.60) = 1000
    assert charge["provisional_patient_responsibility_cents"] == 1_000
    assert charge["final_patient_responsibility_cents"] is None
    assert charge["patient_responsibility_cents"] == 1_000
    assert charge["floor_adjustment_cents"] == 0
    assert charge["status"] == "PENDING"


def test_final_responsibility_takes_its_base_net_of_payer(api):
    """PRD §3.10: "The **final** variant runs only at adjudication with a paid
    outcome, and it takes its base net-of-payer: the residual is the gross amount
    less what the payer actually allowed, clamped at 0 so it never goes negative,
    and the base is 0 for a no-charge category, 0 for `MEDICAID`, the residual for
    `PRIVATE_INSURANCE`, and the full gross for `SELF_PAY`."
    PRD §3.10: "Identical stored inputs produce different numbers under the two
    variants — a 12,000-cent gross on a `TIER_C` private-insurance charge where the
    payer allowed 8,000 gives a provisional 1,000 cents but a final 1,600 cents."

    Design: Difficulty/dual_variant_calc/charge_responsibility_provisional_gross_first_vs_final_net_of_payer
    """
    ctx = setup_private_insurance_pending_charge()
    submit_claim(ctx["charge"]["id"])

    resp = api.adjudicate_charge(
        ctx["charge"]["id"], {"outcome": "PAID", "payer_paid_amount_cents": 8_000}, BILLING
    )
    charge = validate_success(resp)

    assert charge["provisional_patient_responsibility_cents"] == 1_000
    assert charge["final_patient_responsibility_cents"] == 1_600
    assert charge["patient_responsibility_cents"] == 1_600
    assert charge["floor_adjustment_cents"] == 0
    assert charge["status"] == "PAID"

    visit = get_visit(ctx["visit"]["id"])
    assert_visit_buckets(
        visit,
        gross=12_000,
        no_charge=0,
        patient_responsibility=1_600,
        write_off=0,
        payer_billed=10_400,
    )
    assert visit["billing_status"] == "CHARGES_POSTED"


def test_poverty_percentage_rounds_before_the_tier_is_banded(api):
    """PRD §3.2: "**Second**, and this order is deliberate, it selects
    `discount_tier` using the *rounded* percentage, not the raw one: at or below
    100.00% the tier is `TIER_A`; above 100.00% and at or below 138.00% it is
    `TIER_B`; above 138.00% and at or below 175.00% it is `TIER_C`; above 175.00%
    and at or below 200.00% it is `TIER_D`; and strictly above 200.00% it is
    `TIER_E`."
    PRD §3.2: "Rounding before banding is what decides the edges — a raw percentage
    of 100.0000641 rounds to 100.00 and therefore lands in `TIER_A`, not `TIER_B`."

    Design: Difficulty/combinatorial_formula/fpl_round_to_two_dp_before_tier_banding_keeps_tier_a_at_100_0000641
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student(first_name="Cleo", last_name="Park")

    resp = api.update_financial_profile(
        student["id"],
        {
            "household_income_annual_cents": 1_560_001,
            "household_size": 1,
            "payer_route": "SELF_PAY",
        },
        REGISTRAR,
    )
    edge = validate_success(resp)

    assert float(edge["fpl_percent"]) == pytest.approx(100.00, abs=0.001)
    assert_fpl_precision(edge["fpl_percent"])
    assert edge["discount_tier"] == "TIER_A", (
        "Banding the unrounded 100.0000641 would wrongly land in TIER_B"
    )


def test_the_next_income_step_lands_in_the_second_tier(api):
    """PRD §3.2: "**First**, it computes the poverty threshold for that household:
    1,560,000 cents for a household of one, plus 550,000 cents for each additional
    person — so a household of four has a threshold of 3,210,000 cents."
    PRD §3.2: "at or below 100.00% the tier is `TIER_A`; above 100.00% and at or
    below 138.00% it is `TIER_B`"

    Design: Difficulty/combinatorial_formula/fpl_round_to_two_dp_before_tier_banding_keeps_tier_a_at_100_0000641
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student(first_name="Cleo", last_name="Park")
    set_financial_profile(
        student["id"],
        household_income_annual_cents=1_560_001,
        household_size=1,
        payer_route="SELF_PAY",
    )

    resp = api.update_financial_profile(
        student["id"],
        {
            "household_income_annual_cents": 1_570_000,
            "household_size": 1,
            "payer_route": "SELF_PAY",
        },
        REGISTRAR,
    )
    stepped = validate_success(resp)

    assert float(stepped["fpl_percent"]) == pytest.approx(100.64, abs=0.001)
    assert stepped["discount_tier"] == "TIER_B"
    assert validate_success(api.get_student(student["id"], REGISTRAR))["discount_tier"] == "TIER_B"


def test_nominal_fee_floor_tops_up_the_single_eligible_charge(api):
    """PRD §3.10: "Third, the floor is applied only when all three of the following
    hold: the eligible set is non-empty, the student's `payer_route` is not
    `MEDICAID` — Medicaid families are never charged a nominal fee — and the
    encounter total is strictly below 500 cents, so an encounter that already totals
    exactly 500 is left alone. When it applies, the target is the eligible charge
    with the greatest `gross_amount_cents`, ties broken by earliest `created_at` and
    never by identifier, and that charge's `floor_adjustment_cents` is set to 500
    cents minus the encounter total."

    Design: Difficulty/combinatorial_formula/encounter_nominal_fee_floor_four_step_evaluation_order
    """
    ctx = _self_pay_encounter_with_an_immunization_dose()

    student = validate_success(api.get_student(ctx["student"]["id"], REGISTRAR))
    assert float(student["fpl_percent"]) == pytest.approx(93.46, abs=0.001)
    assert student["discount_tier"] == "TIER_A"

    completed = complete_visit(ctx["visit"]["id"], ctx["clinician"]["id"])

    acute = charge_of_category(ctx["visit"]["id"], "ACUTE_OFFICE_VISIT")
    assert acute["gross_amount_cents"] == 12_000
    assert acute["provisional_patient_responsibility_cents"] == 0
    assert acute["floor_adjustment_cents"] == 500
    assert acute["patient_responsibility_cents"] == 500
    assert acute["status"] == "PENDING"
    assert completed["patient_responsibility_total_cents"] == 500


def test_the_no_charge_immunization_row_is_excluded_from_the_floor(api):
    """PRD §3.10: "`IMMUNIZATION_ADMIN` charges are born terminal, in `NO_CHARGE`,
    with a provisional responsibility of 0 and an operative
    `patient_responsibility_cents` of 0, and they are excluded from the encounter
    nominal-fee floor entirely. Their 3,000-cent gross still counts toward the
    encounter's gross bucket and its no-charge bucket."
    PRD §3.10: "First, the eligible set is every charge of that encounter whose
    status is neither `NO_CHARGE` nor `REVERSED`; each eligible charge has its
    `floor_adjustment_cents` cleared to 0, and its unfloored amount is taken as its
    `final_patient_responsibility_cents` when that is non-null and its
    `provisional_patient_responsibility_cents` otherwise."

    Design: Difficulty/combinatorial_formula/encounter_nominal_fee_floor_four_step_evaluation_order
    """
    ctx = _self_pay_encounter_with_an_immunization_dose()

    complete_visit(ctx["visit"]["id"], ctx["clinician"]["id"])

    rows = charges_for_visit(ctx["visit"]["id"])
    assert len(rows) == 2, f"Expected the encounter charge plus one dose charge, got {len(rows)}"

    immunization = charge_of_category(ctx["visit"]["id"], "IMMUNIZATION_ADMIN")
    assert immunization["gross_amount_cents"] == 3_000
    assert immunization["floor_adjustment_cents"] == 0
    assert immunization["patient_responsibility_cents"] == 0
    assert immunization["status"] == "NO_CHARGE"

    visit = get_visit(ctx["visit"]["id"])
    assert_visit_buckets(
        visit,
        gross=15_000,
        no_charge=3_000,
        patient_responsibility=500,
        write_off=0,
        payer_billed=11_500,
    )
    assert visit["clinical_status"] == "COMPLETED"
    assert visit["billing_status"] == "PENDING_CHARGES"


def test_billing_axis_reaches_pending_charges_while_the_clinical_axis_completes(api):
    """PRD §3.10: "An encounter that completes and mints at least one charge that is
    not already terminal moves `NOT_APPLICABLE → PENDING_CHARGES`."
    PRD §3.5: "The clinical axis, `clinical_status`, tracks what happened to the
    child: `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED` or `NO_SHOW`. The
    billing axis, `billing_status`, tracks what happened to the money:
    `NOT_APPLICABLE`, `PENDING_CHARGES`, `CHARGES_POSTED` or `REVERSED`."

    Design: Difficulty/non_linear_state_machine/visit_billing_axis_advances_while_clinical_axis_stays_completed
    """
    ctx = setup_visit_in_progress(
        setup_enrolled_student(
            first_name="Ben",
            last_name="Ortiz",
            financial={
                "household_income_annual_cents": 3_200_000,
                "household_size": 2,
                "payer_route": "PRIVATE_INSURANCE",
                "insurance_member_id": "PI-778",
            },
            guardians=[
                {
                    "full_name": "Rosa Ortiz",
                    "relationship": "MOTHER",
                    "contact_email": "rosa@example.org",
                    "is_primary": True,
                }
            ],
        )
    )

    completed = validate_success(
        api.complete_visit(
            ctx["visit"]["id"], {"disposition": "TREATED_SENT_HOME"}, ctx["clinician_headers"]
        )
    )

    assert completed["clinical_status"] == "COMPLETED"
    assert completed["billing_status"] == "PENDING_CHARGES"
    assert completed["disposition"] == "TREATED_SENT_HOME"


def test_billing_axis_reaches_charges_posted_while_the_clinical_axis_holds(api):
    """PRD §3.10: "Thereafter, any charge transition that leaves every charge of the
    encounter terminal moves the axis `PENDING_CHARGES → CHARGES_POSTED`."
    PRD §3.5: "The two evolve independently — the billing axis is a pure function of
    the encounter's charge rows and moves without any clinical-axis change, and the
    clinical axis never waits for money to settle."

    Design: Difficulty/non_linear_state_machine/visit_billing_axis_advances_while_clinical_axis_stays_completed
    """
    ctx = setup_private_insurance_pending_charge()
    after_completion = get_visit(ctx["visit"]["id"])
    assert after_completion["clinical_status"] == "COMPLETED"
    assert after_completion["billing_status"] == "PENDING_CHARGES"

    submit_claim(ctx["charge"]["id"])
    validate_success(
        api.adjudicate_charge(
            ctx["charge"]["id"], {"outcome": "PAID", "payer_paid_amount_cents": 12_000}, BILLING
        )
    )

    charge = get_charge(ctx["charge"]["id"])
    assert charge["status"] == "PAID"
    assert charge["final_patient_responsibility_cents"] == 0
    assert charge["floor_adjustment_cents"] == 500
    assert charge["patient_responsibility_cents"] == 500

    visit = get_visit(ctx["visit"]["id"])
    assert visit["clinical_status"] == "COMPLETED", "The clinical axis never moved"
    assert visit["billing_status"] == "CHARGES_POSTED"
    assert_visit_buckets(
        visit,
        gross=12_000,
        no_charge=0,
        patient_responsibility=500,
        write_off=0,
        payer_billed=11_500,
    )


def test_bucket_residual_is_zero_after_the_encounter_completes(api):
    """PRD §2.10: "And the visit-level residual — the gross bucket minus the sum of
    the payer-billed, patient-responsibility, write-off and no-charge buckets — must
    be exactly 0 both before and after every forward action and its compensating
    action."
    PRD §3.10: "And `payer_billed_total_cents` sums, over charges that are neither
    `REVERSED` nor `NO_CHARGE`, the gross amount less the operative patient
    responsibility less the written-off amount."

    Design: Difficulty/compensating_invariant/visit_charge_bucket_residual_stays_zero_across_complete_and_reverse
    """
    ctx = _self_pay_encounter_with_an_immunization_dose()

    completed = complete_visit(ctx["visit"]["id"], ctx["clinician"]["id"])

    assert_visit_buckets(
        completed,
        gross=15_000,
        no_charge=3_000,
        patient_responsibility=500,
        write_off=0,
        payer_billed=11_500,
    )


def test_bucket_residual_stays_zero_after_the_charge_is_reversed(api):
    """PRD §3.10: "**Reversal** is the compensating action for a charge posted in
    error. It carries a `reason` and is accepted from `PENDING`, `CLAIM_SUBMITTED`,
    `CLAIM_DENIED` and `CLAIM_APPEALED`, moving the charge to `REVERSED` in every
    case with identical side effects: the charge leaves every encounter bucket, its
    `floor_adjustment_cents` is cleared and the encounter nominal-fee floor is
    re-derived across the surviving charges, the buckets are recomputed, and the
    conserved residual stays 0."

    Design: Difficulty/compensating_invariant/visit_charge_bucket_residual_stays_zero_across_complete_and_reverse
    """
    ctx = _self_pay_encounter_with_an_immunization_dose()
    complete_visit(ctx["visit"]["id"], ctx["clinician"]["id"])
    acute = charge_of_category(ctx["visit"]["id"], "ACUTE_OFFICE_VISIT")
    assert acute["floor_adjustment_cents"] == 500

    reversed_charge = validate_success(
        api.reverse_charge(
            acute["id"], {"reason": "Charge posted against the wrong encounter"}, BILLING
        )
    )

    assert reversed_charge["status"] == "REVERSED"
    assert reversed_charge["floor_adjustment_cents"] == 0

    visit = get_visit(ctx["visit"]["id"])
    assert_visit_buckets(
        visit,
        gross=3_000,
        no_charge=3_000,
        patient_responsibility=0,
        write_off=0,
        payer_billed=0,
    )
    assert visit["clinical_status"] == "COMPLETED"


def test_medicaid_family_is_exempt_from_the_encounter_nominal_fee_floor(api):
    """PRD §3.10: "Third, the floor is applied only when all three of the following
    hold: the eligible set is non-empty, the student's `payer_route` is not
    `MEDICAID` — Medicaid families are never charged a nominal fee — and the
    encounter total is strictly below 500 cents, so an encounter that already totals
    exactly 500 is left alone."
    PRD §3.2: "above 175.00% and at or below 200.00% it is `TIER_D`"

    Design: Corner/calculations/medicaid_charge_is_exempt_from_the_encounter_nominal_fee_floor
    """
    ctx = setup_visit_in_progress(
        setup_enrolled_student(
            first_name="Kai",
            last_name="Rivera",
            financial={
                "household_income_annual_cents": 3_800_000,
                "household_size": 2,
                "payer_route": "MEDICAID",
                "insurance_member_id": "MCD-9001",
            },
            guardians=[
                {
                    "full_name": "Lia Rivera",
                    "relationship": "MOTHER",
                    "contact_email": "lia@example.org",
                    "is_primary": True,
                }
            ],
        )
    )

    student = validate_success(api.get_student(ctx["student"]["id"], REGISTRAR))
    assert float(student["fpl_percent"]) == pytest.approx(180.09, abs=0.001)
    assert student["discount_tier"] == "TIER_D"

    completed = complete_visit(ctx["visit"]["id"], ctx["clinician"]["id"])

    charge = charge_of_category(ctx["visit"]["id"], "ACUTE_OFFICE_VISIT")
    assert charge["payer_route"] == "MEDICAID"
    assert charge["gross_amount_cents"] == 12_000
    assert charge["provisional_patient_responsibility_cents"] == 0
    assert charge["floor_adjustment_cents"] == 0, "Medicaid families never carry the nominal fee"
    assert charge["patient_responsibility_cents"] == 0

    assert_visit_buckets(
        completed,
        gross=12_000,
        no_charge=0,
        patient_responsibility=0,
        write_off=0,
        payer_billed=12_000,
    )


def test_denial_appeal_cycle_runs_twice_then_the_write_off_lands(api):
    """PRD §3.10: "**Appealing** moves a charge `CLAIM_DENIED → CLAIM_APPEALED`,
    carries an `appeal_note`, increments `appeal_count` by 1 and is capped at 2
    appeals — a third is refused with `ERR_APPEAL_LIMIT_EXCEEDED`. The pair
    `CLAIM_DENIED → CLAIM_APPEALED → CLAIM_DENIED` is a genuine cycle and may run
    twice. **Writing off** moves a charge `CLAIM_DENIED → WRITTEN_OFF` and is
    permitted only once both appeals have been used, that is only when
    `appeal_count` equals exactly 2; attempting it earlier is refused with
    `ERR_WRITE_OFF_NOT_PERMITTED`. A write-off carries a `reason` and sets
    `write_off_amount_cents` to the gross amount less `payer_paid_amount_cents` less
    the operative `patient_responsibility_cents`, then recomputes the buckets."

    Design: Corner/state_machines/charge_denial_appeal_cycle_then_write_off_after_cap
    """
    ctx = setup_private_insurance_pending_charge()
    charge_id = ctx["charge"]["id"]
    submit_claim(charge_id)
    validate_success(
        api.adjudicate_charge(
            charge_id,
            {
                "outcome": "DENIED",
                "payer_paid_amount_cents": 0,
                "denial_reason": "Eligibility not on file",
            },
            BILLING,
        )
    )

    too_early = api.write_off_charge(charge_id, {"reason": "Too early"}, BILLING)
    validate_error(too_early, ApiErrorId.ERR_WRITE_OFF_NOT_PERMITTED.value, 409)

    for note, reason in (
        ("First appeal with eligibility proof", "Still not on file"),
        ("Second appeal with school letter", "Final denial"),
    ):
        validate_success(api.appeal_charge(charge_id, {"appeal_note": note}, BILLING))
        validate_success(
            api.adjudicate_charge(
                charge_id,
                {"outcome": "DENIED", "payer_paid_amount_cents": 0, "denial_reason": reason},
                BILLING,
            )
        )

    third_appeal = api.appeal_charge(charge_id, {"appeal_note": "Third appeal"}, BILLING)
    validate_error(third_appeal, ApiErrorId.ERR_APPEAL_LIMIT_EXCEEDED.value, 409)

    written_off = validate_success(
        api.write_off_charge(charge_id, {"reason": "Appeals exhausted"}, BILLING)
    )

    assert written_off["appeal_count"] == 2
    assert written_off["status"] == "WRITTEN_OFF"
    assert written_off["write_off_amount_cents"] == 11_000
    assert written_off["patient_responsibility_cents"] == 1_000

    visit = get_visit(ctx["visit"]["id"])
    assert_visit_buckets(
        visit,
        gross=12_000,
        no_charge=0,
        patient_responsibility=1_000,
        write_off=11_000,
        payer_billed=0,
    )
    assert visit["billing_status"] == "CHARGES_POSTED"


def test_a_settled_self_pay_charge_cannot_be_reversed(api):
    """PRD §3.10: "**Recording a family payment** moves a charge `PENDING → PAID`,
    is permitted only when the route is `SELF_PAY` — a Medicaid or private-insurance
    charge is refused with `ERR_CLAIM_NOT_APPLICABLE` — and requires the supplied
    `amount_cents` to equal the charge's operative `patient_responsibility_cents`
    exactly, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`; on success it stores
    `patient_paid_amount_cents`, recomputes the encounter buckets and may bubble the
    encounter's billing axis to `CHARGES_POSTED`."
    PRD §3.10: "`NO_CHARGE`, `PAID`, `WRITTEN_OFF` and `REVERSED` are the four
    terminal charge states."

    Design: Corner/state_machines/paid_charge_cannot_be_reversed_terminal_lockdown
    """
    ctx = setup_pending_charge()
    charge_id = ctx["charge"]["id"]

    paid = validate_success(
        api.record_patient_payment(charge_id, {"amount_cents": 500}, BILLING)
    )
    assert paid["status"] == "PAID"
    assert paid["patient_paid_amount_cents"] == 500

    resp = api.reverse_charge(
        charge_id, {"reason": "Attempt to unwind a settled charge"}, BILLING
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    visit = get_visit(ctx["visit"]["id"])
    assert_visit_buckets(
        visit,
        gross=12_000,
        no_charge=0,
        patient_responsibility=500,
        write_off=0,
        payer_billed=11_500,
    )
    assert visit["billing_status"] == "CHARGES_POSTED"


def test_claim_routing_refuses_both_wrong_directions(api):
    """PRD §3.10: "**Submitting a claim** moves a charge `PENDING → CLAIM_SUBMITTED`
    and is permitted only when the snapshotted payer route is `MEDICAID` or
    `PRIVATE_INSURANCE`; a self-pay charge submitted as a claim is refused with
    `ERR_CLAIM_NOT_APPLICABLE`."
    PRD §2.6 rung 32: "On `POST /sbhc/charges/{id}/submit-claim` the charge's payer
    route must be Medicaid or private insurance, and on `POST
    /sbhc/charges/{id}/record-patient-payment` it must be self-pay — either violation
    is `ERR_CLAIM_NOT_APPLICABLE`"

    Design: Corner/errors/claim_routing_errors_on_self_pay_submit_and_insured_patient_payment
    """
    self_pay = setup_pending_charge()
    insured = setup_private_insurance_pending_charge()

    wrong_submit = api.submit_claim(self_pay["charge"]["id"], BILLING)
    validate_error(wrong_submit, ApiErrorId.ERR_CLAIM_NOT_APPLICABLE.value, 409)

    wrong_payment = api.record_patient_payment(
        insured["charge"]["id"], {"amount_cents": 1_000}, BILLING
    )
    validate_error(wrong_payment, ApiErrorId.ERR_CLAIM_NOT_APPLICABLE.value, 409)

    assert get_charge(self_pay["charge"]["id"])["status"] == "PENDING"
    assert get_charge(insured["charge"]["id"])["status"] == "PENDING"
    assert get_charge(self_pay["charge"]["id"])["patient_responsibility_cents"] == 500
    assert get_charge(insured["charge"]["id"])["patient_responsibility_cents"] == 1_000


def test_family_payment_must_equal_the_operative_responsibility_exactly(api):
    """PRD §3.10: "requires the supplied `amount_cents` to equal the charge's
    operative `patient_responsibility_cents` exactly, otherwise
    `ERR_PAYMENT_AMOUNT_MISMATCH`"
    PRD §2.6 rung 32: "and on `POST /sbhc/charges/{id}/record-patient-payment` the
    supplied `amount_cents` must equal the charge's operative patient responsibility
    exactly, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/errors/patient_payment_amount_mismatch_returns_payment_amount_mismatch
    """
    ctx = setup_pending_charge()
    charge_id = ctx["charge"]["id"]

    short_payment = api.record_patient_payment(charge_id, {"amount_cents": 400}, BILLING)
    validate_error(short_payment, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, 409)
    assert get_charge(charge_id)["status"] == "PENDING"

    exact = validate_success(
        api.record_patient_payment(charge_id, {"amount_cents": 500}, BILLING)
    )

    assert exact["status"] == "PAID"
    assert exact["patient_paid_amount_cents"] == 500
    assert get_visit(ctx["visit"]["id"])["billing_status"] == "CHARGES_POSTED"
