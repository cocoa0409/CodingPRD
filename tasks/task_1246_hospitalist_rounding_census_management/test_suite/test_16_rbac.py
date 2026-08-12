"""RBAC deny tests: role-permission and ownership-rule failures.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers, build_user_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, create_consult_for,
)

ADMIN = TEST_USERS["group_admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


class TestHospitalistCreateHospitalistUnauthorized:
    """Corner instance: hospitalist_create_hospitalist_unauthorized."""

    def test_hospitalist_cannot_create_hospitalist(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint
        ... is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /hospitalists is authorized for `GroupAdmin` only.

        Design: Corner/rbac/hospitalist_create_hospitalist_unauthorized
        """
        resp = api.create_hospitalist(
            {"full_name": "Rogue", "specialty": "ICU"},
            make_hospitalist_headers("any-id"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestSpecialistGenerateReportUnauthorized:
    """Corner instance: specialist_generate_report_unauthorized."""

    def test_specialist_cannot_generate_report(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint
        ... is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /productivity-reports/generate is authorized for
        `GroupAdmin` only.
        PRD §3.8: "Reporting itself is a `GroupAdmin` function."

        Design: Corner/rbac/specialist_generate_report_unauthorized
        """
        h = create_hospitalist("H One", "ICU")
        resp = api.generate_productivity_report(
            {"hospitalist_id": h["id"], "period_start": "2026-05-01",
             "period_end": "2026-05-31"},
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestGroupAdminAcceptAdmissionUnauthorized:
    """Corner instance: groupadmin_accept_admission_unauthorized."""

    def test_groupadmin_cannot_accept_admission(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint
        ... is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /admissions/{id}/accept is authorized for `Hospitalist`
        only.
        PRD §2.7 item 2 (authorization and ownership) fires before item 8
        (cross-entity offer-ownership).

        Design: Corner/rbac/groupadmin_accept_admission_unauthorized
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="R001", acuity="LOW", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["offered_to_hospitalist_id"] == h1["id"]
        resp = api.accept_admission(a1["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestHospitalistAcknowledgeConsultUnauthorized:
    """Corner instance: hospitalist_acknowledge_consult_unauthorized."""

    def test_hospitalist_cannot_acknowledge(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint
        ... is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /consult-requests/{id}/acknowledge is authorized for
        `ConsultingSpecialist` only.
        PRD §3.7: "Acknowledgement is the `ConsultingSpecialist`'s first
        move".

        Design: Corner/rbac/hospitalist_acknowledge_consult_unauthorized
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="R002", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        admit_and_accept(p1["id"])
        c1 = create_consult_for(p1["id"], h1["id"], "NEUROLOGY", "ROUTINE", "headache")
        resp = api.acknowledge_consult(c1["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        c_now = get_success_data(api.get_consult_request(c1["id"], ADMIN))
        assert c_now["status"] == "OPEN"


class TestMissingAuthHeadersReturns401:
    """Corner instance: missing_auth_headers_returns_401."""

    def test_no_role_header_fails(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD §2.7 item 1 (authentication) fires before any role or business
        check.

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        # Call with no headers at all
        resp = api._request("GET", "/hospitalists", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
