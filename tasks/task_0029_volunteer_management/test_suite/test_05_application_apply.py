"""Application creation: matching, validations, and ERR_* preconditions
(PRD §3.4).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    apply_to_activity,
    apply_to_activity_payload,
    api_client,
    assert_application,
    create_skill,
    create_verified_volunteer,
    create_volunteer,
    create_volunteer_with_clearance,
    define_activity_role,
    equip_volunteer_with_skills,
    make_organizer_headers,
    make_volunteer_headers,
    publish_activity,
    setup_organizer,
    setup_recruiting_activity,
    validate_error,
    validate_success,
)


class TestApplyHappyPath:
    def test_apply_creates_application_in_applied_with_distance_km(self, api):
        """PRD §3.4: 'The newly-created Application row begins in status
        APPLIED.' PRD §3.4 also: 'The server computes distance_km at
        apply time as the great-circle distance between (home_lat,
        home_lng) and (location_lat, location_lng), using the haversine
        formula on a spherical Earth of mean radius 6371.0088
        kilometres.'"""
        organizer, activity, _ = setup_recruiting_activity()
        v = create_verified_volunteer(home_lat=30.000000, home_lng=120.000000)
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_application(data)
        assert data["status"] == "APPLIED"
        assert data["activity_id"] == activity["id"]
        assert data["volunteer_id"] == v["id"]
        # Same coords -> distance 0.00.
        assert float(data["distance_km"]) == 0.00


class TestIdentityNotVerified:
    def test_apply_with_pending_identity_rejected(self, api):
        """PRD §3.4: 'the volunteer's identity_verification_status is
        not VERIFIED (ERR_IDENTITY_NOT_VERIFIED)'"""
        organizer, activity, _ = setup_recruiting_activity()
        v = create_volunteer()  # PENDING
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_IDENTITY_NOT_VERIFIED")


class TestBackgroundCheckRequired:
    def test_apply_to_sensitive_activity_without_clearance_rejected(self, api):
        """PRD §3.4: 'the activity has requires_sensitive_clearance of
        true and the volunteer's background_check_status is not CLEARED
        (ERR_BACKGROUND_CHECK_REQUIRED)'"""
        sensitive_skill = create_skill(sensitivity_level="SENSITIVE")
        organizer, activity, _ = setup_recruiting_activity(
            required_skill_codes=[sensitive_skill["code"]],
        )
        v = create_verified_volunteer()
        equip_volunteer_with_skills(v, [sensitive_skill])
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_BACKGROUND_CHECK_REQUIRED")

    def test_apply_to_sensitive_activity_with_clearance_succeeds(self, api):
        """PRD §3.4: implicit positive — when CLEARED, sensitive
        activities accept the application. Asserts the predicate is
        narrow (CLEARED, not just != NONE).

        PRD §3.4: 'the volunteer's background_check_status is not
        CLEARED (ERR_BACKGROUND_CHECK_REQUIRED)'"""
        sensitive_skill = create_skill(sensitivity_level="SENSITIVE")
        organizer, activity, _ = setup_recruiting_activity(
            required_skill_codes=[sensitive_skill["code"]],
        )
        v = create_volunteer_with_clearance()
        equip_volunteer_with_skills(v, [sensitive_skill])
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "APPLIED"


class TestSkillMismatch:
    def test_apply_without_required_skill_rejected(self, api):
        """PRD §3.4: 'the volunteer does not hold an APPROVED
        VolunteerSkill for every entry of Activity.required_skill_codes
        (ERR_SKILL_MISMATCH)'"""
        skill = create_skill()
        organizer, activity, _ = setup_recruiting_activity(
            required_skill_codes=[skill["code"]],
        )
        v = create_verified_volunteer()
        # Note: V did NOT declare-and-approve the skill.
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_SKILL_MISMATCH")


class TestRecruitmentClosed:
    def test_apply_when_clock_before_recruit_open_rejected(self, api):
        """PRD §3.4: 'the activity's status is not RECRUITING, or the
        current clock time is outside the half-open recruitment window
        starting at recruit_open_at and ending strictly before
        recruit_close_at (ERR_RECRUITMENT_CLOSED)'

        Apply BEFORE clock has reached recruit_open_at — Activity.status
        is still PUBLISHED, not RECRUITING.
        """
        organizer = setup_organizer()
        activity, _ = publish_activity(organizer=organizer)  # PUBLISHED
        v = create_verified_volunteer()
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_RECRUITMENT_CLOSED")


class TestDistanceExceeded:
    def test_apply_with_volunteer_far_away_rejected(self, api):
        """PRD §3.4: 'the computed distance_km exceeds 50 kilometres
        (ERR_DISTANCE_EXCEEDED)'"""
        organizer, activity, _ = setup_recruiting_activity(
            location_lat=30.000000, location_lng=120.000000,
        )
        # Volunteer placed roughly 1500 km north of the activity.
        v = create_verified_volunteer(home_lat=43.000000, home_lng=120.000000)
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_DISTANCE_EXCEEDED")


class TestDuplicateApplication:
    def test_duplicate_apply_for_same_activity_rejected(self, api):
        """PRD §3.4: 'a non-terminal Application of the same
        (activity_id, volunteer_id) already exists
        (ERR_DUPLICATE_APPLICATION)'"""
        organizer, activity, _ = setup_recruiting_activity()
        v = create_verified_volunteer()
        first = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_success(first, expected_status=201)
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_DUPLICATE_APPLICATION")


class TestInvalidReferenceActivityRole:
    def test_apply_with_role_from_other_activity_rejected(self, api):
        """PRD §3.4: 'when activity_role_id is supplied, the referenced
        ActivityRole exists but its activity_id does not equal the
        surrounding activity's id (ERR_INVALID_REFERENCE)'"""
        organizer = setup_organizer()
        # Activity A in RECRUITING with its own role.
        organizer, activity_a, roles_a = setup_recruiting_activity(
            organizer=organizer, role_labels=["LEAD"],
        )
        # Activity B in RECRUITING with its own role.
        organizer2, activity_b, roles_b = setup_recruiting_activity(
            role_labels=["SUPPORT"],
        )
        v = create_verified_volunteer()
        # Apply to A but pass a role belonging to B.
        res = api.apply_to_activity(
            apply_to_activity_payload(
                activity_id=activity_a["id"], activity_role_id=roles_b[0]["id"]
            ),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_INVALID_REFERENCE")
