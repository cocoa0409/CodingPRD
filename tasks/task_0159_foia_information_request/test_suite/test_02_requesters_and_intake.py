"""Requester profile + request filing + acknowledgement — PRD §3.1, §3.2."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    acknowledge_request,
    assert_request,
    assert_requester,
    create_request_payload,
    create_requester,
    create_requester_payload,
    file_request,
    make_requester_headers,
    patch_requester_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Requester registration — PRD §3.1
# ===========================================================================
class TestRequesterRegistration:

    def test_register_commercial_requester(self, api):
        """PRD §3.1: "the tier must be one of `COMMERCIAL`,
        `EDUCATIONAL_NONCOMMERCIAL`, or `PUBLIC_INTEREST`."
        PRD §3.1: "A registered requester starts with `status` of `ACTIVE`".

        Claim: a commercial registration succeeds, returns status=ACTIVE,
        and tier_justification may be omitted.
        """
        payload = create_requester_payload(
            requester_tier="COMMERCIAL", tier_justification=None,
        )
        resp = api.create_requester(payload, TEST_USERS["officer_headers"])
        data = validate_success(resp, expected_status=201)
        assert_requester(data)
        assert data["status"] == "ACTIVE"
        assert data["requester_tier"] == "COMMERCIAL"
        assert data["version"] == 1

    def test_register_educational_requires_tier_justification(self, api):
        """PRD §3.1: "The non-commercial tiers also require a free-text
        `tier_justification` of up to 1000 characters explaining why the
        requester qualifies".

        Claim: an educational registration with an empty/omitted
        tier_justification fails with ERR_INVALID_INPUT.
        """
        payload = {
            "full_name": "No Justification User",
            "contact_email": "x@example.test",
            "requester_tier": "EDUCATIONAL_NONCOMMERCIAL",
        }
        resp = api.create_requester(payload, TEST_USERS["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_register_public_interest_with_justification(self, api):
        """PRD §3.1: "the tier must be one of `COMMERCIAL`,
        `EDUCATIONAL_NONCOMMERCIAL`, or `PUBLIC_INTEREST`."

        Claim: a public-interest registration with a non-empty
        tier_justification succeeds.
        """
        payload = create_requester_payload(
            requester_tier="PUBLIC_INTEREST",
            tier_justification="Newsroom serving the public interest.",
        )
        resp = api.create_requester(payload, TEST_USERS["officer_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["requester_tier"] == "PUBLIC_INTEREST"
        assert data["tier_justification"] == (
            "Newsroom serving the public interest."
        )

    def test_register_with_unknown_tier_rejected(self, api):
        """PRD §3.1: "the tier must be one of `COMMERCIAL`,
        `EDUCATIONAL_NONCOMMERCIAL`, or `PUBLIC_INTEREST`."

        Claim: an unknown tier value fails with ERR_INVALID_INPUT.
        """
        payload = {
            "full_name": "Bad Tier",
            "contact_email": "x@example.test",
            "requester_tier": "GOLD_STAR",
        }
        resp = api.create_requester(payload, TEST_USERS["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


# ===========================================================================
# Requester GET / 404 — PRD §2.4 + §4
# ===========================================================================
class TestRequesterFetch:

    def test_get_nonexistent_requester_404(self, api):
        """PRD §2.4: "A missing path-parameter resource yields
        `ERR_NOT_FOUND` with HTTP 404."

        Claim: GET on a non-existent requester id fails with
        ERR_NOT_FOUND at HTTP 404.
        """
        resp = api.get_requester(
            NON_EXISTENT_UUID, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# PATCH requester / version concurrency — PRD §2.5, §3.1
# ===========================================================================
class TestRequesterPatch:

    def test_patch_with_wrong_version_rejected(self, api):
        """PRD §2.5: "When `version` is supplied and does not match the
        resource's current `version`, the server rejects the call with
        `ERR_VERSION_CONFLICT` and HTTP 409 and makes no state change."

        Claim: PATCH with version != current.version fails with
        ERR_VERSION_CONFLICT.
        """
        requester = create_requester()
        payload = patch_requester_payload(
            version=requester["version"] + 5,
            contact_email="newaddr@example.test",
        )
        resp = api.patch_requester(
            requester["id"], payload,
            make_requester_headers(requester["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_without_version_succeeds_and_increments(self, api):
        """PRD §2.5: "When `version` is omitted from the body, the
        optimistic-concurrency check is skipped and the operation
        proceeds on the current state."
        PRD §2.5: "Successful mutations always increment `version` by
        one and refresh `updated_at` to the moment of the write".

        Claim: PATCH with no version field succeeds, increments version
        by 1.
        """
        requester = create_requester()
        payload = patch_requester_payload(contact_email="updated@example.test")
        resp = api.patch_requester(
            requester["id"], payload,
            make_requester_headers(requester["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["version"] == requester["version"] + 1
        assert data["contact_email"] == "updated@example.test"


# ===========================================================================
# Filing requests — PRD §3.2
# ===========================================================================
class TestFileRequest:

    def test_file_request_returns_intake_status(self, api):
        """PRD §3.2: "A newly filed request lands in `INTAKE` status".

        Claim: POST /foia/requests creates a Request with status=INTAKE,
        fee_estimate_accepted=false, glomar_invoked=false,
        glomar_exemption_basis=[], tolling_days_consumed=0.
        """
        requester = create_requester()
        payload = create_request_payload(requester_id=requester["id"])
        resp = api.create_request(
            payload, make_requester_headers(requester["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_request(data)
        assert data["status"] == "INTAKE"
        assert data["fee_estimate_accepted"] is False
        assert data["fee_waiver_granted"] is None
        assert data["glomar_invoked"] is False
        assert data["glomar_exemption_basis"] == []
        assert data["tolling_days_consumed"] == 0

    def test_file_request_with_unknown_requester_fk(self, api):
        """PRD §2.4: "Any cross-entity reference that fails to resolve
        yields `ERR_FK_NOT_FOUND` with HTTP 404."

        Claim: filing a request with a non-existent requester_id fails
        with ERR_FK_NOT_FOUND.
        """
        # Use a placeholder Requester role — Requester is the only role
        # that may POST /foia/requests per PRD §4, but ownership is not
        # the gating rule here; the FK lookup is.
        payload = create_request_payload(requester_id=NON_EXISTENT_UUID)
        resp = api.create_request(
            payload, make_requester_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


# ===========================================================================
# Acknowledgement — PRD §3.2
# ===========================================================================
class TestAcknowledge:

    def test_acknowledge_intake_request_transitions_to_acknowledged(self, api):
        """PRD §3.2: "An officer subsequently acknowledges the request,
        transitioning it from `INTAKE` to `ACKNOWLEDGED`."
        PRD §3.2: "Acknowledgement sets `filed_at` to the current server
        time".

        Claim: /acknowledge transitions INTAKE -> ACKNOWLEDGED, sets
        filed_at, and computes response_due_at.
        """
        requester = create_requester()
        request = file_request(requester=requester)
        ack = acknowledge_request(request["id"])
        assert ack["status"] == "ACKNOWLEDGED"
        assert ack["filed_at"] is not None
        assert ack["response_due_at"] is not None

    def test_acknowledge_non_intake_request_rejected(self, api):
        """PRD §3.2: "Acknowledgement is permitted only when the request
        is currently in `INTAKE`".

        Claim: a second /acknowledge on an already-acknowledged request
        fails with ERR_INVALID_STATE at HTTP 409.
        """
        requester = create_requester()
        request = file_request(requester=requester)
        acknowledge_request(request["id"])
        resp = api.acknowledge_request(
            request["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
