"""The three pricing regimes, the sliding-fee arithmetic and the money conservation identity."""

from types import SimpleNamespace

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    make_billing_specialist_headers,
    assert_coverage,
    assert_money_split_closes,
    assert_same_date,
    auto_procedure_id,
    build_coverage,
    build_patient,
    build_school_consent,
    build_site,
    exam_encounter,
    get_success_data,
    make_program_admin_headers,
    make_site_coordinator_headers,
    perform_procedure,
    plan_procedure,
    register_encounter,
    screen_encounter,
    set_clock,
    setup_program_site_and_staff,
    setup_screened_and_examined,
    setup_treated_encounter_with_varnish,
    setup_visit_in_progress,
    validate_error,
    validate_success,
)

ADMIN = make_program_admin_headers()


def _two_payer_fixture():
    """Two patients at one visit with the identical procedure set but different payers."""
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(
        stack, scope_tier="SCREENING_FLUORIDE_SEALANT", payer_type="MEDICAID_MCO",
        patient_overrides={"external_ref": "S-001", "annual_household_income_cents": 3000000},
    )
    patient2 = build_patient(
        stack.site_id, stack.coord_headers, external_ref="S-002", first_name="Noah",
        last_name="Park", date_of_birth="2015-11-20", household_size=3,
        annual_household_income_cents=7200000,
    )
    consent2 = build_school_consent(
        patient2["id"], stack.site_id, stack.pp_id, stack.coord_headers,
        scope_tier="SCREENING_FLUORIDE_SEALANT", guardian_name="Ivy Park",
    )
    coverage2 = build_coverage(patient2["id"], payer_type="COMMERCIAL_FFS")

    register_encounter(stack)
    medicaid_enc = stack.enc_id
    register_encounter(stack, patient_id=patient2["id"], consent_id=consent2["id"],
                       coverage_id=coverage2["id"])
    commercial_enc = stack.enc_id

    for encounter_id in (medicaid_enc, commercial_enc):
        screen_encounter(stack, encounter_id=encounter_id)
        exam_encounter(stack, encounter_id=encounter_id)
        varnish = plan_procedure(stack, "D1206", encounter_id=encounter_id)
        perform_procedure(stack, varnish["id"])

    return SimpleNamespace(stack=stack, medicaid_enc=medicaid_enc, commercial_enc=commercial_enc)


def test_medicaid_encounter_rate_allows_the_whole_encounter_total(api):
    """PRD §3.6: "Under `MEDICAID_ENCOUNTER_RATE`, an encounter with no `PERFORMED` procedures
    at all has an `allowed_amount_cents` of zero; otherwise the allowed amount is the lesser
    of a single all-inclusive encounter rate of 18,500 cents and the encounter's own
    `total_charge_cents`."
    PRD §3.6: "Under `MEDICAID_ENCOUNTER_RATE` the patient's share is zero, flatly, because
    balance-billing a Medicaid member is prohibited."
    PRD §3.6: "Finally, `plan_paid_cents` is `allowed_amount_cents` minus
    `patient_responsibility_cents`, and `write_off_cents` is `total_charge_cents` minus
    `allowed_amount_cents`."

    Design: Difficulty/dual_variant_calc/medicaid_encounter_rate_vs_commercial_fee_schedule_on_identical_procedure_sets
    """
    fx = _two_payer_fixture()
    encounter = validate_success(
        api.price_encounter(fx.medicaid_enc, {}, fx.stack.billing_headers)
    )
    assert encounter["subtotal_cents"] == 13825
    assert encounter["supply_surcharge_cents"] == 1200
    assert encounter["total_charge_cents"] == 15025
    assert encounter["pricing_regime"] == "MEDICAID_ENCOUNTER_RATE"
    assert encounter["allowed_amount_cents"] == 15025
    assert encounter["patient_responsibility_cents"] == 0
    assert encounter["plan_paid_cents"] == 15025
    assert encounter["write_off_cents"] == 0
    assert_money_split_closes(encounter)


