"""Difficulty-design coverage.

This file contains at least TWO tests for every instance declared in
SCAFFOLD_DIFFICULTY_DESIGN.yaml. Each test carries the comment marker
`# difficulty: <rule_id>/<instance.name>` so the coverage audit can
trace tests back to instances.

PRD citations follow the same C1/C2/C3 rules as every other test file.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_and_post_charge,
    advance_clock_to,
    anchor_clock_in_plan_year_2026,
    assert_allowed_amount_conservation,
    discharge_encounter,
    finalize_coding,
    post_payment_payload,
    re_get_encounter,
    re_get_policy,
    setup_billed_with_balance,
    setup_charges_captured_encounter,
    setup_coded_encounter,
    setup_difficulty_estimate_vs_final,
    setup_difficulty_two_billed_encounters,
    setup_difficulty_two_registered_encounters,
    setup_eligibility_verified_encounter,
    setup_patient_with_policy,
    setup_registered_encounter,
    submit_clearance_payload,
    submit_coding_payload,
    validate_error,
    validate_success,
    verify_eligibility,
    verify_eligibility_payload,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantEstimateVsFinal:
    """Rule 1 instance estimate_vs_final_patient_responsibility."""

    # difficulty: dual_variant_calc/estimate_vs_final_patient_responsibility
    def test_estimate_and_final_diverge_for_different_billable(self, api):
        """PRD §3.5: "The **estimate** variant uses `total_charges_cents` as its billable input, writes `estimated_patient_responsibility_cents`, and does **not** mutate either of the policy accumulators."
        PRD §3.5: "The **final** variant uses `ClearanceDecision.allowed_amount_cents` as its billable input, writes `patient_responsibility_cents`"

        Claim: with total_charges_cents=150000 and allowed_amount=
        120000 (deductible=100000, coinsurance=2000, oop_max=200000):
        estimated_patient_responsibility_cents=110000 BUT
        patient_responsibility_cents=104000 — the two values DIFFER
        because they read different billable inputs.
        """
        patient, policy, encounter = setup_difficulty_estimate_vs_final(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=150_000,
        )
        # At CHARGES_CAPTURED, estimate reflects total_charges_cents.
        assert encounter["estimated_patient_responsibility_cents"] == 110_000
        # Walk to CLEARED with allowed=120000.
        finalize_coding(encounter=encounter,
                        cpt_codes=["99213"])
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=120_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["patient_responsibility_cents"] == 104_000
        assert refreshed["payer_responsibility_cents"] == 16_000
        # Crucial — estimate and final differ.
        assert (
            refreshed["estimated_patient_responsibility_cents"]
            != refreshed["patient_responsibility_cents"]
        )

    # difficulty: dual_variant_calc/estimate_vs_final_patient_responsibility
    def test_final_variant_writes_distinct_field_from_estimate(self, api):
        """PRD §3.5: "writes `estimated_patient_responsibility_cents`"
        PRD §3.5: "writes `patient_responsibility_cents`"

        Claim: the two variants write to DIFFERENT fields on the
        Encounter. After clearance, both fields exist and the final
        variant's field has been populated.
        """
        patient, policy, encounter = setup_difficulty_estimate_vs_final(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=150_000,
        )
        finalize_coding(encounter=encounter, cpt_codes=["99213"])
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=120_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        # estimated_* was seeded earlier; patient_* is new.
        assert "estimated_patient_responsibility_cents" in refreshed
        assert "patient_responsibility_cents" in refreshed
        assert refreshed["patient_responsibility_cents"] == 104_000


class TestDualVariantPRCodeDenial:
    """Rule 1 instance payer_vs_patient_split_under_pr_denial_code."""

    # difficulty: dual_variant_calc/payer_vs_patient_split_under_pr_denial_code
    def test_pr_code_routes_full_charges_to_patient(self, api):
        """PRD §3.6: "when `denial_reason_code` equals one of the patient-responsibility reason codes (`PR-1`, `PR-2`, or `PR-3`), the unallowed portion bypasses the deductible / coinsurance / OOP waterfall entirely and flows into `patient_responsibility_cents` in full."

        Claim: decision=DENIED, denial_reason_code='PR-1',
        total_charges=150000 yields payer=0 AND patient=150000.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=150_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="DENIED", allowed_amount_cents=0,
                denial_reason_code="PR-1",
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["payer_responsibility_cents"] == 0
        assert refreshed["patient_responsibility_cents"] == 150_000

    # difficulty: dual_variant_calc/payer_vs_patient_split_under_pr_denial_code
    def test_pr_code_bypass_leaves_accumulators_untouched(self, api):
        """PRD §3.6: "the unallowed portion bypasses the deductible / coinsurance / OOP waterfall entirely and flows into `patient_responsibility_cents` in full."

        Claim: under PR-code bypass, InsurancePolicy.deductible_met_
        cents stays at 0 (the waterfall didn't run, so its accumulator
        update didn't run).
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=150_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="DENIED", allowed_amount_cents=0,
                denial_reason_code="PR-1",
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed_policy = re_get_policy(patient["id"], policy["id"])
        assert refreshed_policy["deductible_met_cents"] == 0


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialTieredWaterfall:
    """Rule 2 instance tiered_waterfall_with_oop_cap."""

    # difficulty: combinatorial_formula/tiered_waterfall_with_oop_cap
    def test_oop_cap_clips_three_input_combination(self, api):
        """PRD §3.5: "The member-payable amount is the smaller of the
        uncapped member responsibility and that OOP remaining."

        Claim: deductible=50000, coinsurance=2500, oop_max=80000,
        allowed=200000: deductible_portion=50000, coinsurance=37500,
        uncapped=87500, OOP-clipped to 80000; payer=120000.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=50_000,
            coinsurance_rate_bps=2500,
            oop_max_cents=80_000,
            unit_price_cents=200_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=200_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["patient_responsibility_cents"] == 80_000
        assert refreshed["payer_responsibility_cents"] == 120_000

    # difficulty: combinatorial_formula/tiered_waterfall_with_oop_cap
    def test_oop_clipping_propagates_to_policy_accumulator(self, api):
        """PRD §3.5: "adds the **member-payable amount** (from Step 4) to the policy's `oop_accumulated_cents`. Both accumulator updates are clamped to their respective caps"

        Claim: when OOP cap clips member to 80000, oop_accumulated_
        cents lands at 80000 (the clipped value, clamped to oop_max=
        80000).
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=50_000,
            coinsurance_rate_bps=2500,
            oop_max_cents=80_000,
            unit_price_cents=200_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=200_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed_policy = re_get_policy(patient["id"], policy["id"])
        assert refreshed_policy["oop_accumulated_cents"] == 80_000


class TestCombinatorialRoundingOrder:
    """Rule 2 instance coinsurance_rounding_order_bucket_then_round."""

    # difficulty: combinatorial_formula/coinsurance_rounding_order_bucket_then_round
    def test_bucket_then_round_not_per_line(self, api):
        """PRD §2.7: "the raw coinsurance amount is produced by multiplying the post-deductible billable cents by the coinsurance basis points and dividing by ten thousand, and that single intermediate value is rounded to the nearest whole cent using half-up rounding **once**, after the multiplication and division have been performed. Rounding is never applied per line item"

        Claim: two charges of 3333 each at 17.5% coinsurance, with
        deductible=0, produce member=1167 (bucket-then-round), not
        1166 (round-per-line).
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=0,
            coinsurance_rate_bps=1750,
            oop_max_cents=99_999,
            charges=[
                {"cpt_code": "99213", "unit_price_cents": 3333},
                {"cpt_code": "99214", "unit_price_cents": 3333},
            ],
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=6666,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["patient_responsibility_cents"] == 1167

    # difficulty: combinatorial_formula/coinsurance_rounding_order_bucket_then_round
    def test_bucket_rounding_payer_complement(self, api):
        """PRD §3.6: "`payer_responsibility_cents` plus `patient_responsibility_cents` equals `allowed_amount_cents` exactly."

        Claim: payer_responsibility = 6666 - 1167 = 5499 follows
        from the same single rounded value of the coinsurance bucket.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=0,
            coinsurance_rate_bps=1750,
            oop_max_cents=99_999,
            charges=[
                {"cpt_code": "99213", "unit_price_cents": 3333},
                {"cpt_code": "99214", "unit_price_cents": 3333},
            ],
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=6666,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["payer_responsibility_cents"] == 5499
        assert_allowed_amount_conservation(refreshed, 6666)


class TestSequentialPayerThenPatient:
    """Rule 2 instance sequential_payer_then_patient_evaluation."""

    # difficulty: combinatorial_formula/sequential_payer_then_patient_evaluation
    def test_patient_computed_before_payer(self, api):
        """PRD §3.6: "payer_responsibility_cents is set to
        allowed_amount_cents minus the member-payable amount produced
        by running the final variant of the patient-responsibility
        waterfall against allowed_amount_cents".

        Claim: patient is computed by the waterfall first (OOP-cap-
        clipped to 80000); payer is then the subtraction yielding
        120000.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=50_000,
            coinsurance_rate_bps=2500,
            oop_max_cents=80_000,
            unit_price_cents=200_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=200_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["patient_responsibility_cents"] == 80_000
        assert refreshed["payer_responsibility_cents"] == 120_000

    # difficulty: combinatorial_formula/sequential_payer_then_patient_evaluation
    def test_payer_equals_allowed_minus_patient(self, api):
        """PRD §3.6: "so `payer_responsibility_cents` plus `patient_responsibility_cents` equals `allowed_amount_cents` exactly."

        Claim: under any APPROVED clearance, payer + patient ==
        allowed_amount_cents.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=50_000,
            coinsurance_rate_bps=2500,
            oop_max_cents=80_000,
            unit_price_cents=200_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=200_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert_allowed_amount_conservation(refreshed, 200_000)


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestEncounterBranchingBilled:
    """Rule 3 instance encounter_branching_billed_to_resolved_or_written_off."""

    # difficulty: non_linear_state_machine/encounter_branching_billed_to_resolved_or_written_off
    def test_billed_to_resolved_via_payment(self, api):
        """PRD §3.7: "If the running balance reaches exactly zero
        after a non-REFUND payment is applied, the encounter
        transitions from BILLED to RESOLVED — a terminal status."

        Claim: a CASH payment of the full balance advances Encounter
        A to RESOLVED.
        """
        (pA, polA, encA), (pB, polB, encB) = (
            setup_difficulty_two_billed_encounters(
                patient_responsibility_cents=10_000,
            )
        )
        api.post_payment(
            encA["id"],
            post_payment_payload(amount_cents=10_000, method="CASH"),
            TEST_USERS["biller_headers"],
        )
        refreshed_a = re_get_encounter(encA["id"])
        assert refreshed_a["status"] == "RESOLVED"
        # No BadDebtRecord side effect on the payment branch.
        assert refreshed_a["write_off_cents"] == 0

    # difficulty: non_linear_state_machine/encounter_branching_billed_to_resolved_or_written_off
    def test_billed_to_written_off_via_aged_write_off(self, api):
        """PRD §3.8: "The encounter's write_off_cents is set equal to
        the bad-debt record's write_off_cents, and the encounter
        transitions from BILLED to WRITTEN_OFF — the second terminal
        status for an encounter."

        Claim: advancing the clock past 90 days and calling write-off
        on Encounter B transitions it to WRITTEN_OFF with
        write_off_cents=10000.
        """
        # Anchor BEFORE building, so billed_at lands at 2026-02-01.
        advance_clock_to("2026-02-01T00:00:00.000Z")
        patient, policy, enc = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        advance_clock_to("2026-05-02T00:00:00.000Z")
        api.write_off_encounter(
            enc["id"], TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(enc["id"])
        assert refreshed["status"] == "WRITTEN_OFF"
        assert refreshed["write_off_cents"] == 10_000


class TestPolicyBranchingAtVerification:
    """Rule 3 instance insurance_policy_branching_at_verification."""

    # difficulty: non_linear_state_machine/insurance_policy_branching_at_verification
    def test_eligible_branch_sets_policy_eligible_encounter_advances(
        self, api,
    ):
        """PRD §3.3: "When the payer reports the policy as eligible
        (the policy_eligible=true branch), the policy transitions
        from UNVERIFIED to ELIGIBLE and the encounter transitions
        from REGISTERED to ELIGIBILITY_VERIFIED."

        Claim: ELIGIBLE branch → policy=ELIGIBLE AND
        encounter=ELIGIBILITY_VERIFIED.
        """
        (pA, polA, encA), _ = (
            setup_difficulty_two_registered_encounters()
        )
        api.verify_eligibility(
            encA["id"], verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        refreshed_enc = re_get_encounter(encA["id"])
        assert refreshed_enc["status"] == "ELIGIBILITY_VERIFIED"
        refreshed_pol = re_get_policy(pA["id"], polA["id"])
        assert refreshed_pol["status"] == "ELIGIBLE"

    # difficulty: non_linear_state_machine/insurance_policy_branching_at_verification
    def test_ineligible_branch_sets_policy_ineligible_encounter_stays(
        self, api,
    ):
        """PRD §3.3: "When the payer reports the policy as not
        eligible (the policy_eligible=false branch), the policy
        transitions from UNVERIFIED to INELIGIBLE — a terminal status
        for the policy — and the encounter remains in REGISTERED so
        that registration can re-route to a different policy via the
        metadata update."

        Claim: INELIGIBLE branch → policy=INELIGIBLE AND
        encounter=REGISTERED.
        """
        _, (pB, polB, encB) = (
            setup_difficulty_two_registered_encounters()
        )
        api.verify_eligibility(
            encB["id"], verify_eligibility_payload(policy_eligible=False),
            TEST_USERS["registration_clerk_headers"],
        )
        refreshed_enc = re_get_encounter(encB["id"])
        assert refreshed_enc["status"] == "REGISTERED"
        refreshed_pol = re_get_policy(pB["id"], polB["id"])
        assert refreshed_pol["status"] == "INELIGIBLE"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestChargePostCascadeDepthThree:
    """Rule 4 instance charge_post_cascade_depth_three."""

    # difficulty: transitive_cascade/charge_post_cascade_depth_three
    def test_post_drives_total_then_estimate(self, api):
        """PRD §3.4: "Posting triggers `charge_total_aggregation` to refresh the encounter's `total_charges_cents` (now including this newly posted line) and triggers the estimate variant of `patient_responsibility_calc` to refresh `estimated_patient_responsibility_cents`."

        Claim: posting a 150000-cent charge against deductible=
        100000, coinsurance=2000, oop_max=200000 drives total to
        150000 and estimate to 110000 in a single transition.
        """
        from test_helpers import add_charge
        patient, policy, encounter = setup_eligibility_verified_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
        )
        charge = add_charge(encounter=encounter, unit_price_cents=150_000)
        s0 = re_get_encounter(encounter["id"])
        assert s0["total_charges_cents"] == 0
        assert s0["estimated_patient_responsibility_cents"] == 0
        api.post_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        s1 = re_get_encounter(encounter["id"])
        assert s1["total_charges_cents"] == 150_000
        assert s1["estimated_patient_responsibility_cents"] == 110_000

    # difficulty: transitive_cascade/charge_post_cascade_depth_three
    def test_post_emits_posted_status_on_charge(self, api):
        """PRD §3.4: "**Posting** a pending charge — advancing it from `PENDING` to `POSTED` — stamps the line's `posted_at` and is permitted only while the encounter is in `ELIGIBILITY_VERIFIED`"

        Claim: the post call's response carries status=POSTED, the
        first link of the cascade.
        """
        from test_helpers import add_charge
        patient, policy, encounter = setup_eligibility_verified_encounter()
        charge = add_charge(encounter=encounter, unit_price_cents=10_000)
        res = api.post_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        data = validate_success(res)
        assert data["status"] == "POSTED"


class TestClearanceCascadeThroughPolicy:
    """Rule 4 instance clearance_cascade_through_policy_accumulators."""

    # difficulty: transitive_cascade/clearance_cascade_through_policy_accumulators
    def test_clearance_increments_policy_accumulators(self, api):
        """PRD §3.5: "after the member-payable amount has been computed, adds the **deductible portion** (from Step 1) to the policy's `deductible_met_cents` and adds the **member-payable amount** (from Step 4) to the policy's `oop_accumulated_cents`"

        Claim: a CLEARED transition increments both InsurancePolicy
        accumulators based on the just-computed waterfall outputs.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=150_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=120_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed_policy = re_get_policy(patient["id"], policy["id"])
        assert refreshed_policy["deductible_met_cents"] == 100_000
        assert refreshed_policy["oop_accumulated_cents"] == 104_000

    # difficulty: transitive_cascade/clearance_cascade_through_policy_accumulators
    def test_clearance_writes_responsibility_split_on_encounter(self, api):
        """PRD §3.6: "The transition from `CODED` to `CLEARED` runs the payer-clearance calculation and then the final variant of the patient-responsibility waterfall."

        Claim: after a clearance call, both Encounter.payer_
        responsibility_cents and Encounter.patient_responsibility_
        cents are written.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=150_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=120_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["patient_responsibility_cents"] == 104_000
        assert refreshed["payer_responsibility_cents"] == 16_000


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestStateBeatsFiscalOnDischarge:
    """Rule 5 instance state_beats_business_fiscal_on_discharge."""

    # difficulty: priority_pair_validation_conflict/state_beats_business_fiscal_on_discharge
    def test_second_discharge_returns_state_not_fiscal(self, api):
        """PRD §2.10: "The order is: authentication headers (`ERR_AUTH_MISSING`) first, then role authorization (`ERR_FORBIDDEN`), then path-segment existence checks left-to-right (`ERR_NOT_FOUND`), then foreign-key existence checks for identifiers inside the request body (`ERR_NOT_FOUND`), then the state-machine guard for the target operation (`ERR_INVALID_STATE`), then domain-specific business validations."

        Claim: a second discharge call on an already-discharged
        encounter returns ERR_INVALID_STATE — the state guard fires
        before the fiscal-charges check that would otherwise demand
        POSTED charges.
        """
        # Build through CHARGES_CAPTURED (discharged once).
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        assert encounter["status"] == "CHARGES_CAPTURED"
        # Second discharge.
        res = api.discharge_encounter(
            encounter["id"],
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    # difficulty: priority_pair_validation_conflict/state_beats_business_fiscal_on_discharge
    def test_discharge_on_registered_returns_state_not_fiscal(self, api):
        """PRD §2.10: "then the state-machine guard for the target operation (`ERR_INVALID_STATE`), then domain-specific business validations"

        Claim: discharge on a REGISTERED encounter (state-illegal AND
        no POSTED charges) returns ERR_INVALID_STATE rather than
        ERR_CHARGES_NOT_READY.
        """
        patient, policy, encounter = setup_registered_encounter()
        res = api.discharge_encounter(
            encounter["id"],
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestExistenceBeatsReferentialOnEncounterCreate:
    """Rule 5 instance existence_beats_business_referential_on_encounter_create."""

    # difficulty: priority_pair_validation_conflict/existence_beats_business_referential_on_encounter_create
    def test_nonexistent_policy_id_returns_not_found(self, api):
        """PRD §2.10: "then foreign-key existence checks for identifiers inside the request body (`ERR_NOT_FOUND`), then the state-machine guard for the target operation (`ERR_INVALID_STATE`), then domain-specific business validations"

        Claim: POST /encounters with a non-existent policy_id returns
        ERR_NOT_FOUND, BEFORE any policy/patient mismatch could be
        evaluated.
        """
        from test_helpers import (
            NON_EXISTENT_UUID,
            create_encounter_payload,
            create_patient,
        )
        patient = create_patient()
        res = api.create_encounter(
            create_encounter_payload(
                patient_id=patient["id"], policy_id=NON_EXISTENT_UUID,
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    # difficulty: priority_pair_validation_conflict/existence_beats_business_referential_on_encounter_create
    def test_real_policy_owned_by_other_patient_returns_mismatch(self, api):
        """PRD §3.2: "Before the encounter is persisted, the system verifies that the policy referenced by `policy_id` belongs to the patient referenced by `patient_id`; if the policy's `patient_id` does not match the encounter's `patient_id`, the admission is rejected with `ERR_POLICY_PATIENT_MISMATCH`."

        Claim: when the policy DOES exist but is owned by another
        patient, the mismatch surfaces (i.e., the existence check
        passes; the mismatch is the next-priority failure).
        """
        from test_helpers import create_encounter_payload, create_policy
        from test_helpers import create_patient as create_p
        patient_a = create_p()
        patient_b = create_p()
        policy_for_b = create_policy(patient=patient_b)
        res = api.create_encounter(
            create_encounter_payload(
                patient_id=patient_a["id"],
                policy_id=policy_for_b["id"],
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_POLICY_PATIENT_MISMATCH")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestWriteOffAt90DaysInclusive:
    """Rule 6 instance write_off_at_exactly_ninety_days_inclusive."""

    # difficulty: boundary_precision_check/write_off_at_exactly_ninety_days_inclusive
    def test_write_off_at_89_days_rejected(self, api):
        """PRD §3.8: "the boundary is inclusive, so a day count of exactly 90 passes and a day count of 89 does not."
        PRD §3.8: "Failing this gate produces `ERR_WRITE_OFF_TOO_EARLY`."

        Claim: clock at 89 days 23h59m59s elapsed from billed_at
        returns ERR_WRITE_OFF_TOO_EARLY.
        """
        advance_clock_to("2026-02-01T00:00:00.000Z")
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        advance_clock_to("2026-05-01T23:59:59.999Z")
        res = api.write_off_encounter(
            encounter["id"], TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_WRITE_OFF_TOO_EARLY")

    # difficulty: boundary_precision_check/write_off_at_exactly_ninety_days_inclusive
    def test_write_off_at_exactly_90_days_succeeds(self, api):
        """PRD §3.8: "the boundary is inclusive, so a day count of exactly 90 passes and a day count of 89 does not."

        Claim: clock at exactly 90 days elapsed accepts the write-off
        and yields BadDebtRecord.write_off_cents == 10000.
        """
        advance_clock_to("2026-02-01T00:00:00.000Z")
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        advance_clock_to("2026-05-02T00:00:00.000Z")
        data = validate_success(
            api.write_off_encounter(
                encounter["id"], TEST_USERS["biller_headers"],
            ),
            expected_status=201,
        )
        assert data["write_off_cents"] == 10_000
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "WRITTEN_OFF"


class TestDischargeRequiresNonEmptyPosted:
    """Rule 6 instance discharge_requires_nonempty_posted_charges."""

    # difficulty: boundary_precision_check/discharge_requires_nonempty_posted_charges
    def test_discharge_with_zero_posted_charges_rejected(self, api):
        """PRD §3.6: "Discharge requires that at least one charge line exist in `POSTED` and that zero charge lines remain in `PENDING`; either condition failing produces `ERR_CHARGES_NOT_READY`."

        Claim: discharging an encounter with zero POSTED charges and
        zero PENDING charges (empty ledger) returns ERR_CHARGES_NOT_
        READY.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        res = api.discharge_encounter(
            encounter["id"],
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_CHARGES_NOT_READY")
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "ELIGIBILITY_VERIFIED"

    # difficulty: boundary_precision_check/discharge_requires_nonempty_posted_charges
    def test_discharge_succeeds_at_one_posted_charge_boundary(self, api):
        """PRD §3.6: "Discharge requires that at least one charge line exist in `POSTED` and that zero charge lines remain in `PENDING`"

        Claim: with EXACTLY one POSTED charge and zero PENDING,
        discharge succeeds (X+1 side of the boundary).
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        add_and_post_charge(encounter=encounter, unit_price_cents=1)
        res = api.discharge_encounter(
            encounter["id"],
            TEST_USERS["registration_clerk_headers"],
        )
        validate_success(res)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "CHARGES_CAPTURED"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestEncounterDependsOnPolicyEligibility:
    """Rule 7 instance encounter_advancement_depends_on_policy_eligibility."""

    # difficulty: cross_entity_state_dependency/encounter_advancement_depends_on_policy_eligibility
    def test_ineligible_policy_leaves_encounter_at_registered(self, api):
        """PRD §3.3: "When the payer reports the policy as not eligible (the `policy_eligible=false` branch), the policy transitions from `UNVERIFIED` to `INELIGIBLE` — a terminal status for the policy — and the encounter remains in `REGISTERED` so that registration can re-route to a different policy via the metadata update."

        Claim: an INELIGIBLE-branch verification leaves the encounter
        at REGISTERED (cross-entity dependency).
        """
        patient, policy, encounter = setup_registered_encounter()
        api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=False),
            TEST_USERS["registration_clerk_headers"],
        )
        refreshed_enc = re_get_encounter(encounter["id"])
        assert refreshed_enc["status"] == "REGISTERED"
        refreshed_pol = re_get_policy(patient["id"], policy["id"])
        assert refreshed_pol["status"] == "INELIGIBLE"

    # difficulty: cross_entity_state_dependency/encounter_advancement_depends_on_policy_eligibility
    def test_eligible_policy_advances_encounter(self, api):
        """PRD §3.3: "the policy transitions from `UNVERIFIED` to `ELIGIBLE` and the encounter transitions from `REGISTERED` to `ELIGIBILITY_VERIFIED`."

        Claim: ELIGIBLE-branch verification advances the encounter to
        ELIGIBILITY_VERIFIED.
        """
        patient, policy, encounter = setup_registered_encounter()
        api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "ELIGIBILITY_VERIFIED"


class TestCodingDependsOnChargeCPTSet:
    """Rule 7 instance coding_finalize_depends_on_chargeitem_cpt_set."""

    # difficulty: cross_entity_state_dependency/coding_finalize_depends_on_chargeitem_cpt_set
    def test_finalize_with_missing_cpt_rejected(self, api):
        """PRD §3.6: "On finalize, the multiset of `cpt_codes` on the coding record must be exactly the multiset of `cpt_code` values across all non-`VOIDED` charge lines for this encounter; the codes may be in any order, but every CPT on the encounter must appear on the coding record with the correct multiplicity and vice versa. A mismatch produces `ERR_CODING_CPT_MISMATCH`."

        Claim: cpt_codes=['99213'] when the encounter has POSTED
        charges 99213 AND 99214 returns ERR_CODING_CPT_MISMATCH.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter(
                charges=[
                    {"cpt_code": "99213", "unit_price_cents": 1_000},
                    {"cpt_code": "99214", "unit_price_cents": 1_000},
                ],
            )
        )
        res = api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9",
                cpt_codes=["99213"], finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        validate_error(res, "ERR_CODING_CPT_MISMATCH")
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "CHARGES_CAPTURED"

    # difficulty: cross_entity_state_dependency/coding_finalize_depends_on_chargeitem_cpt_set
    def test_finalize_with_matching_cpts_advances_encounter_to_coded(
        self, api,
    ):
        """PRD §3.6: "and as a side effect transitions the encounter from `CHARGES_CAPTURED` to `CODED`"

        Claim: cpt_codes=['99213','99214'] matching exactly the
        non-VOIDED ChargeItem multiset succeeds and advances the
        encounter to CODED.
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter(
                charges=[
                    {"cpt_code": "99213", "unit_price_cents": 1_000},
                    {"cpt_code": "99214", "unit_price_cents": 1_000},
                ],
            )
        )
        api.submit_coding(
            encounter["id"],
            submit_coding_payload(
                primary_icd10="J18.9",
                cpt_codes=["99213", "99214"], finalize=True,
            ),
            TEST_USERS["coder_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "CODED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestPlanYearMustMatchCurrentYear:
    """Rule 8 instance policy_plan_year_must_match_current_calendar_year."""

    # difficulty: resource_temporal_overlap/policy_plan_year_must_match_current_calendar_year
    def test_prior_year_policy_rejected_on_verify(self, api):
        """PRD §3.3: "the policy's `plan_year` must equal the current calendar year derived from the server clock; a stale plan-year produces `ERR_PLAN_YEAR_EXPIRED`."

        Claim: plan_year=2025 with clock anchored to 2026-02-01
        returns ERR_PLAN_YEAR_EXPIRED.
        """
        from test_helpers import (
            create_encounter,
            create_patient,
            create_policy,
        )
        anchor_clock_in_plan_year_2026()
        patient = create_patient()
        policy = create_policy(patient=patient, plan_year=2025)
        encounter = create_encounter(patient=patient, policy=policy)
        res = api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_PLAN_YEAR_EXPIRED")
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "REGISTERED"

    # difficulty: resource_temporal_overlap/policy_plan_year_must_match_current_calendar_year
    def test_current_year_policy_accepted_on_verify(self, api):
        """PRD §3.3: "the policy's plan_year must equal the current
        calendar year derived from the server clock".

        Claim: plan_year=2026 with clock at 2026-02-01 passes the
        gate and advances the encounter.
        """
        from test_helpers import (
            create_encounter,
            create_patient,
            create_policy,
        )
        anchor_clock_in_plan_year_2026()
        patient = create_patient()
        policy = create_policy(patient=patient, plan_year=2026)
        encounter = create_encounter(patient=patient, policy=policy)
        res = api.verify_eligibility(
            encounter["id"],
            verify_eligibility_payload(policy_eligible=True),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_success(res)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "ELIGIBILITY_VERIFIED"


class TestWriteOffWindowAgeThreshold:
    """Rule 8 instance writeoff_window_aggregate_age_threshold."""

    # difficulty: resource_temporal_overlap/writeoff_window_aggregate_age_threshold
    def test_write_off_at_88_days_rejected(self, api):
        """PRD §3.8: "the elapsed time since `billed_at` must be at least 90 days"
        PRD §3.8: "Failing this gate produces `ERR_WRITE_OFF_TOO_EARLY`."

        Claim: clock at ~88 days elapsed returns ERR_WRITE_OFF_TOO_
        EARLY and leaves the encounter at BILLED with no BadDebtRecord
        created.
        """
        advance_clock_to("2026-02-01T00:00:00.000Z")
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        advance_clock_to("2026-04-30T00:00:00.000Z")
        res = api.write_off_encounter(
            encounter["id"], TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_WRITE_OFF_TOO_EARLY")
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "BILLED"
        assert refreshed["write_off_cents"] == 0

    # difficulty: resource_temporal_overlap/writeoff_window_aggregate_age_threshold
    def test_encounter_stays_billed_after_early_write_off_attempt(self, api):
        """PRD §3.8: "Failing this gate produces `ERR_WRITE_OFF_TOO_EARLY`."

        Claim: a too-early write-off attempt does not advance the
        encounter; its status stays at BILLED with write_off_cents=0.
        """
        advance_clock_to("2026-02-01T00:00:00.000Z")
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=5_000,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        api.write_off_encounter(
            encounter["id"], TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "BILLED"
        assert refreshed["write_off_cents"] == 0


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestAllowedAmountConservationInvariant:
    """Rule 9 instance allowed_amount_conservation_payer_plus_patient."""

    # difficulty: compensating_invariant/allowed_amount_conservation_payer_plus_patient
    def test_payer_plus_patient_equals_allowed(self, api):
        """PRD §3.6: "so `payer_responsibility_cents` plus `patient_responsibility_cents` equals `allowed_amount_cents` exactly."

        Claim: with deductible=50000, coinsurance=2500, oop_max=
        80000, total=200000, allowed=200000: patient=80000,
        payer=120000, sum=200000.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=50_000,
            coinsurance_rate_bps=2500,
            oop_max_cents=80_000,
            unit_price_cents=200_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=200_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["patient_responsibility_cents"] == 80_000
        assert refreshed["payer_responsibility_cents"] == 120_000
        assert_allowed_amount_conservation(refreshed, 200_000)

    # difficulty: compensating_invariant/allowed_amount_conservation_payer_plus_patient
    def test_conservation_holds_under_partial_decision(self, api):
        """PRD §3.6: "`payer_responsibility_cents` plus `patient_responsibility_cents` equals `allowed_amount_cents` exactly."

        Claim: under PARTIAL adjudication with allowed=60000 and
        deductible=50000, coinsurance=2000, oop_max=200000:
        patient + payer == 60000.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=50_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=100_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="PARTIAL", allowed_amount_cents=60_000,
                denial_reason_code="CO-45",
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert_allowed_amount_conservation(refreshed, 60_000)


class TestOutstandingBalanceConservation:
    """Rule 9 instance outstanding_balance_conservation_under_payment_and_refund."""

    # difficulty: compensating_invariant/outstanding_balance_conservation_under_payment_and_refund
    def test_payment_then_refund_restores_balance(self, api):
        """PRD §3.7: "when the payment's method is REFUND, the
        payment's amount_cents is added to the running balance;
        otherwise the payment's amount_cents is subtracted from the
        running balance."

        Claim: with starting outstanding=10000, a CARD of 4000 then
        a REFUND of 4000 leaves outstanding back at 10000 (encounter
        remains BILLED).
        """
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        s0 = re_get_encounter(encounter["id"])
        assert s0["outstanding_balance_cents"] == 10_000
        api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=4_000, method="CARD"),
            TEST_USERS["biller_headers"],
        )
        s1 = re_get_encounter(encounter["id"])
        assert s1["outstanding_balance_cents"] == 6_000
        api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=4_000, method="REFUND"),
            TEST_USERS["biller_headers"],
        )
        s2 = re_get_encounter(encounter["id"])
        assert s2["outstanding_balance_cents"] == 10_000
        assert s2["status"] == "BILLED"

    # difficulty: compensating_invariant/outstanding_balance_conservation_under_payment_and_refund
    def test_partial_payment_outstanding_equals_starting_minus_payment(
        self, api,
    ):
        """PRD §3.7: "Each PatientPayment, processed in ascending
        order of posted_at with id ascending as the tie-breaker, is
        applied to the running balance: when the payment's method is
        REFUND, the payment's amount_cents is added to the running
        balance; otherwise the payment's amount_cents is subtracted
        from the running balance."

        Claim: a single CASH payment of 3000 against starting
        outstanding=10000 yields outstanding=7000.
        """
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=3_000, method="CASH"),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["outstanding_balance_cents"] == 7_000
