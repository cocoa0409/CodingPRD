"""API client: one method per endpoint the PRD declares.

Every resource is mounted flat under the ``/political-ads`` prefix; the logical
clock control sits outside it at ``/_clock/set_current_utc``.
"""

from prd_bench_local_runner.testing import GenericApiClient

P = "/political-ads"


class ApiClient(GenericApiClient):

    # ---------------------------------------------------- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --------------------------------------------------------- stations ----
    def create_station(self, payload, headers):
        return self._request("POST", f"{P}/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"{P}/stations/{station_id}", headers=headers)

    def audit_sweep(self, station_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/stations/{station_id}/audit-sweep", payload or {}, headers
        )

    # -------------------------------------------------------- elections ----
    def create_election(self, payload, headers):
        return self._request("POST", f"{P}/elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request("GET", f"{P}/elections/{election_id}", headers=headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", f"{P}/elections", headers=headers, params=params)

    def create_luc_determination(self, election_id, payload, headers):
        return self._request(
            "POST", f"{P}/elections/{election_id}/luc-determinations", payload, headers
        )

    # ------------------------------------------------------ advertisers ----
    def create_advertiser(self, payload, headers):
        return self._request("POST", f"{P}/advertisers", payload, headers)

    def get_advertiser(self, advertiser_id, headers):
        return self._request("GET", f"{P}/advertisers/{advertiser_id}", headers=headers)

    def list_advertisers(self, headers, params=None):
        return self._request("GET", f"{P}/advertisers", headers=headers, params=params)

    def review_advertiser(self, advertiser_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/advertisers/{advertiser_id}/review", payload or {}, headers
        )

    def decide_advertiser(self, advertiser_id, payload, headers):
        return self._request(
            "POST", f"{P}/advertisers/{advertiser_id}/decision", payload, headers
        )

    # ----------------------------------------------------- rate classes ----
    def create_rate_class(self, payload, headers):
        return self._request("POST", f"{P}/rate-classes", payload, headers)

    def get_rate_class(self, rate_class_id, headers):
        return self._request("GET", f"{P}/rate-classes/{rate_class_id}", headers=headers)

    def list_rate_classes(self, headers, params=None):
        return self._request("GET", f"{P}/rate-classes", headers=headers, params=params)

    def withdraw_rate_class(self, rate_class_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/rate-classes/{rate_class_id}/withdraw", payload or {}, headers
        )

    # ----------------------------------------------------------- orders ----
    def create_order(self, payload, headers):
        return self._request("POST", f"{P}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{P}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{P}/orders", headers=headers, params=params)

    def add_spot(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/spots", payload, headers)

    def submit_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/orders/{order_id}/submit", payload or {}, headers
        )

    def decide_order(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/decision", payload, headers)

    def record_payment(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/payments", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"{P}/orders/{order_id}/cancel", payload, headers)

    # ------------------------------------------------------------ spots ----
    def get_spot(self, spot_id, headers):
        return self._request("GET", f"{P}/spots/{spot_id}", headers=headers)

    def list_spots(self, headers, params=None):
        return self._request("GET", f"{P}/spots", headers=headers, params=params)

    def set_spot_disposition(self, spot_id, payload, headers):
        return self._request("POST", f"{P}/spots/{spot_id}/disposition", payload, headers)

    # ----------------------------------------------- political file ------ -
    def get_file_entry(self, entry_id, headers):
        return self._request("GET", f"{P}/file-entries/{entry_id}", headers=headers)

    def list_file_entries(self, headers, params=None):
        return self._request("GET", f"{P}/file-entries", headers=headers, params=params)

    def post_file_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{P}/file-entries/{entry_id}/post", payload, headers
        )

    # ----------------------------------------- equal-opportunity requests ---
    def create_eo_request(self, payload, headers):
        return self._request("POST", f"{P}/eo-requests", payload, headers)

    def get_eo_request(self, request_id, headers):
        return self._request("GET", f"{P}/eo-requests/{request_id}", headers=headers)

    def list_eo_requests(self, headers, params=None):
        return self._request("GET", f"{P}/eo-requests", headers=headers, params=params)

    def respond_eo_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{P}/eo-requests/{request_id}/respond", payload, headers
        )

    # ------------------------------------------- lowest-unit-charge rows ----
    def get_luc_determination(self, determination_id, headers):
        return self._request(
            "GET", f"{P}/luc-determinations/{determination_id}", headers=headers
        )

    def list_luc_determinations(self, headers, params=None):
        return self._request(
            "GET", f"{P}/luc-determinations", headers=headers, params=params
        )

    # ---------------------------------------------------- rebate ledger ----
    def get_rebate(self, rebate_id, headers):
        return self._request("GET", f"{P}/rebates/{rebate_id}", headers=headers)

    def list_rebates(self, headers, params=None):
        return self._request("GET", f"{P}/rebates", headers=headers, params=params)

    # -------------------------------------------------------- complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{P}/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{P}/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", f"{P}/complaints", headers=headers, params=params)

    def respond_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{P}/complaints/{complaint_id}/respond", payload, headers
        )


api_client = ApiClient()