def test_commercial_fee_schedule_sums_per_line_minima_and_never_allows_the_surcharge(api):
    """PRD §3.6: "Under `COMMERCIAL_FEE_SCHEDULE`, the allowed amount is built line by line:
    for each `PERFORMED` procedure, take the lesser of its own `charge_cents` and the
    contracted schedule amount for its code — 2,600 cents for `D0190`, 4,300 for `D0150`,
    3,375 for `D1206`, 4,725 for `D1351` and 3,100 for `D0272` — and sum those per-line
    minima."
    PRD §3.6: "**The supply surcharge is never allowable under the commercial schedule**,
    even though it sits inside `total_charge_cents` and is therefore inside the Medicaid cap."
    PRD §3.6: "Under `COMMERCIAL_FEE_SCHEDULE` the share is 20 percent of the allowed amount,
    rounded half up to a whole cent — a single multiplication against the allowed amount, in
    which the patient's household size and income never participate and no floor ever
    applies."

    Design: Difficulty/dual_variant_calc/medicaid_encounter_rate_vs_commercial_fee_schedule_on_identical_procedure_sets
    """
    fx = _two_payer_fixture()
    medicaid = validate_success(api.price_encounter(fx.medicaid_enc, {}, fx.stack.billing_headers))
    commercial = validate_success(
        api.price_encounter(fx.commercial_enc, {}, fx.stack.billing_headers)
    )
    assert commercial["subtotal_cents"] == 13825
    assert commercial["total_charge_cents"] == 15025
    assert commercial["pricing_regime"] == "COMMERCIAL_FEE_SCHEDULE"
    assert commercial["allowed_amount_cents"] == 10275
    assert commercial["patient_responsibility_cents"] == 2055
    assert commercial["plan_paid_cents"] == 8220
    assert commercial["write_off_cents"] == 4750
    assert_money_split_closes(commercial)
    assert commercial["allowed_amount_cents"] != medicaid["allowed_amount_cents"], (
        "The identical procedure set must price differently under the two regimes"
    )


def _band_d_fixture():
    """A band-D uninsured encounter carrying five PERFORMED procedures."""
    stack = setup_screened_and_examined(
        scope_tier="SCREENING_FLUORIDE_SEALANT", payer_type="UNINSURED",
        screening={"cavitated_lesion_count": 2},
        patient_overrides={"household_size": 4, "annual_household_income_cents": 6099000},
    )
    varnish = plan_procedure(stack, "D1206")
    seal3 = plan_procedure(stack, "D1351", tooth_number=3, surface="O")
    seal14 = plan_procedure(stack, "D1351", tooth_number=14, surface="O")
    for proc in (varnish, seal3, seal14):
        perform_procedure(stack, proc["id"])
    return stack


def test_uninsured_determination_puts_the_household_in_band_d(api):
    """PRD §3.6: "The patient's `annual_household_income_cents` is divided by that threshold,
    multiplied by 100, and rounded half up to exactly one decimal place to give
    `fpl_percent`."
    PRD §3.6: "above 138.0 and at or below 175.0 is band `C`; above 175.0 and at or below
    200.0 is band `D`; anything above 200.0 is band `E`."

    Design: Difficulty/combinatorial_formula/sliding_fee_rounding_order_round_each_line_then_sum
    """
    stack = _band_d_fixture()
    coverage = validate_success(api.get_coverage(stack.cov_id, ADMIN))
    assert_coverage(coverage)
    assert coverage["fpl_percent"] == pytest.approx(190.0, abs=0.01)
    assert coverage["sliding_fee_band"] == "D"


