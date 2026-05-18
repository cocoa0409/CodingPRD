"""Earnest Money Deposit lifecycle, floor, and disposition (PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_emd,
    assert_emd_conservation,
    cancel_escrow,
    create_emd_held,
    create_escrow_file_basic,
    emd_payload,
    emd_release_payload,
    re_get_emd,
    re_get_escrow_file,
    release_emd_with_reason,
    setup_emd_held,
    validate_error,
    validate_success,
    version_only_payload,
    with_idempotency,
)


# ===========================================================================
# Create EMD — PRD §3.2
# ===========================================================================
class TestCreateEMD:

    def test_create_emd_returns_pending_funds(self, api):
        """PRD §3.2: "The deposit begins in PENDING_FUNDS."

        Claim: POST /earnest-money returns 201 with status =
        PENDING_FUNDS.
        """
        bundle = create_escrow_file_basic()
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.create_emd(
            emd_payload(escrow_file_id=bundle["escrow_file"]["id"],
                        amount=3000.00),
            eo,
        )
        data = validate_success(resp, expected_status=201)
        assert_emd(data)
        assert data["status"] == "PENDING_FUNDS"
        assert data["amount"] == pytest.approx(3000.00)
        assert data["forfeited_amount"] == pytest.approx(0.0)
        assert data["refunded_amount"] == pytest.approx(0.0)


# ===========================================================================
# EMD floor — PRD §3.2 (and difficulty rule 6)
# ===========================================================================
class TestEMDFloor:

    def test_emd_floor_exact_one_percent_passes(self, api):
        """PRD §3.2: "the amount must be greater than or equal to one
        percent of the parent escrow file's purchase_price, with
        exactly one percent permitted (the comparison is strictly
        inclusive — the boundary value passes)".

        Claim: amount == 1.0% of purchase_price (3000 on 300000) funds
        successfully to HELD.

        # difficulty: boundary_precision_check/emd_floor_one_percent_exact_equality
        """
        bundle = create_escrow_file_basic(purchase_price=300000.00)
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        # Create EMD at exact-equality boundary.
        create_resp = api.create_emd(
            emd_payload(
                escrow_file_id=bundle["escrow_file"]["id"],
                amount=3000.00,
            ),
            eo,
        )
        emd = validate_success(create_resp, expected_status=201)
        eo2 = with_idempotency(TEST_USERS["escrow_officer_headers"])
        fund = api.fund_emd(
            emd["id"], version_only_payload(version=emd["version"]), eo2,
        )
        funded = validate_success(fund)
        assert funded["status"] == "HELD"

    def test_emd_floor_just_under_one_percent_rejected(self, api):
        """PRD §3.2: "A deposit that falls beneath this threshold is
        rejected with ERR_EMD_BELOW_FLOOR. The floor check is enforced
        not only at funding time but at every endpoint that creates,
        modifies, or funds the deposit."

        Claim: amount = 2999.99 on a 300000 sale fails the EMD floor
        with ERR_EMD_BELOW_FLOOR at create time (per PRD's "at every
        endpoint that creates, modifies, or funds" clause).

        # difficulty: boundary_precision_check/emd_floor_one_percent_exact_equality
        """
        bundle = create_escrow_file_basic(purchase_price=300000.00)
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        # Create EMD at sub-floor amount — PRD says the floor check
        # fires at create, modify, OR fund, so create is permitted to
        # reject.
        create_resp = api.create_emd(
            emd_payload(
                escrow_file_id=bundle["escrow_file"]["id"],
                amount=2999.99,
            ),
            eo,
        )
        validate_error(create_resp, ApiErrorId.ERR_EMD_BELOW_FLOOR)


# ===========================================================================
# EMD disposition variants — PRD §3.2 + difficulty rule 1
# ===========================================================================
class TestEMDDispositionVariants:

    def test_release_buyer_default_forfeits_to_seller(self, api):
        """PRD §3.2: "When the file cancels under buyer default ... the
        entire deposit forfeits to the seller."

        Claim: release with reason=BUYER_DEFAULT yields
        RELEASED_TO_SELLER with forfeited_amount = amount and
        refunded_amount = 0.

        # difficulty: dual_variant_calc/emd_disposition_buyer_vs_seller_default
        """
        bundle = setup_emd_held(emd_amount=3000.00)
        emd = bundle["emd"]
        result = release_emd_with_reason(
            emd["id"], "BUYER_DEFAULT", version=emd["version"],
        )
        assert result["status"] == "RELEASED_TO_SELLER"
        assert result["forfeited_amount"] == pytest.approx(3000.00)
        assert result["refunded_amount"] == pytest.approx(0.0)
        assert_emd_conservation(result)

    def test_release_seller_default_refunds_to_buyer(self, api):
        """PRD §3.2: "When the file cancels because the seller failed
        to deliver clear title or violated the CC&R disclosure
        obligation, the deposit refunds to the buyer in full".

        Claim: release with reason=SELLER_DEFAULT yields
        RELEASED_TO_BUYER with refunded_amount = amount.

        # difficulty: dual_variant_calc/emd_disposition_buyer_vs_seller_default
        """
        bundle = setup_emd_held(emd_amount=3000.00)
        emd = bundle["emd"]
        result = release_emd_with_reason(
            emd["id"], "SELLER_DEFAULT", version=emd["version"],
        )
        assert result["status"] == "RELEASED_TO_BUYER"
        assert result["forfeited_amount"] == pytest.approx(0.0)
        assert result["refunded_amount"] == pytest.approx(3000.00)
        assert_emd_conservation(result)

    def test_release_title_defect_refunds_to_buyer(self, api):
        """PRD §3.2 (TITLE_DEFECT triggers the same refund-to-buyer
        branch): "When the file cancels because the seller failed to
        deliver clear title or violated the CC&R disclosure obligation,
        the deposit refunds to the buyer in full".

        Claim: reason=TITLE_DEFECT refunds to buyer.
        """
        bundle = setup_emd_held(emd_amount=3000.00)
        emd = bundle["emd"]
        result = release_emd_with_reason(
            emd["id"], "TITLE_DEFECT", version=emd["version"],
        )
        assert result["status"] == "RELEASED_TO_BUYER"
        assert result["refunded_amount"] == pytest.approx(3000.00)
        assert result["forfeited_amount"] == pytest.approx(0.0)
        assert_emd_conservation(result)

    def test_mutual_release_split_correct_shares(self, api):
        """PRD §3.2: "On a successful mutual release, the status moves
        to SPLIT, refunded_amount is set to the buyer share and
        forfeited_amount is set to the seller share".

        Claim: MUTUAL_RELEASE with shares summing to amount yields
        SPLIT with correctly assigned components.
        """
        bundle = setup_emd_held(emd_amount=3000.00)
        emd = bundle["emd"]
        result = release_emd_with_reason(
            emd["id"], "MUTUAL_RELEASE",
            version=emd["version"],
            split_buyer_share=1200.00,
            split_seller_share=1800.00,
        )
        assert result["status"] == "SPLIT"
        assert result["refunded_amount"] == pytest.approx(1200.00)
        assert result["forfeited_amount"] == pytest.approx(1800.00)
        assert_emd_conservation(result)


# ===========================================================================
# Mutual release split invariant — PRD §3.2 (difficulty rule 9)
# ===========================================================================
class TestMutualReleaseSplitInvariant:

    def test_split_shares_not_summing_to_amount_rejected(self, api):
        """PRD §3.2: "The two shares must sum to the deposit amount
        exactly — no rounding tolerance whatsoever — or the request is
        rejected with ERR_EMD_SPLIT_INVARIANT."

        Claim: split shares 1000 + 1000 on a 3000 deposit yields
        ERR_EMD_SPLIT_INVARIANT.
        """
        bundle = setup_emd_held(emd_amount=3000.00)
        emd = bundle["emd"]
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.release_emd(
            emd["id"],
            emd_release_payload(
                reason="MUTUAL_RELEASE",
                split_buyer_share=1000.00,
                split_seller_share=1000.00,
                version=emd["version"],
            ),
            eo,
        )
        validate_error(resp, ApiErrorId.ERR_EMD_SPLIT_INVARIANT)


# ===========================================================================
# Conservation invariant — PRD §2.13 (difficulty rule 9)
# ===========================================================================
class TestEMDPoolConservation:

    @pytest.mark.parametrize(
        "reason,buyer_share,seller_share",
        [
            ("BUYER_DEFAULT", None, None),
            ("SELLER_DEFAULT", None, None),
            ("MUTUAL_RELEASE", 1200.00, 1800.00),
        ],
    )
    def test_emd_conservation_each_branch(
        self, api, reason, buyer_share, seller_share,
    ):
        """PRD §2.13: "for any EarnestMoneyDeposit that has left
        PENDING_FUNDS or HELD, the sum of forfeited_amount and
        refunded_amount always equals the row's amount — the cents
        that entered the deposit are accounted for in exactly one of
        those two buckets, with no leakage."

        Claim: every disposition variant conserves amount.

        # difficulty: compensating_invariant/emd_pool_dollar_conservation
        """
        bundle = setup_emd_held(emd_amount=3000.00)
        emd = bundle["emd"]
        result = release_emd_with_reason(
            emd["id"], reason,
            version=emd["version"],
            split_buyer_share=buyer_share,
            split_seller_share=seller_share,
        )
        # Compensating invariant always satisfied.
        total = round(result["forfeited_amount"] + result["refunded_amount"], 2)
        assert total == pytest.approx(3000.00, abs=0.01)
        assert_emd_conservation(result)
