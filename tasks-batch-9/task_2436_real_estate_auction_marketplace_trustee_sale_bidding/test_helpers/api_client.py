"""API client: one method per endpoint the PRD defines."""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """Trustee Auction Marketplace client. Every method returns the raw response."""

    # ------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)

    # ----------------------------------------------------------- sellers
    def create_seller(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"{API_PREFIX}/sellers/{seller_id}", headers=headers)

    def list_seller_asset_listings(self, seller_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/sellers/{seller_id}/asset-listings",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------- asset listings
    def create_asset_listing(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/asset-listings", payload, headers)

    def file_disclosures(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/asset-listings/{listing_id}/disclosures", payload, headers
        )

    def record_title_clearance(self, listing_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/asset-listings/{listing_id}/title-clearance",
            payload,
            headers,
        )

    def relist_asset_listing(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/asset-listings/{listing_id}/relist", payload, headers
        )

    def get_asset_listing(self, listing_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/asset-listings/{listing_id}", headers=headers
        )

    def list_asset_listings(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/asset-listings", headers=headers, params=params
        )

    def list_asset_listing_trustee_sales(self, listing_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/asset-listings/{listing_id}/trustee-sales",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------- trustee sales
    def create_trustee_sale(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/trustee-sales", payload, headers)

    def confirm_trustee_sale(self, sale_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/trustee-sales/{sale_id}/confirm", payload, headers
        )

    def postpone_trustee_sale(self, sale_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/trustee-sales/{sale_id}/postpone", payload, headers
        )

    def cancel_trustee_sale(self, sale_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/trustee-sales/{sale_id}/cancel", payload, headers
        )

    def get_trustee_sale(self, sale_id, headers):
        return self._request("GET", f"{API_PREFIX}/trustee-sales/{sale_id}", headers=headers)

    def list_trustee_sale_auction_events(self, sale_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/trustee-sales/{sale_id}/auction-events",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------- auction events
    def create_auction_event(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/auction-events", payload, headers)

    def add_lot(self, event_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/auction-events/{event_id}/lots", payload, headers
        )

    def open_auction_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/auction-events/{event_id}/open", payload, headers
        )

    def reschedule_auction_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/auction-events/{event_id}/reschedule", payload, headers
        )

    def get_auction_event(self, event_id, headers):
        return self._request("GET", f"{API_PREFIX}/auction-events/{event_id}", headers=headers)

    def list_auction_events(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/auction-events", headers=headers, params=params
        )

    # ------------------------------------------------------ auction lots
    def update_reserve_price(self, lot_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/auction-lots/{lot_id}/reserve-price", payload, headers
        )

    def place_bid(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/auction-lots/{lot_id}/bids", payload, headers
        )

    def close_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/auction-lots/{lot_id}/close", payload, headers
        )

    def execute_sale_contract(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/auction-lots/{lot_id}/sale-contract", payload, headers
        )

    def create_second_chance_offer(self, lot_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/auction-lots/{lot_id}/second-chance-offers",
            payload,
            headers,
        )

    def get_auction_lot(self, lot_id, headers):
        return self._request("GET", f"{API_PREFIX}/auction-lots/{lot_id}", headers=headers)

    def list_auction_lots(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/auction-lots", headers=headers, params=params
        )

    def list_lot_sale_contracts(self, lot_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/auction-lots/{lot_id}/sale-contracts",
            headers=headers,
            params=params,
        )

    def get_settlement_preview(self, lot_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/auction-lots/{lot_id}/settlement-preview",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------- bidders
    def create_bidder(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/bidders", payload, headers)

    def record_identity_verification(self, bidder_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/bidders/{bidder_id}/identity-verification",
            payload,
            headers,
        )

    def fund_deposit(self, bidder_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/bidders/{bidder_id}/deposits", payload, headers
        )

    def get_bidder(self, bidder_id, headers):
        return self._request("GET", f"{API_PREFIX}/bidders/{bidder_id}", headers=headers)

    def list_bidder_exclusions(self, bidder_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/bidders/{bidder_id}/eligibility-exclusions",
            headers=headers,
            params=params,
        )

    def get_eligibility_assessment(self, bidder_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/bidders/{bidder_id}/eligibility-assessment",
            headers=headers,
            params=params,
        )

    # --------------------------------------------- eligibility exclusions
    def create_eligibility_exclusion(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/eligibility-exclusions", payload, headers)

    def lift_eligibility_exclusion(self, exclusion_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/eligibility-exclusions/{exclusion_id}/lift",
            payload,
            headers,
        )

    # -------------------------------------------------------------- bids
    def get_bid(self, bid_id, headers):
        return self._request("GET", f"{API_PREFIX}/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/bids", headers=headers, params=params)

    # ----------------------------------------------------- deposit holds
    def get_deposit_hold(self, hold_id, headers):
        return self._request("GET", f"{API_PREFIX}/deposit-holds/{hold_id}", headers=headers)

    def list_deposit_holds(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/deposit-holds", headers=headers, params=params
        )

    # ---------------------------------------------------- sale contracts
    def close_sale_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sale-contracts/{contract_id}/close", payload, headers
        )

    def record_fallout(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sale-contracts/{contract_id}/fallout", payload, headers
        )

    def get_sale_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/sale-contracts/{contract_id}", headers=headers
        )

    # ----------------------------------------------- second-chance offers
    def respond_to_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/second-chance-offers/{offer_id}/respond", payload, headers
        )

    def get_second_chance_offer(self, offer_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/second-chance-offers/{offer_id}", headers=headers
        )

    def list_second_chance_offers(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/second-chance-offers", headers=headers, params=params
        )


api_client = ApiClient()
