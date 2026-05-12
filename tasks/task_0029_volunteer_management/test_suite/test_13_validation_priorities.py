"""Validation priority ordering (PRD §2.7).

Covers difficulty-design rule 5 instances 1 and 2: dual-failure
scenarios where PRD §2.7 explicitly pins which error_id wins.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    api_client,
    apply_to_activity_payload,
    check_in_payload,
    create_skill,
    create_verified_volunteer,
    create_volunteer,
    equip_volunteer_with_skills,
    make_volunteer_headers,
    publish_activity,
    setup_organizer,
    setup_recruiting_activity,
    validate_error,
)


class TestStateBeforeCheckInProof:
    """difficulty: priority_pair_validation_conflict/state_vs_business_safety_check_in_proof_vs_activity_state"""

    def test_check_in_when_activity_recruiting_and_no_proof_returns_invalid_state(
        self, api
    ):
        """PRD §2.7: 'When multiple validations would fire on the same
        request, the system evaluates them in a fixed priority order so
        that the most fundamental failure surfaces first. The order
        is: ... then state-machine permissibility for the requested
        transition; ... then field-level format validation; and last,
        optimistic-concurrency version comparison.'

        Both ERR_INVALID_STATE (Activity not RUNNING) and
        ERR_CHECK_IN_PROOF_FAILED (no site_code, no GPS) would apply.
        PRD §2.7 places state-machine permissibility before
        field-level/format validation.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_check_in_proof_vs_activity_state
        """
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        # Apply but DON'T advance clock to start_at: Activity stays RECRUITING.
        from test_helpers import apply_to_activity, approve_application
        application = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=application, organizer=organizer)
        # Activity still RECRUITING (not RUNNING). Submit no proof.
        res = api.check_in(
            application["id"], check_in_payload(),
            make_volunteer_headers(v["id"]),
        )
        # PRD §2.7 places state-machine permissibility BEFORE field-level
        # checks (where check-in proof falls). State error must surface.
        validate_error(res, "ERR_INVALID_STATE")


class TestIdentityBeforeRecruitmentClosed:
    """difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_identity_vs_recruitment_window"""

    def test_unverified_volunteer_applying_to_closed_recruitment_returns_identity_error(
        self, api
    ):
        """PRD §2.7: 'then identity-verification for any
        volunteer-initiated activity action; then the background-check
        requirement when the target activity needs sensitive clearance;
        then the skill-tag match against Activity.required_skill_codes;
        then recruitment-window and time-conflict checks.'

        PRD §2.7 also illustrates: 'a caller whose identity is
        unverified and who would also fail a skill-match check always
        receives ERR_IDENTITY_NOT_VERIFIED first'. Same priority
        relationship governs identity vs recruitment-window.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_identity_vs_recruitment_window
        """
        # Activity in PUBLISHED (not RECRUITING) so the recruitment-window
        # check would fire with ERR_RECRUITMENT_CLOSED. Volunteer is
        # PENDING (not VERIFIED). PRD §2.7 puts identity-verification
        # priority above recruitment-window.
        organizer = setup_organizer()
        activity, _ = publish_activity(organizer=organizer)
        v = create_volunteer()  # PENDING identity
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_IDENTITY_NOT_VERIFIED")
