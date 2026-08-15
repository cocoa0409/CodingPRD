"""Authentication, authorization, ownership, and validation-order rungs
(PRD §2.1, §2.8)."""

from test_helpers import (
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, ApiErrorId,
    create_funder_report_payload,
    register_client, create_staff_member, open_case, grant_consent,
    create_partner_org, create_draft_referral, send_referral,
    create_draft_assessment, submit_assessment, staff_headers,
    partner_headers, client_headers, make_funder_auditor_headers,
    create_funder_report,
)

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this list, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.list_clients(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unknown_role_returns_unauthenticated(self):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this list, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.list_clients(
            headers={"X-User-ID": "someone", "X-User-Role": "SuperUser"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestExistenceBeforeState:
    def test_existence_checked_before_state(self):
        """PRD §2.8: "When a request violates several rules at once, the error it
        receives is determined by a fixed precedence ladder; the first failing
        rung decides the response."
        PRD §2.8: "3. **Existence** — path identifiers (`client_id`, `staff_id`,
        `organization_id`, `case_id`, `assessment_id`, `plan_id`, `note_id`,
        `consent_id`, `referral_id`, `appointment_id`, `program_id`,
        `enrollment_id`, `session_id`, `wk_enrollment_id`, `screening_id`,
        `report_id`) are resolved first, then identifiers referenced in the body,
        validated left to right (in the order `client_id`, `assigned_manager_id`,
        `organization_id`, `room_id`, `case_id`, `program_id`, `session_id`,
        `advocate_id`, `referral_id`, `household_head_id` as they apply); the
        first unknown id yields `ERR_NOT_FOUND`."

        Design: Corner/validations/existence_checked_before_state
        """
        mgr = create_staff_member()
        resp = api_client.send_referral(NON_EXISTENT_UUID, staff_headers(mgr))
        data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert data["error_id"] == "ERR_NOT_FOUND"


class TestPartnerOrgOwnership:
    def test_partner_org_cannot_respond_to_other_orgs_referral(self):
        """PRD §2.1: "When `X-User-Role` is `PartnerOrg`, `X-User-ID` is the `id`
        of the acting `Organization`, and a partner may read or respond only to
        referrals whose `organization_id` equals its own `X-User-ID`."
        PRD §3.5: "a mismatch between the referral's `organization_id` and the
        actor's `X-User-ID` is `ERR_FORBIDDEN`"

        Design: Corner/rbac/partner_org_cannot_respond_to_other_orgs_referral
        """
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org_x = create_partner_org(name="Org PX", categories=("LEGAL",), email="px@org.test")
        org_y = create_partner_org(name="Org PY", categories=("LEGAL",), email="py@org.test")
        ref = create_draft_referral(case, org_x, "LEGAL", mgr)
        send_referral(ref["id"], mgr)

        resp = api_client.respond_referral(ref["id"], {"decision": "ACCEPTED"},
                                           partner_headers(org_y))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api_client.get_referral(ref["id"], staff_headers(mgr)))
        assert after["status"] == "SENT", "a foreign partner's respond must not move the referral"


class TestClientOwnership:
    def test_client_reads_only_own_case(self):
        """PRD §2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of
        the acting `Client`; the client may read only its own record, its own
        cases, and its own consents, and may revoke a consent only when that
        consent's `client_id` equals `X-User-ID`."
        PRD §2.1: "When a properly authenticated role attempts an operation that
        role is not permitted to perform, or fails an ownership rule attached to
        the resource, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/client_reads_only_own_case
        """
        mgr = create_staff_member()
        client1 = register_client(full_name="Rima One")
        client2 = register_client(full_name="Rima Two")
        case1 = open_case(client1, mgr)
        case2 = open_case(client2, mgr)

        own = validate_success(api_client.get_case(case1["id"], client_headers(client1)))
        assert own["id"] == case1["id"]
        resp = api_client.get_case(case2["id"], client_headers(client1))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestExclusiveOperations:
    def test_intake_specialist_cannot_verify_assessment(self):
        """PRD §3.3: "a `CaseManager` or `CenterAdmin` verifies a `SUBMITTED`
        assessment"
        PRD §2.1: "When a properly authenticated role attempts an operation that
        role is not permitted to perform, or fails an ownership rule attached to
        the resource, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/intake_specialist_cannot_verify_assessment
        """
        mgr = create_staff_member(full_name="Mgr One")
        intake = create_staff_member(role_level="INTAKE", clearance_level=1, full_name="Intake I")
        client = register_client()
        case = open_case(client, mgr)
        asmt = create_draft_assessment(case, mgr, score=1)
        submit_assessment(asmt, mgr)

        resp = api_client.verify_assessment(asmt["id"], staff_headers(intake))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api_client.get_assessment(asmt["id"], staff_headers(mgr)))
        assert after["status"] == "SUBMITTED"

    def test_case_manager_cannot_seal_case(self):
        """PRD §3.2: "moving a case from `STANDARD` or `RESTRICTED` to `SEALED` is
        reserved to a `CenterAdmin` — any other role receives `ERR_FORBIDDEN`"
        PRD §3.2: "A `CaseManager` or `CenterAdmin` may move `STANDARD` to
        `RESTRICTED` and back"

        Design: Corner/rbac/case_manager_cannot_seal_case
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)

        ok = validate_success(api_client.set_case_privacy(
            case["id"], {"to_posture": "RESTRICTED", "reason": "sensitive"},
            staff_headers(mgr)))
        assert ok["privacy_posture"] == "RESTRICTED"

        resp = api_client.set_case_privacy(
            case["id"], {"to_posture": "SEALED", "reason": "court order"},
            staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api_client.get_case(case["id"], staff_headers(mgr)))
        assert after["privacy_posture"] == "RESTRICTED", "a denied seal must not move the posture"

    def test_auditor_exclusive_review_and_staff_denied(self):
        """PRD §3.9: "Review belongs to the `FunderAuditor`, whose `decision` of
        `ACCEPTED` or `RETURNED` is valid only against a `SUBMITTED` report and
        stamps `reviewed_by_id`."
        PRD §2.1: "When a properly authenticated role attempts an operation that
        role is not permitted to perform, or fails an ownership rule attached to
        the resource, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/auditor_exclusive_review_and_staff_denied
        """
        report = create_funder_report()
        submitted = validate_success(api_client.submit_funder_report(report["id"], ADMIN))
        assert submitted["status"] == "SUBMITTED"

        # CenterAdmin may not review.
        resp = api_client.review_funder_report(report["id"], {"decision": "ACCEPTED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        # FunderAuditor may not create clients.
        resp2 = api_client.create_client(
            {"full_name": "Vida Client", "preferred_language": "tw",
             "date_of_birth": "1997-07-07"}, make_funder_auditor_headers())
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)
        # The auditor's own review succeeds.
        accepted = validate_success(api_client.review_funder_report(
            report["id"], {"decision": "ACCEPTED"}, make_funder_auditor_headers()))
        assert accepted["status"] == "ACCEPTED"
