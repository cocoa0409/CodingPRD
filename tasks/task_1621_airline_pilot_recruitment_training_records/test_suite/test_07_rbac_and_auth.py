"""Authentication, role authorization, and entity-backed identity checks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_applicant,
    make_check_airman_headers,
    make_checkride,
    make_instructor,
    make_pilot_headers,
    set_clock,
    setup_enrollment_at_checkride_phase,
    validate_error,
    validate_success,
)

REC = TEST_USERS["recruiter_headers"]


class TestAuthentication:
    def test_missing_auth_headers_return_401(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the acting
        role."
        PRD §2.1: "A request with missing headers or an unrecognized role is
        rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/missing_auth_headers_return_401
        """
        resp = api.list_applicants({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_recruiter_cannot_run_ops_scan(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        list — or that fails a role-specific identity check — is rejected with
        `ERR_FORBIDDEN_ROLE` (403)."
        PRD §4: POST /pilot-training/_ops/run-daily-scan is authorized for
        SystemAdmin only.

        Design: Corner/rbac/recruiter_cannot_run_ops_scan
        """
        resp = api.run_daily_scan(REC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_pilot_cannot_read_another_applicant(self, api):
        """PRD §2.1: "When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of
        the acting Applicant; ownership checks compare the resource's applicant
        reference — or the applicant id in the path — to `X-User-ID`, so a
        Pilot may read only their own applicant record, submit bids only under
        their own `applicant_id`, withdraw only their own bids, and withdraw
        only their own application."
        PRD §2.1: "A request whose role is not in the endpoint's authorized
        list — or that fails a role-specific identity check — is rejected with
        `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/pilot_cannot_read_another_applicant
        """
        ap_a = make_applicant("own@x.com", "L460", full_name="Own Er")
        ap_b = make_applicant("oth@x.com", "L461", full_name="Oth Er")
        pilot = make_pilot_headers(ap_a["id"])

        resp = api.get_applicant(ap_b["id"], pilot)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        own = validate_success(api.get_applicant(ap_a["id"], pilot))
        assert own["id"] == ap_a["id"], "A Pilot reads their own record"

    def test_check_airman_cannot_record_others_ride(self, api):
        """PRD §2.1: "When `X-User-Role` is `CheckAirman`, `X-User-ID` is the
        `id` of the acting Instructor; identity checks compare it to the
        `check_airman_id` of the checkride being recorded, so a check airman
        may record an outcome only on a ride assigned to them."
        PRD §3.5: "Outcome recording is performed by the assigned check airman:
        the acting `CheckAirman`'s identity must equal the checkride's
        `check_airman_id`, otherwise `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/check_airman_cannot_record_others_ride
        """
        ctx = setup_enrollment_at_checkride_phase(
            eq_kwargs={"code": "FK06", "sim_rate": 38000, "ioe_hours": 8},
            ap_kwargs={"email": "ro@x.com", "license_number": "L462",
                       "full_name": "Rid Own"},
            instructor_name="Ins One")
        assigned = make_instructor("Ins Two", "CHECK_AIRMAN")
        other = make_instructor("Ins Three", "CHECK_AIRMAN")
        ck = make_checkride(ctx["enrollment"]["id"], assigned["id"],
                            scheduled_at="2026-08-12T09:00:00Z")
        set_clock("2026-08-12T09:00:00Z")
        # A different, otherwise clean CHECK_AIRMAN may not record the ride.
        resp = api.record_checkride_outcome(
            ck["id"], {"outcome": "PASS"}, make_check_airman_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
