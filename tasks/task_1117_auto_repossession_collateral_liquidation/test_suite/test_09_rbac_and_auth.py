"""Authentication, role exclusivity, ownership scopes, and segregation of
duties (PRD §2.1, §2.7, §2.9)."""
from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    assign_agent,
    consign,
    create_agent,
    create_auction_house,
    create_borrower,
    file_complaint,
    get_consignment,
    list_ledger_entries,
    make_auctioneer_headers,
    make_borrower_headers,
    make_compliance_officer_headers,
    report_sale,
    rm_headers,
    set_clock,
    setup_case_consign_pending,
    setup_case_cure_pending,
    setup_case_in_auction,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "All interactions with the API must be authenticated
        through a pair of mandatory HTTP headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the caller's operational
        capacity. ... A request with missing headers, or a role value outside
        those five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_unauthenticated
        """
        ok = api.list_recovery_cases(rm_headers())
        validate_success(ok)
        resp = api.list_recovery_cases(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleExclusivity:
    def test_borrower_cannot_register_agent_unauthorized(self, api):
        """PRD §2.1: "A properly authenticated caller whose role is not listed
        among the endpoint's permitted roles is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST `/repo-agents` Register a repossession agent vendor
        RecoveryManager"

        Design: Corner/rbac/borrower_cannot_register_agent_unauthorized
        """
        resp = api.create_repo_agent(
            {"name": "X", "license_number": "L",
             "licensed_state_codes": ["CA"], "max_active_assignments": 1},
            make_borrower_headers(UNKNOWN_UUID))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_agent_cannot_list_consignment_unauthorized(self, api):
        """PRD §2.1: "A properly authenticated caller whose role is not listed
        among the endpoint's permitted roles is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST `/consignments/{id}/list` List a `DRAFT` consignment
        with a closed auction window | Auctioneer"
        PRD §2.7: "(2) the caller's role is permitted on the endpoint
        (`ERR_UNAUTHORIZED`); (3) the caller owns the target resource ...; (4)
        every identifier in the path resolves to an existing resource"

        Design: Corner/rbac/agent_cannot_list_consignment_unauthorized
        """
        resp = api.list_consignment(
            UNKNOWN_UUID,
            {"listing_start": "2026-05-28T00:00:00Z",
             "listing_end": "2026-05-30T00:00:00Z"},
            TEST_USERS["repo_agent_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_manager_cannot_pay_cure_unauthorized(self, api):
        """PRD §2.1: "A properly authenticated caller whose role is not listed
        among the endpoint's permitted roles is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST `/recovery-cases/{id}/cure-payments` Borrower pays the
        cure amount | Borrower"

        Design: Corner/rbac/manager_cannot_pay_cure_unauthorized
        """
        resp = api.create_cure_payment(
            UNKNOWN_UUID, {"amount_cents": 100}, rm_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestOwnershipScopes:
    def test_borrower_other_case_payment_forbidden(self, api):
        """PRD §2.9: "A `Borrower` acts only on cases whose loan's
        `borrower_id` equals the caller's `X-User-ID` — this governs cure
        payments, quote acceptance, complaint filing, item claim and unclaim,
        and deficiency dispute and payment. ... A caller who is authenticated
        and role-permitted but outside the owning scope is rejected with
        `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/borrower_other_case_payment_forbidden
        """
        ctx = setup_case_cure_pending(
            borrower_overrides={"full_name": "OwnA", "email": "owa@x.com"},
            loan_overrides={"vin": "VIN00000000000068",
                            "principal_balance_cents": 500_000, "apr_bps": 900,
                            "monthly_payment_cents": 20_000, "missed_installments": 2,
                            "accrued_interest_cents": 8_000, "late_fees_cents": 3_000})
        other_borrower = create_borrower(full_name="OwnB", email="owb@x.com")
        set_clock("2026-05-02T00:00:00Z")  # in-window; only ownership can fail
        resp = api.create_cure_payment(
            ctx["case"]["id"], {"amount_cents": 43_000},
            make_borrower_headers(other_borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert list_ledger_entries(ctx["case"]["id"]) == []
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "CURE_PENDING"

    def test_auctioneer_other_house_list_forbidden(self, api):
        """PRD §2.9: "An `Auctioneer` acts only on consignments whose
        `auction_house_id` equals the caller's `X-User-ID`. A caller who is
        authenticated and role-permitted but outside the owning scope is
        rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/auctioneer_other_house_list_forbidden
        """
        ctx = setup_case_consign_pending(
            borrower_overrides={"full_name": "AO", "email": "ao@x.com"},
            loan_overrides={"vin": "VIN00000000000069"})
        house1 = create_auction_house(name="H1")
        house2 = create_auction_house(name="H2", fee_bps=300, transport_fee_cents=9_000)
        consignment = consign(ctx["case"]["id"], house1["id"])

        resp = api.list_consignment(
            consignment["id"],
            {"listing_start": "2026-05-28T00:00:00Z",
             "listing_end": "2026-05-30T00:00:00Z"},
            make_auctioneer_headers(house2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert get_consignment(consignment["id"])["status"] == "DRAFT"


class TestSegregationOfDuties:
    def test_case_opener_cannot_certify_own_sale(self, api):
        """PRD §2.9: "The `RecoveryManager` who opened a case — recorded as the
        case's `opened_by_user_id` — may not certify that case's sale and may
        not resolve that case's complaint, regardless of the caller's current
        role assignment. An attempt to do either is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.6: "Certification moves the record to `CERTIFIED`, the
        consignment to `SOLD`, and the case from `IN_AUCTION` to
        `SALE_CONFIRMED`"

        Design: Corner/rbac/case_opener_cannot_certify_own_sale
        """
        ctx = setup_case_in_auction(
            borrower_overrides={"full_name": "SD", "email": "sd@x.com"},
            loan_overrides={"vin": "VIN00000000000070"})
        set_clock("2026-06-05T00:00:00Z")
        sale = report_sale(ctx["consignment"]["id"], ctx["auction_house"]["id"], 1_200_000)

        # The case was opened by operator rm_1; an officer call carrying that
        # same id is segregated out regardless of role.
        resp = api.certify_sale(sale["id"], make_compliance_officer_headers("rm_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        certified = validate_success(api.certify_sale(
            sale["id"], make_compliance_officer_headers("co_1")))
        assert certified["status"] == "CERTIFIED"
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "SALE_CONFIRMED"

    def test_case_opener_cannot_resolve_own_complaint(self, api):
        """PRD §2.9: "The `RecoveryManager` who opened a case — recorded as the
        case's `opened_by_user_id` — may not certify that case's sale and may
        not resolve that case's complaint, regardless of the caller's current
        role assignment. An attempt to do either is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.8: "The complaint must still be `UNDER_REVIEW`
        (`ERR_INVALID_COMPLAINT_STATE`), and the resolver must not be the
        manager who opened the case (`ERR_SEGREGATION_OF_DUTIES`)"

        Design: Corner/rbac/case_opener_cannot_resolve_own_complaint
        """
        ctx = setup_case_cure_pending(
            borrower_overrides={"full_name": "SR", "email": "sr@x.com"},
            loan_overrides={"vin": "VIN00000000000071",
                            "principal_balance_cents": 500_000, "apr_bps": 900,
                            "monthly_payment_cents": 20_000, "missed_installments": 2,
                            "accrued_interest_cents": 8_000, "late_fees_cents": 3_000})
        set_clock("2026-05-16T00:00:00Z")  # cure-expires
        agent = create_agent(name="Agent W2", license_number="LIC-W2")
        assign_agent(ctx["case"]["id"], agent["id"])  # case -> REPO_ACTIVE
        complaint = file_complaint(ctx["case"]["id"], ctx["borrower"]["id"],
                                   category="BREACH_OF_PEACE", description="threats")

        resp = api.resolve_complaint(
            complaint["id"], {"outcome": "DISMISSED"},
            make_compliance_officer_headers("rm_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        complaints = validate_success(api.list_case_complaints(ctx["case"]["id"], rm_headers()))
        assert complaints[0]["status"] == "UNDER_REVIEW"
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "COMPLAINT_REVIEW"