def test_sliding_fee_rounds_each_line_before_summing(api):
    """PRD §3.6: "Take the encounter's `PERFORMED` procedures in `created_at` ascending order,
    multiply each one's `charge_cents` by one minus the band's discount fraction, round each
    product half up to a whole cent, and only then sum the rounded per-line amounts. Summing
    first and rounding once produces a different number and is not what this system computes."
    PRD §3.6: "Under `UNINSURED_SLIDING_FEE` the encounter is self-pay, so the allowed amount
    **is** the patient's share: `allowed_amount_cents` is set equal to
    `patient_responsibility_cents` after step five has run."

    Design: Difficulty/combinatorial_formula/sliding_fee_rounding_order_round_each_line_then_sum
    """
    stack = _band_d_fixture()
    encounter = validate_success(api.price_encounter(stack.enc_id, {}, stack.billing_headers))
    assert encounter["subtotal_cents"] == 26525
    assert encounter["supply_surcharge_cents"] == 2000
    assert encounter["total_charge_cents"] == 28525
    assert encounter["pricing_regime"] == "UNINSURED_SLIDING_FEE"
    assert encounter["patient_responsibility_cents"] == 17242, (
        "Round-per-line-then-sum gives 17242; summing first and rounding once gives 17241"
    )
    assert encounter["allowed_amount_cents"] == 17242
    assert encounter["plan_paid_cents"] == 0
    assert encounter["write_off_cents"] == 11283
    assert_money_split_closes(encounter)


def test_supply_surcharge_tier_is_keyed_on_the_pre_surcharge_subtotal(api):
    """PRD §3.6: "A flat per-encounter surcharge is selected by a tier keyed **on
    `subtotal_cents`**, the pre-surcharge figure, and computed exactly once; it is never
    re-evaluated against `total_charge_cents` even though `total_charge_cents` contains it."
    PRD §3.6: "A subtotal above 5,000 and at or below 15,000 cents yields 1,200 cents."

    Design: Difficulty/combinatorial_formula/supply_surcharge_tier_keyed_on_presurcharge_subtotal_not_on_total
    """
    stack = setup_treated_encounter_with_varnish(payer_type="MEDICAID_MCO")
    encounter = validate_success(api.price_encounter(stack.enc_id, {}, stack.billing_headers))
    assert encounter["subtotal_cents"] == 13825
    assert encounter["supply_surcharge_cents"] == 1200, (
        "Re-tiering against the 15025 total would wrongly select 2000"
    )
    assert encounter["total_charge_cents"] == 15025


def test_total_charge_is_subtotal_plus_the_single_surcharge(api):
    """PRD §3.6: "`subtotal_cents` is the sum of `charge_cents` over every procedure of this
    encounter whose `status` is exactly `PERFORMED`."
    PRD §3.6: "`total_charge_cents` is then `subtotal_cents` plus `supply_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/supply_surcharge_tier_keyed_on_presurcharge_subtotal_not_on_total
    """
    stack = setup_treated_encounter_with_varnish(payer_type="MEDICAID_MCO")
    encounter = validate_success(api.price_encounter(stack.enc_id, {}, stack.billing_headers))
    assert encounter["total_charge_cents"] == (
        encounter["subtotal_cents"] + encounter["supply_surcharge_cents"]
    )
    assert encounter["allowed_amount_cents"] == 15025
    assert encounter["plan_paid_cents"] == 15025
    assert encounter["write_off_cents"] == 0


def _empty_performed_set_fixture():
    """An UNINSURED band-A encounter whose two auto-created procedures have both been voided."""
    stack = setup_screened_and_examined(
        scope_tier="SCREENING_FLUORIDE", payer_type="UNINSURED",
        screening={
            "cavitated_lesion_count": 0,
            "pain_reported": False,
            "abscess_or_swelling": False,
            "untreated_decay_present": False,
        },
        patient_overrides={"household_size": 4, "annual_household_income_cents": 3000000},
    )
    for code in ("D0190", "D0150"):
        get_success_data(
            api_client.void_procedure(
                auto_procedure_id(stack.enc_id, code),
                {"void_reason": "DOCUMENTATION_ERROR"},
                stack.dentist_headers,
            )
        )
    get_success_data(api_client.close_encounter(stack.enc_id, stack.dentist_headers))
    return stack


