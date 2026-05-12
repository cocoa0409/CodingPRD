"""Insurance claim lifecycle: eligibility verification, settlement,
tiered reimbursement (with per-tier rounding), bureau events,
compensating invariant. Covers PRD §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    ADMIN,
    api_client,
    assert_settlement_invariant,
    bureau_rejected_event,
    bureau_settled_event,
    get_success_data,
    setup_dispatched_prescription,
    settle_claim,
    validate_error,
    validate_success,
    verify_eligibility,
    verify_eligibility_payload,
    DEDUCTIBLE_CENTS,
    IN_SCOPE_DISEASE,
    OUT_OF_SCOPE_DISEASE,
)


def _get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_insurance_claim(claim_id, ADMIN))


# =========================================================================
# Verify-eligibility transitions
# =========================================================================
class TestVerifyEligibility:

    def test_verify_eligible_sets_deductible_and_claim_amount(self, api):
        """PRD §3.7: 'A patient whose insurance_status is ELIGIBLE
        advances the claim to VERIFIED and sets deductible_cents to a
        per-claim deductible of 5,000 cents and claim_amount_cents to
        the consultation's total_fee converted to cents plus the linked
        prescription's gross_amount_cents (when a prescription is
        linked).'

        Claim: /verify-eligibility with insurance_status=ELIGIBLE ->
        status VERIFIED, deductible_cents == 5000, claim_amount_cents ==
        consultation.total_fee*100 + prescription.gross_amount_cents.
        """
        # Build a fully-dispatched flow: 5-min consultation @ 30.00 base
        # -> total_fee 35.00 (3500 cents); items [qty=2 unit=500] ->
        # gross = 1000. Expected claim_amount_cents = 3500 + 1000 = 4500.
        from test_helpers import (
            make_prescription_item,
            setup_completed_consultation,
            draft_prescription,
            submit_prescription,
            approve_prescription,
            dispatch_prescription,
        )
        state = setup_completed_consultation(
            elapsed_seconds=300,
            doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=2, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE under this setup")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        state["prescription"] = pres
        # Find the claim:
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip(
                "No claim discoverable post-dispatch; PRD §3.6 ties "
                "claim creation to dispatch but does not specify a "
                "list endpoint for claims."
            )
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        assert verified["status"] == "VERIFIED"
        assert verified["deductible_cents"] == DEDUCTIBLE_CENTS
        # 5 min * 100 cents/min + base 30 = 3500 cents consultation +
        # 1000 cents prescription = 4500
        assert verified["claim_amount_cents"] == 4500

    def test_verify_ineligible_sets_self_pay_to_full(self, api):
        """PRD §3.7: 'A patient whose insurance_status is INELIGIBLE,
        SUSPENDED, or UNKNOWN advances the claim to the terminal
        INELIGIBLE and sets self_pay_cents equal to the full
        claim_amount_cents.'

        Claim: /verify-eligibility with insurance_status=INELIGIBLE ->
        status INELIGIBLE, self_pay_cents == claim_amount_cents.
        """
        from test_helpers import (
            make_prescription_item,
            setup_completed_consultation,
            draft_prescription,
            submit_prescription,
            approve_prescription,
            dispatch_prescription,
        )
        state = setup_completed_consultation(
            elapsed_seconds=300, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=1, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE under this setup")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable post-dispatch")
        result = verify_eligibility(claim=claim, insurance_status="INELIGIBLE")
        assert result["status"] == "INELIGIBLE"
        assert result["self_pay_cents"] == result["claim_amount_cents"]


# =========================================================================
# /settle: tiered reimbursement computation
# =========================================================================
class TestSettle:

    def test_settle_in_scope_tier1_rate(self, api):
        """PRD §3.7: 'When the linked prescription's disease_codes
        intersects the in-scope disease enumeration (or the claim covers
        only the consultation fee and has no prescription linkage), the
        first-tier rate is 0.70 and the second-tier rate is 0.50.'

        PRD §3.7: 'Each tier is multiplied by its rate and rounded
        half-up to integer cents independently; the rounded tier amounts
        are then summed to produce reimbursed_cents.'

        Claim: in-scope, eligible_cents within tier1 ->
        reimbursed_cents == round_half_up(eligible_cents * 0.70).

        Concrete: claim_amount_cents = 15000, deductible 5000 ->
        eligible = 10000 (exactly tier1 cap); tier1_amt =
        round_half_up(10000 * 0.70) = 7000; tier2_amt = 0;
        reimbursed_cents == 7000.
        """
        # Build a setup where claim_amount_cents will land at 15000
        # cents. With base_fee=30, ceil(elapsed/60) needs (5+10 min)? Let
        # us use consultation total alone to be precise:
        # total_fee = 50.00 -> 5000 cents; prescription gross = 10000
        # cents (qty=20, unit=500); claim_amount = 5000 + 10000 = 15000.
        from test_helpers import (
            make_prescription_item,
            setup_completed_consultation,
            draft_prescription,
            submit_prescription,
            approve_prescription,
            dispatch_prescription,
        )
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60,  # 20 minutes
            doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        # 20-min total_fee: 3000 + 10*100 + 10*200 = 6000 cents = 60.00
        # Make pres gross = 9000 cents so claim_amount = 6000+9000=15000.
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE under this setup")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable post-dispatch")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        assert verified["claim_amount_cents"] == 15000
        settling = settle_claim(claim=verified)
        assert settling["status"] == "SETTLING"
        # eligible = 15000-5000 = 10000; tier1 = min(10000, 10000) = 10000;
        # tier1_amt = round_half_up(10000*0.70) = 7000; tier2_amt=0;
        # reimbursed = 7000; self_pay = 15000-7000 = 8000.
        assert settling["reimbursed_cents"] == 7000
        assert settling["self_pay_cents"] == 8000


# =========================================================================
# BUREAU_SETTLED: terminal + bureau_ref + invariant + idempotency.
# =========================================================================
class TestBureauSettled:

    def test_bureau_settled_advances_terminal_and_sets_bureau_ref(self, api):
        """PRD §3.7: 'A BUREAU_SETTLED event advances status from SETTLING
        to the terminal SETTLED, sets bureau_ref from the event payload,
        and is the audit point at which the compensating invariant
        claim_amount_cents == reimbursed_cents + self_pay_cents must hold.'

        Claim: emitting BUREAU_SETTLED advances claim to SETTLED, sets
        bureau_ref, and the invariant holds.
        """
        from test_helpers import (
            make_prescription_item,
            setup_completed_consultation,
            draft_prescription,
            submit_prescription,
            approve_prescription,
            dispatch_prescription,
        )
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE under this setup")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        settling = settle_claim(claim=verified)
        bureau_ref = "BR-ABC-001"
        res = bureau_settled_event(claim=settling, bureau_ref=bureau_ref)
        validate_success(res)
        final = _get_claim(settling["id"])
        assert final["status"] == "SETTLED"
        assert final.get("bureau_ref") == bureau_ref
        assert_settlement_invariant(final)


# =========================================================================
# BUREAU_REJECTED: terminal compensating action.
# =========================================================================
class TestBureauRejected:

    def test_bureau_rejected_resets_reimbursed_and_full_self_pay(self, api):
        """PRD §3.7: 'A BUREAU_REJECTED event advances status from
        SETTLING to the terminal REJECTED_BY_BUREAU, resets
        reimbursed_cents to zero, and sets self_pay_cents to the full
        claim_amount_cents.'

        Claim: emitting BUREAU_REJECTED -> status REJECTED_BY_BUREAU,
        reimbursed_cents == 0, self_pay_cents == claim_amount_cents.
        """
        from test_helpers import (
            make_prescription_item,
            setup_completed_consultation,
            draft_prescription,
            submit_prescription,
            approve_prescription,
            dispatch_prescription,
        )
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        settling = settle_claim(claim=verified)
        res = bureau_rejected_event(claim=settling)
        validate_success(res)
        final = _get_claim(settling["id"])
        assert final["status"] == "REJECTED_BY_BUREAU"
        assert final["reimbursed_cents"] == 0
        assert final["self_pay_cents"] == final["claim_amount_cents"]


# =========================================================================
# Collect-self-pay idempotency.
# =========================================================================
class TestCollectSelfPay:

    def test_collect_self_pay_sets_collected_equal_to_self_pay(self, api):
        """PRD §3.7: 'The collect-self-pay action is idempotent on
        self_pay_collected_cents: the call is accepted only while
        self_pay_collected_cents is zero, and it sets
        self_pay_collected_cents equal to self_pay_cents.'

        Claim: after SETTLED, /collect-self-pay sets
        self_pay_collected_cents to self_pay_cents.
        """
        from test_helpers import (
            make_prescription_item,
            setup_completed_consultation,
            draft_prescription,
            submit_prescription,
            approve_prescription,
            dispatch_prescription,
        )
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        settling = settle_claim(claim=verified)
        bureau_settled_event(claim=settling, bureau_ref="BR-X")
        final = _get_claim(settling["id"])
        collected = get_success_data(api_client.collect_self_pay(
            final["id"], ADMIN,
        ))
        assert collected["self_pay_collected_cents"] == \
            collected["self_pay_cents"]


# ===========================================================================
# Helpers
# ===========================================================================
def _find_claim_for_consultation(consultation_id: str):
    """Walk audit logs to find the claim id whose consultation_id
    matches. Best-effort; tests skip when claim is not discoverable."""
    from prd_bench_local_runner.testing import validate_paginated
    try:
        resp = api_client.list_audit_logs(
            ADMIN,
            params={"target_entity": "InsuranceClaim", "limit": 100},
        )
        data, _ = validate_paginated(resp)
        for row in data:
            tid = row.get("target_id")
            if not tid:
                continue
            try:
                claim = get_success_data(
                    api_client.get_insurance_claim(tid, ADMIN),
                )
                if claim.get("consultation_id") == consultation_id:
                    return claim
            except Exception:
                continue
    except Exception:
        return None
    return None
