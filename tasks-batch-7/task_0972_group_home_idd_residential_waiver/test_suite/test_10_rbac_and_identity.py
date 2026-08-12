"""RBAC, identity resolution, segregation of duties, ownership (PRD 2.1)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    admit_resident,
    create_active_isp,
    create_and_verify_visit,
    create_incident_payload,
    create_isp_draft,
    create_medication_order_payload,
    create_shift_payload,
    get_success_data,
    make_billing_headers,
    make_case_manager_headers,
    make_compliance_headers,
    make_dsp_headers,
    make_qidp_headers,
    set_clock,
    setup_agency,
    setup_agency_with_clinical_staff,
    setup_agency_with_core_staff,
    setup_billable_pipeline,
    setup_claim_for_individual,
    setup_enrolled_individual,
    setup_home,
    setup_staff,
    setup_submitted_claim,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["agency_admin_headers"]
ANY = TEST_USERS["any_headers"]
BILL1 = TEST_USERS["billing_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestMissingAuthHeaders:
    """Auth header presence is checked first (PRD 2.1)."""

    def test_missing_headers_rejected_400(self, api):
        """PRD 2.1: "If either header is missing or empty, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_rejected
        """
        resp = api.create_agency({"name": "Agency A"}, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_missing_role_header_rejected_400(self, api):
        """PRD 2.1: "If either header is missing or empty, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_rejected
        """
        resp = api.create_agency({"name": "Agency A"}, headers={"X-User-ID": "tester-1"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleIdentityMismatch:
    """Entity-backed roles resolve to a matching ACTIVE StaffMember (PRD 2.1)."""

    def test_role_header_disagreeing_with_staff_record_rejected(self, api):
        """PRD 2.1: "The system additionally requires that the resolved
        `StaffMember` be in `ACTIVE` status and that the staff member's
        `staff_role` match the value carried by `X-User-Role`; a mismatch is
        rejected with `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."

        Design: Corner/validations/role_identity_mismatch_forbidden
        """
        agency = setup_agency()
        cm = setup_staff(agency["id"], "CASE_MANAGER", full_name="Casey Manager")
        # DSP role header carrying the CASE_MANAGER staff id.
        resp = api.create_incident(
            create_incident_payload(cm["id"], cm["id"],
                                    description="Identity mismatch probe body"),
            make_dsp_headers(cm["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_IDENTITY_MISMATCH)

    def test_terminated_staff_identity_rejected(self, api):
        """PRD 2.1: "The system additionally requires that the resolved
        `StaffMember` be in `ACTIVE` status" — after termination the same
        X-User-ID fails identity resolution.

        Design: Corner/rbac/terminated_staff_member_cannot_act_forbidden
        """
        base = setup_agency_with_clinical_staff()
        agency, cm, q, d1 = base["agency"], base["cm"], base["q"], base["d1"]
        home = setup_home(agency, certified_bed_count=2)
        ind = setup_enrolled_individual(agency, cm, q)
        set_clock("2026-06-01T00:00:00Z")
        mo = get_success_data(api_client.create_medication_order(
            create_medication_order_payload(ind["id"]),
            make_qidp_headers(q["id"]),
        ))
        get_success_data(api_client.terminate_staff(d1["id"], ADMIN))
        resp = api_client.create_admin_event(
            {"medication_order_id": mo["id"],
             "scheduled_time": "2026-06-02T08:00:00Z",
             "outcome": "GIVEN",
             "administered_time": "2026-06-02T08:05:00Z"},
            make_dsp_headers(d1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_IDENTITY_MISMATCH)

    def test_termination_cancels_future_shifts(self, api):
        """PRD 3.4 (staff workflow): "Termination by an `AgencyAdmin` moves a
        staff member from `ACTIVE` to the terminal state `TERMINATED` and
        cascades: every shift assignment for this staff member in `SCHEDULED`
        or `CONFIRMED` status whose `window_start` is strictly after now
        transitions to `CANCELLED`."

        Design: Corner/rbac/terminated_staff_member_cannot_act_forbidden
        """
        base = setup_agency_with_clinical_staff()
        agency, d1 = base["agency"], base["d1"]
        home = setup_home(agency, certified_bed_count=2)
        set_clock("2026-06-01T00:00:00Z")
        shift = get_success_data(api_client.create_shift(
            create_shift_payload(
                home["id"], d1["id"],
                window_start="2026-06-05T07:00:00Z", window_end="2026-06-05T15:00:00Z",
            ), ADMIN,
        ))
        terminated = get_success_data(api_client.terminate_staff(d1["id"], ADMIN))
        assert terminated["status"] == "TERMINATED"
        shift_after = get_success_data(api_client.get_shift(shift["id"], ANY))
        assert shift_after["status"] == "CANCELLED"


class TestRoleDenials:
    """RBAC matrix denials (PRD 2.1 and endpoint table)."""

    def test_dsp_cannot_create_claim(self, api):
        """PRD 2.1: "If the role named in `X-User-Role` is not permitted for
        the endpoint per the role matrix, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." POST /claims is authorized
        for BillingSpecialist only (PRD endpoint table).

        Design: Corner/rbac/dsp_cannot_create_claim_forbidden
        """
        agency = setup_agency()
        d1 = setup_staff(agency["id"], "DSP", full_name="Dee Spone",
                         certifications=["MED_CERT"])
        resp = api.create_claim(
            {"individual_id": d1["id"],
             "service_period_start": "2026-06-01",
             "service_period_end": "2026-06-02"},
            make_dsp_headers(d1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_case_manager_cannot_approve_isp(self, api):
        """PRD endpoint table: POST /isps/{ispId}/approve is authorized for
        QIDP only; PRD 2.1 rejects other roles with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

        Design: Corner/rbac/case_manager_cannot_approve_isp_forbidden
        """
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        isp = create_isp_draft(ind, base["cm"])
        get_success_data(api_client.submit_isp_review(
            isp["id"], make_case_manager_headers(base["cm"]["id"]),
        ))
        resp = api_client.approve_isp(
            isp["id"], make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        isp_after = get_success_data(api_client.get_isp(isp["id"], ANY))
        assert isp_after["status"] == "PENDING_REVIEW"

    def test_suspend_is_compliance_officer_exclusive(self, api):
        """PRD endpoint table: POST /homes/{homeId}/suspend and /reinstate are
        authorized for ComplianceOfficer only; PRD 2.1 rejects other roles
        with `ERR_INSUFFICIENT_PERMISSIONS`.

        Design: Corner/rbac/suspend_is_compliance_officer_exclusive
        """
        agency = setup_agency()
        home = setup_home(agency, certified_bed_count=2)
        resp = api_client.suspend_home(home["id"], make_billing_headers("bill-1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        suspended = get_success_data(api_client.suspend_home(home["id"], COMPLIANCE))
        assert suspended["status"] == "SUSPENDED"
        reinstated = get_success_data(api_client.reinstate_home(home["id"], COMPLIANCE))
        assert reinstated["status"] == "ACTIVE"


class TestGetEndpointsAllowAnyRole:
    """All GET endpoints are shared across authenticated roles (PRD 2.1)."""

    def test_single_get_succeeds_for_any_authenticated_caller(self, api):
        """PRD 2.1: "The `Any` role denotes that any authenticated caller (any
        of the six preceding roles) may perform the operation - in practice,
        all GET endpoints."

        Design: Corner/rbac/get_endpoints_allow_any_role
        """
        agency = setup_agency()
        home = setup_home(agency, certified_bed_count=2, name="Home A1")
        data = validate_success(api.get_home(home["id"], ANY))
        assert data["name"] == "Home A1"

    def test_filtered_list_honors_agency_filter(self, api):
        """PRD endpoint table: GET /homes is a filtered list; the agency_id
        filter restricts the result set to the named agency.

        Design: Corner/rbac/get_endpoints_allow_any_role
        """
        agency_a = setup_agency(name="Agency A")
        setup_home(agency_a, certified_bed_count=2, name="Home A1")
        setup_home(agency_a, certified_bed_count=3, name="Home A2")
        agency_b = setup_agency(name="Agency B")
        setup_home(agency_b, certified_bed_count=4, name="Home B1")
        _data, meta = validate_paginated(api.list_homes(
            ANY, params={"agency_id": agency_a["id"]},
        ))
        assert meta["total_count"] == 2


class TestClaimSubmitBlockedByHomePosture:
    """Claim submit gated by resident's home posture (PRD 2.11, 3.10)."""

    def _setup_critical_home_with_draft_claim(self, api):
        ctx = setup_billable_pipeline(clock_iso="2026-06-02T08:45:00Z")
        home = setup_home(ctx["agency"], certified_bed_count=2)
        admit_resident(home, ctx["individual"], ctx["cm"], ctx["q"], bed_label="R1-A")
        # CRITICAL incident submitted BEFORE the claim exists (nothing held).
        inc = get_success_data(api_client.create_incident(
            create_incident_payload(
                ctx["individual"]["id"], home["id"],
                category="ELOPEMENT", severity="CRITICAL",
                description="Resident left the home unsupervised",
            ), ctx["d1_headers"],
        ))
        get_success_data(api_client.submit_incident(inc["id"], ctx["d1_headers"]))
        # Now verify a visit and sweep a fresh DRAFT claim.
        create_and_verify_visit(ctx, "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
        claim = setup_claim_for_individual(ctx)
        return ctx, claim

    def test_claim_creation_not_posture_gated(self, api):
        """PRD 2.11: "While a home's posture is `CRITICAL`, two downstream
        operations are blocked: creating a new bed assignment into that home,
        and submitting a billing claim for any resident of that home." Claim
        generation is not in the blocked list.

        Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_by_home_posture
        """
        _ctx, claim = self._setup_critical_home_with_draft_claim(api)
        assert claim["status"] == "DRAFT"

    def test_submit_rejected_while_posture_critical(self, api):
        """PRD 3.10: "Submission is gated by the resident's home posture: if
        the home at which the individual holds an active bed assignment has
        `compliance_posture` equal to `CRITICAL`, submission is rejected with
        `ERR_HOME_POSTURE_CRITICAL` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_by_home_posture
        """
        _ctx, claim = self._setup_critical_home_with_draft_claim(api)
        resp = api_client.submit_claim(claim["id"], make_billing_headers("bill-1"))
        validate_error(resp, ApiErrorId.ERR_HOME_POSTURE_CRITICAL)
        after = get_success_data(api_client.get_claim(claim["id"], ANY))
        assert after["status"] == "DRAFT"
