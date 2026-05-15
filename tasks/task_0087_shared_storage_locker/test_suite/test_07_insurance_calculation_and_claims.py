"""Insurance premium calculation and claim lifecycle (PRD §3.4, §3.9)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    INSURANCE_AGENT_ID,
    approve_claim,
    approve_claim_payload,
    create_active_rental,
    deny_claim,
    file_insurance_claim,
    make_renter_headers,
    pay_claim,
    reject_evidence,
    request_evidence,
    setup_basic_rental,
    setup_cabinet_with_compartment,
    setup_returned_rental_with_insurance_claim,
    submit_evidence,
    validate_error,
    validate_success,
)


# ===========================================================================
# Insurance-premium formula (PRD §3.4)
# ===========================================================================
class TestInsurancePremium:

    def test_none_tier_premium_is_zero(self, api):
        """PRD §3.4: "For NONE the entire premium is zero."

        Claim: insurance_tier=NONE → insurance_premium_cents=0.
        """
        ctx = setup_basic_rental(insurance_tier="NONE", declared_value_cents=0)
        assert ctx["rental"]["insurance_premium_cents"] == 0

    def test_basic_tier_premium_non_linear_inputs(self, api):
        """PRD §3.4: "BASIC carries a base rate of 50 cents per day ...
        the rental's total duration in days is billing_units multiplied
        by the unit-duration in seconds for the rental's mode, divided
        by 86,400, rounded up to the next whole day. ... a value-loading
        amount is computed as declared_value_cents multiplied by the
        tier loading rate (0.002 for BASIC, 0.005 for PREMIUM) and then
        rounded up to the next whole cent; the rounding-up is applied
        after the multiplication."

        Claim: BASIC + 2-day rental + declared=500000 →
        premium = 50*2 + ceil(500000*0.002) = 100 + 1000 = 1100.

        # difficulty: combinatorial_formula/insurance_premium_three_inputs_nonlinear
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="DAILY",
        )
        rental, _ = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-basic-prem",
            rental_mode="DAILY",
            billing_units=2,
            insurance_tier="BASIC",
            declared_value_cents=500_000,
            unlock_channel="QR",
        )
        assert rental["insurance_premium_cents"] == 1100, (
            f"BASIC premium expected 1100 (=50*2 + ceil(500000*0.002)=100+1000), "
            f"got {rental['insurance_premium_cents']}"
        )

    def test_premium_tier_premium_non_linear_inputs(self, api):
        """PRD §3.4: "BASIC carries a base rate of 50 cents per day and
        PREMIUM carries 150 cents per day."
        PRD §3.4: "a value-loading amount is computed as
        declared_value_cents multiplied by the tier loading rate (0.002
        for BASIC, 0.005 for PREMIUM) and then rounded up to the next
        whole cent."

        Claim: PREMIUM + 2-day rental + declared=500000 →
        premium = 150*2 + ceil(500000*0.005) = 300 + 2500 = 2800.

        # difficulty: combinatorial_formula/insurance_premium_three_inputs_nonlinear
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="DAILY", slot_count=2,
        )
        rental, _ = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-prem-prem",
            rental_mode="DAILY",
            billing_units=2,
            insurance_tier="PREMIUM",
            declared_value_cents=500_000,
            unlock_channel="QR",
        )
        assert rental["insurance_premium_cents"] == 2800, (
            f"PREMIUM premium expected 2800 (=150*2 + ceil(500000*0.005)=300+2500), "
            f"got {rental['insurance_premium_cents']}"
        )

    def test_basic_value_loading_caps_at_2000(self, api):
        """PRD §3.4: "the value-loading amount is then capped by the
        tier's loading cap (2,000 cents for BASIC, 10,000 cents for
        PREMIUM) by taking the smaller of the two."

        Claim: BASIC + 1-day rental + declared=2,000,000 →
        loading raw = ceil(2,000,000*0.002) = 4000; capped at 2000.
        Premium = 50*1 + 2000 = 2050.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            rental_mode="DAILY", slot_count=1,
        )
        rental, _ = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-basic-cap",
            rental_mode="DAILY",
            billing_units=1,
            insurance_tier="BASIC",
            declared_value_cents=2_000_000,
            unlock_channel="QR",
        )
        assert rental["insurance_premium_cents"] == 2050, (
            f"BASIC capped premium expected 2050 (=50 + min(4000,2000)=50+2000), "
            f"got {rental['insurance_premium_cents']}"
        )


