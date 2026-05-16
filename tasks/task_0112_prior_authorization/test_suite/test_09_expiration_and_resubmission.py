"""Approval expiration via clock + sweep, and resubmission.

PRD §3.10 (expiration sweep), §3.8 (resubmission rules).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    create_authorization_request,
    create_authorization_request_payload,
    expire_authorization_via_sweep,
    make_provider_headers,
    re_get_authorization,
    setup_approved_authorization,
    setup_denied_authorization,
    setup_reference_data,
    setup_resubmission_with_n_reused_evidence,
    validate_error,
    validate_success,
)


# ===========================================================================
# Sweep transitions APPROVED -> EXPIRED
# ===========================================================================
class TestExpirationSweep:
    """PRD §3.10: sweep transitions APPROVED → EXPIRED when now() >=
    expires_at."""

    def test_sweep_expires_aged_approved_authorization(self, api):
        """PRD §3.10: "The expiration sweep — an admin-driven test
        capability — examines every authorization currently in APPROVED
        and, for each one whose current server time has reached or
        passed expires_at, advances its status to EXPIRED, refreshes
        updated_at, and increments version. The endpoint returns the
        set of ids it swept as expired_authorization_request_ids."

        Claim: advancing the clock past expires_at and running the
        sweep transitions an APPROVED authorization to EXPIRED.
        """
        _, _, _, auth = setup_approved_authorization(
            approval_validity_days=1,
        )
        assert auth["status"] == "APPROVED"
        version_before = auth["version"]
        expired = expire_authorization_via_sweep(authorization=auth)
        assert expired["status"] == "EXPIRED"
        assert expired["version"] >= version_before + 1


# ===========================================================================
# Resubmission validations
# ===========================================================================
class TestResubmission:
    """PRD §3.8: three checks govern resubmission."""

    def test_resubmission_on_non_expired_prior_rejected(self, api):
        """PRD §3.8: "the prior's status must be EXPIRED;
        resubmissions targeting a prior that is still in any earlier
        state, or one that was withdrawn, are rejected with
        ERR_PRIOR_REQUEST_NOT_EXPIRED."

        Claim: pointing prior_request_id to a DENIED (not EXPIRED)
        authorization returns ERR_PRIOR_REQUEST_NOT_EXPIRED.
        """
        _, provider, catalog_item, denied = setup_denied_authorization()
        # Build a new patient so the resubmission can reuse but the
        # prior remains DENIED rather than EXPIRED.
        from test_helpers import create_patient
        patient2 = create_patient()
        payload = create_authorization_request_payload(
            patient_id=patient2["id"],
            provider_id=provider["id"],
            service_catalog_item_id=catalog_item["id"],
            prior_request_id=denied["id"],
        )
        res = api.create_authorization_request(
            payload, make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_PRIOR_REQUEST_NOT_EXPIRED")

    def test_resubmission_nonexistent_prior_rejected(self, api):
        """PRD §3.8: "the referenced prior must exist (else
        ERR_PRIOR_REQUEST_NOT_FOUND)".

        Claim: prior_request_id pointing to a nonexistent uuid returns
        ERR_PRIOR_REQUEST_NOT_FOUND.
        """
        patient, provider, catalog_item = setup_reference_data()
        payload = create_authorization_request_payload(
            patient_id=patient["id"],
            provider_id=provider["id"],
            service_catalog_item_id=catalog_item["id"],
            prior_request_id=NON_EXISTENT_UUID,
        )
        res = api.create_authorization_request(
            payload, make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_PRIOR_REQUEST_NOT_FOUND")

    def test_at_most_one_resubmission_per_prior_request_id(self, api):
        """PRD §3.8: "at most one resubmission may exist per
        prior_request_id: a second attempt to resubmit the same
        expired authorization is rejected with
        ERR_RESUBMISSION_ALREADY_EXISTS".

        Claim: a second create_authorization_request with the same
        prior_request_id returns ERR_RESUBMISSION_ALREADY_EXISTS.
        """
        _, provider, catalog_item, prior, _resub, _evs = (
            setup_resubmission_with_n_reused_evidence(num_reused=1)
        )
        # First resubmission already created by the fixture.
        # Build another patient so the second attempt is independent.
        from test_helpers import create_patient
        patient2 = create_patient()
        payload = create_authorization_request_payload(
            patient_id=patient2["id"],
            provider_id=provider["id"],
            service_catalog_item_id=catalog_item["id"],
            prior_request_id=prior["id"],
        )
        res = api.create_authorization_request(
            payload, make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_RESUBMISSION_ALREADY_EXISTS")

    def test_resubmission_on_expired_prior_succeeds(self, api):
        """PRD §3.8: "A resubmission is created by issuing a new
        AuthorizationRequest whose body sets prior_request_id to the id
        of the expired authorization."

        Claim: a resubmission against an EXPIRED prior succeeds and
        carries prior_request_id on the new record.
        """
        _, _, _, prior, resub, _ = (
            setup_resubmission_with_n_reused_evidence(num_reused=0)
        )
        assert prior["status"] == "EXPIRED"
        assert resub["prior_request_id"] == prior["id"]
