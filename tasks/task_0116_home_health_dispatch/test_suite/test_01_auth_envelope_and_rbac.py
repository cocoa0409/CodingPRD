"""Auth, RBAC, response envelope, pagination, and existence checks.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination), §2.5
(nested-resource left-to-right validation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_clinician,
    create_clinician_payload,
    create_patient,
    create_patient_payload,
    is_iso8601_timestamp,
    setup_open_episode,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing / malformed headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Either header missing or malformed terminates the
        request with ERR_AUTH_MISSING."

        Claim: a POST with neither header set returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Either header missing or malformed terminates the
        request with ERR_AUTH_MISSING."

        Claim: omitting X-User-ID returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-Role": "IntakeCoordinator"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Either header missing or malformed terminates the
        request with ERR_AUTH_MISSING."

        Claim: omitting X-User-Role returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-ID": "intake-coordinator-001"},
        )
        validate_error(res, "ERR_AUTH_MISSING")


# ===========================================================================
# §2.1 RBAC — role not authorized for endpoint
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "A request whose role is not authorized for the endpoint
    per §1.7 (reflected in §4's table) is rejected with ERR_FORBIDDEN.\""""

    def test_field_clinician_cannot_create_patient(self, api):
        """PRD §4: POST /patients is exclusive to IntakeCoordinator and
        PlatformAdmin.

        Claim: a FieldClinician calling POST /patients returns
        ERR_FORBIDDEN.
        """
        res = api.create_patient(
            create_patient_payload(),
            build_user_headers("clinician-x", "FieldClinician"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_intake_coordinator_cannot_create_clinician(self, api):
        """PRD §4: POST /clinicians is exclusive to PlatformAdmin.

        Claim: an IntakeCoordinator calling POST /clinicians returns
        ERR_FORBIDDEN.
        """
        res = api.create_clinician(
            create_clinician_payload(),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_intake_coordinator_cannot_close_episode(self, api):
        """PRD §4: POST /episodes/{episodeId}/close is exclusive to
        BillingSpecialist.

        Claim: an IntakeCoordinator calling close returns ERR_FORBIDDEN.
        """
        _, _, episode = setup_open_episode()
        res = api.close_episode(
            episode["id"],
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_billing_specialist_cannot_create_visit(self, api):
        """PRD §4: POST /episodes/{episodeId}/visits is exclusive to
        IntakeCoordinator.

        Claim: a BillingSpecialist calling schedule-visit returns
        ERR_FORBIDDEN.
        """
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        res = api.create_visit(
            episode["id"],
            {
                "clinician_id": clinician["id"],
                "visit_type": "SN",
                "visit_date": episode["start_date"],
                "start_minute": 480,
                "end_minute": 540,
            },
            TEST_USERS["billing_specialist_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_intake_coordinator_cannot_advance_clock(self, api):
        """PRD §4: POST /_clock/advance is exclusive to PlatformAdmin.

        Claim: an IntakeCoordinator advancing the clock returns
        ERR_FORBIDDEN.
        """
        res = api.clock_advance(
            {"target_date": "2026-12-31"},
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: all 2xx and 4xx responses follow a standard envelope."""

    def test_success_envelope_carries_meta_and_data(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body".
        PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."

        Claim: a successful POST /patients returns a body with meta,
        response_type=='object', and an api_request_id beginning with
        req_.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["intake_coordinator_headers"],
        )
        assert res.status_code == 201
        body = res.json()
        assert "meta" in body
        assert "api_request_id" in body["meta"]
        rid = body["meta"]["api_request_id"]
        assert isinstance(rid, str) and rid.startswith("req_"), (
            "PRD §2.2: api_request_id is a server-generated unique "
            "identifier for the request that starts with req_, "
            f"got {rid!r}"
        )
        assert "api_request_timestamp" in body["meta"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict)

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: error responses carry "response_type: error" with
        data containing error_id and message.

        Claim: a 401 ERR_AUTH_MISSING response carries error_id and
        message inside data.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: list endpoints support limit (default 10, min 1, max 100)
    and offset (default 0)."""

    def test_list_patients_pagination_meta(self, api):
        """PRD §2.3: "The meta object on a list response includes limit,
        offset, total_count, and has_more in addition to the standard
        envelope fields."

        Claim: GET /patients returns meta with limit, offset,
        total_count, and has_more.
        """
        for _ in range(3):
            create_patient()
        data, meta = validate_paginated(
            api.list_patients(TEST_USERS["intake_coordinator_headers"]),
        )
        assert isinstance(data, list)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"missing pagination key {key}"

    def test_list_patients_limit_default_10(self, api):
        """PRD §2.3: "The limit parameter caps the number of items
        returned and defaults to 10".

        Claim: an unpaginated GET /patients returns at most 10 results
        and meta.limit == 10.
        """
        for _ in range(2):
            create_patient()
        data, meta = validate_paginated(
            api.list_patients(TEST_USERS["intake_coordinator_headers"]),
        )
        assert meta["limit"] == 10
        assert len(data) <= 10

    def test_list_patients_explicit_limit_and_offset(self, api):
        """PRD §2.3: "The limit parameter caps the number of items
        returned and defaults to 10, with a minimum of 1 and a maximum
        of 100. The offset parameter skips that many items from the
        beginning of the result set and defaults to 0."

        Claim: explicit limit and offset are honoured in meta.
        """
        for _ in range(3):
            create_patient()
        data, meta = validate_paginated(api.list_patients(
            TEST_USERS["intake_coordinator_headers"],
            params={"limit": 1, "offset": 0},
        ))
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert len(data) <= 1


# ===========================================================================
# §2.5 Nested-resource validation
# ===========================================================================
class TestExistence:
    """PRD §2.5: "The server validates path identifiers strictly
    left-to-right and stops on the first one that does not resolve,
    returning ERR_NOT_FOUND for that identifier.\""""

    def test_get_nonexistent_patient_returns_not_found(self, api):
        """PRD §2.5: missing path-parameter resource → ERR_NOT_FOUND.

        Claim: GET /patients/{nonexistent} returns ERR_NOT_FOUND.
        """
        res = api.get_patient(
            NON_EXISTENT_UUID,
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_nonexistent_episode_returns_not_found(self, api):
        """PRD §2.5: missing path-parameter resource → ERR_NOT_FOUND.

        Claim: GET /episodes/{nonexistent} returns ERR_NOT_FOUND.
        """
        res = api.get_episode(
            NON_EXISTENT_UUID,
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_nested_left_to_right_patient_missing_before_oasis(self, api):
        """PRD §2.5: "A request that references a missing patient will
        surface the patient-level miss before the server attempts to
        load the OASIS, even if the OASIS identifier is itself
        fabricated."

        Claim: GET /patients/{nonexistent}/oasis/{nonexistent} returns
        ERR_NOT_FOUND (resolved at the patient level).
        """
        res = api.get_oasis(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")
