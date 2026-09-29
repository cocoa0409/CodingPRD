"""Authentication precedes every other check, and one envelope covers all 4xx."""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_error_envelope, assert_version_is
from test_helpers.test_users import PLATFORM_ADMIN_USER_ID, UNBOUND_TRIAGE_NURSE


class TestAuthenticationIsCheckedFirst:
    def test_a_read_with_no_headers_at_all_is_unauthenticated(self, world):
        """PRD §2.1: "When either header is absent or empty, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is
        examined."

        Design: Corner/errors/missing_or_malformed_auth_headers_return_unauthenticated
        """
        response = world.api.get_triage_call(NON_EXISTENT_UUID, {})

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert_error_envelope(response, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_an_id_without_a_role_and_a_role_without_an_id_both_fail_at_401(self, world):
        """PRD §2.1: "Every request other than the logical-clock control endpoint must
        present two headers: `X-User-ID`, identifying the acting principal, and
        `X-User-Role`, naming the role that principal is acting in."

        Design: Corner/errors/missing_or_malformed_auth_headers_return_unauthenticated
        """
        role_missing = world.api.create_practice(
            f.practice_payload(name="No Auth Health"),
            {"X-User-ID": PLATFORM_ADMIN_USER_ID},
        )
        id_missing = world.api.list_protocols({"X-User-Role": "PlatformAdmin"}, None)
        role_empty = world.api.list_protocols(
            {"X-User-ID": PLATFORM_ADMIN_USER_ID, "X-User-Role": ""}, None
        )

        validate_error(role_missing, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        validate_error(id_missing, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        validate_error(role_empty, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_an_invalid_body_with_no_headers_is_401_and_not_400(self, world):
        """PRD §2.1: "When either header is absent or empty, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is
        examined."

        Design: Corner/errors/missing_or_malformed_auth_headers_return_unauthenticated
        """
        response = world.api.create_nurse({"full_name": "", "seniority_level": 99}, {})

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert "id" not in (response.json().get("data") or {}), (
            "a rejected create must not leak a minted identifier"
        )


@pytest.fixture
def practice_with_one_fresh_intake_call(world):
    """One practice and one call still sitting at INTAKE."""
    world.set_clock("2026-08-03T14:30:00Z")
    world.create_practice(name="Northside Family Health")
    call = world.open_call(
        caller_name="Dana Reyes",
        caller_phone="+14155550100",
        reason_text="chest discomfort",
    )
    return call


class TestErrorEnvelopeIsUniformAcrossFailureClasses:
    def test_role_rejection_and_not_found_share_the_envelope(
        self, world, practice_with_one_fresh_intake_call
    ):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_is_uniform_when_each_failure_class_is_rejected
        """
        call = practice_with_one_fresh_intake_call

        forbidden = world.api.create_nurse(
            f.nurse_payload(full_name="Nora Vance", seniority_level=3),
            UNBOUND_TRIAGE_NURSE,
        )
        missing = world.api.match_patient(
            call["id"], f.match_patient_payload(NON_EXISTENT_UUID), world.intake
        )

        validate_error(forbidden, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert_error_envelope(forbidden, ApiErrorId.ERR_UNAUTHORIZED)
        validate_error(missing, ApiErrorId.ERR_PATIENT_NOT_FOUND, 404)
        assert_error_envelope(missing, ApiErrorId.ERR_PATIENT_NOT_FOUND)

    def test_a_malformed_body_and_a_bad_state_share_the_envelope(
        self, world, practice_with_one_fresh_intake_call
    ):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/errors/error_envelope_is_uniform_when_each_failure_class_is_rejected
        """
        call = practice_with_one_fresh_intake_call

        malformed = world.api.match_patient(
            call["id"],
            {"patient_id": "not-a-uuid", "match_method": "FINGERPRINT"},
            world.intake,
        )
        wrong_state = world.api.record_consent(
            call["id"], f.consent_payload(), world.intake
        )

        validate_error(malformed, ApiErrorId.ERR_INVALID_REQUEST, 400)
        assert_error_envelope(malformed, ApiErrorId.ERR_INVALID_REQUEST)
        validate_error(wrong_state, ApiErrorId.ERR_CALL_INVALID_STATE, 409)
        assert_error_envelope(wrong_state, ApiErrorId.ERR_CALL_INVALID_STATE)

    def test_none_of_the_four_refusals_touched_the_call(
        self, world, practice_with_one_fresh_intake_call
    ):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format".

        Design: Corner/errors/error_envelope_is_uniform_when_each_failure_class_is_rejected
        """
        call = practice_with_one_fresh_intake_call
        world.api.create_nurse(f.nurse_payload(), UNBOUND_TRIAGE_NURSE)
        world.api.match_patient(
            call["id"], f.match_patient_payload(NON_EXISTENT_UUID), world.intake
        )
        world.api.match_patient(
            call["id"],
            {"patient_id": "not-a-uuid", "match_method": "FINGERPRINT"},
            world.intake,
        )
        world.api.record_consent(call["id"], f.consent_payload(), world.intake)

        after = world.call(call["id"])

        assert after["status"] == "INTAKE"
        assert_version_is(after, 1, "four refusals wrote nothing")
        assert after["patient_id"] is None
        assert after["consent_recorded_at"] is None
        _, meta = validate_paginated(
            world.api.list_triage_calls(world.admin, {"practice_id": world.practice_id})
        )
        assert meta["total_count"] == 1
