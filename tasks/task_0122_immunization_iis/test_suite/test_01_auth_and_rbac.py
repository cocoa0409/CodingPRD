"""Auth headers, role validity, RBAC, and not-found existence checks.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination), §2.5
(left-to-right existence), §2.6 (priority cascade: auth -> existence
-> state -> safety -> business).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_patient,
    create_patient_payload,
    create_provider_organization,
    create_vaccine_product_payload,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth headers - missing or empty
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "If either header is absent the server responds
        with ERR_AUTH_HEADER_MISSING."

        Claim: a request with neither header set returns
        ERR_AUTH_HEADER_MISSING.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        validate_error(res, "ERR_AUTH_HEADER_MISSING")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is absent the server responds
        with ERR_AUTH_HEADER_MISSING."

        Claim: omitting X-User-ID returns ERR_AUTH_HEADER_MISSING.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-Role": "PublicHealthOfficer"},
        )
        validate_error(res, "ERR_AUTH_HEADER_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is absent the server responds
        with ERR_AUTH_HEADER_MISSING."

        Claim: omitting X-User-Role returns ERR_AUTH_HEADER_MISSING.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-ID": "any-id"},
        )
        validate_error(res, "ERR_AUTH_HEADER_MISSING")


# ===========================================================================
# §2.1 Invalid role values
# ===========================================================================
class TestAuthHeaderInvalid:
    """PRD §2.1: invalid role -> ERR_AUTH_HEADER_INVALID."""

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: "If X-User-Role is not one of the four declared
        roles, the server responds with ERR_AUTH_HEADER_INVALID."

        Claim: a role outside the four-element set returns
        ERR_AUTH_HEADER_INVALID.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={
                "X-User-ID": "u-1",
                "X-User-Role": "Admin",
            },
        )
        validate_error(res, "ERR_AUTH_HEADER_INVALID")

    def test_misspelled_role_rejected(self, api):
        """PRD §2.1: "If X-User-Role is not one of the four declared
        roles, the server responds with ERR_AUTH_HEADER_INVALID."

        Claim: a typo'd role returns ERR_AUTH_HEADER_INVALID.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={
                "X-User-ID": "u-1",
                "X-User-Role": "providerclinician",
            },
        )
        validate_error(res, "ERR_AUTH_HEADER_INVALID")