def test_pricing_an_empty_performed_set_yields_all_zero_money(api):
    """PRD §3.6: "A subtotal of exactly zero yields a `supply_surcharge_cents` of zero."
    PRD §3.6: "An encounter with no `PERFORMED` procedures has a
    `patient_responsibility_cents` of zero under every regime."

    Design: Difficulty/boundary_precision_check/pricing_an_encounter_with_zero_performed_procedures_yields_all_zero_money
    """
    stack = _empty_performed_set_fixture()
    encounter = validate_success(api.price_encounter(stack.enc_id, {}, stack.billing_headers))
    assert encounter["billing_status"] == "PRICED"
    assert encounter["subtotal_cents"] == 0
    assert encounter["supply_surcharge_cents"] == 0
    assert encounter["total_charge_cents"] == 0
    assert encounter["allowed_amount_cents"] == 0
    assert encounter["patient_responsibility_cents"] == 0, (
        "The 2500 nominal fee floor must not be applied to an empty PERFORMED set"
    )
    assert encounter["plan_paid_cents"] == 0
    assert encounter["write_off_cents"] == 0
    assert_money_split_closes(encounter)


def test_an_emptied_encounter_still_pins_its_regime_and_releases_its_chair_minutes(api):
    """PRD §3.6: "The coverage's `payer_type` selects the pricing regime, which is pinned onto
    the encounter as `pricing_regime` and remains the record of which branch produced the
    money: `MEDICAID_MCO` selects `MEDICAID_ENCOUNTER_RATE`, `COMMERCIAL_FFS` selects
    `COMMERCIAL_FEE_SCHEDULE`, and `UNINSURED` selects `UNINSURED_SLIDING_FEE`."
    PRD §3.5: "voiding a `PLANNED` procedure releases its chair minutes"

    Design: Difficulty/boundary_precision_check/pricing_an_encounter_with_zero_performed_procedures_yields_all_zero_money
    """
    stack = _empty_performed_set_fixture()
    encounter = validate_success(api.price_encounter(stack.enc_id, {}, stack.billing_headers))
    assert encounter["pricing_regime"] == "UNINSURED_SLIDING_FEE"
    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["booked_chair_minutes"] == 0


def _fpl_boundary_fixture():
    """Two four-person households, one at exactly 100.0 percent and one at 100.1 percent."""
    set_clock("2026-05-11T09:00:00Z")
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    edge = build_patient(site["id"], coord, external_ref="S-001", household_size=4,
                         annual_household_income_cents=3210000)
    over = build_patient(site["id"], coord, external_ref="S-002", first_name="Noah",
                         last_name="Park", date_of_birth="2015-11-20", household_size=4,
                         annual_household_income_cents=3213210)
    cov_edge = build_coverage(edge["id"], payer_type="UNINSURED", verify=False)
    cov_over = build_coverage(over["id"], payer_type="UNINSURED", verify=False)
    return SimpleNamespace(cov_edge_id=cov_edge["id"], cov_over_id=cov_over["id"])


def test_exactly_one_hundred_percent_of_poverty_stays_in_band_a(api):
    """PRD §3.6: "The federal poverty threshold for the household is 15,600 dollars —
    1,560,000 cents — for a household of one, plus 5,500 dollars, or 550,000 cents, for each
    additional person; that is, the base amount plus the per-person increment multiplied by
    one less than the patient's `household_size`."
    PRD §3.6: "A percentage of exactly 100.0 is therefore band `A`, exactly 138.0 is band `B`,
    exactly 175.0 is band `C` and exactly 200.0 is band `D`."
    PRD §3.6: "`determination_date` is set to the logical clock date."

    Design: Difficulty/boundary_precision_check/fpl_percent_exactly_one_hundred_stays_band_a_while_one_hundred_point_one_moves_to_band_b
    """
    fx = _fpl_boundary_fixture()
    coverage = validate_success(
        api.verify_coverage(fx.cov_edge_id, {"verified_through_date": "2026-12-31"}, _billing())
    )
    assert coverage["fpl_percent"] == pytest.approx(100.0, abs=0.01)
    assert coverage["sliding_fee_band"] == "A"
    assert coverage["verification_status"] == "VERIFIED"
    assert_same_date(coverage["determination_date"], "2026-05-11", "determination_date")


