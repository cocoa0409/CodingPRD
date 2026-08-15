"""Campaign stand-up, catalog, groups, sellers, and prizes: creation rules,
uniqueness constraints, and state gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_campaign_payload,
    create_group_payload,
    create_prize_payload,
    create_product_payload,
    create_seller_payload,
    get_success_data,
    reset_clock,
    setup_campaign_group_product,
    setup_open_campaign_with_seller,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]
SUPP = TEST_USERS["supplier_rep_headers"]


class TestCampaignCreation:
    def test_campaign_create_returns_draft_with_system_fields(self, api):
        """PRD §3.1: "The campaign begins in `DRAFT` and passes through `OPEN`,
        `ORDERING_CLOSED`, `SUPPLIER_ORDERED`, `DELIVERED`, `SORTED`,
        `DISTRIBUTION_COMPLETE`, `RECONCILED`, and finally `CLOSED`".
        PRD §2.4: "All primary resources — Campaign, StudentGroup, Product,
        IncentivePrize, Seller, Order, OrderLine, Payment, SupplierOrder,
        SupplierOrderLine, DistributionEvent, SortTicket, PickupAppointment,
        ReconciliationClaim, ReturnRequest, and PrizeAward — carry a standard
        set of system-managed fields".

        Design: Corner/entities/campaign_create_returns_draft_with_system_fields
        """
        reset_clock()
        resp = api.create_campaign(create_campaign_payload(), ADMIN)
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT", (
            f"new campaign must begin in DRAFT, got {data['status']}")
        for field in ("id", "created_at", "updated_at", "version"):
            assert field in data, f"system-managed field {field} missing"
        assert isinstance(data["version"], int)

    def test_campaign_create_inverted_window_returns_invalid_request(self, api):
        """PRD §3.1: "The order window end must be strictly later than its
        start, and the expected delivery date must be strictly later than the
        order window end."
        PRD §2.10: "Third, request-body schema validation — required fields
        present, types and enum members valid, integer ranges respected,
        non-empty line arrays — rejected with `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/entities/campaign_create_inverted_window_returns_invalid_request
        """
        payload = create_campaign_payload(
            order_window_start="2026-08-20T00:00:00Z",
            order_window_end="2026-08-01T00:00:00Z",
        )
        resp = api.create_campaign(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestCatalogRules:
    def test_product_create_applies_campaign_default_profit_share(self, api):
        """PRD §3.1: "`profit_share_bps`, which overrides the group share for
        this product and, when omitted, snapshots the campaign's
        `default_profit_share_bps` at creation".

        Design: Corner/entities/product_create_applies_campaign_default_profit_share
        """
        reset_clock()
        campaign = get_success_data(api.create_campaign(
            create_campaign_payload(default_profit_share_bps=5000), ADMIN))
        resp = api.create_product(
            create_product_payload(campaign_id=campaign["id"]), ADMIN)
        product = validate_success(resp, 201)
        assert product["profit_share_bps"] == 5000, (
            "omitted profit_share_bps must snapshot the campaign default 5000, "
            f"got {product['profit_share_bps']}")

    def test_product_duplicate_sku_rejected(self, api):
        """PRD §3.1: "a catalog `sku` unique within the campaign (a duplicate
        is rejected with `ERR_DUPLICATE_SKU`)".

        Design: Corner/entities/product_duplicate_sku_rejected
        """
        reset_clock()
        campaign = get_success_data(api.create_campaign(
            create_campaign_payload(), ADMIN))
        get_success_data(api.create_product(
            create_product_payload(campaign_id=campaign["id"]), ADMIN))
        resp = api.create_product(
            create_product_payload(campaign_id=campaign["id"], name="Bar Again",
                                   unit_price_cents=1200,
                                   supplier_unit_cost_cents=700,
                                   case_pack_size=6),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU)

    def test_group_duplicate_name_rejected(self, api):
        """PRD §3.1: "Each **StudentGroup** is created with its `campaign_id`,
        a `name` unique within the campaign (duplicates rejected with
        `ERR_DUPLICATE_GROUP_NAME`)".

        Design: Corner/entities/group_duplicate_name_rejected
        """
        reset_clock()
        campaign = get_success_data(api.create_campaign(
            create_campaign_payload(), ADMIN))
        get_success_data(api.create_group(
            create_group_payload(campaign_id=campaign["id"]), COORD))
        resp = api.create_group(
            create_group_payload(campaign_id=campaign["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_GROUP_NAME)

    def test_seller_duplicate_name_rejected(self, api):
        """PRD §3.1: "Each **Seller** is enrolled into a group by `group_id`
        with a `display_name` unique within that group (duplicates rejected
        with `ERR_DUPLICATE_SELLER_NAME`)".

        Design: Corner/entities/seller_duplicate_name_rejected
        """
        reset_clock()
        campaign, group, _product = setup_campaign_group_product()
        get_success_data(api.create_seller(
            create_seller_payload(group_id=group["id"]), COORD))
        resp = api.create_seller(
            create_seller_payload(group_id=group["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SELLER_NAME)

    def test_seller_create_missing_display_name_returns_invalid_request(self, api):
        """PRD §2.10: "Third, request-body schema validation — required fields
        present, types and enum members valid, integer ranges respected,
        non-empty line arrays — rejected with `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/entities/seller_create_missing_display_name_returns_invalid_request
        """
        reset_clock()
        campaign, group, _product = setup_campaign_group_product()
        resp = api.create_seller({"group_id": group["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_prize_create_bad_tier_type_returns_invalid_request(self, api):
        """PRD §3.1: "Each **IncentivePrize** carries a `name`, a `tier_type`
        of `UNITS_SOLD`, `REVENUE_CENTS`, or `ORDERS_COUNT` selecting which
        seller metric the threshold reads".
        PRD §2.10: "Third, request-body schema validation — required fields
        present, types and enum members valid, integer ranges respected,
        non-empty line arrays — rejected with `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/entities/prize_create_bad_tier_type_returns_invalid_request
        """
        reset_clock()
        campaign = get_success_data(api.create_campaign(
            create_campaign_payload(), ADMIN))
        resp = api.create_prize(
            create_prize_payload(campaign_id=campaign["id"], tier_type="DOLLARS"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_seller_create_with_unknown_group_returns_not_found(self, api):
        """PRD §2.10: "Fifth, body foreign keys must resolve to existing
        entities, each yielding its entity-specific 404
        (`ERR_PRODUCT_NOT_FOUND` for product ids inside order lines,
        `ERR_GROUP_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_ORDER_LINE_NOT_FOUND`, `ERR_DISTRIBUTION_EVENT_NOT_FOUND`)".

        Design: Corner/entities/seller_create_with_unknown_group_returns_not_found
        """
        resp = api.create_seller(
            create_seller_payload(
                group_id="8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"),
            COORD)
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_FOUND)

    def test_get_campaign_nonexistent_returns_not_found(self, api):
        """PRD §2.10: "the server validates their existence left to right and
        rejects with the per-segment 404 error for the first identifier that
        does not correspond to an existing resource: `ERR_CAMPAIGN_NOT_FOUND`".

        Design: Corner/entities/get_campaign_nonexistent_returns_not_found
        """
        resp = api.get_campaign("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND)


class TestCampaignStateGates:
    def test_campaign_open_twice_returns_invalid_state(self, api):
        """PRD §2.10: "Seventh, state-machine admission: the target entity —
        or, for creates, the related entity whose lifecycle gates creation —
        must be in a permitting state, else `ERR_INVALID_STATE` (HTTP 409)".
        PRD §3.1: "the admin opens the campaign, moving it `DRAFT` → `OPEN`."

        Design: Corner/state_machines/campaign_open_twice_returns_invalid_state
        """
        reset_clock()
        campaign, _group, _product = setup_campaign_group_product()
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        resp = api.open_campaign(campaign["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancelled_campaign_terminal_lockdown(self, api):
        """PRD §3.1: "cancellation by a `FundraiserAdmin` is permitted from
        `DRAFT` or `OPEN` only when no order of the campaign carries cleared
        value, otherwise `ERR_CAMPAIGN_CANCEL_BLOCKED`."
        PRD §2.10: "Seventh, state-machine admission: the target entity — or,
        for creates, the related entity whose lifecycle gates creation — must
        be in a permitting state, else `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/cancelled_campaign_terminal_lockdown
        """
        reset_clock()
        campaign, _group, _product = setup_campaign_group_product()
        cancelled = get_success_data(api.cancel_campaign(campaign["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED"
        resp_cancel = api.cancel_campaign(campaign["id"], ADMIN)
        validate_error(resp_cancel, ApiErrorId.ERR_INVALID_STATE)
        resp_open = api.open_campaign(campaign["id"], ADMIN)
        validate_error(resp_open, ApiErrorId.ERR_INVALID_STATE)
        final = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert final["status"] == "CANCELLED"

    def test_campaign_open_without_catalog_returns_not_ready(self, api):
        """PRD §3.1: "With at least one `ACTIVE` product and at least one
        student group in place — otherwise the open attempt is rejected with
        `ERR_CAMPAIGN_NOT_READY` — the admin opens the campaign".

        Design: Corner/state_machines/campaign_open_without_catalog_returns_not_ready
        """
        reset_clock()
        campaign = get_success_data(api.create_campaign(
            create_campaign_payload(), ADMIN))
        get_success_data(api.create_group(
            create_group_payload(campaign_id=campaign["id"]), COORD))
        resp = api.open_campaign(campaign["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_READY)

    def test_campaign_version_increments_on_transition(self, api):
        """PRD §3.1: "Opening increments the campaign's `version` by 1."
        PRD §2.11: "Each mutation of a resource refreshes its `updated_at` and
        increments its `version` by 1".

        Design: Corner/entities/campaign_version_increments_on_transition
        """
        reset_clock()
        campaign, _group, _product = setup_campaign_group_product()
        v0 = campaign["version"]
        created_at = campaign["created_at"]
        opened = get_success_data(api.open_campaign(campaign["id"], ADMIN))
        assert opened["status"] == "OPEN"
        assert opened["version"] == v0 + 1, (
            f"open must increment version by exactly 1: {v0} -> "
            f"{opened['version']}")
        assert opened["updated_at"] >= created_at
