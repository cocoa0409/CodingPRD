"""Skill catalog and VolunteerSkill review cycle (PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_skill,
    assert_volunteer_skill,
    create_skill,
    create_skill_payload,
    create_verified_volunteer,
    declare_and_approve_skill,
    declare_volunteer_skill_payload,
    make_skilladmin_headers,
    make_volunteer_headers,
    resubmit_volunteer_skill_payload,
    validate_error,
    validate_success,
)


class TestSkillCatalog:
    def test_create_skill_with_defaults(self, api, skilladmin_headers):
        """PRD §3.2: 'Each Skill carries a code (unique, 2 to 40
        characters, uppercase snake_case), a human-readable name, a
        requires_certificate flag (default false) ..., and a
        sensitivity_level of either STANDARD (default) or SENSITIVE.'"""
        res = api.create_skill(
            create_skill_payload(code="FIRST_AID_CARE"), skilladmin_headers
        )
        data = validate_success(res, expected_status=201)
        assert_skill(data)
        assert data["code"] == "FIRST_AID_CARE"
        assert data["sensitivity_level"] == "STANDARD"
        assert data["requires_certificate"] is False


class TestVolunteerSkillFreshDeclaration:
    def test_declare_skill_starts_self_declared(self, api):
        """PRD §3.2: 'The new declaration begins in review_status
        SELF_DECLARED.'"""
        v = create_verified_volunteer()
        skill = create_skill()
        res = api.declare_skill(
            declare_volunteer_skill_payload(skill_id=skill["id"]),
            make_volunteer_headers(v["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_volunteer_skill(data)
        assert data["review_status"] == "SELF_DECLARED"

    def test_duplicate_declaration_rejected(self, api):
        """PRD §3.2: 'A volunteer may not hold two VolunteerSkill rows
        for the same (volunteer_id, skill_id) simultaneously in any
        state other than REJECTED; a duplicate attempt is rejected with
        ERR_DUPLICATE_SKILL_DECLARATION.'"""
        v = create_verified_volunteer()
        skill = create_skill()
        first = api.declare_skill(
            declare_volunteer_skill_payload(skill_id=skill["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_success(first, expected_status=201)
        res = api.declare_skill(
            declare_volunteer_skill_payload(skill_id=skill["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_DUPLICATE_SKILL_DECLARATION")


class TestVolunteerSkillSubmission:
    def test_submit_self_declared_advances_to_under_review(self, api):
        """PRD §3.2: 'The volunteer then submits the declaration for
        review, advancing review_status from SELF_DECLARED to
        UNDER_REVIEW.'"""
        v = create_verified_volunteer()
        skill = create_skill()
        declared = api.declare_skill(
            declare_volunteer_skill_payload(skill_id=skill["id"]),
            make_volunteer_headers(v["id"]),
        ).json()["data"]
        res = api.submit_volunteer_skill(declared["id"], make_volunteer_headers(v["id"]))
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "UNDER_REVIEW"

    def test_submit_without_required_certificate_rejected(self, api):
        """PRD §3.2: 'Submission requires that the certificate-attachment
        rule still hold — if Skill.requires_certificate is true, the
        row's certificate_url must be non-null at submission; otherwise
        the submit is rejected with ERR_INVALID_STATE.'"""
        v = create_verified_volunteer()
        skill = create_skill(requires_certificate=True)
        declared = api.declare_skill(
            declare_volunteer_skill_payload(skill_id=skill["id"]),
            make_volunteer_headers(v["id"]),
        ).json()["data"]
        res = api.submit_volunteer_skill(declared["id"], make_volunteer_headers(v["id"]))
        validate_error(res, "ERR_INVALID_STATE")


class TestVolunteerSkillReview:
    def test_approve_under_review_advances_to_approved(self, api, skilladmin_headers):
        """PRD §3.2: 'A SkillAdmin then either approves the declaration
        (advancing review_status from UNDER_REVIEW to APPROVED and
        stamping the acting admin's id into reviewer_id and the current
        server time into reviewed_at) or rejects it.'"""
        v = create_verified_volunteer()
        skill = create_skill()
        declared = api.declare_skill(
            declare_volunteer_skill_payload(skill_id=skill["id"]),
            make_volunteer_headers(v["id"]),
        ).json()["data"]
        api.submit_volunteer_skill(declared["id"], make_volunteer_headers(v["id"]))
        res = api.approve_volunteer_skill(declared["id"], skilladmin_headers)
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "APPROVED"
        assert data.get("reviewer_id") is not None
        assert data.get("reviewed_at") is not None

    def test_reject_under_review_advances_to_rejected_terminal(
        self, api, skilladmin_headers
    ):
        """PRD §3.2: 'or rejects it (advancing review_status from
        UNDER_REVIEW to REJECTED, also stamping reviewer_id and
        reviewed_at); REJECTED is terminal.'"""
        v = create_verified_volunteer()
        skill = create_skill()
        declared = api.declare_skill(
            declare_volunteer_skill_payload(skill_id=skill["id"]),
            make_volunteer_headers(v["id"]),
        ).json()["data"]
        api.submit_volunteer_skill(declared["id"], make_volunteer_headers(v["id"]))
        rejected = api.reject_volunteer_skill(declared["id"], skilladmin_headers)
        validate_success(rejected, expected_status=200)
        # PRD §3.2 calls REJECTED terminal — re-approving is invalid.
        res = api.approve_volunteer_skill(declared["id"], skilladmin_headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestResubmitAfterApproval:
    def test_resubmit_with_refreshed_cert_reverts_to_under_review(
        self, api, skilladmin_headers
    ):
        """PRD §3.2: 'For a previously-APPROVED declaration whose
        certificate has gone stale, the volunteer may resubmit the row
        with a refreshed certificate_url in the request body; the row
        reverts from APPROVED to UNDER_REVIEW for re-review, with the
        new certificate_url overwriting the old.'"""
        v = create_verified_volunteer()
        skill = create_skill(requires_certificate=True)
        approved = declare_and_approve_skill(
            volunteer=v, skill=skill, certificate_url="https://example.test/old.pdf"
        )
        res = api.resubmit_volunteer_skill(
            approved["id"],
            resubmit_volunteer_skill_payload(certificate_url="https://example.test/new.pdf"),
            make_volunteer_headers(v["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["review_status"] == "UNDER_REVIEW"
        assert data.get("certificate_url") == "https://example.test/new.pdf"