def test_one_tenth_of_a_percent_above_the_ceiling_drops_to_band_b(api):
    """PRD §3.6: "an `fpl_percent` at or below 100.0 is band `A`; above 100.0 and at or below
    138.0 is band `B`; above 138.0 and at or below 175.0 is band `C`"
    PRD §3.6: "The patient's `annual_household_income_cents` is divided by that threshold,
    multiplied by 100, and rounded half up to exactly one decimal place to give `fpl_percent`."

    Design: Difficulty/boundary_precision_check/fpl_percent_exactly_one_hundred_stays_band_a_while_one_hundred_point_one_moves_to_band_b
    """
    fx = _fpl_boundary_fixture()
    coverage = validate_success(
        api.verify_coverage(fx.cov_over_id, {"verified_through_date": "2026-12-31"}, _billing())
    )
    assert coverage["fpl_percent"] == pytest.approx(100.1, abs=0.01)
    assert coverage["sliding_fee_band"] == "B"


def _billing():
    return make_billing_specialist_headers()


def _priced_band_a_fixture():
    """A band-A uninsured encounter priced with three PERFORMED procedures."""
    stack = setup_treated_encounter_with_varnish(
        payer_type="UNINSURED",
        patient_overrides={"household_size": 4, "annual_household_income_cents": 3000000},
    )
    stack.priced = get_success_data(
        api_client.price_encounter(stack.enc_id, {}, stack.billing_headers)
    )
    return stack


def test_money_split_closes_before_the_void_and_the_floor_raises_the_poorest_share(api):
    """PRD §2.10: "For every encounter whose `billing_status` is `PRICED`, `CLAIMED`, `PAID`
    or `DENIED`, its `total_charge_cents` equals the sum of `plan_paid_cents`,
    `patient_responsibility_cents` and `write_off_cents`."
    PRD §3.6: "The floor genuinely *raises* the share for the poorest households: a band `A`
    patient's discounted total is zero and their responsibility is 2,500 cents."

    Design: Difficulty/compensating_invariant/money_split_identity_closes_again_after_void_and_reprice
    """
    stack = _priced_band_a_fixture()
    priced = stack.priced
    assert priced["total_charge_cents"] == 15025
    assert priced["plan_paid_cents"] == 0
    assert priced["patient_responsibility_cents"] == 2500
    assert priced["write_off_cents"] == 12525
    assert_money_split_closes(priced)


def test_money_split_closes_again_after_a_void_and_a_reprice(api):
    """PRD §3.5: "In every case the owning encounter's `subtotal_cents`,
    `supply_surcharge_cents` and `total_charge_cents` are recomputed from the procedures that
    remain `PERFORMED`, and if the encounter's `billing_status` was `PRICED` it reverts to
    `UNBILLED` with its four money fields zeroed and `pricing_regime` cleared to null."
    PRD §2.10: "The identity holds under all three pricing regimes, holds when a manual
    patient-share override has been applied, and must be re-established exactly after every
    void-driven or taint-driven recompute."

    Design: Difficulty/compensating_invariant/money_split_identity_closes_again_after_void_and_reprice
    """
    stack = _priced_band_a_fixture()
    voided = validate_success(
        api.void_procedure(stack.varnish_id, {"void_reason": "PATIENT_DECLINED_AT_CHAIR"},
                           stack.dentist_headers)
    )
    assert voided["status"] == "VOIDED"
    reverted = validate_success(api.get_encounter(stack.enc_id, ADMIN))
    assert reverted["billing_status"] == "UNBILLED"
    assert reverted["pricing_regime"] is None

    repriced = validate_success(api.price_encounter(stack.enc_id, {}, stack.billing_headers))
    assert repriced["billing_status"] == "PRICED"
    assert repriced["subtotal_cents"] == 9300
    assert repriced["supply_surcharge_cents"] == 1200
    assert repriced["total_charge_cents"] == 10500
    assert repriced["allowed_amount_cents"] == 2500
    assert repriced["patient_responsibility_cents"] == 2500
    assert repriced["plan_paid_cents"] == 0
    assert repriced["write_off_cents"] == 8000
    assert_money_split_closes(repriced)

    patient = validate_success(api.get_patient(stack.patient_id, ADMIN))
    assert patient["varnish_applications_in_period"] == 0
    assert patient["last_varnish_date"] is None


