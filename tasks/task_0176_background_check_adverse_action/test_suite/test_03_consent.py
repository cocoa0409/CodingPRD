"""Consent recording, supersession, revocation — PRD §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_hours,
    add_minutes,
    assert_consent_disclosure,
    assert_status,
    create_candidate,
    iso_utc,
    make_candidate_headers,
    record_consent_as_candidate,
    record_consent_as_recruiter,
    record_consent_payload,
    upsert_jurisdiction_policy,
    utcnow,
    validate_error,
    validate_success,
)


# ===========================================================================
# Recording consent — PRD §3.2
# ===========================================================================
class TestConsentRecording:

    def test_recruiter_records_consent_on_behalf_of_candidate(
        self, api, recruiter_headers,
    ):
        """PRD §3.2: "Either the `Recruiter` (on behalf of the
        candidate) or the `Candidate` (acting on their own row) may
        record one."

        Claim: POST /fcra/candidates/{id}/consent as Recruiter ->
        ConsentDisclosure with status=ACTIVE.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        resp = api.record_consent(
            cand["id"], record_consent_payload(), recruiter_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_consent_disclosure(data)
        assert data["status"] == "ACTIVE"
        assert data["candidate_id"] == cand["id"]

    def test_candidate_records_consent_on_own_row(self, api):
        """PRD §3.2: "Either the `Recruiter` (on behalf of the
        candidate) or the `Candidate` (acting on their own row) may
        record one."

        Claim: POST /fcra/candidates/{id}/consent as Candidate with
        ownership-matched X-User-ID -> 201 with status=ACTIVE.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        resp = api.record_consent(
            cand["id"], record_consent_payload(),
            make_candidate_headers(cand["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"

    def test_new_consent_supersedes_prior_active_consent(
        self, api, recruiter_headers,
    ):
        """PRD §3.2: "Recording a new consent for a candidate whose row
        already has an `ACTIVE` consent supersedes the old one: the
        prior consent's `status` moves to `SUPERSEDED` and the new
        row's `status` is `ACTIVE`."

        Claim: a second POST recording creates a new ACTIVE consent and
        the first consent's status becomes SUPERSEDED.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        first = record_consent_as_recruiter(candidate_id=cand["id"])
        assert first["status"] == "ACTIVE"
        second = record_consent_as_recruiter(candidate_id=cand["id"])
        assert second["status"] == "ACTIVE"
        # The PRD doesn't define a list-consents endpoint, but we can
        # observe the rule by trying to use the prior consent_id when
        # opening an order: it should fail with ERR_CONSENT_INVALID
        # (the consent is now SUPERSEDED, not ACTIVE).
        order_resp = api.create_order(
            {
                "candidate_id": cand["id"],
                "consent_disclosure_id": first["id"],
                "stage_at_order": "PRE_OFFER",
                "requested_packages": ["CRIMINAL"],
            },
            recruiter_headers,
        )
        validate_error(order_resp, ApiErrorId.ERR_CONSENT_INVALID.value)


# ===========================================================================
# Temporal validity — PRD §3.2
# ===========================================================================
class TestConsentTimestampValidity:
    """PRD §3.2: "consent_timestamp must be less than or equal to the
    server's current time, and `disclosure_presented_at` must be less
    than or equal to `consent_timestamp` ... A violation of either
    inequality surfaces as `ERR_CONSENT_TIMESTAMP_INVALID` (HTTP 422)."
    """

    def test_consent_timestamp_in_future_rejected(
        self, api, recruiter_headers,
    ):
        """PRD §3.2: "consent_timestamp must be less than or equal to
        the server's current time ... A violation of either inequality
        surfaces as `ERR_CONSENT_TIMESTAMP_INVALID` (HTTP 422)."

        Claim: POST consent with consent_timestamp far in the future ->
        ERR_CONSENT_TIMESTAMP_INVALID.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        # 10 years from now is unambiguously future regardless of the
        # server clock's logical offset.
        future = iso_utc(utcnow().replace(year=utcnow().year + 10))
        payload = record_consent_payload(
            consent_timestamp=future,
            disclosure_presented_at=future,
        )
        resp = api.record_consent(cand["id"], payload, recruiter_headers)
        validate_error(
            resp, ApiErrorId.ERR_CONSENT_TIMESTAMP_INVALID.value,
        )

    def test_disclosure_presented_after_consent_rejected(
        self, api, recruiter_headers,
    ):
        """PRD §3.2: "`disclosure_presented_at` must be less than or
        equal to `consent_timestamp` (the candidate cannot sign before
        seeing the disclosure ...) ... A violation of either inequality
        surfaces as `ERR_CONSENT_TIMESTAMP_INVALID` (HTTP 422)."

        Claim: disclosure_presented_at > consent_timestamp ->
        ERR_CONSENT_TIMESTAMP_INVALID.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        consent_ts = iso_utc(utcnow())
        # disclosure presented LATER than consent — impossible in real
        # life, must be rejected.
        disclosure_at = add_hours(consent_ts, 1)
        payload = record_consent_payload(
            consent_timestamp=consent_ts,
            disclosure_presented_at=disclosure_at,
        )
        resp = api.record_consent(cand["id"], payload, recruiter_headers)
        validate_error(
            resp, ApiErrorId.ERR_CONSENT_TIMESTAMP_INVALID.value,
        )


# ===========================================================================
# Revocation — PRD §3.2
# ===========================================================================
class TestConsentRevocation:

    def test_candidate_revokes_own_consent(self, api):
        """PRD §3.2: "The acting `Candidate` may revoke their `ACTIVE`
        consent at any time; revocation moves `status` to `REVOKED`,
        stamps `revoked_at` with the server's current time, and writes
        an `AuditEvent` of type `CONSENT_REVOKED`."

        Claim: POST /fcra/candidates/{id}/consent/revoke as candidate
        -> 200, consent.status=REVOKED, revoked_at non-null.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        consent = record_consent_as_recruiter(candidate_id=cand["id"])
        resp = api.revoke_consent(
            cand["id"], make_candidate_headers(cand["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "REVOKED"
        assert data.get("revoked_at") is not None

    def test_recruiter_cannot_revoke_consent(self, api, recruiter_headers):
        """PRD §4: "POST /fcra/candidates/{candidateId}/consent/revoke
        ... Candidate" — only the Candidate role may revoke.
        PRD §2.1: "If the role is not authorised for the endpoint per
        the matrix described in §4, the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Claim: Recruiter POST /consent/revoke -> ERR_FORBIDDEN.
        """
        upsert_jurisdiction_policy(code="CA")
        cand = create_candidate(residence_jurisdiction="CA")
        record_consent_as_recruiter(candidate_id=cand["id"])
        resp = api.revoke_consent(cand["id"], recruiter_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
