"""The provisional charge, the final charge, and the five-hop retroactive cascade."""

import pytest

from test_helpers import (
    BILLER,
    VERIFIER,
    api_client,
    bill_encounter,
    record_payment_payload,
    refresh_encounter,
    refresh_health_center,
    refresh_patient,
    setup_boot_fs,
    setup_encounter,
    setup_income_verification,
    setup_patient,
    validate_success,
    verify_income_verification_payload,
)


def _verify(income_verification_id):
    return validate_success(
        api_client.verify_income_verification(
            income_verification_id, verify_income_verification_payload("VERIFY"), VERIFIER
        )
    )


def _self_pay_visit_billed_before_any_documentation():
    ctx = setup_boot_fs()
    patient = setup_patient(mrn="MRN-003", full_name="Dara Kim", household_size=2)
    encounter = setup_encounter(
        ctx,
        patient["id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=12000,
    )
    bill_encounter(encounter, "CLM-3001")
    ctx.update({"patient": patient, "patient_id": patient["id"], "encounter": encounter})
    return ctx


def test_provisional_charge_bills_the_full_gross_when_no_verification_covers_the_visit():
    """With no documentation on file a self-pay visit owes the undiscounted charge.

    PRD 3.5: "Step two handles the absence of documentation. If the
    income-verification selector produced no row (and none was supplied), then
    `sliding_fee_applied` is false, `charge_basis` is `FULL_CHARGE_UNVERIFIED`, both
    `pinned_discount_tier_id` and `income_verification_id` are null, and
    `patient_charge_cents` is the full `gross_charge_cents` when `payer_type` is
    `SELF_PAY` and 0 for any other remaining payer."

    Design: Difficulty/dual_variant_calc/patient_charge_provisional_vs_final_on_retroactive_verification
    """
    ctx = _self_pay_visit_billed_before_any_documentation()
    encounter = ctx["encounter"]

    assert encounter["patient_charge_cents"] == 12000, (
        "the provisional variant charges the full gross to an undocumented "
        f"self-pay patient, got {encounter['patient_charge_cents']}"
    )
    assert encounter["charge_basis"] == "FULL_CHARGE_UNVERIFIED"
    assert encounter["sliding_fee_applied"] is False
    assert encounter["pinned_discount_tier_id"] is None
    assert encounter["income_verification_id"] is None
    assert refresh_encounter(encounter["id"])["pps_claim_status"] == "BILLED"
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 12000


def test_final_charge_rewrites_the_billed_encounter_with_a_negative_adjustment():
    """Retroactive verification re-prices the same visit and moves the claim.

    PRD 3.4: "For each such encounter the server rewrites `patient_charge_cents`,
    `charge_basis`, `pinned_discount_tier_id` and `income_verification_id`, records
    the difference between the newly computed charge and the previously stored one
    in `charge_adjustment_cents`, and moves the claim to `PENDING_ADJUSTMENT` — from
    `BILLED → PENDING_ADJUSTMENT` or from `PAID → PENDING_ADJUSTMENT` as the case
    may be."

    Design: Difficulty/dual_variant_calc/patient_charge_provisional_vs_final_on_retroactive_verification
    """
    ctx = _self_pay_visit_billed_before_any_documentation()
    patient = refresh_patient(ctx["patient_id"])
    verification = setup_income_verification(
        patient,
        declared_annual_income_cents=2190000,
        household_size=2,
        documentation_type="TAX_RETURN",
        effective_date="2026-02-01T00:00:00Z",
    )

    verified = _verify(verification["id"])
    assert verified["fpg_percent"] == pytest.approx(100.00, abs=0.01)

    repriced = refresh_encounter(ctx["encounter"]["id"])
    assert repriced["patient_charge_cents"] == 2500, (
        "the final variant applies the partial-discount band and the nominal "
        f"floor, got {repriced['patient_charge_cents']}"
    )
    assert repriced["charge_basis"] == "SLIDING_FEE_TIER"
    assert repriced["charge_adjustment_cents"] == -9500, (
        "the adjustment is the final amount minus the provisional one, so "
        f"2500 - 12000, got {repriced['charge_adjustment_cents']}"
    )
    assert (
        repriced["pinned_discount_tier_id"] == ctx["tiers_by_label"]["PARTIAL_A"]["id"]
    )
    assert repriced["income_verification_id"] == verification["id"]
    assert repriced["pps_claim_status"] == "PENDING_ADJUSTMENT"
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500


def _managed_care_visit_part_paid_before_any_documentation():
    ctx = setup_boot_fs()
    patient = setup_patient(mrn="MRN-005", full_name="Gia Okafor", household_size=2)
    encounter = setup_encounter(
        ctx,
        patient["id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="MEDICAID_MCO",
        gross_charge_cents=30000,
    )
    bill_encounter(encounter, "CLM-6001")
    paid = validate_success(
        api_client.record_encounter_payment(
            encounter["id"], record_payment_payload(14000), BILLER
        )
    )
    ctx.update(
        {
            "patient": patient,
            "patient_id": patient["id"],
            "encounter": encounter,
            "paid_encounter": paid,
        }
    )
    return ctx


def test_retroactive_verification_rewrites_the_charge_and_restores_the_patient_ledger():
    """The second and third hops re-price the paid claim and rebuild the balance.

    PRD 3.4: "The third hop restores the ledger. Because those encounters'
    `patient_charge_cents` changed, the patient's `patient_balance_cents` is
    recomputed from the conservation rule of section 2.8 and the patient's `version`
    increments by one."

    Design: Difficulty/transitive_cascade/retroactive_verification_cascades_charge_ledger_and_receivable_depth_four
    """
    ctx = _managed_care_visit_part_paid_before_any_documentation()
    assert ctx["encounter"]["patient_charge_cents"] == 0, (
        "an undocumented managed-care visit owes nothing provisionally"
    )
    assert ctx["encounter"]["charge_basis"] == "FULL_CHARGE_UNVERIFIED"

    patient = refresh_patient(ctx["patient_id"])
    verification = setup_income_verification(
        patient,
        declared_annual_income_cents=2190000,
        household_size=2,
        documentation_type="TAX_RETURN",
        effective_date="2026-02-01T00:00:00Z",
    )
    verified = _verify(verification["id"])

    assert verified["status"] == "VERIFIED"
    assert verified["fpg_percent"] == pytest.approx(100.00, abs=0.01)
    assert verified["assigned_tier_label"] == "PARTIAL_A"

    repriced = refresh_encounter(ctx["encounter"]["id"])
    assert repriced["patient_charge_cents"] == 2500, (
        "the managed-care clamp holds the charge at the nominal fee, got "
        f"{repriced['patient_charge_cents']}"
    )
    assert repriced["charge_basis"] == "SLIDING_FEE_TIER"
    assert repriced["charge_adjustment_cents"] == 2500, (
        "the adjustment is 2500 minus the provisional 0, got "
        f"{repriced['charge_adjustment_cents']}"
    )
    assert repriced["pps_claim_status"] == "PENDING_ADJUSTMENT"
    assert repriced["income_verification_id"] == verification["id"]
    assert (
        repriced["pinned_discount_tier_id"] == ctx["tiers_by_label"]["PARTIAL_A"]["id"]
    )

    reloaded_patient = refresh_patient(ctx["patient_id"])
    assert reloaded_patient["patient_balance_cents"] == 2500
    assert reloaded_patient["sliding_fee_status"] == "VERIFIED"


def test_retroactive_verification_recomputes_the_residual_and_the_grantee_receivable():
    """The fourth and fifth hops move the wraparound residual and roll it up.

    PRD 3.4: "The fifth hop rolls the change up to the grantee. Because residuals
    moved, `wraparound_receivable_cents` is recomputed and the grantee's `version`
    increments by one." The residual itself is defined in PRD 3.7: "Then
    `wraparound_due_cents` is the greater of 0 and the quantity
    `pps_encounter_rate_cents` minus `mco_paid_cents` minus the counted patient
    portion."

    Design: Difficulty/transitive_cascade/retroactive_verification_cascades_charge_ledger_and_receivable_depth_four
    """
    ctx = _managed_care_visit_part_paid_before_any_documentation()
    assert ctx["paid_encounter"]["wraparound_due_cents"] == 4000, (
        "18000 minus a 14000 payment minus a counted patient portion of 0, got "
        f"{ctx['paid_encounter']['wraparound_due_cents']}"
    )
    assert (
        refresh_health_center(ctx["health_center_id"])["wraparound_receivable_cents"]
        == 4000
    )

    patient = refresh_patient(ctx["patient_id"])
    verification = setup_income_verification(
        patient,
        declared_annual_income_cents=2190000,
        household_size=2,
        documentation_type="TAX_RETURN",
        effective_date="2026-02-01T00:00:00Z",
    )
    _verify(verification["id"])

    repriced = refresh_encounter(ctx["encounter"]["id"])
    assert repriced["wraparound_due_cents"] == 1500, (
        "18000 minus 14000 minus the newly counted 2500 patient portion, got "
        f"{repriced['wraparound_due_cents']}"
    )
    assert (
        refresh_health_center(ctx["health_center_id"])["wraparound_receivable_cents"]
        == 1500
    ), "the grantee receivable follows the residual down"
