"""The inability-to-pay waiver, the wraparound residual, and the compensating void."""

import pytest

from test_helpers import (
    ApiErrorId,
    BILLER,
    REP,
    SECOND_OFFICER,
    SECOND_REP,
    api_client,
    decide_waiver,
    refresh_encounter,
    refresh_health_center,
    refresh_patient,
    setup_boot_fs,
    setup_encounter,
    setup_requested_waiver,
    setup_verified_patient,
    setup_wraparound_claimed_encounter,
    validate_error,
    validate_success,
    void_encounter_payload,
)


def _managed_care_claim_with_a_requested_waiver():
    """A partial-discount managed-care visit clamped to the nominal fee, residual claimed."""
    ctx = setup_boot_fs()
    verified = setup_verified_patient(
        ctx,
        mrn="MRN-004",
        full_name="Eli Mora",
        household_size=1,
        declared_annual_income_cents=2430000,
        documentation_type="W2",
    )
    assert verified["income_verification"]["fpg_percent"] == pytest.approx(
        150.00, abs=0.01
    ), "2430000 against the 2026 guideline amount for a household of one is 150.00"
    assert verified["income_verification"]["assigned_tier_label"] == "PARTIAL_B"

    encounter = setup_wraparound_claimed_encounter(
        ctx,
        verified["patient_id"],
        payer_type="MEDICAID_MCO",
        gross_charge_cents=30000,
        claim_reference="CLM-4001",
        mco_paid_cents=14000,
        encounter_date="2026-03-01T00:00:00Z",
    )
    waiver = setup_requested_waiver(
        encounter, waiver_reason="NO_INCOME", headers=SECOND_REP
    )
    ctx.update(
        {
            "patient": verified["patient"],
            "patient_id": verified["patient_id"],
            "encounter": encounter,
            "waiver": waiver,
        }
    )
    return ctx


def test_granting_the_waiver_lifts_the_residual_and_forces_a_rebill_without_touching_the_claim():
    """The counted patient portion drops to zero, so the outstanding claim must be re-claimed.

    PRD 3.6: "In the third hop, because the residual changed while the encounter's
    `wraparound_status` was `CLAIMED`, that status moves `CLAIMED →
    REBILL_REQUIRED`, the grantee's `wraparound_receivable_cents` is recomputed, and
    the grantee's `version` increments by one." PRD 3.6 adds: "Notice what the grant
    does *not* touch: `pps_claim_status` is untouched, which is the clearest
    illustration that the encounter's two state dimensions move independently."

    Design: Difficulty/combinatorial_formula/wraparound_pinned_evaluation_order_with_granted_waiver_mode_c
    """
    ctx = _managed_care_claim_with_a_requested_waiver()
    assert ctx["encounter"]["wraparound_due_cents"] == 1500, (
        "18000 minus 14000 minus a counted patient portion of 2500, got "
        f"{ctx['encounter']['wraparound_due_cents']}"
    )
    assert ctx["encounter"]["wraparound_status"] == "CLAIMED"

    granted = decide_waiver(ctx["waiver"], "GRANT", SECOND_OFFICER)
    assert granted["status"] == "GRANTED"
    assert granted["waived_amount_cents"] == 2500, (
        "the waiver's waived_amount_cents is set to the encounter's "
        f"patient_charge_cents, got {granted['waived_amount_cents']}"
    )

    after = refresh_encounter(ctx["encounter"]["id"])
    assert after["wraparound_due_cents"] == 4000, (
        "with the counted portion at zero the residual is 18000 minus 14000, got "
        f"{after['wraparound_due_cents']}"
    )
    assert after["wraparound_status"] == "REBILL_REQUIRED"
    assert after["pps_claim_status"] == "PAID", (
        "the grant leaves the claim dimension exactly where it was"
    )
    assert (
        refresh_health_center(ctx["health_center_id"])["wraparound_receivable_cents"]
        == 4000
    )


def test_the_granted_waiver_freezes_the_tier_and_the_charge_while_clearing_the_ledger():
    """Recomputation re-enters below the tier assignment, so the charge itself is frozen.

    PRD 3.5: "Every later recomputation re-enters at the fifth step with the first
    four frozen: a granted waiver never re-runs the tier assignment, and a
    retroactive verification never re-opens a decided waiver." PRD 3.6 states the
    ledger hop: "In the first hop, because the encounter's `waived_amount_cents`
    changed, the patient's `patient_balance_cents` is reduced by that amount and the
    patient's `version` increments by one."

    Design: Difficulty/combinatorial_formula/wraparound_pinned_evaluation_order_with_granted_waiver_mode_c
    """
    ctx = _managed_care_claim_with_a_requested_waiver()
    assert ctx["encounter"]["patient_charge_cents"] == 2500, (
        "the managed-care clamp reduces a 12000 partial-discount amount to the "
        f"nominal fee, got {ctx['encounter']['patient_charge_cents']}"
    )
    assert ctx["encounter"]["pps_encounter_rate_cents"] == 18000

    decide_waiver(ctx["waiver"], "GRANT", SECOND_OFFICER)

    after = refresh_encounter(ctx["encounter"]["id"])
    assert after["waived_amount_cents"] == 2500
    assert after["patient_charge_cents"] == 2500, (
        "the patient charge is frozen by the grant, not zeroed"
    )
    assert (
        after["pinned_discount_tier_id"] == ctx["tiers_by_label"]["PARTIAL_B"]["id"]
    ), "the tier assignment is not re-run"
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 0, (
        "the balance falls by the waived amount, leaving nothing owed"
    )


