"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (Section 2.6) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- watch models ---
    def create_watch_model(self, payload, headers):
        return self._request("POST", "/watch-models", payload, headers)

    def get_watch_model(self, model_id, headers):
        return self._request("GET", f"/watch-models/{model_id}", headers=headers)

    # --- watchmakers ---
    def create_watchmaker(self, payload, headers):
        return self._request("POST", "/watchmakers", payload, headers)

    def get_watchmaker(self, watchmaker_id, headers):
        return self._request("GET", f"/watchmakers/{watchmaker_id}", headers=headers)

    # --- watches (inventory) ---
    def create_watch(self, payload, headers):
        return self._request("POST", "/watches", payload, headers)

    def get_watch(self, watch_id, headers):
        return self._request("GET", f"/watches/{watch_id}", headers=headers)

    def list_watches(self, headers, params=None):
        return self._request("GET", "/watches", headers=headers, params=params)

    def authenticate_watch(self, watch_id, headers):
        return self._request("POST", f"/watches/{watch_id}/authenticate", {}, headers)

    def flag_watch(self, watch_id, headers, payload=None):
        return self._request(
            "POST", f"/watches/{watch_id}/flag-inauthentic", payload or {}, headers
        )

    def get_provenance(self, watch_id, headers, params=None):
        return self._request(
            "GET", f"/watches/{watch_id}/provenance", headers=headers, params=params
        )

    def create_appraisal(self, watch_id, payload, headers):
        return self._request("POST", f"/watches/{watch_id}/appraisals", payload, headers)

    def list_appraisals(self, watch_id, headers, params=None):
        return self._request(
            "GET", f"/watches/{watch_id}/appraisals", headers=headers, params=params
        )

    def offer_watch(self, watch_id, headers):
        return self._request("POST", f"/watches/{watch_id}/offer", {}, headers)

    # --- waitlist ---
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/waitlist-entries", payload, headers)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def accept_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/accept", {}, headers)

    def decline_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/decline", {}, headers)

    # --- service tickets ---
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def diagnose_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/diagnose", {}, headers)

    def finish_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/finish", {}, headers)

    def collect_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/collect", {}, headers)

    def pay_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/payments", payload, headers
        )

    # --- layaway ---
    def create_layaway_plan(self, payload, headers):
        return self._request("POST", "/layaway-plans", payload, headers)

    def get_layaway_plan(self, plan_id, headers):
        return self._request("GET", f"/layaway-plans/{plan_id}", headers=headers)

    def list_layaway_plans(self, headers, params=None):
        return self._request("GET", "/layaway-plans", headers=headers, params=params)

    def pay_layaway(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/layaway-plans/{plan_id}/payments", payload, headers
        )

    def default_layaway(self, plan_id, headers):
        return self._request("POST", f"/layaway-plans/{plan_id}/default", {}, headers)

    def cancel_layaway(self, plan_id, headers):
        return self._request("POST", f"/layaway-plans/{plan_id}/cancel", {}, headers)

    # --- trade-in / consignment ---
    def create_trade_in_offer(self, payload, headers):
        return self._request("POST", "/trade-in-offers", payload, headers)

    def get_trade_in_offer(self, offer_id, headers):
        return self._request("GET", f"/trade-in-offers/{offer_id}", headers=headers)

    def list_trade_in_offers(self, headers, params=None):
        return self._request("GET", "/trade-in-offers", headers=headers, params=params)

    def accept_trade_in_offer(self, offer_id, headers):
        return self._request("POST", f"/trade-in-offers/{offer_id}/accept", {}, headers)

    def settle_trade_in_offer(self, offer_id, headers):
        return self._request("POST", f"/trade-in-offers/{offer_id}/settle", {}, headers)


api_client = ApiClient()
