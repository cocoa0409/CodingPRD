"""Authentication, role authorization, ownership gates, and duty segregation."""
from test_helpers import (
    TIER2_EXPOSURE,
    TEST_USERS,
    create_approved_firm,
    create_budget_payload,
    create_deadline,
    create_engagement_payload,
    create_matter_payload,
    create_settlement_under_review,
    create_staff_user,
    create_staff_user_payload,
    create_tier2_policy,
    fresh_matter_version,
    get_success_data,
    make_counsel_headers,
    make_dgc_headers,
    make_fin_headers,
    make_ops_headers,
    setup_active_matter,
    setup_staffing_matter,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId, MatterStatus

OPS = TEST_USERS["ops_headers"]


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in which
        they act. A request with a missing or malformed header, or whose `X-User-Role`
        does not name one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_matters(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_litigation_counsel_cannot_approve_budget(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized list is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: budget approve is authorized for FinanceBusinessPartner only.

        Design: Corner/rbac/litigation_counsel_cannot_approve_budget
        """
        ctx = setup_staffing_matter()
        version = fresh_matter_version(ctx["matter_id"], ctx["counsel"])
        budget = get_success_data(api.create_budget(
            ctx["matter_id"],
            create_budget_payload(expected_matter_version=version), ctx["counsel"]))
        get_success_data(api.submit_budget(budget["id"], ctx["counsel"]))

        resp = api.approve_budget(budget["id"], ctx["counsel"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_finance_cannot_create_matter(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized list is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: matter intake is authorized for LitigationCounsel only.

        Design: Corner/rbac/finance_cannot_create_matter
        """
        fin = create_staff_user("Fin Finance", "fin@corp.example", "FINANCE")
        resp = api.create_matter(
            create_matter_payload(owning_counsel_id=fin["id"]),
            make_fin_headers(fin["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_legal_ops_cannot_approve_settlement(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized list is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: settlement approve is authorized for DeputyGeneralCounsel,
        GeneralCounsel, ChiefFinancialOfficer, and BoardCommittee only.

        Design: Corner/rbac/legal_ops_cannot_approve_settlement
        """
        ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
        create_tier2_policy(ctx)
        create_settlement_under_review(ctx, proposed_amount_cents=5_000_000)
        ops_user = create_staff_user("Ops Oliver", "ops@corp.example", "OPERATIONS")

        resp = api.approve_settlement(ctx["sr_id"], make_ops_headers(ops_user["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_owner_gate_non_owner_counsel_rejected(self, api):
        """PRD §3.1: "The transition requires that all three exposure fields are set
        and that the high end is at least the low end, and it is owner-gated: the
        acting user's `X-User-ID` must equal the matter's `owning_counsel_id`, failing
        which the call is rejected with `ERR_NOT_MATTER_OWNER`."

        Design: Corner/rbac/owner_gate_non_owner_counsel_rejected
        """
        owner = create_staff_user("Casey A", "a@corp.example", "LEGAL")
        other = create_staff_user("Blair B", "b@corp.example", "LEGAL")
        matter = get_success_data(api.create_matter(
            create_matter_payload(owning_counsel_id=owner["id"],
                                  exposure_low_cents=1_000_000,
                                  exposure_high_cents=4_000_000,
                                  probability_of_loss_pct=60),
            make_counsel_headers(owner["id"])))

        resp = api.submit_assessment(matter["id"], make_counsel_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_MATTER_OWNER)
        current = get_success_data(api.get_matter(matter["id"], make_counsel_headers(owner["id"])))
        assert current["status"] == MatterStatus.INTAKE.value


class TestUniqueness:
    def test_staff_user_email_uniqueness_enforced(self, api):
        """PRD §3.1: "A `LegalOperationsAnalyst` registers each staff user with a
        `full_name`, a corporate `email` (unique across the directory — a duplicate is
        rejected with `ERR_DUPLICATE`), a `job_family`, and an optional `is_active`
        flag that defaults to true."

        Design: Corner/entities/staff_user_email_uniqueness_enforced
        """
        create_staff_user("Casey Counsel", "casey@corp.example", "LEGAL")
        resp = api.create_staff_user(
            create_staff_user_payload(full_name="Casey Clone",
                                      email="casey@corp.example",
                                      job_family="FINANCE"), OPS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestSegregationOfDuties:
    def test_budget_approve_by_submitter_rejected_sod(self, api):
        """PRD §2.8: "A budget may not be approved by the user recorded as its
        `submitted_by_user_id`."
        PRD §2.8: "Four approval actions therefore enforce segregation of duties, and
        a breach of any of them is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/budget_approve_by_submitter_rejected_sod
        """
        dual = create_staff_user("Dual Hat", "dual@corp.example", "LEGAL")
        fin = create_staff_user("Fin Finance", "fin@corp.example", "FINANCE")
        dual_counsel = make_counsel_headers(dual["id"])
        matter = get_success_data(api.create_matter(
            create_matter_payload(owning_counsel_id=dual["id"],
                                  exposure_low_cents=1_000_000,
                                  exposure_high_cents=4_000_000,
                                  probability_of_loss_pct=60), dual_counsel))
        get_success_data(api.submit_assessment(matter["id"], dual_counsel))
        create_deadline(matter["id"], dual["id"])
        get_success_data(api.advance_to_staffing(matter["id"], dual_counsel))
        version = fresh_matter_version(matter["id"], dual_counsel)
        budget = get_success_data(api.create_budget(
            matter["id"], create_budget_payload(expected_matter_version=version),
            dual_counsel))
        get_success_data(api.submit_budget(budget["id"], dual_counsel))

        resp = api.approve_budget(budget["id"], make_fin_headers(dual["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(
            api.approve_budget(budget["id"], make_fin_headers(fin["id"])))
        assert approved["status"] == "APPROVED"

    def test_engagement_approve_sod_lead_counsel_owner(self, api):
        """PRD §2.8: "And for an engagement whose `role_type` is `LEAD_COUNSEL`, the
        approver must not be the matter's `owning_counsel_id`, since the owning counsel
        is considered the proposer of the staffing request."
        PRD §2.8: "Four approval actions therefore enforce segregation of duties, and
        a breach of any of them is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/state_machines/engagement_approve_sod_lead_counsel_owner
        """
        dual = create_staff_user("Dual DGC", "dual@corp.example", "EXECUTIVE")
        dgc = create_staff_user("Dana Deputy", "dana@corp.example", "EXECUTIVE")
        gc = create_staff_user("Gena Counsel", "gena@corp.example", "EXECUTIVE")
        dual_counsel = make_counsel_headers(dual["id"])
        matter = get_success_data(api.create_matter(
            create_matter_payload(owning_counsel_id=dual["id"],
                                  exposure_low_cents=1_000_000,
                                  exposure_high_cents=4_000_000,
                                  probability_of_loss_pct=60), dual_counsel))
        get_success_data(api.submit_assessment(matter["id"], dual_counsel))
        create_deadline(matter["id"], dual["id"])
        get_success_data(api.advance_to_staffing(matter["id"], dual_counsel))
        firm = create_approved_firm(gc["id"])
        engagement = get_success_data(api.create_engagement(
            matter["id"],
            create_engagement_payload(firm_id=firm["id"], role_type="LEAD_COUNSEL"),
            dual_counsel))

        resp = api.approve_engagement(engagement["id"], make_dgc_headers(dual["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(
            api.approve_engagement(engagement["id"], make_dgc_headers(dgc["id"])))
        assert approved["status"] == "APPROVED"