def _second_self_pay_visit_with_a_granted_waiver():
    """Two identical self-pay visits, the second one waived."""
    ctx = setup_boot_fs()
    verified = setup_verified_patient(
        ctx,
        mrn="MRN-001",
        full_name="Ada Rivera",
        household_size=2,
        declared_annual_income_cents=2190000,
    )
    first = setup_encounter(
        ctx,
        verified["patient_id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=12000,
    )
    balance_before = refresh_patient(verified["patient_id"])["patient_balance_cents"]
    second = setup_encounter(
        ctx,
        verified["patient_id"],
        encounter_date="2026-03-10T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=12000,
    )
    waiver = setup_requested_waiver(
        second, waiver_reason="HARDSHIP_ATTESTATION", headers=REP
    )
    granted = decide_waiver(waiver, "GRANT", SECOND_OFFICER)
    ctx.update(
        {
            "patient_id": verified["patient_id"],
            "first_encounter": first,
            "second_encounter": second,
            "waiver": granted,
            "balance_before": balance_before,
        }
    )
    return ctx


def test_a_nonpayment_void_is_refused_on_an_encounter_protected_by_a_granted_waiver():
    """The inability-to-pay finding permanently blocks a non-payment void.

    PRD 3.6: "A granted waiver means the patient was found unable to pay, so the
    encounter may never afterwards be voided for non-payment: an attempt to void it
    with `void_reason` equal to `NONPAYMENT` is rejected with
    `ERR_INABILITY_TO_PAY_PROTECTED`."

    Design: Difficulty/compensating_invariant/void_restores_patient_balance_with_zero_drift_after_a_granted_waiver
    """
    ctx = _second_self_pay_visit_with_a_granted_waiver()
    assert ctx["balance_before"] == 2500
    assert ctx["waiver"]["waived_amount_cents"] == 2500
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500, (
        "granting the waiver takes the balance from 5000 back to 2500"
    )

    validate_error(
        api_client.void_encounter(
            ctx["second_encounter"]["id"],
            void_encounter_payload("NONPAYMENT"),
            BILLER,
        ),
        ApiErrorId.ERR_INABILITY_TO_PAY_PROTECTED.value,
    )
    assert refresh_encounter(ctx["second_encounter"]["id"])["pps_claim_status"] != "VOID"


def test_a_coding_error_void_unwinds_the_waived_encounter_with_zero_ledger_drift():
    """A waived encounter contributes nothing on the way out, so the balance is exact.

    PRD 3.7: "All four carry the same compensating side effects: the transition sets
    `pps_claim_status` to `VOID` and sets `charge_adjustment_cents` to the negative
    of the quantity `patient_charge_cents` minus `waived_amount_cents`." PRD 3.7
    continues: "It reduces the patient's `patient_balance_cents` by that same
    quantity — with zero drift, so that an encounter and its void cancel exactly —
    and increments the patient's `version` by one."

    Design: Difficulty/compensating_invariant/void_restores_patient_balance_with_zero_drift_after_a_granted_waiver
    """
    ctx = _second_self_pay_visit_with_a_granted_waiver()

    voided = validate_success(
        api_client.void_encounter(
            ctx["second_encounter"]["id"],
            void_encounter_payload("CODING_ERROR"),
            BILLER,
        )
    )

    assert voided["pps_claim_status"] == "VOID"
    assert voided["waived_amount_cents"] == 2500
    assert voided["charge_adjustment_cents"] == 0, (
        "patient_charge_cents minus waived_amount_cents is zero here, so the "
        f"negative of it is zero, got {voided['charge_adjustment_cents']}"
    )
    assert voided["wraparound_status"] == "NOT_APPLICABLE"
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500, (
        "the balance returns to exactly its pre-encounter value of 2500"
    )
    assert (
        validate_success(api_client.get_waiver(ctx["waiver"]["id"], REP))["status"]
        == "GRANTED"
    ), "the void does not reopen a decided waiver"
