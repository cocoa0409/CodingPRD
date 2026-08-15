"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- party onboarding (PRD §3.1) ---
    def create_seller(self, payload, headers):
        return self._request("POST", "/api/sellers", payload, headers)

    def create_agent(self, payload, headers):
        return self._request("POST", "/api/agents", payload, headers)

    def create_buyer(self, payload, headers):
        return self._request("POST", "/api/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/api/buyers/{buyer_id}", headers=headers)

    def qualify_buyer(self, buyer_id, payload, headers):
        return self._request(
            "POST", f"/api/buyers/{buyer_id}/qualify", payload, headers
        )

    # --- listings and tracts (PRD §3.2) ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/api/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/api/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/api/listings", headers=headers, params=params)

    def create_tract(self, payload, headers):
        return self._request("POST", "/api/tracts", payload, headers)

    def get_tract(self, tract_id, headers):
        return self._request("GET", f"/api/tracts/{tract_id}", headers=headers)

    def list_tracts(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"/api/listings/{listing_id}/tracts", headers=headers, params=params
        )

    def package_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/api/listings/{listing_id}/package", headers=headers
        )

    def market_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/api/listings/{listing_id}/market", headers=headers
        )

    def withdraw_listing(self, listing_id, headers):
        return self._request(
            "POST", f"/api/listings/{listing_id}/withdraw", headers=headers
        )

    # --- comparables and valuation (PRD §3.3) ---
    def create_comparable(self, payload, headers):
        return self._request("POST", "/api/comparables", payload, headers)

    def get_valuation(self, tract_id, headers, variant="PROVISIONAL"):
        return self._request(
            "GET",
            f"/api/tracts/{tract_id}/valuation",
            headers=headers,
            params={"variant": variant},
        )

    # --- auctions (PRD §3.5, §3.7) ---
    def create_auction(self, payload, headers):
        return self._request("POST", "/api/auctions", payload, headers)

    def get_auction(self, auction_id, headers):
        return self._request("GET", f"/api/auctions/{auction_id}", headers=headers)

    def list_auctions(self, listing_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/listings/{listing_id}/auctions",
            headers=headers,
            params=params,
        )

    def open_auction(self, auction_id, headers):
        return self._request(
            "POST", f"/api/auctions/{auction_id}/open", headers=headers
        )

    def award_auction(self, auction_id, headers):
        return self._request(
            "POST", f"/api/auctions/{auction_id}/award", headers=headers
        )

    def no_sale_auction(self, auction_id, headers):
        return self._request(
            "POST", f"/api/auctions/{auction_id}/no-sale", headers=headers
        )

    # --- bids (PRD §3.6) ---
    def place_bid(self, payload, headers):
        return self._request("POST", "/api/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/api/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/api/bids", headers=headers, params=params)

    # --- earnest-money deposits (PRD §3.7) ---
    def record_payment(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"/api/deposits/{deposit_id}/record-payment", payload, headers
        )

    def verify_deposit(self, deposit_id, headers):
        return self._request(
            "POST", f"/api/deposits/{deposit_id}/verify", headers=headers
        )

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/api/deposits/{deposit_id}", headers=headers)

    def list_bid_deposits(self, bid_id, headers):
        return self._request(
            "GET", f"/api/bids/{bid_id}/deposits", headers=headers
        )

    # --- lease disclosures and rights (PRD §3.4) ---
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/api/disclosures", payload, headers)

    def acknowledge_disclosure(self, disclosure_id, headers):
        return self._request(
            "POST", f"/api/disclosures/{disclosure_id}/acknowledge", headers=headers
        )

    def list_tract_disclosures(self, tract_id, headers):
        return self._request(
            "GET", f"/api/tracts/{tract_id}/disclosures", headers=headers
        )

    def create_rights(self, payload, headers):
        return self._request("POST", "/api/rights", payload, headers)

    def list_tract_rights(self, tract_id, headers):
        return self._request("GET", f"/api/tracts/{tract_id}/rights", headers=headers)

    # --- closings and statements (PRD §3.8) ---
    def create_closing(self, payload, headers):
        return self._request("POST", "/api/closings", payload, headers)

    def get_closing(self, closing_id, headers):
        return self._request("GET", f"/api/closings/{closing_id}", headers=headers)

    def list_auction_closings(self, auction_id, headers):
        return self._request(
            "GET", f"/api/auctions/{auction_id}/closings", headers=headers
        )

    def post_track_event(self, closing_id, payload, headers):
        return self._request(
            "POST", f"/api/closings/{closing_id}/track-events", payload, headers
        )

    def create_statement(self, payload, headers):
        return self._request("POST", "/api/statements", payload, headers)

    def list_closing_statements(self, closing_id, headers):
        return self._request(
            "GET", f"/api/closings/{closing_id}/statements", headers=headers
        )

    def terminate_closing(self, closing_id, headers):
        return self._request(
            "POST", f"/api/closings/{closing_id}/terminate", headers=headers
        )


api_client = ApiClient()
