"""Resolution outcome → Application state mapping and side effects.

PRD §3.5, §2.11.
"""
from __future__ import annotations

from test_helpers import (
    SEC,
    find_audit_entries,
    get_application,
    list_audit_logs,
    setup_resolved_initial_review,
)


# ===========================================================================
# APPROVE cascade (PRD §3.5)
# ===========================================================================
class TestApproveCascade:
    """PRD §3.5: 'An APPROVE outcome moves the application to APPROVED,
    locks approved_submission_version to the agenda item's
    pinned_submission_version, sets approval_resolution_id to the
    resolution's id, and emits both a REGULATORY_SYNC and an
    IM_NOTIFICATION audit row.'"""

    def test_approve_outcome_application_becomes_approved(self, api):
        """PRD §3.5: 'An APPROVE outcome moves the application to
        APPROVED'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        assert bundle["resolution"]["outcome"] == "APPROVE"
        assert bundle["application"]["status"] == "APPROVED", (
            f"PRD §3.5: 'moves the application to APPROVED'; got "
            f"{bundle['application']['status']!r}"
        )

    def test_approve_locks_approved_submission_version(self, api):
        """PRD §3.5: 'locks approved_submission_version to the agenda
        item's pinned_submission_version, sets approval_resolution_id
        to the resolution's id'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        agenda = bundle["agenda_item"]
        resolution = bundle["resolution"]
        assert app["approved_submission_version"] == \
            agenda["pinned_submission_version"], (
            f"PRD §3.5: 'locks approved_submission_version to the "
            f"agenda item's pinned_submission_version'; got app="
            f"{app.get('approved_submission_version')!r}, agenda="
            f"{agenda.get('pinned_submission_version')!r}"
        )
        assert app["approval_resolution_id"] == resolution["id"], (
            f"PRD §3.5: 'sets approval_resolution_id to the resolution's "
            f"id'; got {app.get('approval_resolution_id')!r} vs "
            f"{resolution['id']!r}"
        )

    def test_approve_emits_regulatory_sync_audit(self, api):
        """PRD §2.11: 'this event accompanies every Application
        transition into APPROVED, APPROVED_WITH_MOD, REJECTED,
        SUSPENDED, TERMINATED, or COMPLETED (but not NO_QUORUM
        outcomes, which do not constitute regulatory decisions).'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        rows = list_audit_logs(SEC, event_type="REGULATORY_SYNC",
                               subject_entity="Application",
                               subject_id=app["id"])
        assert len(rows) >= 1, (
            f"PRD §2.11: 'this event accompanies every Application "
            f"transition into APPROVED ...'; got {rows!r}"
        )

    def test_approve_emits_im_notification_audit(self, api):
        """PRD §2.11: 'IM_NOTIFICATION audit row to drive the internal
        IM channel for every REVIEW_DECISION whose outcome is a
        regulator-visible decision (again excluding NO_QUORUM).'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        app = bundle["application"]
        rows = list_audit_logs(SEC, event_type="IM_NOTIFICATION",
                               subject_entity="Application",
                               subject_id=app["id"])
        assert len(rows) >= 1, (
            f"PRD §2.11: 'IM_NOTIFICATION audit row to drive the "
            f"internal IM channel for every REVIEW_DECISION whose "
            f"outcome is a regulator-visible decision'; got {rows!r}"
        )


# ===========================================================================
# REJECT cascade (PRD §3.5)
# ===========================================================================
class TestRejectCascade:
    """PRD §3.5: 'A REJECT outcome moves the application to REJECTED
    and emits REGULATORY_SYNC and IM_NOTIFICATION.'"""

    def test_reject_outcome_application_becomes_rejected(self, api):
        """PRD §3.5: 'A REJECT outcome moves the application to
        REJECTED'."""
        bundle = setup_resolved_initial_review(
            vote_split={"REJECT": 5, "APPROVE": 1, "DEFER": 1},
            member_count=9,
        )
        assert bundle["resolution"]["outcome"] == "REJECT"
        assert bundle["application"]["status"] == "REJECTED", (
            f"PRD §3.5: 'A REJECT outcome moves the application to "
            f"REJECTED'; got {bundle['application']['status']!r}"
        )