def _closed_but_unbilled_fixture():
    stack = setup_treated_encounter_with_varnish(payer_type="MEDICAID_MCO")
    get_success_data(api_client.close_encounter(stack.enc_id, stack.dentist_headers))
    return stack


def test_the_billing_axis_walks_its_cycle_while_the_clinical_axis_stays_closed(api):
    """PRD §3.5: "`clinical_status` tracks what happened in the chair; `billing_status` tracks
    what happened to the money. Neither constrains the other: an encounter can be `CLOSED` and
    still `UNBILLED`, or `TREATED` and already `PAID`."
    PRD §3.6: "`CLAIMED → PAID` and `CLAIMED → DENIED` record the payer's decision, driven by
    an `outcome` of `PAID` or `DENIED`, with a `denial_reason` recorded on the denial. `DENIED
    → CLAIMED` resubmits a denied claim without repricing it and clears `denial_reason` back
    to null."

    Design: Difficulty/non_linear_state_machine/encounter_clinical_and_billing_axes_advance_independently_including_denied_resubmit
    """
    stack = _closed_but_unbilled_fixture()
    billing = stack.billing_headers
    validate_success(api.price_encounter(stack.enc_id, {}, billing))
    validate_success(api.claim_encounter(stack.enc_id, billing))
    denied = validate_success(
        api.adjudicate_encounter(stack.enc_id, {"outcome": "DENIED", "denial_reason": "MISSING_NPI"},
                                 billing)
    )
    assert denied["billing_status"] == "DENIED"
    assert denied["denial_reason"] == "MISSING_NPI"

    resubmitted = validate_success(api.claim_encounter(stack.enc_id, billing))
    assert resubmitted["billing_status"] == "CLAIMED"
    assert resubmitted["denial_reason"] is None

    paid = validate_success(api.adjudicate_encounter(stack.enc_id, {"outcome": "PAID"}, billing))
    assert paid["billing_status"] == "PAID"
    assert paid["clinical_status"] == "CLOSED", "The clinical axis never moved"


def test_repricing_is_not_required_between_a_denial_and_a_resubmission(api):
    """PRD §3.6: "`DENIED → CLAIMED` resubmits a denied claim without repricing it and clears
    `denial_reason` back to null."
    PRD §3.6: "Under `MEDICAID_ENCOUNTER_RATE`, an encounter with no `PERFORMED` procedures at
    all has an `allowed_amount_cents` of zero; otherwise the allowed amount is the lesser of a
    single all-inclusive encounter rate of 18,500 cents and the encounter's own
    `total_charge_cents`."

    Design: Difficulty/non_linear_state_machine/encounter_clinical_and_billing_axes_advance_independently_including_denied_resubmit
    """
    stack = _closed_but_unbilled_fixture()
    billing = stack.billing_headers
    validate_success(api.price_encounter(stack.enc_id, {}, billing))
    validate_success(api.claim_encounter(stack.enc_id, billing))
    validate_success(
        api.adjudicate_encounter(stack.enc_id, {"outcome": "DENIED", "denial_reason": "MISSING_NPI"},
                                 billing)
    )
    validate_success(api.claim_encounter(stack.enc_id, billing))
    paid = validate_success(api.adjudicate_encounter(stack.enc_id, {"outcome": "PAID"}, billing))

    assert paid["total_charge_cents"] == 15025
    assert paid["allowed_amount_cents"] == 15025
    assert paid["pricing_regime"] == "MEDICAID_ENCOUNTER_RATE"
    assert_money_split_closes(paid)


