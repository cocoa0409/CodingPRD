"""Insurance waterfall, self-pay discount, follow-up window, claim
lifecycle, deductible decrement.

PRD §3.7 (charge calculation, follow-up window, billing cascades),
PRD §3.5 (aggregate score is read-only).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_CONTROLLED_WINDOW_DAYS,
    SCHEDULE_II_WINDOW_DAYS,
    SCHEDULE_III_TO_V_WINDOW_DAYS,
    SELF_PAY_DISCOUNT_BPS,
    TEST_USERS,
    appeal_claim,
    approve_claim,
    assert_claim_billed_conservation,
    assert_claim_waterfall_invariant,
    assert_insurance_claim,
    assert_self_pay_invoice,
    complete_consult,
    create_insured_patient,
    create_prescription,
    deny_claim,
    get_post_complete_claim_or_invoice,
    issue_prescription,
    make_physician_headers,
    mark_paid_claim,
    occ_payload,
    parse_iso,
    re_get_claim,
    re_get_consult,
    re_get_invoice,
    re_get_patient,
    setup_completed_consult,
    setup_completed_insurance_consult_for_billing,
    setup_consult_with_no_rx_for_empty_followup,
    setup_in_progress_consult,
    setup_insurance_waterfall_pinning,
    setup_two_consults_dual_billing_mode,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 Dual variants — self-pay discount vs insurance waterfall
# ===========================================================================
class TestChargeCalculationVariants:

    def test_self_pay_standard_discount_yields_8500(self, api):
        """PRD §3.7: "the platform applies a courtesy discount of
        fifteen percent (1500 basis points): the discount in cents is
        the base charge multiplied by 0.15 and then rounded half-up to
        the nearest whole cent. The consult's final_charge_cents is the
        base charge minus that rounded discount."

        Claim: for STANDARD tier (base=10000), self-pay
        final_charge_cents = 10000 - 1500 = 8500.

        difficulty: dual_variant_calc/consult_charge_self_pay_vs_insurance
        """
        _, _, _, consult = setup_completed_consult(
            billing_mode="SELF_PAY", visit_tier="STANDARD",
        )
        assert consult["base_charge_cents"] == 10000
        assert consult["final_charge_cents"] == 8500

    def test_insurance_standard_waterfall_yields_5200(self, api):
        """PRD §3.7: "deductible_applied_cents is the smaller of the
        base charge and the patient's
        insurance_deductible_remaining_cents ... copay_applied_cents is
        the smaller of the step-one leftover and the patient's
        insurance_copay_cents ... coinsurance_applied_cents is the
        step-two leftover multiplied by the patient's
        insurance_coinsurance_bps divided by 10000, then rounded
        half-up to the nearest whole cent."

        Claim: STANDARD tier (base=10000), deductible=2000, copay=2000,
        coinsurance_bps=2000 → patient_responsibility =
        2000 + 2000 + round_half_up((10000 - 4000) * 0.20)
              = 2000 + 2000 + 1200 = 5200.

        difficulty: dual_variant_calc/consult_charge_self_pay_vs_insurance
        """
        _, _, _, consult, claim = (
            setup_completed_insurance_consult_for_billing(
                visit_tier="STANDARD",
                deductible_cents=2000,
                copay_cents=2000,
                coinsurance_bps=2000,
            )
        )
        assert consult["base_charge_cents"] == 10000
        assert claim["billed_cents"] == 10000
        assert claim["deductible_applied_cents"] == 2000
        assert claim["copay_applied_cents"] == 2000
        assert claim["coinsurance_applied_cents"] == 1200
        assert claim["patient_responsibility_cents"] == 5200
        assert consult["final_charge_cents"] == 5200
        assert_claim_waterfall_invariant(claim)


# ===========================================================================
# §3.7 Insurance waterfall — per-step half-up rounding pin
# ===========================================================================
class TestInsuranceWaterfallRounding:

    def test_per_step_half_up_rounding_on_uneven_inputs(self, api):
        """PRD §3.7: "coinsurance_applied_cents is the step-two leftover
        multiplied by the patient's insurance_coinsurance_bps divided by
        10000, then rounded half-up to the nearest whole cent."
        PRD §2.8: "Intermediate ratios ... are computed in floating
        point and rounded half-up to the nearest cent after each step
        of the waterfall, in the order specified by the calculation."

        Claim: with base=5000, deductible=333, copay=333,
        coinsurance_bps=1250:
            deductible_applied = min(5000, 333) = 333
            after_deductible    = 5000 - 333 = 4667
            copay_applied       = min(4667, 333) = 333
            after_copay         = 4667 - 333 = 4334
            coinsurance_raw     = 4334 * 1250 / 10000 = 541.75
            coinsurance_applied = round_half_up(541.75) = 542
            patient_resp        = 333 + 333 + 542 = 1208

        difficulty: combinatorial_formula/insurance_waterfall_rounding_order_pin
        """
        physician, _, _, consult = setup_insurance_waterfall_pinning(
            deductible_cents=333, copay_cents=333,
            coinsurance_bps=1250, visit_tier="BRIEF",
        )
        # Now complete the consult to trigger billing.
        consult = complete_consult(
            consult=consult, physician=physician,
        )
        claim = get_post_complete_claim_or_invoice(consult, "INSURANCE")
        assert claim is not None, (
            "Setup failed: claim not found after completing waterfall "
            "consult."
        )
        assert consult["base_charge_cents"] == 5000
        assert claim["billed_cents"] == 5000
        assert claim["deductible_applied_cents"] == 333
        assert claim["copay_applied_cents"] == 333
        # 4334 * 0.1250 = 541.75; half-up to nearest cent = 542.
        assert claim["coinsurance_applied_cents"] == 542
        assert claim["patient_responsibility_cents"] == (
            333 + 333 + 542
        )
        assert consult["final_charge_cents"] == 1208


# ===========================================================================
# §3.7 SelfPayInvoice creation
# ===========================================================================
class TestSelfPayInvoiceCreation:

    def test_self_pay_completion_creates_invoice(self, api):
        """PRD §3.7: "As a side effect of completion, a SelfPayInvoice
        row is created with consult_id equal to the completing consult,
        subtotal_cents equal to the base charge, discount_cents equal
        to the rounded discount, amount_due_cents equal to subtotal
        minus discount, and status set to ISSUED."

        Claim: STANDARD self-pay completion creates an invoice with
        subtotal=10000, discount=1500, amount_due=8500, status=ISSUED.
        """
        _, _, _, consult = setup_completed_consult(
            billing_mode="SELF_PAY", visit_tier="STANDARD",
        )
        invoice = get_post_complete_claim_or_invoice(consult, "SELF_PAY")
        assert invoice is not None, (
            "Setup failed: invoice not found after completing self-pay "
            "consult."
        )
        assert_self_pay_invoice(invoice)
        assert invoice["subtotal_cents"] == 10000
        assert invoice["discount_cents"] == 1500
        assert invoice["amount_due_cents"] == 8500
        assert invoice["status"] == "ISSUED"


# ===========================================================================
# §3.7 Claim lifecycle — submit → approve → pay; deny → appeal → approve
# ===========================================================================
class TestClaimLifecycle:

    def test_claim_starts_in_submitted_after_complete(self, api):
        """PRD §3.7: "As a side effect, an InsuranceClaim row is created
        with consult_id equal to the completing consult, billed_cents
        equal to the base charge, the three waterfall components
        populated as above, patient_responsibility_cents set,
        payer_paid_cents initialized to 0, and status set to SUBMITTED."

        Claim: a newly-auto-created claim has status=SUBMITTED.
        """
        _, _, _, _, claim = (
            setup_completed_insurance_consult_for_billing()
        )
        assert claim["status"] == "SUBMITTED"

    def test_payer_approves_then_marks_paid_decrements_deductible(self, api):
        """PRD §3.7: "marks an APPROVED claim as paid, which sets
        payer_paid_cents to billed_cents minus
        patient_responsibility_cents, decrements the patient's
        insurance_deductible_remaining_cents by deductible_applied_cents
        (floored at 0 so the field never goes negative)".

        Claim: after approve + mark-paid, payer_paid_cents == billed -
        patient_responsibility AND the patient's deductible drops by
        deductible_applied.

        difficulty: transitive_cascade/claim_paid_decrements_patient_deductible_depth_2
        """
        _, _, patient, _, claim = (
            setup_completed_insurance_consult_for_billing(
                deductible_cents=2000, copay_cents=2000,
                coinsurance_bps=2000,
            )
        )
        pre = re_get_patient(patient["id"])
        deductible_before = pre["insurance_deductible_remaining_cents"]
        assert deductible_before == 2000
        claim = approve_claim(claim=claim)
        claim = mark_paid_claim(claim=claim)
        assert claim["status"] == "PAID"
        # PRD §3.7: payer_paid_cents = billed - patient_responsibility.
        expected_payer = (
            claim["billed_cents"] - claim["patient_responsibility_cents"]
        )
        assert claim["payer_paid_cents"] == expected_payer == 4800
        # Patient deductible decremented by deductible_applied (=2000).
        post = re_get_patient(patient["id"])
        deductible_after = post["insurance_deductible_remaining_cents"]
        assert deductible_after == 0
        # PRD §3.7: "the difference between the patient's pre-payment
        # and post-payment insurance_deductible_remaining_cents equals
        # deductible_applied_cents."
        assert (
            deductible_before - deductible_after
        ) == claim["deductible_applied_cents"]
        assert_claim_billed_conservation(claim)

    def test_claim_denial_appeal_approve_cycle(self, api):
        """PRD §3.7: "a DENIED claim can be appealed by a
        ComplianceOfficer, advancing it to APPEALED, from which the
        payer may again APPROVED."

        Claim: deny → appeal → approve → mark-paid completes the cycle
        ending in PAID with payer_paid_cents > 0.

        difficulty: non_linear_state_machine/claim_denial_appeal_cycle
        """
        _, _, _, _, claim = (
            setup_completed_insurance_consult_for_billing()
        )
        claim = deny_claim(claim=claim, denial_reason="missing pre-auth")
        assert claim["status"] == "DENIED"
        assert claim["denial_reason"] == "missing pre-auth"
        claim = appeal_claim(claim=claim)
        assert claim["status"] == "APPEALED"
        # PRD §3.7 silence: denial_reason preservation through the
        # appeal cycle is not explicitly stated in PRD prose. Following
        # the two-reader rule, a faithful PRD-only reader could choose
        # to clear or retain it; we do not assert preservation here.
        claim = approve_claim(claim=claim)
        assert claim["status"] == "APPROVED"
        claim = mark_paid_claim(claim=claim)
        assert claim["status"] == "PAID"
        assert claim["payer_paid_cents"] > 0
        assert_claim_billed_conservation(claim)


# ===========================================================================
# §3.7 ERR_CLAIM_ALREADY_EXISTS — uniqueness on consult_id
# ===========================================================================
class TestClaimUniqueness:
    """PRD §3.7: "exactly one InsuranceClaim per consult is permitted;
    a second creation attempt collides on the uniqueness constraint
    over consult_id and is rejected with ERR_CLAIM_ALREADY_EXISTS.\""""

    def test_second_complete_does_not_create_second_claim(self, api):
        """PRD §3.7: "Like the self-pay case, exactly one InsuranceClaim
        per consult is permitted; a second creation attempt collides on
        the uniqueness constraint over consult_id and is rejected with
        ERR_CLAIM_ALREADY_EXISTS."
        PRD §2.6: "state-machine permissibility for the target resource
        (→ ERR_INVALID_STATE)".

        Claim: re-completing a COMPLETED consult returns
        ERR_INVALID_STATE (uniqueness is enforced by the upstream state
        guard; the ERR_CLAIM_ALREADY_EXISTS error_id has no PRD-
        reachable trigger through the /complete endpoint alone).
        """
        physician, _, _, consult = setup_completed_consult(
            billing_mode="INSURANCE",
        )
        res = api.complete_consult(
            consult["id"], occ_payload(version=consult["version"]),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.7 Follow-up window — coverage of the 90-day branch.
#
# PRD §3.7 names the FollowUp side effect at completion. PRD does not
# pin a portable surface for the FollowUp id under a Consult (no
# list-followups-by-consult endpoint, no FOLLOWUP_SCHEDULED audit event
# type). The strictest PRD-implementable test here probes only what is
# observable: the consult itself completes successfully when
# requires_followup is true. The numeric due_by claim is escalated to
# the summary report under `cross-entity-cascade` for the followup
# secondary side effect, since two PRD-only readers could choose
# different surfaces (consult.due_by, an embedded followup object, or
# an audit event payload) and PRD does not name one canonically.
# ===========================================================================
class TestFollowUpCreation:

    def test_completion_with_requires_followup_succeeds(self, api):
        """PRD §3.7: "if the consult was created with requires_followup
        true, a FollowUp row is created with consult_id equal to the
        completing consult, status set to SCHEDULED, and due_by
        computed by the follow-up window rule."

        Claim: a consult with requires_followup=true and NO
        prescriptions completes successfully; this implies the
        underlying FollowUp side-effect did not raise
        ERR_FOLLOWUP_WINDOW_EMPTY (the 90-day window is strictly later
        than "now").
        """
        physician, _, consult = (
            setup_consult_with_no_rx_for_empty_followup()
        )
        res = api.complete_consult(
            consult["id"], occ_payload(version=consult["version"]),
            make_physician_headers(physician["id"]),
        )
        data = validate_success(res, 200)
        assert data["status"] == "COMPLETED"
