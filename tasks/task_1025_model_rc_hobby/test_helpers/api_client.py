"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def safety_ack(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/safety-ack", {}, headers)

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # --- PreOrderCampaign ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/open", {}, headers)

    def allocate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/allocate", {}, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/cancel", {}, headers)

    # --- PreOrderReservation ---
    def create_reservation(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/pre-orders", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/pre-orders/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/pre-orders", headers=headers, params=params)

    def transition_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/pre-orders/{reservation_id}/transition", payload, headers)

    # --- Order ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def transition_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/transition", payload, headers)

    # --- ServiceJob ---
    def create_service_job(self, payload, headers):
        return self._request("POST", "/service-jobs", payload, headers)

    def get_service_job(self, job_id, headers):
        return self._request("GET", f"/service-jobs/{job_id}", headers=headers)

    def list_service_jobs(self, headers, params=None):
        return self._request("GET", "/service-jobs", headers=headers, params=params)

    def transition_service_job(self, job_id, payload, headers):
        return self._request("POST", f"/service-jobs/{job_id}/transition", payload, headers)

    # --- RaceEvent ---
    def create_race_event(self, payload, headers):
        return self._request("POST", "/race-events", payload, headers)

    def get_race_event(self, event_id, headers):
        return self._request("GET", f"/race-events/{event_id}", headers=headers)

    def transition_race_event(self, event_id, payload, headers):
        return self._request("POST", f"/race-events/{event_id}/transition", payload, headers)

    # --- RaceEntry ---
    def create_race_entry(self, event_id, payload, headers):
        return self._request("POST", f"/race-events/{event_id}/entries", payload, headers)

    def get_race_entry(self, entry_id, headers):
        return self._request("GET", f"/race-entries/{entry_id}", headers=headers)

    def list_race_entries(self, headers, params=None):
        return self._request("GET", "/race-entries", headers=headers, params=params)

    def transition_race_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/race-entries/{entry_id}/transition", payload, headers)


api_client = ApiClient()
