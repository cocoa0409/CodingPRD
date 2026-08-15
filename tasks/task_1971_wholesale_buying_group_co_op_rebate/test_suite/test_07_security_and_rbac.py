"""Security and segregation-of-duties: user-context validation, role
authorization, body referential integrity, and member ownership checks.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    bootstrap_coop,
    create_active_member,
    create_onboarded_supplier,
    create_open_program,
    enroll_member,
    submit_report,
    create_distribution_for_current_quarter,
    calculate_distribution,
    approve_distribution,
    open_accepted_audit,
    create_supplier,
    make_member_rep_headers,
    make_supplier_rep_headers,
)


class TestUserContext:
    def test_missing_auth_headers_rejected(self, api, admin_headers):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming that
        principal's role. A request in which either header is missing or
        malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`
        (HTTP 400)."

        A request sent with neither header fails user-context validation.

        Design: Corner/validations/missing_auth_headers_rejected
        """
        bootstrap_coop()
        resp = api.list_members({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


class TestRoleAuthorization:
    def test_err_forbidden_trigger(self, api, admin_headers):
        """PRD §2.1: "Once the headers are accepted, the role is checked
        against the endpoint's authorization list (see §4); a principal
        whose role is not permitted for the endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /coop/members is authorized for CoopAdmin only.

        A MemberRep — even a well-formed, entity-backed one — cannot enroll
        a new member retailer.

        Design: Corner/errors/err_forbidden_trigger
        """
        bootstrap_coop()
        member = create_active_member()
        resp = api.create_member(
            {"legal_name": "BadActor", "commitment_level": "STANDARD"},
            make_member_rep_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_supplierrep_cannot_disburse_distribution(
        self, api, admin_headers, finance_headers
    ):
        """PRD §4: POST /coop/distributions/{id}/disburse is authorized for
        FinanceOfficer only.
        PRD §2.1: "a principal whose role is not permitted for the endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/supplierrep_cannot_disburse_distribution
        """
        bootstrap_coop()
        supplier = create_onboarded_supplier()
        distribution = create_distribution_for_current_quarter()
        calculated = calculate_distribution(distribution)
        get_success_data(api.approve_distribution(calculated["id"], finance_headers))
        resp = api.disburse_distribution(
            calculated["id"], make_supplier_rep_headers(supplier["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_distribution(calculated["id"], finance_headers))
        assert after["status"] == "APPROVED"

    def test_programauditor_cannot_churn_member(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §4: POST /coop/members/{id}/churn is authorized for CoopAdmin
        only.
        PRD §2.1: "a principal whose role is not permitted for the endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        The churn attempt is rejected and the member is untouched.

        Design: Corner/rbac/programauditor_cannot_churn_member
        """
        bootstrap_coop()
        member = create_active_member()
        resp = api.churn_member(member["id"], auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_member(member["id"], admin_headers))
        assert after["status"] == "ACTIVE"

    def test_financeofficer_cannot_resolve_audit(
        self, api, admin_headers, finance_headers
    ):
        """PRD §4: POST /coop/volume-audits/{id}/resolve is authorized for
        ProgramAuditor only.
        PRD §2.1: "a principal whose role is not permitted for the endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        The resolve attempt by finance is rejected and the audit stays
        ACCEPTED.

        Design: Corner/rbac/financeofficer_cannot_resolve_audit
        """
        scenario = {}
        bootstrap_coop()
        member = create_active_member()
        supplier = create_onboarded_supplier()
        program = create_open_program(
            supplier, program_code="P-RBAC",
            tier_schedule=[{"min_qty": 0, "rate_bps": 100}],
        )
        enrollment = enroll_member(member, program)
        report = submit_report(enrollment, member, 0, 5, 5000)
        audit = open_accepted_audit(report, member)

        resp = api.resolve_audit(
            audit["id"], {"audited_qty": 5, "audited_cents": 5000}, finance_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_volume_audit(audit["id"], admin_headers))
        assert after["status"] == "ACCEPTED"


class TestReferentialIntegrity:
    def test_enrollment_with_nonexistent_member_returns_reference_not_found(
        self, api, admin_headers
    ):
        """PRD §3.4: "A `CoopAdmin` or a `MemberRep` submits a payload
        containing the `member_id` and the `program_id`; both references
        must resolve, or the request fails with `ERR_REFERENCE_NOT_FOUND`
        (HTTP 422)."

        Design: Corner/errors/err_reference_not_found_trigger
        """
        bootstrap_coop()
        supplier = create_onboarded_supplier()
        program = create_open_program(supplier, program_code="P-REF")
        resp = api.create_enrollment(
            {"member_id": NON_EXISTENT_UUID, "program_id": program["id"]},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


class TestMemberOwnership:
    def test_memberrep_cannot_act_on_other_members_report(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §2.1: "When `X-User-Role` is `MemberRep`, `X-User-ID` is the
        `id` of the acting `Member`; ownership checks on any resource that
        references a `Member` compare the resource's member foreign-key
        field to `X-User-ID`, and a mismatch on a member-scoped operation is
        rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §3.4: "The response is a revision, which only the member's own
        `MemberRep` may file: the role check fails with `ERR_FORBIDDEN`, and
        the ownership check — the caller's `X-User-ID` must equal the `id`
        of the member that owns the report — fails with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/memberrep_cannot_act_on_other_members_report
        """
        bootstrap_coop()
        m1 = create_active_member("M1")
        m2 = create_active_member("M2")
        supplier = create_onboarded_supplier()
        program = create_open_program(
            supplier, program_code="P-OWN",
            tier_schedule=[{"min_qty": 0, "rate_bps": 100}],
        )
        e1 = enroll_member(m1, program)
        report = submit_report(e1, m1, 0, 5, 5000)
        get_success_data(api.flag_purchase_report(report["id"], auditor_headers))

        resp = api.revise_purchase_report(
            report["id"],
            {"self_report_qty": 8, "self_report_cents": 8000},
            make_member_rep_headers(m2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        old_after = get_success_data(api.get_purchase_report(report["id"], auditor_headers))
        assert old_after["status"] == "FLAGGED", "rejected revision must not supersede"
