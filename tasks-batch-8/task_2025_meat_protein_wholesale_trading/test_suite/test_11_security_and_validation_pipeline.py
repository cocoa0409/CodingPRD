"""RBAC segregation of duties, the CustomerRep ownership rule, uniqueness
constraints, and the ordered validation pipeline."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_sheet_line,
    amend_forward_contract_payload,
    api_client,
    book_po,
    build_user_headers,
    claim_offer_payload,
    create_allocation_payload,
    create_certificate_payload,
    create_claim_payload,
    create_customer,
    create_customer_payload,
    create_forward_contract,
    create_product,
    create_sheet,
    get_claim,
    get_contract,
    get_lot,
    get_sheet,
    inspect_lot,
    make_customer_rep_headers,
    publish_sheet,
    receive_po,
    request_allocation,
    set_clock,
    setup_available_lot,
    setup_confirmed_allocation,
    setup_delivered_shipment,
    setup_filed_claim,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]
GRADER = TEST_USERS["quality_grader_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]
ANONYMOUS = build_user_headers("anon-1", "Anonymous")


class TestAuthenticationContext:
    def test_invalid_role_header_returns_400(self):
        """PRD §2.1: "When either header is missing, or the role value is not
        one of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any
        other evaluation."

        Design: Corner/validations/invalid_role_header_returns_400
        """
        resp = api_client.list_customers(ANONYMOUS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_auth_priority_beats_not_found(self):
        """PRD §2.8: "Earlier stages mask later ones: a request that fails an
        earlier check reports that check's error and is never evaluated against
        later checks, so the reported error is always the highest-priority
        failure."
        PRD §2.1: "When either header is missing, or the role value is not one
        of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any
        other evaluation."

        Design: Corner/validations/auth_priority_beats_not_found
        """
        resp = api_client.get_customer(NON_EXISTENT_UUID, ANONYMOUS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:
    def test_trader_create_customer_forbidden(self, trader_headers):
        """PRD §2.1: "`DeskAdmin` is the trading desk administrator: it owns
        reference data (suppliers, customers, warehouses, products, yield
        specifications), publishes and closes price sheets, voids fabrication
        batches, and drives the logical clock."
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/validations/trader_create_customer_forbidden
        """
        resp = api_client.create_customer(
            create_customer_payload(customer_code="CUST-NOPE"),
            trader_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        customers = validate_success(api_client.list_customers(ADMIN))
        assert customers == [], "no customer may be persisted by a 403"

    def test_trader_cannot_publish_sheet_returns_403(self, trader_headers):
        """PRD §2.1: "`Trader` is the desk trader: it books and cancels
        purchase orders, drafts price sheets and their lines, and creates and
        amends forward contracts."
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/trader_cannot_publish_sheet_returns_403
        """
        product = create_product(product_code="RIBEYE-RB1", max_fat_pct=12.0)
        sheet = create_sheet()
        add_sheet_line(sheet["id"], product["id"], 700, 10_000)

        resp = api_client.publish_price_sheet(sheet["id"], trader_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_sheet(sheet["id"])["status"] == "DRAFT"

    def test_warehouse_operator_cannot_inspect_returns_403(
            self, warehouse_operator_headers):
        """PRD §2.1: "`QualityGrader` is the QA and USDA documentation officer:
        it inspects lots, quarantines and releases them, and issues and revokes
        inspection certificates — deliberately segregated from receiving."
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/warehouse_operator_cannot_inspect_returns_403
        """
        ctx = setup_available_lot(product_code="RIBEYE-RB2", weight=100)
        # The setup lot is already AVAILABLE; receive a second lot that is
        # still IN_INSPECTION for the forbidden-call probe.
        po = book_po(ctx["supplier"]["id"], ctx["product"]["id"],
                     ordered_weight_lbs=100)
        _, lot = receive_po(po["id"], ctx["warehouse"]["id"], 100,
                            production_date="2026-08-01")

        resp = api_client.inspect_lot(lot["id"], {"measured_fat_pct": 10.0},
                                      warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_lot(lot["id"])["status"] == "IN_INSPECTION"

    def test_customer_rep_cannot_post_offer_returns_403(self):
        """PRD §2.1: "`ClaimsAdjuster` is the claims settlement officer: it
        posts settlement offers and denies claims — segregated from the
        customer side that files, counters, and accepts."
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/customer_rep_cannot_post_offer_returns_403
        """
        ctx = setup_filed_claim(shipped_lbs=100, lot_weight=500,
                                claimed_amount_cents=5_000)
        claim = ctx["claim"]
        rep = make_customer_rep_headers(ctx["customer"]["id"])

        resp = api_client.post_claim_offer(
            claim["id"], claim_offer_payload(4_000, claim["version"]), rep)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = get_claim(claim["id"])
        assert after["status"] == "FILED"
        assert after["offer_round"] == 0

    def test_risk_officer_cannot_amend_contract_returns_403(
            self, risk_officer_headers):
        """PRD §2.1: "`RiskOfficer` is the risk manager: it runs the weekly
        allocation waterfall and cancels forward contracts — deliberately
        segregated from the `Trader` who writes them."
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/risk_officer_cannot_amend_contract_returns_403
        """
        product = create_product(product_code="RIBEYE-RB4", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-RB4")
        fc = create_forward_contract(customer, product["id"], committed_lbs=100)

        resp = api_client.amend_forward_contract(
            fc["id"],
            amend_forward_contract_payload(200, 640, "2026-08-03",
                                           fc["version"]),
            risk_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_contract(fc["id"])["committed_lbs"] == 100

    def test_desk_admin_cannot_file_claim_returns_403(self, desk_admin_headers):
        """PRD §2.1: "`CustomerRep` is a customer representative: it requests
        allocations, accepts or rejects shipments at the receiving dock, and
        files, counters, accepts, or withdraws claims for its own house."
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/desk_admin_cannot_file_claim_returns_403
        """
        ctx = setup_delivered_shipment(shipped_lbs=100, lot_weight=500)
        resp = api_client.create_claim(
            create_claim_payload(ctx["shipment"]["id"], "WEIGHT_SHORTAGE",
                                 3_000),
            desk_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestCustomerRepOwnership:
    def test_customer_rep_acting_for_other_customer_rejected(self):
        """PRD §2.1: "Concretely, when a `CustomerRep` requests an allocation,
        cancels an allocation, accepts or rejects a shipment at the dock, or
        files, counters, accepts, or withdraws a claim, the request is rejected
        with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) unless `X-User-ID` equals the
        `id` of the `Customer` that owns the acted resource — the allocation's
        `customer_id`, the customer of the shipment's allocation, or the
        customer behind the claim's shipment, respectively."

        Design: Corner/validations/customer_rep_acting_for_other_customer_rejected
        """
        product = create_product(product_code="RIBEYE-OWN", max_fat_pct=12.0)
        cust_a = create_customer(customer_code="CUST-OWN-A")
        cust_b = create_customer(customer_code="CUST-OWN-B")
        sheet = create_sheet()
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])

        resp = api_client.create_allocation(
            create_allocation_payload(cust_a["id"], line["id"], 10),
            make_customer_rep_headers(cust_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        allocations = validate_success(api_client.list_allocations(ADMIN))
        assert allocations == [], "no allocation may be persisted by a 403"


class TestUniquenessAndCertificates:
    def test_duplicate_customer_code_returns_409(self, desk_admin_headers):
        """PRD §2.8: "Unique codes do not collide — supplier
        `establishment_number`, `customer_code`, `product_code`, `po_number`,
        `lot_code`, `contract_number`, and `certificate_number` — else
        `ERR_DUPLICATE_CODE` (HTTP 409)"
        PRD §3.1: "Customers are registered with a legal `name`, a unique
        `customer_code`, a `credit_limit_cents` ceiling, and an
        `allocation_tier` of `TIER_1`, `TIER_2`, or `TIER_3`"

        Design: Corner/validations/duplicate_customer_code_returns_409
        """
        first = api_client.create_customer(
            create_customer_payload(customer_code="CUST-DUP"),
            desk_admin_headers,
        )
        validate_success(first, expected_status=201)

        second = api_client.create_customer(
            create_customer_payload(customer_code="CUST-DUP",
                                    allocation_tier="TIER_2"),
            desk_admin_headers,
        )
        validate_error(second, ApiErrorId.ERR_DUPLICATE_CODE)

    def test_certificate_revoke_twice_returns_409(self, quality_grader_headers):
        """PRD §3.4: "Revoking a certificate is a `QualityGrader` act permitted
        only while the certificate is `VALID`; otherwise the request fails with
        `ERR_CERTIFICATE_ALREADY_REVOKED`."

        Design: Corner/validations/certificate_revoke_twice_returns_409
        """
        ctx = setup_available_lot(product_code="RIBEYE-CR", weight=100)
        cert_resp = api_client.create_inspection_certificate(
            create_certificate_payload(ctx["lot"]["id"], "COA",
                                       certificate_number="CERT-CR",
                                       issue_date="2026-08-03"),
            quality_grader_headers,
        )
        cert = validate_success(cert_resp, expected_status=201)

        first = api_client.revoke_inspection_certificate(cert["id"],
                                                         quality_grader_headers)
        assert validate_success(first)["status"] == "REVOKED"

        second = api_client.revoke_inspection_certificate(cert["id"],
                                                          quality_grader_headers)
        validate_error(second, ApiErrorId.ERR_CERTIFICATE_ALREADY_REVOKED)
        get_resp = api_client.get_inspection_certificate(cert["id"],
                                                         quality_grader_headers)
        assert validate_success(get_resp)["status"] == "REVOKED"
