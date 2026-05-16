"""Patient-responsibility waterfall — both variants, rounding, OOP cap.

Covers PRD §3.5 (waterfall arithmetic), §2.7 (rounding pin), and §3.6
(payer_clearance_calc tie-in).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_allowed_amount_conservation,
    re_get_encounter,
    re_get_policy,
    setup_coded_encounter,
    submit_clearance_payload,
    validate_success,
)


# ===========================================================================
# §3.5 — Step 1 (deductible bucket): member pays 100% until met
# ===========================================================================
class TestWaterfallDeductibleBucket:
    """PRD §3.5 Step 1: "The deductible portion of the current calculation is the smaller of the billable input and that remaining deductible.\""""

    def test_billable_below_deductible_yields_all_member(self, api):
        """PRD §3.5: "The deductible remaining is the policy's `deductible_cents` minus its starting `deductible_met_cents`, with negative results clamped to zero. The deductible portion of the current calculation is the smaller of the billable input and that remaining deductible."

        Claim: with deductible=100000, coinsurance=2000, oop_max=
        200000, and an APPROVED allowed_amount=50000 (entirely under
        deductible): patient_responsibility_cents == 50000 AND
        payer_responsibility_cents == 0.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=50_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="APPROVED", allowed_amount_cents=50_000,
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["patient_responsibility_cents"] == 50_000
        assert refreshed["payer_responsibility_cents"] == 0


# ===========================================================================
# §3.5 — Step 2 (coinsurance bucket): rounding pinned ONCE per bucket
# ===========================================================================
class TestWaterfallCoinsuranceBucket:
    """PRD §2.7 + §3.5: coinsurance is rounded ONCE, on the bucket
    total, after multiplication."""

    def test_deductible_plus_coinsurance(self, api):
        """PRD §3.5 Step 2: "The post-deductible billable is the billable input minus the deductible portion. The raw coinsurance amount is that post-deductible billable multiplied by the policy's `coinsurance_rate_bps` and divided by ten thousand."

        Claim: with deductible=100000, coinsurance=2000, oop_max=
        200000, and allowed=120000: deductible_portion=100000,
        post_deductible=20000, coinsurance=0.2*20000=4000, member=
        104000, payer=120000-104000=16000.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=120_000,
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

    def test_coinsurance_rounding_bucket_once_not_per_line(self, api):
        """PRD §2.7: "the raw coinsurance amount is produced by multiplying the post-deductible billable cents by the coinsurance basis points and dividing by ten thousand, and that single intermediate value is rounded to the nearest whole cent using half-up rounding **once**, after the multiplication and division have been performed."

        Claim: with deductible=0, coinsurance=1750, oop_max=99999, and
        two charges of 3333 each (total 6666): bucket-then-round
        yields round_half_up(6666 * 0.175 = 1166.55) = 1167, NOT
        2 * round(583.275) = 1166.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=0,
            coinsurance_rate_bps=1750,
            oop_max_cents=99_999,
            charges=[
                {"cpt_code": "99213", "quantity": 1,
                 "unit_price_cents": 3333},
                {"cpt_code": "99214", "quantity": 1,
                 "unit_price_cents": 3333},
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
        assert refreshed["patient_responsibility_cents"] == 1167, (
            "Bucket-then-round must produce 1167, not 1166. PRD §2.7 "
            "pins rounding once on the coinsurance bucket."
        )
        assert refreshed["payer_responsibility_cents"] == 5499


# ===========================================================================
# §3.5 — Step 4 (OOP cap): clips uncapped member responsibility
# ===========================================================================
class TestWaterfallOOPCap:
    """PRD §3.5 Step 4: "The member-payable amount is the smaller of the uncapped member responsibility and that OOP remaining."""

    def test_oop_cap_clips_member_payable(self, api):
        """PRD §3.5: "The member-payable amount is the smaller of the uncapped member responsibility and that OOP remaining."

        Claim: deductible=50000, coinsurance=2500, oop_max=80000;
        allowed=200000; deductible_portion=50000, post_deductible=
        150000, coinsurance=0.25*150000=37500, uncapped_member=
        87500, but OOP_remaining=80000-0=80000 caps member at 80000;
        payer = 200000 - 80000 = 120000.
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


# ===========================================================================
# §3.5 — Final variant updates accumulators; estimate does NOT
# ===========================================================================
class TestAccumulatorUpdates:
    """PRD §3.5: "after the member-payable amount has been computed, adds the **deductible portion** (from Step 1) to the policy's `deductible_met_cents` and adds the **member-payable amount** (from Step 4) to the policy's `oop_accumulated_cents`"""

    def test_final_variant_updates_deductible_met_and_oop_accumulated(
        self, api,
    ):
        """PRD §3.5: "after the member-payable amount has been computed, adds the **deductible portion** (from Step 1) to the policy's `deductible_met_cents` and adds the **member-payable amount** (from Step 4) to the policy's `oop_accumulated_cents`"

        Claim: with deductible=100000, coinsurance=2000, oop_max=
        200000, and allowed=120000 (APPROVED): deductible_met_cents
        becomes 100000 and oop_accumulated_cents becomes 104000.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=120_000,
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

    def test_pr_code_bypass_does_not_touch_accumulators(self, api):
        """PRD §3.6: "the unallowed portion bypasses the deductible / coinsurance / OOP waterfall entirely and flows into `patient_responsibility_cents` in full."

        Claim: a DENIED+PR-1 path (where the waterfall is bypassed)
        leaves InsurancePolicy.deductible_met_cents unchanged at 0.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=100_000,
            coinsurance_rate_bps=2000,
            oop_max_cents=200_000,
            unit_price_cents=10_000,
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
        # PR-code bypass: waterfall is skipped entirely, so neither
        # accumulator advances.
        assert refreshed_policy["deductible_met_cents"] == 0


# ===========================================================================
# §3.6 — payer + patient == allowed_amount conservation (APPROVED branch)
# ===========================================================================
class TestAllowedAmountConservation:
    """PRD §3.6: "`payer_responsibility_cents` plus `patient_responsibility_cents` equals `allowed_amount_cents` exactly."""

    def test_partial_decision_conservation_holds(self, api):
        """PRD §3.6: "`payer_responsibility_cents` plus `patient_responsibility_cents` equals `allowed_amount_cents` exactly."

        Claim: under PARTIAL adjudication with allowed=80000 and
        deductible=50000, coinsurance=2500, oop_max=80000: patient+
        payer == 80000.
        """
        patient, policy, encounter, _ = setup_coded_encounter(
            deductible_cents=50_000,
            coinsurance_rate_bps=2500,
            oop_max_cents=80_000,
            unit_price_cents=100_000,
        )
        api.submit_clearance(
            encounter["id"],
            submit_clearance_payload(
                decision="PARTIAL", allowed_amount_cents=80_000,
                denial_reason_code="CO-45",
            ),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert_allowed_amount_conservation(refreshed, 80_000)