# ===========================================================================
# Claim filing (PRD §3.9)
# ===========================================================================
class TestClaimFiling:

    def test_file_claim_against_basic_rental_creates_reported(self, api):
        """PRD §3.9: "A Renter who owns an active or completed rental may
        file a single insurance claim against it by supplying rental_id,
        claim_type (one of DAMAGE, LOSS, or THEFT), and
        claimed_amount_cents (strictly positive). ... The new claim's
        status is REPORTED, renter_id is snapshotted from the rental,
        evidence_count is zero."

        Claim: file claim on BASIC rental → status=REPORTED,
        evidence_count=0, renter_id snapshotted from rental.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-claim-1",
        )
        c = ctx["claim"]
        assert c["status"] == "REPORTED"
        assert c["evidence_count"] == 0
        assert c["renter_id"] == "renter-claim-1"

    def test_second_open_claim_rejected(self, api):
        """PRD §3.9: "At most one claim per rental may exist in any state
        other than DENIED or PAID; an attempt to file a second open
        claim is rejected with ERR_CLAIM_ALREADY_OPEN."

        Claim: second claim on the same rental → ERR_CLAIM_ALREADY_OPEN.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-dup-claim",
        )
        from test_helpers import (
            api_client,
            create_insurance_claim_payload,
        )
        payload = create_insurance_claim_payload(
            rental_id=ctx["rental"]["id"],
            claim_type="LOSS",
            claimed_amount_cents=100_000,
        )
        resp = api_client.create_insurance_claim(
            payload, make_renter_headers(ctx["renter_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_OPEN.value)


# ===========================================================================
# Claim lifecycle — happy path (PRD §3.9)
# ===========================================================================
class TestClaimLifecycle:

    def test_request_evidence_moves_to_pending(self, api):
        """PRD §3.9: "The agent requests evidence (REPORTED →
        EVIDENCE_PENDING)."

        Claim: request-evidence on REPORTED claim → EVIDENCE_PENDING.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-rev-1",
        )
        c = request_evidence(ctx["claim"]["id"],
                             version=ctx["claim"]["version"])
        assert c["status"] == "EVIDENCE_PENDING"

    def test_evidence_submission_moves_to_under_review(self, api):
        """PRD §3.9: "the renter then submits evidence by supplying
        evidence_description and optional version; submission increments
        evidence_count and, once evidence_count is at least one, advances
        status to UNDER_REVIEW."

        Claim: submit-evidence on EVIDENCE_PENDING → UNDER_REVIEW with
        evidence_count==1.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-rev-2",
        )
        c = request_evidence(ctx["claim"]["id"],
                             version=ctx["claim"]["version"])
        c = submit_evidence(c["id"], ctx["renter_id"], version=c["version"])
        assert c["status"] == "UNDER_REVIEW"
        assert c["evidence_count"] == 1

    def test_deny_moves_to_denied(self, api):
        """PRD §3.9: "deny by supplying rejection_reason, advancing to
        DENIED."

        Claim: deny on UNDER_REVIEW → DENIED.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-rev-deny",
        )
        c = request_evidence(ctx["claim"]["id"],
                             version=ctx["claim"]["version"])
        c = submit_evidence(c["id"], ctx["renter_id"], version=c["version"])
        c = deny_claim(c["id"], reason="not covered", version=c["version"])
        assert c["status"] == "DENIED"

    def test_approve_then_pay_moves_to_paid(self, api):
        """PRD §3.9: "the agent records the payout (APPROVED → PAID)."

        Claim: approve(payout) → APPROVED with payout_cents; then pay →
        PAID.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC",
            renter_id="renter-pay",
            declared_value_cents=500_000,
            claimed_amount_cents=100_000,
        )
        c = request_evidence(ctx["claim"]["id"],
                             version=ctx["claim"]["version"])
        c = submit_evidence(c["id"], ctx["renter_id"], version=c["version"])
        # Approve with payout under min(claimed=100000, declared=500000, BASIC cap).
        c = approve_claim(c["id"], payout_cents=50_000, version=c["version"])
        assert c["status"] == "APPROVED"
        assert c["payout_cents"] == 50_000
        c = pay_claim(c["id"], version=c["version"])
        assert c["status"] == "PAID"


# ===========================================================================
# Approval cap (PRD §3.9)
# ===========================================================================
class TestApprovalCap:

    def test_payout_above_claimed_amount_rejected(self, api):
        """PRD §3.9: "Approval pins payout_cents to a value no greater
        than the smallest of: claimed_amount_cents, the rental's
        declared_value_cents, and the tier-payout cap that the system
        has configured for the rental's insurance_tier; an approval
        that violates this cap is rejected with ERR_PAYOUT_EXCEEDS_CAP."

        Claim: approve(payout=claimed_amount+1) on a claim with
        declared_value_cents > claimed_amount_cents → ERR_PAYOUT_EXCEEDS_CAP.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC",
            renter_id="renter-cap",
            declared_value_cents=500_000,
            claimed_amount_cents=50_000,
        )
        c = request_evidence(ctx["claim"]["id"],
                             version=ctx["claim"]["version"])
        c = submit_evidence(c["id"], ctx["renter_id"], version=c["version"])
        # payout above claimed_amount_cents = above the min(...).
        from test_helpers import api_client
        resp = api_client.approve_claim(
            c["id"], approve_claim_payload(payout_cents=60_000,
                                           version=c["version"]),
            __import__("test_helpers").TEST_USERS["insurance_agent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PAYOUT_EXCEEDS_CAP.value)


# ===========================================================================
# Claim ownership (PRD §2.1, §3.9)
# ===========================================================================
class TestClaimOwnership:

    def test_non_owner_renter_cannot_submit_evidence(self, api):
        """PRD §3.9: "Throughout the lifecycle, the renter's ownership
        is checked against the claim's snapshotted renter_id."

        Claim: a non-owner Renter submitting evidence → ERR_FORBIDDEN.
        """
        ctx = setup_returned_rental_with_insurance_claim(
            insurance_tier="BASIC", renter_id="renter-claim-owner",
        )
        c = request_evidence(ctx["claim"]["id"],
                             version=ctx["claim"]["version"])
        from test_helpers import api_client, submit_evidence_payload
        resp = api_client.submit_evidence(
            c["id"], submit_evidence_payload(version=c["version"]),
            make_renter_headers("renter-other"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
