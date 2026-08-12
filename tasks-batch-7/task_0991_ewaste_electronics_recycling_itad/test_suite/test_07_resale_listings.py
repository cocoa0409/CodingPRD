"""Resale listings: data gate, sale floor, the ACTIVE->SOLD->RETURNED->ACTIVE
cycle, withdrawal, and the return cascade (PRD §3.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    INTAKE,
    create_quote_settlement,
    list_item,
    new_active_policy,
    scan_and_triage,
    sell_listing,
    setup_finalized_settlement,
    setup_received_manifest,
    setup_sold_item,
    setup_triaged_item,
    validate_error,
    validate_success,
)


class TestListingDataGate:
    def test_listing_unverified_data_item_rejected(self, api, intake_operator_headers):
        """PRD §3.6: "for a data-bearing item, listing requires `data_status` `VERIFIED` whenever the active policy's `resale_requires_verified_sanitization` flag is true — which is also the strict default applied when no policy is active at all — and requires `SANITIZED` or `VERIFIED` when the flag is false; breaching the gate yields `ERR_DATA_SANITIZATION_UNVERIFIED`."

        Design: Corner/state_machines/data_gate_on_listing_unverified
        """
        new_active_policy(sanitization_methods_allowed=["NIST_CLEAR"],
                          resale_requires_verified_sanitization=True)
        ctx = setup_triaged_item(disposition="RESALE", data_bearing=True, declared_grade="B")

        resp = api.create_listing(
            {
                "item_id": ctx["item"]["id"],
                "asking_price_cents": 30000,
                "floor_price_cents": 20000,
                "channel": "RETAIL",
            },
            intake_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DATA_SANITIZATION_UNVERIFIED)
        assert resp.status_code == 422


class TestListingCycle:
    def _cycle_to_returned(self, api):
        """Sell then return a listing; returns (ctx, listing)."""
        ctx = setup_sold_item(sale_price_cents=1500, asking_price_cents=2000,
                              floor_price_cents=1000)
        listing = validate_success(api.return_listing(ctx["listing"]["id"], INTAKE))
        return ctx, listing

    def test_listing_cycle_returns_same_listing_to_active(self, api, intake_operator_headers):
        """PRD §3.6: "From `RETURNED`, the listing may be reactivated — moving back to `ACTIVE` — which requires the item to be in `FOR_RESALE` (`ERR_INVALID_STATE` otherwise) and moves it back to `LISTED`."

        Design: Difficulty/non_linear_state_machine/listing_sold_returned_relist_cycle
        """
        ctx, listing = self._cycle_to_returned(api)
        assert listing["status"] == "RETURNED"
        assert listing["id"] == ctx["listing"]["id"]

        relisted = validate_success(api.relist_listing(listing["id"], intake_operator_headers))
        assert relisted["status"] == "ACTIVE"
        assert relisted["id"] == ctx["listing"]["id"]

    def test_item_rides_listing_cycle_back_to_listed(self, api, intake_operator_headers):
        """PRD §3.6: "On success the listing becomes `SOLD`, the item moves `LISTED` → `SOLD`, and the item's `final_value_cents` is computed per line as the sale price minus the platform's commission, where the commission is the sale price multiplied by the account-tier rate and rounded half-up to whole cents: fifteen percent for `STANDARD` accounts, fifteen percent for `VOLUME`, and ten percent for `ENTERPRISE`."
        PRD §3.6: "From `RETURNED`, the listing may be reactivated — moving back to `ACTIVE` — which requires the item to be in `FOR_RESALE` (`ERR_INVALID_STATE` otherwise) and moves it back to `LISTED`."

        Design: Difficulty/non_linear_state_machine/listing_sold_returned_relist_cycle
        """
        ctx, listing = self._cycle_to_returned(api)
        item = validate_success(api.get_item(ctx["item"]["id"], intake_operator_headers))
        assert item["processing_status"] == "FOR_RESALE"

        validate_success(api.relist_listing(listing["id"], intake_operator_headers))
        item = validate_success(api.get_item(ctx["item"]["id"], intake_operator_headers))
        assert item["processing_status"] == "LISTED"


class TestSellFloorPrice:
    def _two_listed_items(self, api, intake_operator_headers):
        """RECEIVED manifest (declared 2) with two listed grade-A laptops,
        floor 1000 each. Returns (ctx, listing_one, listing_two)."""
        account, manifest = setup_received_manifest(declared_item_count=2)
        item_one = scan_and_triage(manifest["id"], "RESALE", serial_number="SN-FL1")
        item_two = scan_and_triage(manifest["id"], "RESALE", serial_number="SN-FL2")
        listing_one = list_item(item_one["id"], asking_price_cents=1500, floor_price_cents=1000)
        listing_two = list_item(item_two["id"], asking_price_cents=1500, floor_price_cents=1000)
        return ({"account": account, "manifest": manifest}, listing_one, listing_two)

    def test_sell_at_exact_floor_allowed(self, api, intake_operator_headers):
        """PRD §3.6: "the listing must be `ACTIVE` (`ERR_LISTING_NOT_ACTIVE`, checked first), and the offered price must be at least the listing's `floor_price_cents` (`ERR_FLOOR_PRICE_VIOLATION`, checked after the state gate)."

        Design: Corner/validations/sell_at_exact_floor_allowed_below_rejected
        """
        _ctx, listing_one, _listing_two = self._two_listed_items(api, intake_operator_headers)
        listing = sell_listing(listing_one["id"], 1000)
        assert listing["status"] == "SOLD"

    def test_sell_one_cent_below_floor_rejected(self, api, intake_operator_headers):
        """PRD §3.6: "the listing must be `ACTIVE` (`ERR_LISTING_NOT_ACTIVE`, checked first), and the offered price must be at least the listing's `floor_price_cents` (`ERR_FLOOR_PRICE_VIOLATION`, checked after the state gate)."

        Design: Corner/validations/sell_at_exact_floor_allowed_below_rejected
        """
        _ctx, _listing_one, listing_two = self._two_listed_items(api, intake_operator_headers)
        resp = api.sell_listing(listing_two["id"], {"sale_price_cents": 999},
                                intake_operator_headers)
        validate_error(resp, ApiErrorId.ERR_FLOOR_PRICE_VIOLATION)
        assert resp.status_code == 422


class TestWithdrawAndReturn:
    def test_sell_withdrawn_listing_rejected(self, api, intake_operator_headers):
        """PRD §3.6: "The sale is recorded by an `IntakeOperator` supplying a `sale_price_cents`; the listing must be `ACTIVE` (`ERR_LISTING_NOT_ACTIVE`, checked first), and the offered price must be at least the listing's `floor_price_cents` (`ERR_FLOOR_PRICE_VIOLATION`, checked after the state gate)."
        PRD §3.6: "Alternatively, an unsold listing may be withdrawn: `ACTIVE` → `WITHDRAWN` is terminal for the listing and returns the item `LISTED` → `FOR_RESALE`, free to be relisted through a fresh listing or retriaged to recycling."

        Design: Corner/errors/sell_withdrawn_listing_returns_not_active
        """
        ctx = setup_triaged_item(disposition="RESALE")
        listing = list_item(ctx["item"]["id"], asking_price_cents=2000, floor_price_cents=1000)
        validate_success(api.withdraw_listing(listing["id"], intake_operator_headers))

        resp = api.sell_listing(listing["id"], {"sale_price_cents": 1500},
                                intake_operator_headers)
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)
        assert resp.status_code == 409

    def test_return_after_finalize_rejected(self, api, intake_operator_headers):
        """PRD §3.6: "A buyer return moves the listing `SOLD` → `RETURNED` and is only possible while the manifest's money is still fluid: if any settlement of the owning manifest is `FINALIZED` or `PAID`, the return is rejected with `ERR_SETTLEMENT_ALREADY_FINALIZED`."

        Design: Corner/validations/return_after_finalize_rejected
        """
        ctx = setup_finalized_settlement(sale_price_cents=60000)

        resp = api.return_listing(ctx["listing"]["id"], intake_operator_headers)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_ALREADY_FINALIZED)
        assert resp.status_code == 422

        item = validate_success(api.get_item(ctx["item"]["id"], intake_operator_headers))
        assert item["processing_status"] == "COMPLETE"


class TestReturnCascadeRecomputesQuote:
    def _setup_sold_with_quote(self, api):
        """One grade-A laptop sold at 60000, then a QUOTE created against the
        realized sale. Returns (ctx, settlement)."""
        ctx = setup_sold_item(sale_price_cents=60000)
        settlement = create_quote_settlement(ctx["manifest"]["id"])
        return ctx, settlement

    def test_return_recomputes_open_quote_to_catalog_estimate(self, api, intake_operator_headers,
                                                              platform_admin_headers):
        """PRD §3.6: "The return cascade then does three things — the item moves `SOLD` → `FOR_RESALE`, its `final_value_cents` is reset to zero, and any `QUOTE_OPEN` settlement of the owning manifest is recomputed under the quote variant of §3.8 with that settlement's `version` incremented."
        PRD §3.8: "an item already `SOLD` contributes its realized `final_value_cents`, while an unsold item contributes its catalog estimate — a base value for its `category` multiplied by the multiplier for its `declared_grade`, rounded half-up to whole cents."

        Design: Difficulty/transitive_cascade/listing_return_depth2_quote_recompute
        """
        ctx, settlement = self._setup_sold_with_quote(api)
        # SOLD at 60000 with 15% STANDARD commission -> realized 51000.
        assert settlement["gross_buyback_cents"] == 51000

        listing = validate_success(api.return_listing(ctx["listing"]["id"],
                                                      intake_operator_headers))
        assert listing["status"] == "RETURNED"

        settlement = validate_success(api.get_settlement(settlement["id"],
                                                         platform_admin_headers))
        assert settlement["status"] == "QUOTE_OPEN"
        # Unsold again -> catalog estimate 40000 (LAPTOP base x grade A).
        assert settlement["gross_buyback_cents"] == 40000

    def test_return_reverts_item_and_resets_final_value(self, api, intake_operator_headers):
        """PRD §3.6: "The return cascade then does three things — the item moves `SOLD` → `FOR_RESALE`, its `final_value_cents` is reset to zero, and any `QUOTE_OPEN` settlement of the owning manifest is recomputed under the quote variant of §3.8 with that settlement's `version` incremented."

        Design: Difficulty/transitive_cascade/listing_return_depth2_quote_recompute
        """
        ctx, settlement = self._setup_sold_with_quote(api)
        assert settlement["gross_buyback_cents"] == 51000

        listing = validate_success(api.return_listing(ctx["listing"]["id"],
                                                      intake_operator_headers))
        assert listing["status"] == "RETURNED"

        item = validate_success(api.get_item(ctx["item"]["id"], intake_operator_headers))
        assert item["processing_status"] == "FOR_RESALE"
        assert item["final_value_cents"] == 0