def test_verifying_uninsured_coverage_without_an_income_figure_is_refused(api):
    """PRD §2.6: "Verifying a coverage whose `payer_type` is `UNINSURED` requires the
    patient's `annual_household_income_cents` to be non-null, because the federal-poverty
    percentage and the sliding-fee band cannot otherwise be determined."

    Design: Corner/validations/verifying_uninsured_coverage_without_income_returns_sliding_fee_missing
    """
    set_clock("2026-05-11T09:00:00Z")
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    patient = build_patient(site["id"], coord, external_ref="S-001")
    coverage = build_coverage(patient["id"], payer_type="UNINSURED", verify=False)

    resp = api.verify_coverage(coverage["id"], {"verified_through_date": "2026-12-31"}, _billing())
    validate_error(resp, ApiErrorId.ERR_SLIDING_FEE_MISSING.value, 422)

    after = validate_success(api.get_coverage(coverage["id"], ADMIN))
    assert after["verification_status"] == "UNVERIFIED"
    assert after["sliding_fee_band"] is None
    assert after["fpl_percent"] is None


def test_a_manual_share_may_not_be_supplied_on_a_medicaid_encounter(api):
    """PRD §2.6: "A `manual_patient_responsibility_cents` override may not be supplied on an
    encounter whose coverage `payer_type` is `MEDICAID_MCO`; balance-billing a Medicaid member
    is prohibited outright rather than merely computed to zero."
    PRD §3.6: "Supplying it on an encounter whose coverage is `MEDICAID_MCO` is refused
    outright with `ERR_MEDICAID_BALANCE_BILL` — the prohibition is on the attempt, not merely
    on the resulting number."

    Design: Corner/validations/manual_patient_share_on_a_medicaid_encounter_returns_balance_bill_error
    """
    stack = setup_screened_and_examined(scope_tier="SCREENING_FLUORIDE", payer_type="MEDICAID_MCO")
    # Zero is inside the rung-6 range under any reading of "the encounter's
    # total_charge_cents", so the refusal can only come from the balance-bill rung.
    resp = api.price_encounter(
        stack.enc_id, {"manual_patient_responsibility_cents": 0}, stack.billing_headers
    )
    validate_error(resp, ApiErrorId.ERR_MEDICAID_BALANCE_BILL.value, 422)

    encounter = validate_success(api.get_encounter(stack.enc_id, ADMIN))
    assert encounter["billing_status"] == "UNBILLED"
    assert encounter["patient_responsibility_cents"] == 0
    assert encounter["pricing_regime"] is None


def test_pricing_against_a_never_verified_coverage_is_refused_and_writes_nothing(api):
    """PRD §2.6: "The encounter must cite a coverage whose `verification_status` is
    `VERIFIED`; an encounter with a null `coverage_id` fails here too."
    PRD §2.8: "If the coverage is already `UNVERIFIED` or already `EXPIRED` — or if the
    encounter has no `coverage_id` at all — the same `ERR_COVERAGE_UNVERIFIED` is returned
    with no write and no version change."

    Design: Corner/validations/pricing_against_an_unverified_coverage_returns_coverage_unverified
    """
    stack = setup_screened_and_examined(
        scope_tier="SCREENING_FLUORIDE", payer_type="UNINSURED", verify_coverage=False,
        patient_overrides={"household_size": 4, "annual_household_income_cents": 3000000},
    )
    resp = api.price_encounter(stack.enc_id, {}, stack.billing_headers)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_UNVERIFIED.value, 422)

    coverage = validate_success(api.get_coverage(stack.cov_id, ADMIN))
    assert coverage["verification_status"] == "UNVERIFIED"
    assert coverage["version"] == 1, "A coverage that was never VERIFIED is not swept"
    assert validate_success(api.get_encounter(stack.enc_id, ADMIN))["billing_status"] == "UNBILLED"
