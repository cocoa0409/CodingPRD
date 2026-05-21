"""Candidate registration, patch, email uniqueness, jurisdiction
existence — PRD §3.1.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_candidate,
    assert_status,
    create_candidate,
    create_candidate_payload,
    make_candidate_headers,
    unique_email,
    update_candidate_payload,
    upsert_jurisdiction_policy,
    validate_error,
    validate_success,
)


# ===========================================================================
# Candidate creation — PRD §3.1
# ===========================================================================
class TestCandidateRegistration:

    def test_create_candidate_initial_posture_eligible(
        self, api, recruiter_headers,
    ):
        """PRD §3.1: "On a successful registration the candidate's
        initial `eligibility_posture` is `ELIGIBLE`, its computed
        `salary_history_disclosed` is false, and its `archived_at` is
        null."

        Claim: POST /fcra/candidates returns 201 with
        eligibility_posture=ELIGIBLE, salary_history_disclosed=false,
        archived_at=null.
        """
        upsert_jurisdiction_policy(code="CA")
        resp = api.create_candidate(
            create_candidate_payload(residence_jurisdiction="CA"),
            recruiter_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_candidate(data)
        assert data["eligibility_posture"] == "ELIGIBLE"
        assert data["salary_history_disclosed"] is False
        assert data.get("archived_at") is None
        assert data["version"] == 1

    @pytest.mark.parametrize(
        "code", ["CA", "NY", "IL", "TX", "FL", "MA", "WA"],
    )
    def test_create_candidate_supported_jurisdictions(
        self, api, recruiter_headers, code,
    ):
        """PRD §3.1: "The seven supported `residence_jurisdiction`
        values are `CA`, `NY`, `IL`, `TX`, `FL`, `MA`, and `WA`, and a
        `JurisdictionPolicy` row must exist for the supplied code
        (registered separately by a `PlatformAdmin`)."

        Claim: each of the seven codes is accepted when a policy exists.
        """
        upsert_jurisdiction_policy(code=code)
        resp = api.create_candidate(
            create_candidate_payload(residence_jurisdiction=code),
            recruiter_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["residence_jurisdiction"] == code

    def test_duplicate_email_rejected(self, api, recruiter_headers):
        """PRD §3.1: "The candidate's `email` must be unique across
        candidates whose `archived_at` is null; two simultaneous
        registrations of the same email serialize to a single winner
        and the loser sees `ERR_CANDIDATE_EMAIL_TAKEN` (HTTP 409)."

        Claim: second POST with the same email -> ERR_CANDIDATE_EMAIL_TAKEN.
        """
        upsert_jurisdiction_policy(code="CA")
        email = unique_email("dup")
        first = api.create_candidate(
            create_candidate_payload(
                email=email, residence_jurisdiction="CA",
            ),
            recruiter_headers,
        )
        validate_success(first, expected_status=201)
        second = api.create_candidate(
            create_candidate_payload(
                email=email, residence_jurisdiction="CA",
            ),
            recruiter_headers,
        )
        validate_error(second, ApiErrorId.ERR_CANDIDATE_EMAIL_TAKEN.value)


# ===========================================================================
# Candidate patch — PRD §3.1
# ===========================================================================
class TestCandidatePatch:

    def test_patch_full_name_increments_version(
        self, api, recruiter_headers,
    ):
        """PRD §2.4: "an integer `version` that starts at 1 and
        increments by 1 on every mutation."
        PRD §3.1: "A patch may carry a new `full_name`, a new `email`,
        or an optional `version` for OCC."

        Claim: PATCH full_name returns 200 with version=2.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        resp = api.update_candidate(
            cand["id"],
            update_candidate_payload(
                full_name="Renamed Candidate", version=cand["version"],
            ),
            recruiter_headers,
        )
        data = validate_success(resp)
        assert data["full_name"] == "Renamed Candidate"
        assert data["version"] == cand["version"] + 1

    def test_patch_with_stale_version_rejected(
        self, api, recruiter_headers,
    ):
        """PRD §2.5: "When `version` is supplied, the server compares it
        against the current row version; on mismatch the request is
        rejected with `ERR_STALE_VERSION` (HTTP 409) and no fields
        change."

        Claim: PATCH with version=1 after a prior version=1->2 patch
        yields ERR_STALE_VERSION.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        # First successful patch -> version becomes 2.
        first = api.update_candidate(
            cand["id"],
            update_candidate_payload(
                full_name="First Rename", version=cand["version"],
            ),
            recruiter_headers,
        )
        validate_success(first)
        # Replay with the OLD version -> stale.
        stale = api.update_candidate(
            cand["id"],
            update_candidate_payload(
                full_name="Second Rename", version=cand["version"],
            ),
            recruiter_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# Salary History Ban — PRD §2.9
# ===========================================================================
class TestSalaryHistoryBan:

    def test_create_candidate_with_salary_history_in_banned_state(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "when the candidate's jurisdiction has
        `salary_history_ban` set to true, no request body — candidate
        creation, candidate patch, or order creation — may carry a
        `salary_history` field".

        Claim: POST /fcra/candidates with salary_history in a banned
        jurisdiction -> ERR_SALARY_HISTORY_BAN.
        """
        upsert_jurisdiction_policy(code="NY", salary_history_ban=True)
        resp = api.create_candidate(
            create_candidate_payload(
                residence_jurisdiction="NY", salary_history=50_000,
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SALARY_HISTORY_BAN.value)

    def test_patch_with_salary_history_in_banned_state(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "no request body — candidate creation, candidate
        patch, or order creation — may carry a `salary_history` field".

        Claim: PATCH /fcra/candidates/{id} with salary_history in a
        banned jurisdiction -> ERR_SALARY_HISTORY_BAN.
        """
        upsert_jurisdiction_policy(code="MA", salary_history_ban=True)
        cand = create_candidate(residence_jurisdiction="MA")
        resp = api.update_candidate(
            cand["id"],
            update_candidate_payload(
                salary_history=60_000, version=cand["version"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SALARY_HISTORY_BAN.value)

    def test_patch_with_salary_history_after_disclosed_true(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "Once `salary_history_disclosed` becomes true on a
        candidate (because a value was recorded at any point), every
        future endpoint that would accept `salary_history` on that
        candidate rejects the request with `ERR_SALARY_HISTORY_BAN`
        (HTTP 422), regardless of jurisdiction."

        Claim: after a salary_history value is once accepted, a later
        PATCH carrying salary_history is rejected even when the
        jurisdiction's ban is false.
        """
        # Use a state with salary_history_ban=false so disclosure can
        # be recorded once.
        upsert_jurisdiction_policy(code="IL", salary_history_ban=False)
        cand_resp = api.create_candidate(
            create_candidate_payload(
                residence_jurisdiction="IL", salary_history=70_000,
            ),
            recruiter_headers,
        )
        cand = validate_success(cand_resp, expected_status=201)
        assert cand["salary_history_disclosed"] is True
        # Subsequent PATCH carrying salary_history must be rejected.
        resp = api.update_candidate(
            cand["id"],
            update_candidate_payload(
                salary_history=72_000, version=cand["version"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SALARY_HISTORY_BAN.value)
