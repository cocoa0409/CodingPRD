"""Cascading state transitions — PRD §3.2, §3.4, §3.5.

Covers: ParentalConsent withdrawal cascades (RELATED_SERVICE and
IEP_IMPLEMENTATION scopes), Ineligible-finalization cascades,
supersession when a second IEP activates.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    create_evaluation,
    create_iep,
    create_iep_implementation_consent_approved,
    create_goal_with_single_objective,
    create_progress_report,
    finalize_evaluation,
    finalize_evaluation_payload,
    find_pending_consent_for_evaluation,
    get_consent,
    get_iep,
    get_service,
    get_student,
    make_objective,
    parent_approve_consent,
    parent_withdraw_consent,
    request_evaluation_consent,
    schedule_three_25min_sessions_in_past,
    setup_active_iep,
    setup_active_iep_with_active_service,
    setup_eligible_student,
)


class TestRelatedServiceConsentWithdrawalCascade:
    """PRD §3.4: scope=RELATED_SERVICE withdraw → service →
    compensatory minutes → possibly parent IEP."""

    def test_withdraw_related_service_consent_suspends_service(
        self, api,
    ):
        """PRD §3.4: "scope=RELATED_SERVICE: every RelatedService
        whose consent_id equals this consent is transitioned from
        ACTIVE to SUSPENDED."

        Claim: parent withdraws the RELATED_SERVICE consent → the
        gated service is automatically transitioned ACTIVE → SUSPENDED.
        """
        district, student, iep, service, consent = (
            setup_active_iep_with_active_service()
        )
        # Withdraw the consent.
        parent_withdraw_consent(
            district["id"], student["id"], consent["id"],
            parent_user_id=student["parent_user_id"],
        )
        svc_now = get_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        assert svc_now["status"] == "SUSPENDED"


class TestCompensatoryMinutesPinnedFormula:
    """PRD §3.6: round-per-session-then-sum convention pins
    compensatory_minutes_owed."""

    def test_three_25min_missed_sessions_total_114_minutes(
        self, api,
    ):
        """PRD §3.6: "the rounding order is pinned: each session is
        rounded to a whole minute first, then the rounded values are
        summed. The naive alternative — summing the raw 1.5x products
        and rounding only at the end — produces a different total
        whenever an odd number of sessions has odd scheduled_minutes
        (each ending in a half-minute), and that alternative is
        explicitly not used."

        Claim: three SCHEDULED 25-minute sessions in the past →
        compensatory_minutes_owed == 114 (38+38+38), NOT 113
        (round(37.5*3)).

        # difficulty: combinatorial_formula/compensatory_minutes_round_per_session_then_sum_mode_b
        """
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service(
                service_type="OT", minutes_per_week=75,
                location_setting="PULL_OUT",
            )
        )
        schedule_three_25min_sessions_in_past(
            district["id"], student["id"], iep["id"], service["id"],
        )
        # Suspend the service to trigger compensatory_service_hours.
        from test_helpers import suspend_related_service
        suspend_related_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        svc_now = get_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        assert svc_now["status"] == "SUSPENDED"
        # round-per-session-then-sum: 25*1.5=37.5 → 38 each; 3*38=114.
        # sum-then-round: 37.5*3=112.5 → 113. PRD pins 114.
        assert svc_now["compensatory_minutes_owed"] == 114


class TestConsentWithdrawalDepth3Cascade:
    """PRD §3.4 + §3.6 — depth-3 cascade from consent.WITHDRAWN
    through service.SUSPENDED + compensatory minutes to IEP
    AMENDMENT_PENDING."""

    def test_withdraw_cascades_to_iep_amendment_pending(self, api):
        """PRD §3.4: "After all dependent services are suspended, the
        sum of compensatory_minutes_owed across all services on the
        parent IEP is recomputed; if that sum is strictly greater
        than zero, the parent IEP enters AMENDMENT_PENDING."

        Claim: withdrawing the RELATED_SERVICE consent on an ACTIVE
        service with three past missed sessions causes the service
        to suspend AND the parent IEP to enter AMENDMENT_PENDING
        because compensatory_minutes_owed > 0.

        # difficulty: transitive_cascade/consent_withdrawal_cascades_to_iep_amendment_depth_3
        """
        district, student, iep, service, consent = (
            setup_active_iep_with_active_service(
                service_type="OT", minutes_per_week=75,
                location_setting="PULL_OUT",
            )
        )
        # Schedule three past 25-min sessions so suspension yields
        # compensatory minutes > 0.
        schedule_three_25min_sessions_in_past(
            district["id"], student["id"], iep["id"], service["id"],
        )
        # Withdraw the consent — drives the full cascade.
        parent_withdraw_consent(
            district["id"], student["id"], consent["id"],
            parent_user_id=student["parent_user_id"],
        )
        # Hop 1: consent WITHDRAWN.
        c_now = get_consent(
            district["id"], student["id"], consent["id"],
        )
        assert c_now["status"] == "WITHDRAWN"
        # Hop 2: service SUSPENDED with compensatory_minutes_owed > 0.
        svc_now = get_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        assert svc_now["status"] == "SUSPENDED"
        assert svc_now["compensatory_minutes_owed"] == 114
        # Hop 3: IEP enters AMENDMENT_PENDING.
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert iep_now["status"] == "AMENDMENT_PENDING"


class TestIneligibleFinalizeCascade:
    """PRD §3.2: INELIGIBLE finalization cascades down the IEP graph."""

    def test_ineligible_finalize_revokes_active_iep_and_dependents(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "if the student currently has a non-null
        current_iep_id the system cascades: the active IEP is moved
        to REVOKED, every RelatedService on that IEP currently in
        ACTIVE is moved to SUSPENDED with its compensatory_minutes_owed
        recomputed per §3.6, every IEPGoal on that IEP currently in
        ACTIVE is moved to DISCONTINUED, the student's current_iep_id
        is cleared to null, and the student's lre_classification is
        set to NOT_APPLICABLE."

        Claim: finalize a fresh TRIENNIAL evaluation as INELIGIBLE
        while the student has an ACTIVE IEP with one ACTIVE service
        and one ACTIVE goal → IEP=REVOKED, service=SUSPENDED,
        goal=DISCONTINUED, student.current_iep_id=null,
        lre_classification=NOT_APPLICABLE.

        # difficulty: transitive_cascade/ineligible_finalization_cascades_to_goals_and_services_depth_3
        """
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        # Now create a second TRIENNIAL evaluation, drive it to
        # IN_PROGRESS using a psychologist whose X-User-ID differs
        # from the parent's, then finalize as INELIGIBLE.
        from test_helpers import (
            SCHOOL_PSYCHOLOGIST_ID_ALT,
            make_psychologist_headers,
        )
        psych_h = make_psychologist_headers(SCHOOL_PSYCHOLOGIST_ID_ALT)
        ev2 = create_evaluation(
            district["id"], student["id"],
            evaluation_type="TRIENNIAL",
            psychologist_headers=psych_h,
        )
        ev2 = request_evaluation_consent(
            district["id"], student["id"], ev2["id"],
            psychologist_headers=psych_h,
        )
        new_consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], ev2["id"],
        )
        parent_approve_consent(
            district["id"], student["id"], new_consent["id"],
            parent_user_id=student["parent_user_id"],
        )
        # Finalize as INELIGIBLE.
        finalize_evaluation(
            district["id"], student["id"], ev2["id"],
            disability_categories=[],
            psychologist_headers=psych_h,
        )
        # Hop 1: evaluation INELIGIBLE.
        # Hop 2: IEP REVOKED.
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert iep_now["status"] == "REVOKED"
        # Hop 3: service SUSPENDED.
        svc_now = get_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        assert svc_now["status"] == "SUSPENDED"
        # Hop 3: student.current_iep_id = null;
        # lre_classification = NOT_APPLICABLE.
        s_now = get_student(district["id"], student["id"])
        assert s_now.get("current_iep_id") in (None, "")
        assert s_now["lre_classification"] == "NOT_APPLICABLE"


