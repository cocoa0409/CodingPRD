"""Identity, role authorization, and entity-backed ownership checks."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    ApiErrorId,
    create_float_nurse,
    create_nurse,
    create_report,
    FLOAT_COORD,
    make_staff_nurse_headers,
    propose_assignment,
    REGULATOR,
    setup_unit_with_shift,
    validate_error,
)


class TestUserContext:

    def test_missing_auth_headers_rejected(self):
        """PRD section 2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring
        the capacity in which that user acts. If either header is missing, or
        if the supplied role is not one of the roles declared below, the
        request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api_client.create_unit(
            {"name": "NoAuth", "unit_type": "ICU", "bed_count": 10,
             "incentive_budget_cents": 1000},
            {},  # no X-User-ID / X-User-Role headers at all
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400


class TestOwnership:

    def test_not_owner_accept_rejected(self):
        """PRD section 2.1: "Accepting or declining an assignment is only
        permitted to the nurse named on it: if `X-User-ID` does not equal the
        assignment's `nurse_id`, the request is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/not_owner_accept_rejected
        """
        sc = setup_unit_with_shift(name="ICU R1", census=(4, 0, 0, 0))
        n1 = create_nurse(full_name="Owner One", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=5000,
                          home_unit_id=sc["unit"]["id"])
        n2 = create_nurse(full_name="Intruder Two", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=5000,
                          home_unit_id=sc["unit"]["id"])
        asg = propose_assignment(sc["shift"]["id"], n1["id"],
                                 sc["charge_headers"])
        resp = api_client.accept_assignment(
            asg["id"], make_staff_nurse_headers(n2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert resp.status_code == 403


class TestExclusiveOperations:

    def test_staff_nurse_cannot_create_shift_rejected(self):
        """PRD section 2.1: "If the headers are well-formed but the declared
        role is not permitted to perform the requested operation, the request
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: POST /shifts is authorized for NurseAdmin.

        Design: Corner/rbac/staff_nurse_cannot_create_shift_rejected
        """
        sc = setup_unit_with_shift(name="ICU R2", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Staff Sue", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        resp = api_client.create_shift(
            {"unit_id": sc["unit"]["id"], "shift_date": "2026-08-11",
             "shift_code": "DAY"},
            make_staff_nurse_headers(nurse["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert resp.status_code == 403

    def test_regulator_cannot_submit_report_rejected(self):
        """PRD section 2.1: "If the headers are well-formed but the declared
        role is not permitted to perform the requested operation, the request
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: POST /compliance-reports/{reportId}/submit is
        authorized for NurseAdmin; the Regulator may only return or accept.

        Design: Corner/rbac/regulator_cannot_submit_report_rejected
        """
        report = create_report("2026-08-17")
        resp = api_client.submit_compliance_report(report["id"], REGULATOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_admin_cannot_return_report_rejected(self):
        """PRD section 2.1: "If the headers are well-formed but the declared
        role is not permitted to perform the requested operation, the request
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: POST /compliance-reports/{reportId}/return is
        authorized for Regulator.

        Design: Corner/rbac/admin_cannot_return_report_rejected
        """
        report = create_report("2026-08-18")
        resp = api_client.return_compliance_report(
            report["id"], {"return_reason": "overreach"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_float_coordinator_cannot_create_assignments_rejected(self):
        """PRD section 2.1: "If the headers are well-formed but the declared
        role is not permitted to perform the requested operation, the request
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: POST /shifts/{shiftId}/assignments is authorized for
        ChargeNurse.

        Design: Corner/rbac/float_coordinator_cannot_create_assignments_rejected
        """
        sc = setup_unit_with_shift(name="ICU R3", census=(4, 0, 0, 0))
        f1 = create_float_nurse(full_name="Float Finn", competencies=["ICU"])
        resp = api_client.create_assignment(
            sc["shift"]["id"],
            {"nurse_id": f1["id"],
             "expected_shift_version": sc["shift"]["version"]},
            FLOAT_COORD,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
