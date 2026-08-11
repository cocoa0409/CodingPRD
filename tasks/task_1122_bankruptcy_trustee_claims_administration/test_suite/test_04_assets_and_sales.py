"""Asset liquidation: minimum-price gate, objection window, sale lifecycle."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_asset_payload, create_sale_payload,
    create_asset, create_case, create_creditor, set_clock,
    setup_case_in_claims_administration,
    setup_case_in_liquidation,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]


class TestSaleMinimumPriceBoundary:
    def test_hammer_exactly_at_greater_floor_is_approved(self, api):
        """PRD §3.4: "Court approval applies the minimum-price gate: the hammer
        price must be at least the greater of two floors — the sale's own
        `sale_costs_cents`, and one half of the asset's `scheduled_value_cents`
        truncated down to whole cents. A hammer price exactly equal to that
        greater floor is acceptable; anything below is rejected with
        `ERR_BELOW_MINIMUM_PRICE` (HTTP 422)."

        scheduled 800,000 -> half floor 400,000; costs 410,000; the greater
        floor is 410,000 and a hammer of exactly 410,000 is acceptable.

        Design: Difficulty/boundary_precision_check/sale_minimum_price_exact_equality_accepted
        """
        ctx = setup_case_in_liquidation(case_number="26-10011",
                                        scheduled_value_cents=800000)
        case_id = ctx["case"]["id"]
        asset = ctx["asset"]
        get_success_data(api_client.mark_asset_for_sale(asset["id"], TRUSTEE))
        sale = get_success_data(api_client.create_sale(
            case_id, create_sale_payload(asset_id=asset["id"], buyer_name="B1",
                                         hammer_price_cents=410000,
                                         sale_costs_cents=410000), TRUSTEE))
        approved = validate_success(api.approve_sale(sale["id"], COURT))
        assert approved["status"] == "APPROVED"

    def test_hammer_one_cent_below_greater_floor_rejected(self, api):
        """PRD §3.4: "A hammer price exactly equal to that greater floor is
        acceptable; anything below is rejected with `ERR_BELOW_MINIMUM_PRICE`
        (HTTP 422)."

        The greater floor is max(300,000 costs, 400,000 half-scheduled)
        = 400,000; a hammer of 399,999 is one cent below (and net proceeds
        99,999 stay non-negative, as §3.4 requires of every proposed sale).

        Design: Difficulty/boundary_precision_check/sale_minimum_price_exact_equality_accepted
        """
        ctx = setup_case_in_liquidation(case_number="26-10011",
                                        scheduled_value_cents=800000)
        case_id = ctx["case"]["id"]
        asset = ctx["asset"]
        get_success_data(api_client.mark_asset_for_sale(asset["id"], TRUSTEE))
        sale = get_success_data(api_client.create_sale(
            case_id, create_sale_payload(asset_id=asset["id"], buyer_name="B2",
                                         hammer_price_cents=399999,
                                         sale_costs_cents=300000), TRUSTEE))
        resp = api.approve_sale(sale["id"], COURT)
        validate_error(resp, ApiErrorId.ERR_BELOW_MINIMUM_PRICE)


class TestSaleObjectionWindow:
    def _approved_sale_with_window3(self):
        """APPROVED sale approved at 2026-06-05 with objection_window_days 3,
        so effective_on = 2026-06-08."""
        ctx = setup_case_in_liquidation(case_number="26-10015",
                                        objection_window_days=3,
                                        scheduled_value_cents=500000)
        case_id = ctx["case"]["id"]
        asset_id = ctx["asset"]["id"]
        get_success_data(api_client.mark_asset_for_sale(asset_id, TRUSTEE))
        sale = get_success_data(api_client.create_sale(
            case_id, create_sale_payload(asset_id=asset_id,
                                         hammer_price_cents=400000,
                                         sale_costs_cents=0), TRUSTEE))
        set_clock("2026-06-05T00:00:00Z")
        get_success_data(api_client.approve_sale(sale["id"], COURT))
        return ctx, sale

    def test_consummate_before_effective_on_rejected(self, api):
        """PRD §3.4: "Consummation is the trustee's act of posting the
        proceeds, permitted only once the logical clock is at or past
        `effective_on` — earlier attempts are rejected with
        `ERR_OBJECTION_WINDOW_OPEN`."
        PRD §3.4: "Approval stamps `sale_approved_on` with the current logical
        date and computes `effective_on` as the approval date plus the case's
        `objection_window_days` days — the objection window during which the
        order sits before becoming effective."

        Design: Difficulty/resource_temporal_overlap/sale_objection_window_blocks_early_consummation
        """
        ctx, sale = self._approved_sale_with_window3()
        set_clock("2026-06-07T00:00:00Z")  # one day before effective_on
        resp = api.consummate_sale(sale["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_OBJECTION_WINDOW_OPEN)

    def test_consummate_exactly_at_effective_on_succeeds(self, api):
        """PRD §3.4: "Consummation is the trustee's act of posting the
        proceeds, permitted only once the logical clock is at or past
        `effective_on` — earlier attempts are rejected with
        `ERR_OBJECTION_WINDOW_OPEN`."

        Design: Difficulty/resource_temporal_overlap/sale_objection_window_blocks_early_consummation
        """
        ctx, sale = self._approved_sale_with_window3()
        set_clock("2026-06-08T00:00:00Z")  # exactly effective_on
        consummated = validate_success(api.consummate_sale(sale["id"], TRUSTEE))
        assert consummated["status"] == "CONSUMMATED"
        assert consummated["proceeds_status"] == "POSTED"


class TestSaleCreationAssetGate:
    def test_sale_on_under_investigation_asset_rejected(self, api):
        """PRD §3.4: "The trustee proposes a sale of a `MARKED_FOR_SALE` asset
        with a payload naming the `asset_id` (exactly one asset per sale), the
        winning bidder's `buyer_name`, the gross winning bid
        `hammer_price_cents`, and the auctioneer and carrier `sale_costs_cents`
        chargeable to the sale."
        PRD §2.11: "5. From-state validity for the requested transition —
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/sale_create_gated_by_asset_state
        """
        ctx = setup_case_in_liquidation(case_number="26-10014",
                                        scheduled_value_cents=300000)
        # The bar-date sweep left the asset UNDER_INVESTIGATION; never marked.
        resp = api.create_sale(
            ctx["case"]["id"],
            create_sale_payload(asset_id=ctx["asset"]["id"],
                                hammer_price_cents=200000, sale_costs_cents=0),
            TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_sale_on_marked_for_sale_asset_admitted(self, api):
        """PRD §3.4: "A proposed sale starts in `PROPOSED` status with
        `proceeds_status` of `PENDING`, its `net_proceeds_cents` computed as
        the hammer price minus the sale costs (never permitted to be negative),
        and the asset moves to `IN_AUCTION` in the same request."

        Design: Difficulty/cross_entity_state_dependency/sale_create_gated_by_asset_state
        """
        ctx = setup_case_in_liquidation(case_number="26-10014",
                                        scheduled_value_cents=300000)
        asset_id = ctx["asset"]["id"]
        get_success_data(api_client.mark_asset_for_sale(asset_id, TRUSTEE))
        sale = validate_success(api.create_sale(
            ctx["case"]["id"],
            create_sale_payload(asset_id=asset_id, hammer_price_cents=200000,
                                sale_costs_cents=0),
            TRUSTEE), expected_status=201)
        assert sale["status"] == "PROPOSED"
        assert sale["proceeds_status"] == "PENDING"
        assert sale["net_proceeds_cents"] == 200000
        asset = validate_success(api.get_asset(asset_id, TRUSTEE))
        assert asset["status"] == "IN_AUCTION"


class TestSaleCancel:
    def test_sale_cancel_returns_asset_to_marked_for_sale(self, api):
        """PRD §3.4: "Either path moves the sale to its terminal `CANCELLED`
        status and returns the asset from `IN_AUCTION` to `MARKED_FOR_SALE`."
        PRD §3.4: "The named asset must belong to the case (else
        `ERR_REFERENTIAL_INTEGRITY`), and no other sale of the same asset may
        be sitting in `PROPOSED` or `APPROVED` (else `ERR_SALE_ALREADY_PENDING`)."

        Design: Corner/endpoints/sale_cancel_returns_asset_to_marked_for_sale
        """
        ctx = setup_case_in_liquidation(case_number="26-20032",
                                        scheduled_value_cents=200000)
        case_id = ctx["case"]["id"]
        asset_id = ctx["asset"]["id"]
        get_success_data(api_client.mark_asset_for_sale(asset_id, TRUSTEE))
        sale1 = get_success_data(api.create_sale(
            case_id, create_sale_payload(asset_id=asset_id, buyer_name="B1",
                                         hammer_price_cents=150000,
                                         sale_costs_cents=0), TRUSTEE))

        validate_success(api.cancel_sale(sale1["id"], TRUSTEE))
        asset = validate_success(api.get_asset(asset_id, TRUSTEE))
        assert asset["status"] == "MARKED_FOR_SALE"

        sale2 = validate_success(api.create_sale(
            case_id, create_sale_payload(asset_id=asset_id, buyer_name="B2",
                                         hammer_price_cents=160000,
                                         sale_costs_cents=0), TRUSTEE),
            expected_status=201)
        assert sale2["status"] == "PROPOSED"

    def test_second_sale_while_one_pending_rejected(self, api):
        """PRD §3.4: "The trustee proposes a sale of a `MARKED_FOR_SALE` asset
        with a payload naming the `asset_id` (exactly one asset per sale) ..."
        PRD §2.11: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the earliest
        failing tier determines the error surfaced:"
        PRD §2.11: "5. From-state validity for the requested transition —
        `ERR_INVALID_STATE`."

        While the first sale sits PROPOSED the asset is `IN_AUCTION`, so a
        second proposal fails the from-state guard (priority 5), which
        pre-empts the one-pending-sale guard (priority 9).

        Design: Corner/errors/error_sale_already_pending_triggered
        """
        ctx = setup_case_in_liquidation(case_number="26-20041",
                                        scheduled_value_cents=200000)
        case_id = ctx["case"]["id"]
        asset_id = ctx["asset"]["id"]
        get_success_data(api_client.mark_asset_for_sale(asset_id, TRUSTEE))
        get_success_data(api.create_sale(
            case_id, create_sale_payload(asset_id=asset_id, buyer_name="B1",
                                         hammer_price_cents=150000,
                                         sale_costs_cents=0), TRUSTEE))
        resp = api.create_sale(
            case_id, create_sale_payload(asset_id=asset_id, buyer_name="B2",
                                         hammer_price_cents=160000,
                                         sale_costs_cents=0), TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestExemptAsset:
    def test_mark_for_sale_exempt_asset_rejected(self, api):
        """PRD §3.4: "Marking an asset for sale moves it from
        `UNDER_INVESTIGATION` to `MARKED_FOR_SALE` and is guarded twice: an
        asset whose `exempt` flag is true is rejected with `ERR_ASSET_EXEMPT`,
        and the case must be in `CLAIMS_ADMINISTRATION` or `LIQUIDATION`
        posture."

        Design: Corner/validations/mark_for_sale_exempt_asset_rejected
        """
        # The exempt asset must exist before begin_investigation (PRD §3.1
        # rejects opening an investigation with nothing scheduled); the
        # bar-date sweep then moves it to UNDER_INVESTIGATION, so only the
        # exempt guard can fire at mark-for-sale time.
        create_creditor(creditor_ref="CR-20026")
        case = create_case(case_number="26-20026")
        asset = create_asset(case["id"], description="Homestead",
                             scheduled_value_cents=100000, exempt=True)
        get_success_data(api_client.begin_investigation(case["id"], TRUSTEE))
        get_success_data(api_client.set_bar_date(case["id"],
                                                 "2026-06-01T00:00:00Z", CLERK))
        resp = api.mark_asset_for_sale(asset["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_ASSET_EXEMPT)
