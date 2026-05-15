"""Candidate registration, updates, and visibility gating (PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_candidate,
    create_candidate,
    create_candidate_payload,
    create_verified_company,
    forward_application,
    make_candidate_headers,
    make_hr_user_headers,
    mark_application_read,
    submit_application,
    update_candidate_payload,
    validate_error,
    validate_success,
    create_live_posting,
)


# ===========================================================================
# Candidate creation (PRD §3.3)
# ===========================================================================
class TestCandidateCreate:

    def test_create_candidate_defaults_visibility_to_public(
        self, api, candidate_fallback_headers,
    ):
        """PRD §3.3: "a `visibility_mode` (one of `PUBLIC`, `COMPANY_ONLY`,
        `HIDDEN`, defaulting to `PUBLIC`)."

        Claim: omitting visibility_mode yields visibility_mode==PUBLIC.
        """
        payload = create_candidate_payload()
        payload.pop("visibility_mode", None)
        resp = api.create_candidate(payload, candidate_fallback_headers)
        data = validate_success(resp, expected_status=201)
        assert_candidate(data)
        assert data["visibility_mode"] == "PUBLIC"

    def test_create_candidate_email_unique(self, api, candidate_fallback_headers):
        """PRD §3.3: "The `email` is unique across all candidates."

        Claim: duplicate email yields ERR_VALIDATION.
        """
        payload = create_candidate_payload(email="dup-cand@example.com")
        validate_success(
            api.create_candidate(payload, candidate_fallback_headers),
            expected_status=201,
        )
        payload2 = create_candidate_payload(email="dup-cand@example.com")
        resp = api.create_candidate(payload2, candidate_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Candidate PATCH + OCC (PRD §3.3, §2.5)
# ===========================================================================
class TestCandidatePatch:

    def test_patch_visibility_mode(self, api):
        """PRD §3.3: "The candidate may update these fields later through
        the candidate-update capability, which accepts `visibility_mode`,
        `visible_to_company_ids`, and `resume_attachment_url` in any
        combination."

        Claim: PATCH visibility_mode is applied.
        """
        candidate = create_candidate()
        resp = api.update_candidate(
            candidate["id"],
            update_candidate_payload(visibility_mode="HIDDEN"),
            make_candidate_headers(candidate["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["visibility_mode"] == "HIDDEN"

    def test_patch_with_stale_version_returns_version_conflict(self, api):
        """PRD §2.5: "When `version` is supplied, the server compares it
        to the resource's current `version`; if they differ, the request
        is rejected with `ERR_VERSION_CONFLICT`."

        Claim: PATCH with stale version → ERR_VERSION_CONFLICT.
        """
        candidate = create_candidate()
        # Mutate once to bump version.
        api.update_candidate(
            candidate["id"],
            update_candidate_payload(resume_attachment_url="https://x.com/a.pdf"),
            make_candidate_headers(candidate["id"]),
        )
        resp = api.update_candidate(
            candidate["id"],
            update_candidate_payload(
                resume_attachment_url="https://x.com/b.pdf",
                version=candidate["version"],  # stale
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_with_current_version_succeeds(self, api):
        """PRD §2.5: "A successful mutation increments `version` by one
        and refreshes `updated_at`."

        Claim: PATCH with the current version succeeds and increments version.
        """
        candidate = create_candidate()
        v0 = candidate["version"]
        resp = api.update_candidate(
            candidate["id"],
            update_candidate_payload(
                resume_attachment_url="https://x.com/new.pdf",
                version=v0,
            ),
            make_candidate_headers(candidate["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["version"] == v0 + 1


# ===========================================================================
# Visibility gating (PRD §3.3, validation priority 7)
# ===========================================================================
class TestResumeVisibility:

    def test_hidden_blocks_hr_read(self, api):
        """PRD §3.3: "`HIDDEN` blocks every HR-side read or write that
        touches `resume_attachment_url`. Any failure yields
        `ERR_RESUME_NOT_VISIBLE`."

        Claim: HR reading a HIDDEN candidate yields ERR_RESUME_NOT_VISIBLE.
        """
        candidate = create_candidate(visibility_mode="HIDDEN")
        _, hr_user = create_verified_company()
        resp = api.get_candidate(
            candidate["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESUME_NOT_VISIBLE.value)

    def test_company_only_without_company_in_list_blocks_hr_read(self, api):
        """PRD §3.3: "`COMPANY_ONLY` requires the acting company's `id`
        to appear in the candidate's `visible_to_company_ids`."

        Claim: HR from a non-whitelisted Company reading a COMPANY_ONLY
        candidate yields ERR_RESUME_NOT_VISIBLE.
        """
        other_company, _ = create_verified_company()
        candidate = create_candidate(
            visibility_mode="COMPANY_ONLY",
            visible_to_company_ids=[other_company["id"]],
        )
        _, hr_user = create_verified_company()  # different Company
        resp = api.get_candidate(
            candidate["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESUME_NOT_VISIBLE.value)

    def test_company_only_with_company_in_list_allows_hr_read(self, api):
        """PRD §3.3: "`COMPANY_ONLY` requires the acting company's `id`
        to appear in the candidate's `visible_to_company_ids`."

        Claim: HR from a whitelisted Company can read a COMPANY_ONLY candidate.
        """
        company, hr_user = create_verified_company()
        candidate = create_candidate(
            visibility_mode="COMPANY_ONLY",
            visible_to_company_ids=[company["id"]],
        )
        resp = api.get_candidate(
            candidate["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_success(resp, expected_status=200)

    def test_public_allows_any_hr_read(self, api):
        """PRD §3.3: "`PUBLIC` always passes."

        Claim: HR can read a PUBLIC candidate without being in a list.
        """
        candidate = create_candidate(visibility_mode="PUBLIC")
        _, hr_user = create_verified_company()
        resp = api.get_candidate(
            candidate["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_success(resp, expected_status=200)

    def test_forward_application_runs_visibility_check(self, api):
        """PRD §3.3: "The visibility rule applies wherever an HR-side
        actor crosses from a posting-or-application context into the
        candidate's resume. Reading a candidate row, forwarding an
        application, and creating an interview round all check the rule.
        ... Any failure yields `ERR_RESUME_NOT_VISIBLE`."

        Claim: forwarding an application for a HIDDEN candidate yields
        ERR_RESUME_NOT_VISIBLE.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate(visibility_mode="HIDDEN")
        application = submit_application(candidate["id"], posting["id"])
        mark_application_read(application["id"], hr_user["id"])
        resp = api.forward_application(
            application["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESUME_NOT_VISIBLE.value)
