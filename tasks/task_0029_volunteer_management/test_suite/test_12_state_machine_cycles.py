"""Non-linear state-machine cycles (PRD §3.2 VolunteerSkill, §3.3
Activity). Covers difficulty-design rule 3 instances 1 and 2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    create_skill,
    create_verified_volunteer,
    declare_and_approve_skill,
    make_organizer_headers,
    make_skilladmin_headers,
    make_volunteer_headers,
    reject_activity,
    resubmit_volunteer_skill_payload,
    setup_organizer,
    create_draft_activity,
    submit_activity,
    validate_success,
)


class TestActivityRejectedToDraftRevisionCycle:
    """difficulty: non_linear_state_machine/activity_rejected_to_draft_revision_cycle"""

    def test_full_cycle_draft_review_rejected_draft_review_published(self, api):
        """PRD §3.3: 'A rejected activity is not terminal: the original
        organizer may pull the rejected activity back to DRAFT for
        revision, and the revision-resubmit-review loop may run any
        number of times.'

        PRD §2.4: 'every successful mutation, the server bumps the
        row's version by one'.

        Cycle: DRAFT -> UNDER_REVIEW -> REJECTED -> DRAFT -> UNDER_REVIEW
        -> PUBLISHED. Six successful mutations -> version bumps from 1
        to at least 6 (PRD says "starts at 1 on creation" so version=1
        at DRAFT, then +5 transitions reaching 6 at PUBLISHED).

        # difficulty: non_linear_state_machine/activity_rejected_to_draft_revision_cycle
        """
        organizer = setup_organizer()
        activity = create_draft_activity(organizer=organizer)
        original_id = activity["id"]
        # 1: DRAFT (creation -> version=1)
        assert activity["status"] == "DRAFT"
        assert activity["version"] == 1

        # 2: DRAFT -> UNDER_REVIEW
        a2 = submit_activity(activity, organizer)
        assert a2["status"] == "UNDER_REVIEW"
        assert a2["version"] == 2

        # 3: UNDER_REVIEW -> REJECTED
        a3 = reject_activity(activity["id"])
        assert a3["status"] == "REJECTED"
        assert a3["version"] == 3

        # 4: REJECTED -> DRAFT
        a4 = api.revise_activity(
            activity["id"], make_organizer_headers(organizer["id"])
        ).json()["data"]
        assert a4["status"] == "DRAFT"
        assert a4["version"] == 4

        # 5: DRAFT -> UNDER_REVIEW
        a5 = submit_activity(activity, organizer)
        assert a5["status"] == "UNDER_REVIEW"
        assert a5["version"] == 5

        # 6: UNDER_REVIEW -> PUBLISHED
        a6 = api.approve_activity(
            activity["id"], make_skilladmin_headers()
        ).json()["data"]
        assert a6["status"] == "PUBLISHED"
        assert a6["version"] == 6

        # Same row throughout: id unchanged.
        assert a6["id"] == original_id


class TestVolunteerSkillApprovedToUnderReviewLoop:
    """difficulty: non_linear_state_machine/volunteerskill_approved_to_under_review_revision_loop"""

    def test_resubmit_reopens_approved_to_under_review_then_back_to_approved(
        self, api
    ):
        """PRD §3.2: 'For a previously-APPROVED declaration whose
        certificate has gone stale, the volunteer may resubmit the row
        with a refreshed certificate_url in the request body; the row
        reverts from APPROVED to UNDER_REVIEW for re-review, with the
        new certificate_url overwriting the old.'

        Cycle on VolunteerSkill: APPROVED -> UNDER_REVIEW -> APPROVED.

        # difficulty: non_linear_state_machine/volunteerskill_approved_to_under_review_revision_loop
        """
        v = create_verified_volunteer()
        skill = create_skill(requires_certificate=True)
        approved = declare_and_approve_skill(
            volunteer=v, skill=skill, certificate_url="https://example.test/u1.pdf"
        )
        assert approved["review_status"] == "APPROVED"
        assert approved.get("certificate_url") == "https://example.test/u1.pdf"

        # Resubmit with new URL.
        res = api.resubmit_volunteer_skill(
            approved["id"],
            resubmit_volunteer_skill_payload(certificate_url="https://example.test/u2.pdf"),
            make_volunteer_headers(v["id"]),
        )
        reopened = validate_success(res, expected_status=200)
        assert reopened["review_status"] == "UNDER_REVIEW"
        assert reopened.get("certificate_url") == "https://example.test/u2.pdf"

        # Re-approve.
        re_res = api.approve_volunteer_skill(approved["id"], make_skilladmin_headers())
        re_approved = validate_success(re_res, expected_status=200)
        assert re_approved["review_status"] == "APPROVED"
        assert re_approved.get("certificate_url") == "https://example.test/u2.pdf"