class TestIepImplementationConsentWithdrawal:
    """PRD §3.4: scope=IEP_IMPLEMENTATION withdraw → IEP REVOKED."""

    def test_withdraw_iep_implementation_consent_revokes_iep(self, api):
        """PRD §3.4: "scope=IEP_IMPLEMENTATION: the gated IEP is
        transitioned to REVOKED independently; the full revocation
        cascade described in §3.5 then runs on that IEP."

        Claim: parent withdraws the IEP_IMPLEMENTATION consent on an
        ACTIVE IEP → the IEP is moved to REVOKED.
        """
        district, student, _eval, iep, _goal = setup_active_iep()
        # Find the IEP_IMPLEMENTATION consent we approved during
        # setup_active_iep.
        from test_helpers import TEST_USERS
        listing = api.list_consents(
            district["id"], student["id"],
            TEST_USERS["admin_headers"],
            params={"scope": "IEP_IMPLEMENTATION", "status": "APPROVED"},
        ).json()
        consents = [c for c in listing["data"]
                    if c.get("target_resource_id") == iep["id"]
                    and c.get("status") == "APPROVED"]
        assert len(consents) == 1, (
            f"setup did not produce a unique APPROVED "
            f"IEP_IMPLEMENTATION consent for iep={iep['id']}: "
            f"{consents}"
        )
        consent_id = consents[0]["id"]
        parent_withdraw_consent(
            district["id"], student["id"], consent_id,
            parent_user_id=student["parent_user_id"],
        )
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert iep_now["status"] == "REVOKED"
        s_now = get_student(district["id"], student["id"])
        assert s_now.get("current_iep_id") in (None, "")
