"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facility_tenants(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/tenants", headers=headers, params=params)

    # --- Tenant ---
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # --- StorageUnit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def create_lien_notice(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/lien-notices", payload, headers)

    def cure_unit(self, unit_id, headers):
        return self._request("POST", f"/units/{unit_id}/cure", {}, headers)

    # --- LienNotice ---
    def get_lien_notice(self, lien_notice_id, headers):
        return self._request("GET", f"/lien-notices/{lien_notice_id}", headers=headers)

    def list_unit_lien_notices(self, unit_id, headers, params=None):
        return self._request("GET", f"/units/{unit_id}/lien-notices", headers=headers, params=params)

    def mature_lien_notice(self, lien_notice_id, headers):
        return self._request("POST", f"/lien-notices/{lien_notice_id}/mature", {}, headers)

    # --- Auction ---
    def create_auction(self, payload, headers):
        return self._request("POST", "/auctions", payload, headers)

    def get_auction(self, auction_id, headers):
        return self._request("GET", f"/auctions/{auction_id}", headers=headers)

    def list_unit_auctions(self, unit_id, headers, params=None):
        return self._request("GET", f"/units/{unit_id}/auctions", headers=headers, params=params)

    def open_auction(self, auction_id, headers):
        return self._request("POST", f"/auctions/{auction_id}/open", {}, headers)

    def close_auction(self, auction_id, headers):
        return self._request("POST", f"/auctions/{auction_id}/close", {}, headers)

    def place_bid(self, auction_id, payload, headers):
        return self._request("POST", f"/auctions/{auction_id}/bids", payload, headers)

    # --- Bid ---
    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def retract_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/retract", {}, headers)

    # --- Buyer ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    def fund_deposit(self, buyer_id, payload, headers):
        return self._request("POST", f"/buyers/{buyer_id}/fund-deposit", payload, headers)

    # --- Sale ---
    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def pay_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/pay", {}, headers)

    def cleanout_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/cleanout", {}, headers)

    def forfeit_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/forfeit", {}, headers)

    # --- Settlement ---
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def get_sale_settlement(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}/settlement", headers=headers)

    # --- Dispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/review", {}, headers)

    def request_info_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/request-info", {}, headers)

    def provide_info_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/provide-info", payload, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
