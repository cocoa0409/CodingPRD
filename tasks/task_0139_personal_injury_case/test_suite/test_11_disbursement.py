"""Disbursement: approval guards, segregation of duties, waterfall.

PRD §3.9, §3.10.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_disbursement,
    approve_disbursement_payload,
    assert_disbursement_conservation,
    assert_settlement_disbursement,
    ATTORNEY_ID,
    get_case,
    MANAGING_PARTNER_ID,
    make_managing_partner_headers,
    setup_settled,
    setup_settled_via_litigation,
    setup_settled_with_liens,
    setup_trial_awarded,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Approval guard rails
# ===========================================================================
class TestApprovalGuards:

    def test_segregation_of_duties_blocks_same_user(
        self, api,
    ):
        """PRD §3.10: "the acting user's X-User-ID must not equal
        Case.assigned_attorney_id — the same person cannot have
        negotiated the settlement and approved the payout, and a
        violation is rejected with ERR_SEGREGATION_OF_DUTIES."

        Claim: ManagingPartner approving with X-User-ID equal to
        Case.assigned_attorney_id → ERR_SEGREGATION_OF_DUTIES.
        """
        _, case, _, _, _ = setup_settled(
            assigned_attorney_id=ATTORNEY_ID,
        )
        # Build approver headers with X-User-ID == ATTORNEY_ID
        # (deliberately violating SoD).
        bad_headers = make_managing_partner_headers(ATTORNEY_ID)
        resp = api.approve_disbursement(
            case["id"],
            approve_disbursement_payload("CHRONOLOGICAL_PRIORITY"),
            bad_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

    def test_double_approval_rejected(self, api):
        """PRD §3.10: "Case.disbursement_approved_by must still be
        null — a second approval on a case that has already been
        approved is rejected with ERR_DISBURSEMENT_ALREADY_APPROVED."

        Claim: Second POST /disbursement/approve →
        ERR_DISBURSEMENT_ALREADY_APPROVED.
        """
        result = setup_settled_with_liens(case_costs_cents=0)
        approve_disbursement(result["case"]["id"], "CHRONOLOGICAL_PRIORITY")
        # Second attempt
        resp = api.approve_disbursement(
            result["case"]["id"],
            approve_disbursement_payload("CHRONOLOGICAL_PRIORITY"),
            TEST_USERS["managing_partner_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_DISBURSEMENT_ALREADY_APPROVED.value,
        )

    def test_approve_with_negotiating_lien_blocked(self, api):
        """PRD §3.10: "every lien on the case must already be in a
        state acceptable for disbursement: any lien whose status is
        NEGOTIATING blocks the approval".

        Claim: A lien in NEGOTIATING state → approval blocked with
        ERR_INVALID_STATE.
        """
        from test_helpers import api_client, create_lien
        _, case, _, _, _ = setup_settled(case_costs_cents=0)
        lien = create_lien(case["id"], "PROVIDER_NEGOTIATED", 500_000)
        # Open negotiation but never PATCH the reduction → stuck
        # in NEGOTIATING.
        api_client.negotiate_lien(
            case["id"], lien["id"], TEST_USERS["paralegal_headers"],
        )
        resp = api.approve_disbursement(
            case["id"],
            approve_disbursement_payload("CHRONOLOGICAL_PRIORITY"),
            TEST_USERS["managing_partner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Waterfall math — chronological priority
# ===========================================================================
class TestChronologicalWaterfall:

    def test_no_liens_attorney_fee_and_client_net_pin(self, api):
        """PRD §3.9: "The attorney fee in cents is the gross settlement
        multiplied by the chosen rate divided by ten thousand, with
        the product rounded half-up to a whole number of cents."

        Claim: gross=10_000_000, no liens, pre_suit_rate_bps=3333,
        case_costs=0 → attorney_fee=3_333_000, client_net=6_667_000.
        """
        result = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=0,
            pre_suit_rate_bps=3333,
            medicare_face_cents=None,
            provider_negotiated_face_cents=None,
        )
        disbursement = approve_disbursement(
            result["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        assert_settlement_disbursement(disbursement)
        assert disbursement["gross_amount_cents"] == 10_000_000
        assert disbursement["attorney_fee_cents"] == 3_333_000
        assert disbursement["case_costs_cents"] == 0
        assert disbursement["total_lien_payment_cents"] == 0
        assert disbursement["client_net_cents"] == 6_667_000
        assert_disbursement_conservation(disbursement)

    def test_chronological_statutory_reduction_formula(self, api):
        """PRD §3.10: "if the lien's lien_type is MEDICARE, MEDICAID,
        ERISA, or CHILD_SUPPORT and negotiated_amount_cents is null,
        the system applies the statutory ratable-reduction formula —
        the attorney ratio is attorney_fee_cents divided by
        gross_settlement_cents and the cost ratio is case_costs_cents
        divided by gross_settlement_cents, and the reduced figure for
        the lien is face_amount_cents multiplied by the quantity one
        minus the attorney ratio minus the cost ratio, with the
        product rounded half-up to a whole number of cents".

        Claim: gross=10_000_000, attorney_fee=3_333_000 (33.33%),
        case_costs=250_000 (2.5%), MEDICARE face=1_500_000 →
        reduced = 1_500_000 * (1 - 0.3333 - 0.025) = 962_550 (exact
        half-up).
        """
        result = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=250_000,
            pre_suit_rate_bps=3333,
            medicare_face_cents=1_500_000,
        )
        disbursement = approve_disbursement(
            result["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        assert disbursement["attorney_fee_cents"] == 3_333_000
        # 1_500_000 * (1 - 0.3333 - 0.025) = 1_500_000 * 0.6417 = 962_550
        # exactly (round half-up trivially).
        assert disbursement["total_lien_payment_cents"] == 962_550
        # client_net = gross - fee - costs - lien
        # = 10_000_000 - 3_333_000 - 250_000 - 962_550 = 5_454_450
        assert disbursement["client_net_cents"] == 5_454_450
        assert_disbursement_conservation(disbursement)


# ===========================================================================
# Waterfall math — pro-rata
# ===========================================================================
class TestProrataWaterfall:

    def test_prorata_no_liens_residual_invariant(self, api):
        """PRD §3.10: "Under FORWARD_LOOKING_PRORATA, the system first
        sums the face_amount_cents across every lien on the case ...
        The final client_net_cents under pro-rata is the larger of
        zero and the lien pool minus the sum of all
        final_paid_amount_cents that were paid out."

        With no liens, total_lien_payment_cents == 0 and client_net ==
        gross - fee - costs.

        Claim: gross=10_000_000, no liens, pre_suit_rate_bps=3333,
        case_costs=0 → client_net=6_667_000 (same as chronological).
        """
        result = setup_settled_with_liens(
            gross_settlement_cents=10_000_000,
            case_costs_cents=0,
            pre_suit_rate_bps=3333,
        )
        disbursement = approve_disbursement(
            result["case"]["id"], "FORWARD_LOOKING_PRORATA",
        )
        assert disbursement["attorney_fee_cents"] == 3_333_000
        assert disbursement["client_net_cents"] == 6_667_000
        assert_disbursement_conservation(disbursement)


# ===========================================================================
# Trial-tier attorney fee at disbursement
# ===========================================================================
class TestTrialTierAttorneyFee:

    def test_trial_tier_used_when_case_is_trial_awarded(self, api):
        """PRD §3.9: "If Case.status is TRIAL_AWARDED, the trial rate
        trial_rate_bps applies."

        Claim: After TRIAL_AWARDED, attorney_fee_cents uses
        trial_rate_bps.
        """
        result = setup_trial_awarded(
            award_amount_cents=10_000_000, case_costs_cents=0,
            pre_suit_rate_bps=3333,
            post_suit_rate_bps=4000,
            trial_rate_bps=4500,
        )
        disbursement = approve_disbursement(
            result["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        # gross * 4500 / 10000 = 4_500_000.
        assert disbursement["attorney_fee_cents"] == 4_500_000
        assert_disbursement_conservation(disbursement)


# ===========================================================================
# Post-suit tier when SETTLED via LITIGATION
# ===========================================================================
class TestPostSuitTierAttorneyFee:

    def test_post_suit_tier_used_when_case_filed_in_court(self, api):
        """PRD §3.9: "Otherwise, if Case.filed_in_court is true, the
        post-suit rate post_suit_rate_bps applies — this is the path
        taken when the case settles after a complaint has been filed."

        Claim: SETTLED via LITIGATION → attorney_fee uses
        post_suit_rate_bps.
        """
        result = setup_settled_via_litigation(
            gross_settlement_cents=10_000_000,
            case_costs_cents=0,
            pre_suit_rate_bps=3333,
            post_suit_rate_bps=4000,
            trial_rate_bps=4500,
        )
        disbursement = approve_disbursement(
            result["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        # gross * 4000 / 10000 = 4_000_000.
        assert disbursement["attorney_fee_cents"] == 4_000_000
        assert_disbursement_conservation(disbursement)


# ===========================================================================
# Settlement Disbursement entity shape
# ===========================================================================
class TestDisbursementEntityShape:

    def test_disbursement_response_omits_updated_at_and_version(
        self, api,
    ):
        """PRD §2.4: "SettlementDisbursement is created once and
        never revised, so both carry only id and created_at — they
        expose neither updated_at nor version."

        Claim: Disbursement response has no updated_at and no version.
        """
        result = setup_settled_with_liens(case_costs_cents=0)
        disbursement = approve_disbursement(
            result["case"]["id"], "CHRONOLOGICAL_PRIORITY",
        )
        assert "updated_at" not in disbursement, (
            "PRD §2.4: SettlementDisbursement must NOT carry updated_at"
        )
        assert "version" not in disbursement, (
            "PRD §2.4: SettlementDisbursement must NOT carry version"
        )


# ===========================================================================
# Closed case state after approval
# ===========================================================================
class TestPostApprovalCaseState:

    def test_case_status_flips_to_closed_after_approval(self, api):
        """PRD §3.10: "The system also writes disbursement_approved_by
        onto the case, copies it from the approver, and finally flips
        Case.status to CLOSED."

        Claim: After approve, Case.status==CLOSED and
        disbursement_approved_by is the calling X-User-ID.
        """
        result = setup_settled_with_liens(case_costs_cents=0)
        approve_disbursement(result["case"]["id"], "CHRONOLOGICAL_PRIORITY")
        refreshed = get_case(result["case"]["id"])
        assert refreshed["status"] == "CLOSED"
        assert refreshed["disbursement_approved_by"] == MANAGING_PARTNER_ID
