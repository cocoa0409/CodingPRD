"""Computed fields: decision_deadline_at, evidence_completeness_score,
evidence_reuse_discount, approval_expiration (expires_at).

PRD §3.6 (decision deadline), §3.7 (evidence completeness & reuse
discount), §3.10 (approval expiration), §3.11 (appeal decision
deadline).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_APPROVAL_VALIDITY_DAYS,
    DEFAULT_EXPEDITED_SLA_HOURS,
    DEFAULT_STANDARD_SLA_HOURS,
    EXPEDITED_APPEAL_TIER_1_HOURS,
    EXPEDITED_PENDING_INFO_EXTENSION_HOURS,
    HOURS_PER_DAY,
    STANDARD_APPEAL_TIER_1_HOURS,
    STANDARD_PENDING_INFO_EXTENSION_HOURS,
    TEST_DEFAULTS,
    cycle_pending_info,
    decide_authorization,
    file_appeal,
    parse_iso,
    re_get_authorization,
    setup_approved_authorization,
    setup_authorization_for_two_pending_info_cycles,
    setup_denied_authorization,
    setup_submitted_authorization,
    setup_submitted_with_empty_required_categories,
    setup_under_review_authorization,
)


# ===========================================================================
# decision_deadline (PRD §3.6)
# ===========================================================================
class TestDecisionDeadline:
    """PRD §3.6: deadline = submitted_at + base SLA + pending-info
    extensions."""

    def test_standard_deadline_uses_standard_sla_hours(self, api):
        """PRD §3.6: "The base window depends on urgency: a STANDARD
        request uses the version-pinned standard_sla_hours (default 14
        days)".

        Claim: a STANDARD authorization with standard_sla_hours=336
        produces decision_deadline_at == submitted_at + 336 hours.
        """
        _, _, _, auth, _ = setup_submitted_authorization(
            urgency="STANDARD",
            standard_sla_hours=DEFAULT_STANDARD_SLA_HOURS,
        )
        submitted_at = parse_iso(auth["submitted_at"])
        deadline = parse_iso(auth["decision_deadline_at"])
        delta_h = (deadline - submitted_at).total_seconds() / 3600
        assert delta_h == DEFAULT_STANDARD_SLA_HOURS

    def test_expedited_deadline_uses_expedited_sla_hours(self, api):
        """PRD §3.6: "an EXPEDITED request uses the version-pinned
        expedited_sla_hours (default 3 days)".

        Claim: an EXPEDITED authorization with expedited_sla_hours=72
        produces decision_deadline_at == submitted_at + 72 hours.

        difficulty: dual_variant_calc/standard_vs_expedited_decision_deadline
        """
        _, _, _, auth, _ = setup_submitted_authorization(
            urgency="EXPEDITED",
            expedited_sla_hours=DEFAULT_EXPEDITED_SLA_HOURS,
        )
        submitted_at = parse_iso(auth["submitted_at"])
        deadline = parse_iso(auth["decision_deadline_at"])
        delta_h = (deadline - submitted_at).total_seconds() / 3600
        assert delta_h == DEFAULT_EXPEDITED_SLA_HOURS

    def test_one_pending_info_cycle_adds_168_hours_for_standard(self, api):
        """PRD §3.6: "The extension per cycle is 168 hours (one week)
        for a STANDARD request and 24 hours (one day) for an EXPEDITED
        request."

        Claim: after one completed UNDER_REVIEW → PENDING_INFO →
        UNDER_REVIEW cycle on a STANDARD authorization, the deadline
        is submitted_at + 336 + 168 = 504 hours.
        """
        provider, _, auth = (
            setup_authorization_for_two_pending_info_cycles()
        )
        # Cycle 1: request-info -> resume-review (no need to attach
        # more evidence since the fixture already attached all 4 cats
        # → score == 1.00).
        auth = cycle_pending_info(provider=provider, authorization=auth)
        submitted_at = parse_iso(auth["submitted_at"])
        deadline = parse_iso(auth["decision_deadline_at"])
        delta_h = (deadline - submitted_at).total_seconds() / 3600
        assert delta_h == (
            DEFAULT_STANDARD_SLA_HOURS
            + STANDARD_PENDING_INFO_EXTENSION_HOURS
        )


# ===========================================================================
# evidence_completeness (PRD §3.7)
# ===========================================================================
class TestEvidenceCompleteness:
    """PRD §3.7: evidence_completeness_score formula and clamp."""

    def test_empty_required_categories_yields_score_one(self, api):
        """PRD §3.7: "if the catalog item requires no categories, the
        base coverage is 1.00".

        Claim: a catalog item with required_evidence_categories=[]
        produces evidence_completeness_score == 1.00 on the submitted
        authorization, even with zero attached evidence rows.

        Difficulty: boundary_precision_check/empty_required_evidence_categories_yields_score_one
        """
        # difficulty: boundary_precision_check/empty_required_evidence_categories_yields_score_one
        _, _, _, auth = setup_submitted_with_empty_required_categories()
        assert auth["evidence_completeness_score"] == 1.00

    def test_two_of_four_required_yields_score_050(self, api):
        """PRD §3.7: "otherwise, the base coverage is the number of
        required categories for which at least one ATTACHED
        ClinicalEvidence row exists under this authorization, divided
        by the total number of required categories."

        Claim: 2 of 4 required categories yields a base coverage of
        2/4 = 0.50.
        """
        cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
        _, _, _, auth, _ = setup_submitted_authorization(
            required_evidence_categories=cats,
            evidence_categories_to_attach=cats[:2],
        )
        assert auth["evidence_completeness_score"] == 0.50


# ===========================================================================
# evidence_reuse_discount (PRD §3.7)
# ===========================================================================
class TestEvidenceReuseDiscount:
    """PRD §3.7: reuse-discount formula and cap."""

    def test_three_reused_docs_yields_discount_015(self, api):
        """PRD §3.7: "computes the discount as 0.05 multiplied by the
        count of reused documents, but never larger than 0.20 — that
        is, the discount is the smaller of 0.05 times the reused count
        and 0.20."

        Claim: 3 reused documents → discount = 0.15. With 4 of 4
        required categories attached + post-P2P bonus 0.10:
        base 1.00 + 0.10 − 0.15 = 0.95 (no clamp).

        Difficulty: combinatorial_formula/evidence_completeness_three_inputs_with_conditional
        """
        # difficulty: combinatorial_formula/evidence_completeness_three_inputs_with_conditional
        from test_helpers import (
            attach_evidence,
            complete_peer_to_peer,
            iso_offset,
            parse_iso,
            re_get_authorization,
            schedule_peer_to_peer,
            setup_resubmission_with_n_reused_evidence,
            start_review,
        )
        cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
        _, provider, _, _, resub, _ = (
            setup_resubmission_with_n_reused_evidence(
                num_reused=3, required_categories=cats,
            )
        )
        # Submit, start review, do peer-to-peer, complete OVERTURNED.
        from test_helpers import submit_authorization
        submit_authorization(provider=provider, authorization=resub)
        resub = re_get_authorization(resub["id"])
        start_review(authorization=resub)
        resub = re_get_authorization(resub["id"])
        # PRD §3.5: scheduled_at must be strictly AFTER the SERVER clock.
        # The fixture advanced the server clock past prior.expires_at, so
        # the client's wallclock can be earlier than the server clock.
        # Anchor scheduled_at on resub.updated_at (≈ server clock now).
        scheduled_at = iso_offset(
            hours=2, base=parse_iso(resub["updated_at"]),
        )
        p2p = schedule_peer_to_peer(
            provider=provider, authorization=resub,
            scheduled_at=scheduled_at,
        )
        complete_peer_to_peer(p2p=p2p, outcome="OVERTURNED")
        resub = re_get_authorization(resub["id"])
        assert resub["evidence_reuse_discount"] == 0.15
        # PRD §3.7: post-P2P bonus is 0.10 on OVERTURNED. Base coverage
        # 1.00, − discount 0.15, + bonus 0.10 = 0.95 (no clamp).
        assert resub["evidence_completeness_score"] == 0.95

    def test_reuse_discount_capped_at_020(self, api):
        """PRD §3.7: "but never larger than 0.20".

        Claim: 6 reused documents → discount capped at 0.20, not 0.30.
        With 6 reused covering all 4 required cats (base coverage
        1.00) and no P2P bonus: 1.00 − 0.20 = 0.80.

        Difficulty: combinatorial_formula/evidence_reuse_discount_cap_then_completeness_clamp_order
        """
        # difficulty: combinatorial_formula/evidence_reuse_discount_cap_then_completeness_clamp_order
        cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
        from test_helpers import setup_resubmission_with_n_reused_evidence
        _, provider, _, _, resub, _ = (
            setup_resubmission_with_n_reused_evidence(
                num_reused=6, required_categories=cats,
            )
        )
        # Submit (PRD §3.7 trigger: recompute on submission).
        from test_helpers import (
            re_get_authorization,
            submit_authorization,
        )
        submit_authorization(provider=provider, authorization=resub)
        resub = re_get_authorization(resub["id"])
        assert resub["evidence_reuse_discount"] == 0.20
        # Score = base 1.00 - 0.20 reuse discount = 0.80 (no p2p bonus,
        # no clamp triggered).
        assert resub["evidence_completeness_score"] == 0.80


# ===========================================================================
# approval_expiration (PRD §3.10)
# ===========================================================================
class TestApprovalExpiration:
    """PRD §3.10: expires_at = decided_at + approval_validity_days *
    24h."""

    def test_expires_at_uses_pinned_validity_days(self, api):
        """PRD §3.10: "From the moment decided_at is recorded on an
        APPROVED authorization, the system schedules an expires_at
        exactly approval_validity_days days later, using the value
        version-pinned at submission."

        Claim: an authorization approved with default 90-day validity
        has expires_at == decided_at + 90 days.

        difficulty: dual_variant_calc/initial_vs_appeal_overturn_approval_expiration
        """
        _, _, _, auth = setup_approved_authorization(
            approval_validity_days=DEFAULT_APPROVAL_VALIDITY_DAYS,
        )
        decided_at = parse_iso(auth["decided_at"])
        expires_at = parse_iso(auth["expires_at"])
        delta_h = (expires_at - decided_at).total_seconds() / 3600
        assert delta_h == (
            DEFAULT_APPROVAL_VALIDITY_DAYS * HOURS_PER_DAY
        )


# ===========================================================================
# Appeal decision deadline (PRD §3.11)
# ===========================================================================
class TestAppealDeadline:
    """PRD §3.11: per-tier SLAs."""

    def test_standard_tier_one_appeal_uses_240_hours(self, api):
        """PRD §3.11: "For STANDARD authorizations, tier 1 has a
        240-hour window (10 days)".

        Claim: tier-1 appeal on a STANDARD authorization has
        decision_deadline_at == filed_at + 240 hours.
        """
        _, provider, _, auth = setup_denied_authorization(
            urgency="STANDARD",
        )
        appeal = file_appeal(provider=provider, authorization=auth)
        filed = parse_iso(appeal["filed_at"])
        deadline = parse_iso(appeal["decision_deadline_at"])
        delta_h = (deadline - filed).total_seconds() / 3600
        assert delta_h == STANDARD_APPEAL_TIER_1_HOURS

    def test_expedited_tier_one_appeal_uses_72_hours(self, api):
        """PRD §3.11: "For EXPEDITED authorizations, the per-tier
        windows shrink considerably: tier 1 has 72 hours (3 days)".

        Claim: tier-1 appeal on an EXPEDITED authorization has
        decision_deadline_at == filed_at + 72 hours.
        """
        _, provider, _, auth = setup_denied_authorization(
            urgency="EXPEDITED",
        )
        appeal = file_appeal(provider=provider, authorization=auth)
        filed = parse_iso(appeal["filed_at"])
        deadline = parse_iso(appeal["decision_deadline_at"])
        delta_h = (deadline - filed).total_seconds() / 3600
        assert delta_h == EXPEDITED_APPEAL_TIER_1_HOURS
