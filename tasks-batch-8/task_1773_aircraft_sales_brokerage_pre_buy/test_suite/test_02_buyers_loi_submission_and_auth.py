"""Buyer registration/qualification, LOI submission gates, auth, and pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_buyer,
    assert_loi,
    create_buyer_payload,
    create_draft_listing,
    create_loi_payload,
    create_listing_payload,
    get_success_data,
    qualify_buyer_payload,
    run_valuation,
    setup_accepted_deal,
    setup_active_listing,
    setup_canonical_comps,
    setup_qualified_buyer,
    validate_error,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_principal_headers"]
LISTING_AGENT = TEST_USERS["listing_agent_headers"]
BUYER_AGENT = TEST_USERS["buyer_agent_headers"]


class TestBuyerLifecycle:
    def test_buyer_create_defaults_unqualified_then_qualify(self, api):
        """PRD §3.3: "A new buyer starts with `qualification_status` set to
        `UNQUALIFIED`, and both `qualified_budget_usd` and `proof_of_funds_ref`
        are null until qualification occurs."
        PRD §3.3: "the `BuyerAgent` records the buyer's budget ceiling as
        `qualified_budget_usd` together with a bank reference in
        `proof_of_funds_ref`, moving the buyer from `UNQUALIFIED` to `QUALIFIED`
        and incrementing the buyer's `version`."

        Design: Corner/entities/buyer_create_defaults_unqualified_then_qualify
        """
        created = validate_success(
            api.create_buyer(create_buyer_payload(), BUYER_AGENT), 201)
        assert_buyer(created)
        assert created["qualification_status"] == "UNQUALIFIED"
        assert created["qualified_budget_usd"] is None
        assert created["proof_of_funds_ref"] is None

        qualified = validate_success(
            api.qualify_buyer(created["id"],
                              qualify_buyer_payload(qualified_budget_usd=3000000.00,
                                                    proof_of_funds_ref="POF-8891"),
                              BUYER_AGENT))
        assert qualified["qualification_status"] == "QUALIFIED"
        assert float(qualified["qualified_budget_usd"]) == 3000000.00
        assert qualified["proof_of_funds_ref"] == "POF-8891"

    def test_qualify_buyer_not_found_returns_404(self, api):
        """PRD §2.9: "Wherever a path carries identifiers, the system validates
        their existence sequentially from left to right and rejects the request
        with the not-found error corresponding to the first identifier that does
        not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
        `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`,
        `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`,
        or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/qualify_buyer_not_found_returns_404
        """
        get_success_data(api.create_buyer(create_buyer_payload(), BUYER_AGENT))
        resp = api.qualify_buyer(NON_EXISTENT_UUID, qualify_buyer_payload(),
                                 BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_BUYER_NOT_FOUND)


class TestLoiNotFound:
    def test_get_loi_not_found_returns_404(self, api):
        """PRD §2.9: "Wherever a path carries identifiers, the system validates
        their existence sequentially from left to right and rejects the request
        with the not-found error corresponding to the first identifier that does
        not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
        `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`,
        `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`,
        or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_loi_not_found_returns_404
        """
        get_success_data(api.create_buyer(create_buyer_payload(), BUYER_AGENT))
        resp = api.get_loi(NON_EXISTENT_UUID, BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_LOI_NOT_FOUND)


class TestPaginationEnvelope:
    def test_list_lois_empty_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, with a minimum of 1 and a maximum of
        100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/list_lois_empty_pagination_envelope
        """
        get_success_data(api.create_buyer(create_buyer_payload(), BUYER_AGENT))
        resp = api.list_lois(BROKER)
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert data == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"