# ===========================================================================
# APPROVE_WITH_MODIFICATION cascade (PRD §3.5)
# ===========================================================================
class TestAwmCascade:
    """PRD §3.5: 'An APPROVE_WITH_MODIFICATION outcome moves the
    application to APPROVED_WITH_MOD, likewise locks
    approved_submission_version to the pinned version, creates a
    Rectification row with opinions populated from the resolution's
    reviewer comments and due_at set to the resolution's created_at
    plus 30 calendar days, and emits REGULATORY_SYNC and IM_NOTIFICATION
    events.'"""

    def test_awm_outcome_application_becomes_approved_with_mod(self, api):
        """PRD §3.5: 'An APPROVE_WITH_MODIFICATION outcome moves the
        application to APPROVED_WITH_MOD'."""
        # 7 votes cast, 5 AWM + 2 APPROVE → supermajority met, AWM(5) >
        # APPROVE(2) → APPROVE_WITH_MODIFICATION.
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE_WITH_MODIFICATION": 5, "APPROVE": 2},
            member_count=9,
        )
        assert bundle["resolution"]["outcome"] == "APPROVE_WITH_MODIFICATION"
        assert bundle["application"]["status"] == "APPROVED_WITH_MOD", (
            f"PRD §3.5: 'moves the application to APPROVED_WITH_MOD'; "
            f"got {bundle['application']['status']!r}"
        )

    def test_awm_locks_approved_submission_version(self, api):
        """PRD §3.5: 'likewise locks approved_submission_version to the
        pinned version'."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE_WITH_MODIFICATION": 5, "APPROVE": 2},
            member_count=9,
        )
        app = bundle["application"]
        agenda = bundle["agenda_item"]
        assert app["approved_submission_version"] == \
            agenda["pinned_submission_version"], (
            f"PRD §3.5: 'likewise locks approved_submission_version to "
            f"the pinned version'; got "
            f"{app.get('approved_submission_version')!r}"
        )


# ===========================================================================
# DEFER cascade (PRD §3.5)
# ===========================================================================
class TestDeferCascade:
    """PRD §3.5: 'A DEFER outcome moves the application to DEFERRED,
    creates a Rectification with opinions copied from the comments and
    a due_at 30 calendar days out, and emits REGULATORY_SYNC and
    IM_NOTIFICATION.'"""

    def test_defer_outcome_application_becomes_deferred(self, api):
        """PRD §3.5: 'A DEFER outcome moves the application to
        DEFERRED'. Setup: 9 members, 7 votes cast (≥ quorum 7); 5
        DEFER, 2 APPROVE → DEFER ≥ ceil(7/2)=4 → DEFER outcome."""
        bundle = setup_resolved_initial_review(
            vote_split={"DEFER": 5, "APPROVE": 2},
            member_count=9,
        )
        assert bundle["resolution"]["outcome"] == "DEFER"
        assert bundle["application"]["status"] == "DEFERRED", (
            f"PRD §3.5: 'A DEFER outcome moves the application to "
            f"DEFERRED'; got {bundle['application']['status']!r}"
        )


# ===========================================================================
# NO_QUORUM exclusion (PRD §2.11)
# ===========================================================================
class TestNoQuorumNoRegulatorySync:
    """PRD §2.11: 'this event accompanies every Application transition
    into APPROVED, APPROVED_WITH_MOD, REJECTED, SUSPENDED, TERMINATED,
    or COMPLETED (but not NO_QUORUM outcomes, which do not constitute
    regulatory decisions).'"""

    def test_no_quorum_emits_no_regulatory_sync(self, api):
        """PRD §2.11: 'but not NO_QUORUM outcomes, which do not
        constitute regulatory decisions.' PRD §3.5: 'The NO_QUORUM
        case ... moves the application to DEFERRED without creating a
        rectification and without emitting regulatory or IM events.'
        """
        from test_helpers import (
            cast_vote,
            resolve_agenda_item,
            seed_committee,
            setup_application_pending_review,
            setup_open_agenda_item,
        )
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        # 4 votes < 7 quorum → NO_QUORUM
        for m in members[1:5]:
            cast_vote(item["id"], m, "APPROVE")
        resolve_agenda_item(item["id"], chair)
        rows = list_audit_logs(SEC, event_type="REGULATORY_SYNC",
                               subject_entity="Application",
                               subject_id=app["id"])
        assert len(rows) == 0, (
            f"PRD §3.5: 'without emitting regulatory or IM events' on "
            f"NO_QUORUM; got {rows!r}"
        )
