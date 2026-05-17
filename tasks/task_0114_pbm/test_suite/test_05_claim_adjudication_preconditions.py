"""Adjudication preconditions: §2.8 rungs 4-7, 11-12.

Tested in isolation so each precondition fires by itself (PRD §2.8:
"A request that violates multiple rungs of this ladder always
surfaces the lowest-numbered violation; deeper checks are not even
evaluated." — for clean attribution we set up scenarios that violate
exactly ONE precondition).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    adjudicate_claim,
    advance_clock,
    approve_pa,
    create_copay_card,
    create_drug,
    create_formulary_entry,
    create_member,
    create_plan,
    deny_pa,
    occ_payload,
    re_get_claim,
    revoke_pa,
    setup_adjudicated_claim,
    setup_approved_pa,
    setup_denied_pa,
    setup_paid_claim,
    setup_reference_data,
    setup_revoked_pa,
    setup_submitted_pa,
    submit_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rung 4: ERR_INVALID_STATE
# ===========================================================================
class TestStateLegality:

    def test_adjudicate_twice_rejected(self, api, claims_adjudicator_headers):
        """PRD §2.8 rung 4: "The target resource must be in a state
        legal for the requested transition (… claim in SUBMITTED for
        adjudicate …). Violations yield ERR_INVALID_STATE (409)."

        Claim: re-adjudicating an ADJUDICATED claim yields
        ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        claim_adj = setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        res = api.adjudicate_claim(
            claim_adj["id"],
            occ_payload(version=claim_adj["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_pay_from_submitted_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §2.8 rung 4: "claim in ADJUDICATED for pay".

        Claim: paying a SUBMITTED claim yields ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        res = api.pay_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_reverse_from_submitted_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §2.8 rung 4: "claim in PAID for reverse".

        Claim: reversing a SUBMITTED claim yields ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        res = api.reverse_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Rung 5: ERR_MEMBER_NOT_ACTIVE
# ===========================================================================
class TestMemberNotActive:

    def test_adjudicate_with_suspended_member_rejected(
        self, api, admin_headers, claims_adjudicator_headers,
    ):
        """PRD §2.8 rung 5: "for claim adjudicate and prior-
        authorization approve, the referenced Member must satisfy
        enrollment_status equal to ACTIVE; otherwise the request
        yields ERR_MEMBER_NOT_ACTIVE (409)."
        PRD §3.5: "The referenced member must be ACTIVE on penalty of
        ERR_MEMBER_NOT_ACTIVE."

        Claim: adjudicate when member is SUSPENDED ->
        ERR_MEMBER_NOT_ACTIVE.
        """
        _, drug, _, member = setup_reference_data()
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        api.suspend_member(
            member["id"], {"version": member["version"]},
            admin_headers,
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_MEMBER_NOT_ACTIVE")


# ===========================================================================
# Rung 6: ERR_SPECIALTY_CHANNEL_REQUIRED
# ===========================================================================
class TestSpecialtyChannel:

    def test_specialty_drug_with_wrong_channel_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "If the drug's is_specialty is true, the claim's
        channel must be SPECIALTY on penalty of
        ERR_SPECIALTY_CHANNEL_REQUIRED."
        PRD §2.8 rung 6: "Specialty channel match — for claim
        adjudicate, when the drug's is_specialty is true the claim's
        channel must be SPECIALTY; otherwise
        ERR_SPECIALTY_CHANNEL_REQUIRED (422)."

        Claim: adjudicate with is_specialty=true drug on RETAIL_30 ->
        ERR_SPECIALTY_CHANNEL_REQUIRED.
        """
        plan = create_plan()
        drug = create_drug(is_specialty=True)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_SPECIALTY_CHANNEL_REQUIRED")


# ===========================================================================
# Rung 7: ERR_PA_REQUIRED / ERR_PA_DENIED / ERR_PA_REVOKED /
# ERR_PA_EXPIRED / ERR_PA_MISMATCH
# ===========================================================================
class TestPriorAuthorizationGating:

    def test_drug_requires_pa_and_no_pa_referenced_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "If the drug's requires_prior_auth is true, the
        claim must reference a prior authorization that is currently
        APPROVED".
        PRD §2.8 rung 7: "Prior authorization requirement — for claim
        adjudicate, when the drug's requires_prior_auth is true, the
        claim must reference an APPROVED prior authorization whose
        effective window contains the current clock time; otherwise
        ERR_PA_REQUIRED (422)."

        Claim: adjudicate with requires_prior_auth=true and no
        prior_auth_id -> ERR_PA_REQUIRED.
        """
        plan = create_plan()
        drug = create_drug(requires_prior_auth=True)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
            prior_auth_id=None,
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_PA_REQUIRED")

    def test_pa_denied_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "A referenced prior authorization in DENIED
        yields ERR_PA_DENIED".
        PRD §5: ERR_PA_DENIED, 422.

        Claim: adjudicate referencing a DENIED PA -> ERR_PA_DENIED.
        """
        plan = create_plan()
        drug = create_drug(requires_prior_auth=True)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        pa = setup_denied_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
            prior_auth_id=pa["id"],
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_PA_DENIED")

    def test_pa_revoked_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "one in REVOKED yields ERR_PA_REVOKED".

        Claim: adjudicate referencing a REVOKED PA -> ERR_PA_REVOKED.
        """
        plan = create_plan()
        drug = create_drug(requires_prior_auth=True)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        pa = setup_revoked_pa(
            member_id=member["id"], drug_id=drug["id"],
        )
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
            prior_auth_id=pa["id"],
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_PA_REVOKED")

    def test_pa_mismatch_member_id_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "a prior authorization whose member_id or
        drug_id does not match the claim yields ERR_PA_MISMATCH."

        Claim: adjudicate with PA for a DIFFERENT member ->
        ERR_PA_MISMATCH.
        """
        plan = create_plan()
        drug = create_drug(requires_prior_auth=True)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member_a = create_member(plan_id=plan["id"])
        member_b = create_member(plan_id=plan["id"])
        # PA is for member_a.
        pa = setup_approved_pa(
            member_id=member_a["id"], drug_id=drug["id"],
        )
        # Claim is for member_b but references member_a's PA.
        claim = submit_claim(
            member_id=member_b["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
            prior_auth_id=pa["id"],
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_PA_MISMATCH")


# ===========================================================================
# Rung 11: ERR_DRUG_NOT_ON_FORMULARY
# ===========================================================================
class TestFormularyCoverage:

    def test_drug_not_on_formulary_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "The drug must have an ACTIVE FormularyEntry
        matching the member's plan and the claim's drug, on penalty
        of ERR_DRUG_NOT_ON_FORMULARY."
        PRD §2.8 rung 11: "Formulary coverage — for claim adjudicate,
        an ACTIVE FormularyEntry must exist for the pair of the
        member's plan and the claim's drug; otherwise
        ERR_DRUG_NOT_ON_FORMULARY (422)."

        Claim: drug exists but is NOT on the member's plan's
        formulary -> ERR_DRUG_NOT_ON_FORMULARY.
        """
        plan = create_plan()
        # Drug is created but no FormularyEntry for (plan, drug).
        drug = create_drug()
        member = create_member(plan_id=plan["id"])
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_DRUG_NOT_ON_FORMULARY")


# ===========================================================================
# Rung 12: ERR_COPAY_CARD_MISMATCH
# ===========================================================================
class TestCopayCardMismatch:

    def test_copay_card_with_wrong_drug_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "If copay_card_id is supplied, the card's
        member_id and drug_id must match the claim and the card's
        status must be ACTIVE, on penalty of ERR_COPAY_CARD_MISMATCH."
        PRD §2.8 rung 12: "Copay-card matching — for claim adjudicate,
        when copay_card_id is supplied the card's member_id and
        drug_id must match the claim and the card's status must be
        ACTIVE; otherwise ERR_COPAY_CARD_MISMATCH (422)."

        Claim: card bound to a DIFFERENT drug -> ERR_COPAY_CARD_MISMATCH.
        """
        plan = create_plan()
        drug = create_drug()
        other_drug = create_drug()
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        create_formulary_entry(plan_id=plan["id"],
                               drug_id=other_drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        card = create_copay_card(
            member_id=member["id"], drug_id=other_drug["id"],
            max_benefit_cents=1_000, per_claim_cap_cents=1_000,
        )
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
            copay_card_id=card["id"],
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_COPAY_CARD_MISMATCH")

    def test_copay_card_with_wrong_member_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "the card's member_id and drug_id must match the
        claim".

        Claim: card bound to a DIFFERENT member -> ERR_COPAY_CARD_MISMATCH.
        """
        plan = create_plan()
        drug = create_drug()
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member_a = create_member(plan_id=plan["id"])
        member_b = create_member(plan_id=plan["id"])
        card = create_copay_card(
            member_id=member_a["id"], drug_id=drug["id"],
            max_benefit_cents=1_000, per_claim_cap_cents=1_000,
        )
        # Claim is for member_b but uses member_a's card.
        claim = submit_claim(
            member_id=member_b["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
            copay_card_id=card["id"],
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_COPAY_CARD_MISMATCH")


# ===========================================================================
# Rejection side effects: REJECTED status, no YTD change.
# ===========================================================================
class TestRejectionSideEffects:
    """PRD §3.5: "Each precondition failure at adjudicate marks the
    claim as REJECTED, writes the specific failure into reject_reason,
    and leaves all year-to-date counters and copay-card counters
    untouched.\""""

    def test_rejected_claim_does_not_change_member_ytd(
        self, api, admin_headers, claims_adjudicator_headers,
    ):
        """PRD §3.5: "leaves all year-to-date counters and copay-card
        counters untouched."

        Claim: a rejected adjudicate leaves Member YTD unchanged.
        """
        plan = create_plan()
        drug = create_drug(is_specialty=True)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        before = api.get_member(member["id"], admin_headers).json()["data"]
        # Submit with wrong channel for is_specialty -> will be
        # rejected at adjudicate with ERR_SPECIALTY_CHANNEL_REQUIRED.
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_SPECIALTY_CHANNEL_REQUIRED")
        after = api.get_member(member["id"], admin_headers).json()["data"]
        assert (after["ytd_deductible_paid_cents"]
                == before["ytd_deductible_paid_cents"])
        assert after["ytd_oop_paid_cents"] == before["ytd_oop_paid_cents"]