class TestAuthenticationAndRoles:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` value that is not one of the declared roles, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        get_success_data(api.create_buyer(create_buyer_payload(), BUYER_AGENT))
        resp = api.create_listing(create_listing_payload(), {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_wrong_role_create_listing_returns_forbidden(self, api):
        """PRD §2.1: "Each endpoint declares the roles authorized to invoke it,
        and a caller whose role is not in that list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST `/api/listings` | Create an aircraft listing (starts
        DRAFT) | ListingAgent"

        Design: Corner/validations/wrong_role_create_listing_returns_forbidden
        """
        get_success_data(api.create_buyer(create_buyer_payload(), BUYER_AGENT))
        resp = api.create_listing(create_listing_payload(), BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestFiscalGates:
    def test_unqualified_buyer_loi_submit_returns_not_qualified(self, api):
        """PRD §3.4: "First, the referenced buyer must be `QUALIFIED`;
        submitting for an `UNQUALIFIED` buyer is rejected with
        `ERR_BUYER_NOT_QUALIFIED` (HTTP 422)."

        Design: Corner/validations/unqualified_buyer_loi_submit_returns_not_qualified
        """
        listing = setup_active_listing()
        buyer = get_success_data(api.create_buyer(create_buyer_payload(), BUYER_AGENT))
        assert buyer["qualification_status"] == "UNQUALIFIED"
        resp = api.create_loi(create_loi_payload(listing["id"], buyer["id"]),
                              BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_BUYER_NOT_QUALIFIED)

    def test_budget_exactly_equal_to_offer_passes(self, api):
        """PRD §3.4: "Second, the `offer_price_usd` must not exceed the buyer's
        recorded `qualified_budget_usd`; an offer above the ceiling is rejected
        with `ERR_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Corner/calculations/budget_exactly_equal_to_offer_passes
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        resp = api.create_loi(
            create_loi_payload(listing["id"], buyer["id"],
                               offer_price_usd=3000000.00,
                               deposit_amount_usd=150000.00),
            BUYER_AGENT)
        loi = validate_success(resp, 201)
        assert_loi(loi)
        assert loi["status"] == "SUBMITTED"

    def test_budget_exceeded_by_one_cent_returns_error(self, api):
        """PRD §3.4: "Second, the `offer_price_usd` must not exceed the buyer's
        recorded `qualified_budget_usd`; an offer above the ceiling is rejected
        with `ERR_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Corner/calculations/budget_exceeded_by_one_cent_returns_error
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        # deposit 150000.01 >= round_half_up(3000000.01 * 0.05) = 150000.00,
        # so only the budget gate can fail.
        resp = api.create_loi(
            create_loi_payload(listing["id"], buyer["id"],
                               offer_price_usd=3000000.01,
                               deposit_amount_usd=150000.01),
            BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)


class TestDepositMinimumBoundary:
    def test_deposit_exactly_five_percent_passes(self, api):
        """PRD §3.4: "Third, the earnest deposit must meet the minimum: five
        percent of the `offer_price_usd`, computed by multiplying the offer
        price by 0.05 and rounding the product half up to two decimal places; a
        `deposit_amount_usd` equal to or greater than that minimum passes —
        exact equality is acceptable — while anything below it is rejected with
        `ERR_DEPOSIT_BELOW_MINIMUM` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/deposit_exactly_five_percent_boundary
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=4000000.00)
        # round_half_up(3000000.00 * 0.05) = 150000.00 exactly.
        resp = api.create_loi(
            create_loi_payload(listing["id"], buyer["id"],
                               offer_price_usd=3000000.00,
                               deposit_amount_usd=150000.00),
            BUYER_AGENT)
        loi = validate_success(resp, 201)
        assert loi["status"] == "SUBMITTED"
        assert float(loi["deposit_amount_usd"]) == 150000.00

    def test_deposit_one_cent_below_five_percent_rejected(self, api):
        """PRD §3.4: "a `deposit_amount_usd` equal to or greater than that
        minimum passes — exact equality is acceptable — while anything below it
        is rejected with `ERR_DEPOSIT_BELOW_MINIMUM` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/deposit_exactly_five_percent_boundary
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=4000000.00)
        resp = api.create_loi(
            create_loi_payload(listing["id"], buyer["id"],
                               offer_price_usd=3000000.00,
                               deposit_amount_usd=149999.99),
            BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_BELOW_MINIMUM)


class TestListingMustBeActive:
    def test_loi_submit_on_draft_listing_rejected(self, api):
        """PRD §3.4: "Submission requires the listing to be `ACTIVE`; an LOI
        against a listing in any other status is rejected with
        `ERR_LISTING_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/loi_submit_requires_active_listing
        """
        setup_canonical_comps()
        listing = create_draft_listing()
        run_valuation(listing["id"], "FINAL")  # FINAL on record, still DRAFT
        buyer = setup_qualified_buyer(budget=3000000.00)
        resp = api.create_loi(create_loi_payload(listing["id"], buyer["id"]),
                              BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)

    def test_loi_submit_after_activation_succeeds(self, api):
        """PRD §3.4: "Submission requires the listing to be `ACTIVE`; an LOI
        against a listing in any other status is rejected with
        `ERR_LISTING_NOT_ACTIVE` (HTTP 409)."
        PRD §3.4: "A submitted LOI starts in `SUBMITTED` status, with
        `current_price_usd` set equal to the initial `offer_price_usd`, both
        `buyer_acked` and `seller_acked` false, and `disclosure_status` set to
        `PENDING` when `dual_agency` is true and to `NOT_REQUIRED` otherwise."

        Design: Difficulty/cross_entity_state_dependency/loi_submit_requires_active_listing
        """
        setup_canonical_comps()
        listing = create_draft_listing()
        run_valuation(listing["id"], "FINAL")
        buyer = setup_qualified_buyer(budget=3000000.00)
        resp = api.create_loi(create_loi_payload(listing["id"], buyer["id"]),
                              BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)

        get_success_data(api.activate_listing(listing["id"], LISTING_AGENT))
        resp = api.create_loi(create_loi_payload(listing["id"], buyer["id"]),
                              BUYER_AGENT)
        loi = validate_success(resp, 201)
        assert loi["status"] == "SUBMITTED"
        assert float(loi["current_price_usd"]) == 2000000.00
        assert loi["disclosure_status"] == "NOT_REQUIRED"


class TestStateBeatsFiscalPriority:
    def test_loi_on_under_contract_listing_state_error_despite_bad_deposit(self, api):
        """PRD §2.8: "Every request is validated against a fixed pipeline of
        checks, evaluated in the following order, and the first failing check
        determines the error returned"
        PRD §2.8: "5. **State preconditions** ... (b) the domain state gates —
        an ACTIVE listing for LOI creation and acceptance
        (`ERR_LISTING_NOT_ACTIVE`)"
        PRD §2.8: "10. **Fiscal gates** — at LOI submission, evaluated in
        order: the buyer must be QUALIFIED (`ERR_BUYER_NOT_QUALIFIED`, HTTP
        422), then the offer must fit the buyer's qualified budget
        (`ERR_BUDGET_EXCEEDED`, HTTP 422), then the deposit must meet the
        minimum percentage (`ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/loi_create_state_beats_fiscal_priority
        """
        deal = setup_accepted_deal()  # listing now UNDER_CONTRACT
        resp = api.create_loi(
            create_loi_payload(deal["listing"]["id"], deal["buyer"]["id"],
                               offer_price_usd=1000000.00,
                               deposit_amount_usd=1.00),
            BUYER_AGENT)
        # deposit 1.00 is below the 50000.00 minimum, but the state gate fires
        # first at HTTP 409, not the fiscal gate at HTTP 422.
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)

    def test_loi_on_under_contract_listing_state_error_despite_budget_breach(self, api):
        """PRD §2.8: "Every request is validated against a fixed pipeline of
        checks, evaluated in the following order, and the first failing check
        determines the error returned"
        PRD §2.8: "an ACTIVE listing for LOI creation and acceptance
        (`ERR_LISTING_NOT_ACTIVE`)"
        PRD §2.8: "10. **Fiscal gates** — at LOI submission, evaluated in
        order: the buyer must be QUALIFIED (`ERR_BUYER_NOT_QUALIFIED`, HTTP
        422), then the offer must fit the buyer's qualified budget
        (`ERR_BUDGET_EXCEEDED`, HTTP 422), then the deposit must meet the
        minimum percentage (`ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/loi_create_state_beats_fiscal_priority
        """
        deal = setup_accepted_deal()  # listing now UNDER_CONTRACT
        # offer 3500000.00 exceeds the 3000000.00 budget; deposit 175000.00
        # meets the 5% minimum, so the fiscal gates would fail at budget.
        resp = api.create_loi(
            create_loi_payload(deal["listing"]["id"], deal["buyer"]["id"],
                               offer_price_usd=3500000.00,
                               deposit_amount_usd=175000.00),
            BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)
        rows, meta = validate_paginated(
            api.list_lois(BROKER, {"listing_id": deal["listing"]["id"]}))
        assert meta["total_count"] == 1, "The rejected submission persists no LOI"
