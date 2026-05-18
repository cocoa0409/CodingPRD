"""Chapter 7 discharge path — partition pass, stay lifts.

PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_discharge_partition_total_preserved,
    discharge_case,
    re_get_case,
    re_get_claim,
    setup_ch7_discharged_case,
    setup_meeting_held_case,
    validate_error,
)


# ===========================================================================
# Ch7 discharge — PRD §3.7
# ===========================================================================
class TestChapter7Discharge:
    """PRD §3.7: 'A Chapter 7 case advances from MEETING_HELD directly
    to DISCHARGED by judicial order. The judge's discharge transition
    is permitted only when chapter_effective equals CHAPTER_7 — a
    Chapter 13 case must complete its plan first and any attempt to
    discharge it from MEETING_HELD is rejected with
    ERR_PLAN_NOT_COMPLETE. On discharge, the system runs the
    exemption-partition pass: every claim still in ALLOWED is
    partitioned by is_dischargeable such that a true value transitions
    the claim to DISCHARGED and a false value transitions it to
    NON_DISCHARGEABLE_REMAINS.'"""

    def test_ch7_discharge_from_meeting_held_succeeds(self, api):
        """PRD §3.7: "A Chapter 7 case advances from MEETING_HELD
        directly to DISCHARGED by judicial order."

        Claim: discharge a Ch7 case in MEETING_HELD -> status=DISCHARGED.
        """
        debtor, case, _mtr, _cr, _claims = setup_ch7_discharged_case()
        assert case["status"] == "DISCHARGED"

    def test_ch7_discharge_lifts_automatic_stay(self, api):
        """PRD §3.7: "Discharge also flips automatic_stay_active to
        false, lifting the stay at the moment relief is granted."

        Claim: after Ch7 discharge, automatic_stay_active=false.
        """
        debtor, case, _mtr, _cr, _claims = setup_ch7_discharged_case()
        assert case["automatic_stay_active"] is False

    def test_dischargeable_claims_go_to_DISCHARGED(self, api):
        """PRD §3.7: "every claim still in ALLOWED is partitioned by
        is_dischargeable such that a true value transitions the claim
        to DISCHARGED and a false value transitions it to
        NON_DISCHARGEABLE_REMAINS."

        Claim: a claim with is_dischargeable=true ends up in
        DISCHARGED after Ch7 discharge.
        # difficulty: dual_variant_calc/claim_dischargeable_vs_nondischargeable_partition
        """
        debtor, case, _mtr, _cr, post_claims = setup_ch7_discharged_case(
            claims=[
                {"amount_cents": 500_000, "is_dischargeable": True,
                 "claim_class": "GENERAL_UNSECURED"},
            ],
        )
        assert len(post_claims) == 1
        assert post_claims[0]["status"] == "DISCHARGED"

    def test_nondischargeable_claims_go_to_NON_DISCHARGEABLE_REMAINS(self, api):
        """PRD §3.7: "a false value transitions it to
        NON_DISCHARGEABLE_REMAINS."

        Claim: a claim with is_dischargeable=false ends up in
        NON_DISCHARGEABLE_REMAINS after Ch7 discharge.
        # difficulty: dual_variant_calc/claim_dischargeable_vs_nondischargeable_partition
        """
        debtor, case, _mtr, _cr, post_claims = setup_ch7_discharged_case(
            claims=[
                {"amount_cents": 200_000, "is_dischargeable": False,
                 "claim_class": "GENERAL_UNSECURED"},
            ],
        )
        assert len(post_claims) == 1
        assert post_claims[0]["status"] == "NON_DISCHARGEABLE_REMAINS"

    def test_partition_is_total_no_claim_left_in_allowed(self, api):
        """PRD §3.7: "The partition is total — the sum of amount_cents
        across all claims that were ALLOWED immediately before the
        discharge equals the sum across the two terminal buckets
        after, with no claim left in ALLOWED."

        Claim: every formerly-ALLOWED claim is in one of {DISCHARGED,
        NON_DISCHARGEABLE_REMAINS}; total amount_cents preserved.
        # difficulty: compensating_invariant/discharge_partition_preserves_claim_amount_total
        """
        claim_specs = [
            {"amount_cents": 100_000, "is_dischargeable": True,
             "claim_class": "GENERAL_UNSECURED"},
            {"amount_cents": 200_000, "is_dischargeable": False,
             "claim_class": "GENERAL_UNSECURED"},
            {"amount_cents": 300_000, "is_dischargeable": True,
             "claim_class": "GENERAL_UNSECURED"},
        ]
        pre_total = sum(c["amount_cents"] for c in claim_specs)
        debtor, case, _mtr, _cr, post_claims = setup_ch7_discharged_case(
            claims=claim_specs,
        )
        assert len(post_claims) == 3
        for c in post_claims:
            assert c["status"] in {
                "DISCHARGED", "NON_DISCHARGEABLE_REMAINS",
            }
        assert_discharge_partition_total_preserved(
            pre_total, post_claims,
        )


# ===========================================================================
# Ch7 discharge on Ch13 case rejected — PRD §3.7
# ===========================================================================
class TestChapter13CannotDirectDischargeFromMeetingHeld:
    """PRD §3.7: 'a Chapter 13 case must complete its plan first and
    any attempt to discharge it from MEETING_HELD is rejected with
    ERR_PLAN_NOT_COMPLETE.'"""

    def test_chapter_13_discharge_from_meeting_held_rejected(self, api):
        """PRD §3.7: "a Chapter 13 case must complete its plan first
        and any attempt to discharge it from MEETING_HELD is rejected
        with ERR_PLAN_NOT_COMPLETE."

        Claim: discharge against a Ch13 case in MEETING_HELD ->
        ERR_PLAN_NOT_COMPLETE.
        # difficulty: non_linear_state_machine/case_branching_chapter7_vs_chapter13_paths
        """
        debtor, case, _mtr, _cr, _claims = setup_meeting_held_case(
            chapter_requested="CHAPTER_13",
            claims=[{"amount_cents": 500_000,
                     "is_dischargeable": True,
                     "claim_class": "GENERAL_UNSECURED"}],
        )
        assert case["chapter_effective"] == "CHAPTER_13"
        resp = api.discharge_case(
            case["id"], None, TEST_USERS["judge_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_COMPLETE.value)
