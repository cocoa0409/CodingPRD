"""Role authorization (pipeline step 2), entity-backed ownership (step 5),
and header presence (step 1)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_field_payload,
    create_landlord_payload,
    create_notice_payload,
    get_bid,
    get_lease,
    get_notice,
    get_report,
    make_landlord_headers,
    make_tenant_headers,
    serve_notice,
    setup_active_lease,
    setup_bid,
    setup_field,
    setup_landlord,
    setup_lease_with_practices_scenario,
    setup_offering,
    setup_report_scenario,
    setup_tenant,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


class TestRoleExclusivity:
    def test_tenant_cannot_award_offering(self, api):
        """PRD §3.3: "Awarding is the owner-only act of tenant selection — managers shortlist, but only the landlord awards."
        PRD §2.1: "A request whose declared role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/tenant_cannot_award_offering
        """
        landlord = setup_landlord(name="L R1", contact_email="lr1@x.com")
        tenant = setup_tenant(name="T R1", years_experience=5)
        field = setup_field(landlord["id"], name="FR1")
        offering = setup_offering(field["id"])
        bid = setup_bid(offering["id"], tenant["id"], "CASH")
        validate_success(api.shortlist_bid(bid["id"], MGR))
        validate_success(api.close_offering(offering["id"], MGR))

        resp = api.award_offering(
            offering["id"], {"bid_id": bid["id"]},
            make_tenant_headers(tenant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_farmmanager_cannot_award_offering(self, api):
        """PRD §3.3: "Awarding is the owner-only act of tenant selection — managers shortlist, but only the landlord awards."
        PRD §2.1: "A request whose declared role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/farmmanager_cannot_award_offering
        """
        landlord = setup_landlord(name="L R2", contact_email="lr2@x.com")
        tenant = setup_tenant(name="T R2", years_experience=5)
        field = setup_field(landlord["id"], name="FR2")
        offering = setup_offering(field["id"])
        bid = setup_bid(offering["id"], tenant["id"], "CASH")
        validate_success(api.shortlist_bid(bid["id"], MGR))
        validate_success(api.close_offering(offering["id"], MGR))

        resp = api.award_offering(offering["id"], {"bid_id": bid["id"]}, MGR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_landlord_cannot_create_fields(self, api):
        """PRD §2.1: "`FarmManager` is the farm management company's operator and runs nearly the whole workflow: master-data creation, tenant approval and suspension, offering control, bid curation, lease management, cash-rent collection, settlement processing, expense review, compliance enforcement, project execution, landlord reporting, and logical-clock control."
        PRD §2.1: "A request whose declared role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/landlord_cannot_create_fields
        """
        landlord = setup_landlord(name="L R3", contact_email="lr3@x.com")
        resp = api.create_field(
            create_field_payload(landlord["id"], name="FSelf", acres=50,
                                 soil_csr2=70),
            make_landlord_headers(landlord["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestHeaderPresence:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, declaring the caller's role. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        # Empty header set: neither X-User-ID nor X-User-Role is sent.
        resp = api.create_landlord(
            create_landlord_payload(name="L NoHdr", contact_email="lnh@x.com"),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestOwnership:
    def test_bid_withdraw_by_other_tenant_forbidden(self, api):
        """PRD §3.2: "A tenant may also withdraw a bid they own — the bid's `tenant_id` must equal the caller's `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER`"
        PRD §2.1: "When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource that references a `Tenant` compare the resource's foreign-key field to `X-User-ID`."

        Design: Corner/rbac/bid_withdraw_by_other_tenant_forbidden
        """
        landlord = setup_landlord(name="L R5", contact_email="lr5@x.com")
        tenant_a = setup_tenant(name="T R5A", years_experience=5)
        tenant_b = setup_tenant(name="T R5B", years_experience=7)
        field = setup_field(landlord["id"], name="FR5")
        offering = setup_offering(field["id"])
        bid = setup_bid(offering["id"], tenant_a["id"], "CASH")

        resp = api.withdraw_bid(bid["id"], make_tenant_headers(tenant_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_bid(bid["id"])["status"] == "SUBMITTED", (
            "the failed withdrawal leaves the bid untouched"
        )

    def test_expense_create_by_non_lease_tenant_forbidden(self, api):
        """PRD §3.6: "The caller must be the lease's tenant — a mismatch is `ERR_NOT_RESOURCE_OWNER`"

        Design: Corner/rbac/expense_create_by_non_lease_tenant_forbidden
        """
        ctx = setup_active_lease("SHARE")
        tenant_b = setup_tenant(name="T R6B", years_experience=7)
        resp = api.create_expense(
            {
                "lease_id": ctx["lease"]["id"],
                "category": "FUEL",
                "total_cost_cents": 40000,
                "incurred_date": "2027-04-10T00:00:00Z",
                "crop_year": 2027,
            },
            make_tenant_headers(tenant_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    def test_compliance_submit_by_non_lease_tenant_forbidden(self, api):
        """PRD §3.7: "The tenant fulfills an obligation by submitting an `evidence_note` describing the work; submission is allowed from `PENDING` and also from `REJECTED`, so evidence rejected once may be replaced before the cure deadline, and the caller must be the lease's tenant, else `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/compliance_submit_by_non_lease_tenant_forbidden
        """
        ctx = setup_lease_with_practices_scenario(
            [{"practice_type": "COVER_CROP", "due_date": "2027-06-01T00:00:00Z"}]
        )
        tenant_b = setup_tenant(name="T R7B", years_experience=7)
        record = ctx["records"][0]
        resp = api.submit_evidence(
            record["id"], {"evidence_note": "wrong tenant attempt"},
            make_tenant_headers(tenant_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    def test_notice_withdraw_by_non_serving_party_forbidden(self, api):
        """PRD §3.9: "A serving party who changes their mind may withdraw a `SERVED` notice before it becomes effective; the caller must be the serving party and a party to the lease, else `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/notice_withdraw_by_non_serving_party_forbidden
        """
        ctx = setup_active_lease("CASH")
        notice = serve_notice(ctx, "LANDLORD")

        resp = api.withdraw_notice(
            notice["id"], make_tenant_headers(ctx["tenant"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_notice(notice["id"])["status"] == "SERVED"
        assert get_lease(ctx["lease"]["id"])["status"] == "TERMINATION_PENDING"

    def test_report_acknowledge_by_other_landlord_forbidden(self, api):
        """PRD §3.10: "Acknowledgment belongs to the recipient: the caller's `X-User-ID` must equal the report's `landlord_id`, else `ERR_NOT_RESOURCE_OWNER`"

        Design: Corner/rbac/report_acknowledge_by_other_landlord_forbidden
        """
        ctx = setup_report_scenario(
            landlord_overrides={"name": "L R9A", "contact_email": "lr9a@x.com"},
            send=True,
        )
        landlord_b = setup_landlord(name="L R9B", contact_email="lr9b@x.com")
        resp = api.acknowledge_report(
            ctx["report"]["id"], make_landlord_headers(landlord_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        assert get_report(ctx["report"]["id"])["status"] == "SENT"

    def test_notice_served_by_mismatching_role_rejected(self, api):
        """PRD §3.9: "The request names the `lease_id` and a `served_by` value that must match the caller's role — a landlord serves as `LANDLORD`, a tenant as `TENANT`, and a mismatch is an `ERR_VALIDATION` failure"
        PRD §2.8: "a notice `served_by` value that does not match the caller's role all yield `ERR_VALIDATION` (HTTP 400)"

        Design: Corner/rbac/notice_served_by_mismatching_role_rejected
        """
        ctx = setup_active_lease("CASH")
        # A Tenant caller declaring served_by LANDLORD misdeclares the party.
        resp = api.create_notice(
            create_notice_payload(ctx["lease"]["id"], "LANDLORD"),
            make_tenant_headers(ctx["tenant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