# ===========================================================================
# §2.1 RBAC - role recognised but not permitted -> ERR_FORBIDDEN
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "If the role is recognised but is not permitted to
    invoke the requested endpoint, the server responds with
    ERR_FORBIDDEN."
    """

    def test_school_registrar_cannot_create_vaccine_product(self, api):
        """PRD §4: POST /vaccine-products restricted to PublicHealthOfficer.
        PRD §3.2: "Only PublicHealthOfficer may register a new product
        or view the broad listing of products by antigen or by status."

        Claim: SchoolRegistrar posting to /vaccine-products yields
        ERR_FORBIDDEN.
        """
        res = api.create_vaccine_product(
            create_vaccine_product_payload(),
            TEST_USERS["school_registrar_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_school_registrar_cannot_administer_dose(self, api):
        """PRD §2.1: "SchoolRegistrar - school staff who create, issue,
        and revoke school enrollment certificates; cannot administer
        doses."

        Claim: SchoolRegistrar posting to /administer yields
        ERR_FORBIDDEN (in path order, RBAC check occurs before path
        existence; but to be safe we use a real dose path that still
        runs RBAC first per PRD §2.6).
        """
        ctx = setup_basic_scenario()
        # Schedule a dose first
        from test_helpers import schedule_dose
        dose = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
        )
        res = api.administer_dose(
            ctx["patient"]["id"], dose["id"],
            {"administered_at": "2026-01-01T00:00:00.000Z"},
            TEST_USERS["school_registrar_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_provider_clinician_cannot_recall_lot(self, api):
        """PRD §4: POST /vaccine-lots/{lot_id}/recall restricted to
        PublicHealthOfficer.
        PRD §3.5: "A PublicHealthOfficer issues a recall against a
        lot..."

        Claim: ProviderClinician posting to /recall yields ERR_FORBIDDEN.
        """
        ctx = setup_basic_scenario()
        res = api.recall_vaccine_lot(
            ctx["lot"]["id"], {"reason": "MANUFACTURER_DEFECT"},
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_provider_clinician_cannot_create_certificate(self, api):
        """PRD §4: POST /patients/.../certificates restricted to
        SchoolRegistrar.

        Claim: ProviderClinician posting to /certificates yields
        ERR_FORBIDDEN.
        """
        patient = create_patient()
        res = api.create_certificate(
            patient["id"], {"school_year": "2026-2027", "grade_level": "K"},
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_reviewing_clinician_cannot_schedule_dose(self, api):
        """PRD §4: POST /patients/{id}/doses restricted to ProviderClinician.

        Claim: ReviewingClinician posting to /doses yields ERR_FORBIDDEN.
        """
        ctx = setup_basic_scenario()
        res = api.schedule_dose(
            ctx["patient"]["id"],
            {
                "vaccine_product_id": ctx["product"]["id"],
                "lot_id": ctx["lot"]["id"],
                "provider_organization_id": ctx["provider_org"]["id"],
                "administering_clinician_id": "any-clinician",
            },
            TEST_USERS["reviewing_clinician_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.5 Existence path order (left-to-right)
# ===========================================================================
class TestPathExistence:
    """PRD §2.5: "The server validates path parameters strictly
    left-to-right. The patient_id is checked first..."
    """

    def test_get_nonexistent_patient_returns_patient_not_found(self, api):
        """PRD §2.5: "a non-existent patient yields ERR_PATIENT_NOT_FOUND
        before the system attempts to find the dose."

        Claim: GET /patients/{nonexistent} -> ERR_PATIENT_NOT_FOUND.
        """
        res = api.get_patient(
            NON_EXISTENT_UUID,
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_PATIENT_NOT_FOUND")

    def test_get_dose_under_nonexistent_patient_returns_patient_not_found(
        self, api,
    ):
        """PRD §2.5: "a non-existent patient yields ERR_PATIENT_NOT_FOUND
        before the system attempts to find the dose."

        Claim: GET /patients/{bad}/doses/{bad} -> ERR_PATIENT_NOT_FOUND,
        NOT ERR_DOSE_NOT_FOUND.
        """
        res = api.get_dose(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_PATIENT_NOT_FOUND")

    def test_get_dose_with_real_patient_bad_dose_returns_dose_not_found(
        self, api,
    ):
        """PRD §2.5: "Only when the parent is confirmed does the server
        resolve the child segment; a missing dose under a real patient
        yields ERR_DOSE_NOT_FOUND."

        Claim: GET /patients/{real}/doses/{bad} -> ERR_DOSE_NOT_FOUND.
        """
        patient = create_patient()
        res = api.get_dose(
            patient["id"], NON_EXISTENT_UUID,
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_DOSE_NOT_FOUND")

    def test_recall_nonexistent_lot_returns_lot_not_found(self, api):
        """PRD §2.5 / §5: "ERR_LOT_NOT_FOUND" for missing VaccineLot."

        Claim: POST /vaccine-lots/{bad}/recall ->
        ERR_LOT_NOT_FOUND.
        """
        res = api.recall_vaccine_lot(
            NON_EXISTENT_UUID, {"reason": "MANUFACTURER_DEFECT"},
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_LOT_NOT_FOUND")

    def test_get_nonexistent_vaccine_product(self, api):
        """PRD §2.5: "to product_id (ERR_PRODUCT_NOT_FOUND)."

        Claim: GET /vaccine-products/{bad} -> ERR_PRODUCT_NOT_FOUND.
        """
        res = api.get_vaccine_product(
            NON_EXISTENT_UUID,
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_PRODUCT_NOT_FOUND")

    def test_get_nonexistent_adverse_event(self, api):
        """PRD §2.5: "to an adverse-event id (ERR_ADVERSE_EVENT_NOT_FOUND)."

        Claim: GET /adverse-events/{bad} -> ERR_ADVERSE_EVENT_NOT_FOUND.
        """
        res = api.get_adverse_event(
            NON_EXISTENT_UUID,
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_ADVERSE_EVENT_NOT_FOUND")

    def test_get_nonexistent_provider_organization(self, api):
        """PRD §2.5: "to a provider-organization id (ERR_PROVIDER_NOT_FOUND)."

        Claim: GET /provider-organizations/{bad} ->
        ERR_PROVIDER_NOT_FOUND.
        """
        res = api.get_provider_organization(
            NON_EXISTENT_UUID,
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_PROVIDER_NOT_FOUND")


# ===========================================================================
# §2.6 Priority cascade: auth wins over RBAC wins over existence
# ===========================================================================
class TestValidationPriority:
    """PRD §2.6: "Lower-numbered checks shield higher-numbered ones
    from being reached at all."
    """

    def test_missing_header_takes_priority_over_forbidden(self, api):
        """PRD §2.6: "if a request both lacks a header and would also
        fail RBAC, the response is ERR_AUTH_HEADER_MISSING, not
        ERR_FORBIDDEN."

        Claim: missing headers on an endpoint a role would also be
        forbidden from yields ERR_AUTH_HEADER_MISSING, not
        ERR_FORBIDDEN.
        """
        # /vaccine-products is restricted to PublicHealthOfficer.
        # Send NO headers at all; the auth check wins.
        res = api.create_vaccine_product(
            create_vaccine_product_payload(), headers={},
        )
        validate_error(res, "ERR_AUTH_HEADER_MISSING")


# ===========================================================================
# §2.2 / §2.3 Response envelope + pagination
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2 / §2.3 envelope and pagination."""

    def test_create_patient_returns_201_envelope(self, api):
        """PRD §4: "New-resource creation endpoints return HTTP 201."

        Claim: POST /patients returns 201 and envelope shape.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert isinstance(data, dict), "data must be object on create"
        assert "id" in data, "created Patient must carry id"

    def test_list_patients_pagination_envelope(self, api):
        """PRD §2.3: "The meta object on every list response carries
        limit, offset, total_count, and has_more."

        Claim: GET /patients returns a paginated envelope with the
        four meta fields.
        """
        create_patient()
        res = api.list_patients(
            TEST_USERS["public_health_officer_headers"],
            params={"limit": 5, "offset": 0},
        )
        data, meta = validate_paginated(res)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta["limit"] == 5
        assert meta["offset"] == 0
