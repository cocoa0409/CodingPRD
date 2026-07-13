"""Difficulty: dual_variant_calc — the two availability views and the two risk scores.

Both variants are computed from identical stored data yet report different
numbers, so each instance is verified from both sides.
"""
from test_helpers import (
    validate_success,
    setup_dual_variant_scenario,
    setup_organizer_risk_scenario,
    get_campaign,
)


class TestCampaignProvisionalVsSettled:
    """Two CAPTURED donations of net 10000 each (raised 20000, reserve_total 1000),
    one OPEN dispute locking donation D1. provisional=19000, settled=9000."""

    def test_provisional_ignores_open_dispute(self, api):
        """PRD §2.6: "Provisional (optimistic) availability, provisional_available_cents,
        equals raised_cents minus reserve_total_cents minus committed_cents. It ignores
        open disputes and active holds."

        Design: Difficulty/dual_variant_calc/campaign_available_provisional_vs_settled
        """
        b = setup_dual_variant_scenario(api)
        camp = get_campaign(api, b["camp_id"])
        assert camp["provisional_available_cents"] == 19000, (
            f"raised 20000 - reserve 1000 - committed 0 = 19000, "
            f"got {camp['provisional_available_cents']}"
        )

    def test_settled_subtracts_disputed_locked(self, api):
        """PRD §2.6: "Settled (pessimistic) availability, settled_available_cents, equals
        provisional_available_cents minus disputed_locked_cents minus hold_locked_cents."

        Design: Difficulty/dual_variant_calc/campaign_available_provisional_vs_settled
        """
        b = setup_dual_variant_scenario(api)
        camp = get_campaign(api, b["camp_id"])
        assert camp["settled_available_cents"] == 9000, (
            f"provisional 19000 - disputed_locked 10000 - hold_locked 0 = 9000, "
            f"got {camp['settled_available_cents']}"
        )


class TestOrganizerStrictVsLenientRisk:
    """raised 100000, one UPHELD dispute (refunded 5000) and one REJECTED dispute,
    beneficiary VERIFIED. strict counts total=2 -> 33; lenient counts upheld=1 -> 18."""

    def test_strict_counts_every_dispute(self, api, guest_headers):
        """PRD §2.9: "The strict score, strict_risk_score, uses total_dispute_count — it
        counts every dispute, including those still OPEN and those already REJECTED."

        Design: Difficulty/dual_variant_calc/organizer_risk_strict_vs_lenient
        """
        org_id = setup_organizer_risk_scenario(api)
        data = validate_success(api.get_organizer(org_id, guest_headers))
        assert data["strict_risk_score"] == 33, (
            f"15*2 + round_half_up(50*0.05)=30+3=33, got {data['strict_risk_score']}"
        )

    def test_lenient_counts_only_upheld(self, api, guest_headers):
        """PRD §2.9: "The lenient score, lenient_risk_score, uses upheld_dispute_count —
        it counts only disputes resolved as UPHELD."

        Design: Difficulty/dual_variant_calc/organizer_risk_strict_vs_lenient
        """
        org_id = setup_organizer_risk_scenario(api)
        data = validate_success(api.get_organizer(org_id, guest_headers))
        assert data["lenient_risk_score"] == 18, (
            f"15*1 + round_half_up(50*0.05)=15+3=18, got {data['lenient_risk_score']}"
        )
