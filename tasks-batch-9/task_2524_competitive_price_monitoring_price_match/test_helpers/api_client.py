"""API client: one method per endpoint of the Competitive Price Intelligence API.

All endpoints are mounted under the /pricing prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/pricing"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------ markets
    def create_market(self, payload, headers):
        return self._request("POST", f"{PREFIX}/markets", payload, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", f"{PREFIX}/markets/{market_id}", headers=headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/markets", headers=headers, params=params)

    # -------------------------------------------------------------- competitors
    def create_competitor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/competitors", payload, headers)

    def patch_competitor_status(self, competitor_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/competitors/{competitor_id}/status", payload, headers
        )

    def get_competitor(self, competitor_id, headers):
        return self._request("GET", f"{PREFIX}/competitors/{competitor_id}", headers=headers)

    def list_competitors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/competitors", headers=headers, params=params)

    # ----------------------------------------------------------------- products
    def create_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    # ------------------------------------------------------------------- stores
    def create_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"{PREFIX}/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stores", headers=headers, params=params)

    # ------------------------------------------------------------------ matches
    def create_match(self, payload, headers):
        return self._request("POST", f"{PREFIX}/matches", payload, headers)

    def review_match(self, match_id, payload, headers):
        return self._request("POST", f"{PREFIX}/matches/{match_id}/review", payload, headers)

    def revise_match(self, match_id, payload, headers):
        return self._request("POST", f"{PREFIX}/matches/{match_id}/revise", payload, headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"{PREFIX}/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/matches", headers=headers, params=params)

    # ------------------------------------------------------------- observations
    def create_observation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/observations", payload, headers)

    def void_observation(self, observation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/observations/{observation_id}/void", payload, headers
        )

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"{PREFIX}/observations/{observation_id}", headers=headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/observations", headers=headers, params=params)

    # ------------------------------------------------------------ index reports
    def create_index_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/index-reports", payload, headers)

    def publish_index_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/index-reports/{report_id}/publish", payload, headers
        )

    def get_index_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/index-reports/{report_id}", headers=headers)

    def list_index_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/index-reports", headers=headers, params=params)

    # ---------------------------------------------------------- repricing rules
    def create_repricing_rule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/repricing-rules", payload, headers)

    def patch_repricing_rule_status(self, rule_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/repricing-rules/{rule_id}/status", payload, headers
        )

    def get_repricing_rule(self, rule_id, headers):
        return self._request("GET", f"{PREFIX}/repricing-rules/{rule_id}", headers=headers)

    def list_repricing_rules(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/repricing-rules", headers=headers, params=params)

    # ------------------------------------------------------------ change orders
    def create_change_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/change-orders", payload, headers)

    def submit_change_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/change-orders/{order_id}/submit", payload, headers)

    def decide_change_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/change-orders/{order_id}/decide", payload, headers)

    def execute_change_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/change-orders/{order_id}/execute", payload, headers)

    def get_change_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/change-orders/{order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/change-orders", headers=headers, params=params)

    # ----------------------------------------------------------- match policies
    def create_match_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/match-policies", payload, headers)

    def get_match_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/match-policies/{policy_id}", headers=headers)

    def list_match_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/match-policies", headers=headers, params=params)

    # ------------------------------------------------------------------- claims
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def verify_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/verify", payload, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/decide", payload, headers)

    def honor_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/honor", payload, headers)

    def reverse_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/reverse", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def list_claim_override_logs(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/override-logs", headers=headers, params=params
        )

    # ------------------------------------------------------------ label batches
    def create_label_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/label-batches", payload, headers)

    def advance_label_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/label-batches/{batch_id}/advance", payload, headers
        )

    def cancel_label_batch(self, batch_id, payload, headers):
        return self._request("POST", f"{PREFIX}/label-batches/{batch_id}/cancel", payload, headers)

    def get_label_batch(self, batch_id, headers):
        return self._request("GET", f"{PREFIX}/label-batches/{batch_id}", headers=headers)

    def list_label_batches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/label-batches", headers=headers, params=params)


api_client = ApiClient()
