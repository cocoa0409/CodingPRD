"""Role-based access control and request-context guards.

Covers PRD §2.1 (user/role headers) and the per-endpoint role assignments in
the PRD §4 endpoint table.
"""
import pytest

from test_helpers import (
    create_cleared_order,
    create_order_for_plan,
    current_patient_version,
    ingest_adherence_report,
    occ_payload,
    setup_therapy_patient,
    validate_error,
    validate_success,
)


class TestUserContextGuard:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, identifying the role
        under which the user is acting. A request missing either header, or
        carrying a malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        res = api.list_patients(headers={})
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT",
                       expected_status=400)


class TestSegregatedRoleAssignments:
    def test_intake_coordinator_cannot_authorize(
            self, api, intake_coordinator_headers):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.5: "Authorization is a fiscal step performed by a
        `BillingSpecialist`"

        Design: Corner/validations/wrong_role_for_authorize_rejected
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        order = create_cleared_order(patient["id"], ctx["plans"]["FILTER"])
        res = api.authorize_order(
            order["id"], occ_payload(current_patient_version(patient["id"])),
            intake_coordinator_headers)
        validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)

    def test_respiratory_therapist_cannot_authorize(
            self, api, respiratory_therapist_headers):
        """PRD §2.9: "The two steps are also performed by different roles —
        clinical clearance by a `RespiratoryTherapist`, authorization by a
        `BillingSpecialist`"

        Design: Corner/rbac/respiratory_therapist_cannot_authorize
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        order = create_cleared_order(patient["id"], ctx["plans"]["FILTER"],
                                     clearer_id="rt-2")
        res = api.authorize_order(
            order["id"], occ_payload(current_patient_version(patient["id"])),
            respiratory_therapist_headers)
        validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)

    def test_billing_specialist_cannot_clinical_clear(
            self, api, billing_specialist_headers):
        """PRD §3.5: "A `RespiratoryTherapist` performs clinical clearance"
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/billing_specialist_cannot_clinical_clear
        """
        ctx = setup_therapy_patient()
        order = create_order_for_plan(ctx["patient"]["id"], ctx["plans"]["FILTER"])
        res = api.clinical_clear_order(order["id"], billing_specialist_headers)
        validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)

    def test_intake_coordinator_cannot_finalize_adherence(
            self, api, intake_coordinator_headers, respiratory_therapist_headers):
        """PRD §3.4: "A `RespiratoryTherapist` ingests an adherence data
        download" and "Review follows a strict chain."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/intake_coordinator_cannot_finalize_adherence
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=30, compliant_nights=25)
        validate_success(api.begin_review_report(report["id"],
                                                 respiratory_therapist_headers))
        res = api.finalize_report(report["id"], intake_coordinator_headers)
        validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)
