"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- configuration ---
    def create_price_config(self, payload, headers):
        return self._request("POST", "/price-configs", payload, headers)

    def list_price_configs(self, headers, params=None):
        return self._request("GET", "/price-configs", headers=headers, params=params)

    def create_variety_config(self, payload, headers):
        return self._request("POST", "/variety-configs", payload, headers)

    def list_variety_configs(self, headers, params=None):
        return self._request("GET", "/variety-configs", headers=headers, params=params)

    # --- customers & crews ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def deactivate_crew(self, crew_id, headers):
        return self._request("POST", f"/crews/{crew_id}/deactivate", {}, headers)

    def list_crew_referrals_for_crew(self, crew_id, headers, params=None):
        return self._request(
            "GET", f"/crews/{crew_id}/crew-referrals", headers=headers, params=params
        )

    # --- fields & re-seeding ---
    def create_field(self, payload, headers):
        return self._request("POST", "/fields", payload, headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/fields", headers=headers, params=params)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/fields/{field_id}", headers=headers)

    def update_field_quality(self, field_id, payload, headers):
        return self._request("PATCH", f"/fields/{field_id}/quality", payload, headers)

    def maturity_scan(self, field_id, headers):
        return self._request("POST", f"/fields/{field_id}/maturity-scan", {}, headers)

    def archive_field(self, field_id, headers):
        return self._request("POST", f"/fields/{field_id}/archive", {}, headers)

    def create_reseed_plan(self, field_id, payload, headers):
        return self._request("POST", f"/fields/{field_id}/reseed-plans", payload, headers)

    def list_reseed_plans(self, field_id, headers, params=None):
        return self._request(
            "GET", f"/fields/{field_id}/reseed-plans", headers=headers, params=params
        )

    def start_reseed_plan(self, plan_id, headers):
        return self._request("POST", f"/reseed-plans/{plan_id}/start", {}, headers)

    def complete_reseed_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/reseed-plans/{plan_id}/complete", payload, headers)

    # --- harvest ---
    def create_harvest_batch(self, payload, headers):
        return self._request("POST", "/harvest-batches", payload, headers)

    def list_harvest_batches(self, headers, params=None):
        return self._request("GET", "/harvest-batches", headers=headers, params=params)

    def get_harvest_batch(self, batch_id, headers):
        return self._request("GET", f"/harvest-batches/{batch_id}", headers=headers)

    def complete_harvest_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/harvest-batches/{batch_id}/complete", payload, headers
        )

    def cancel_harvest_batch(self, batch_id, headers):
        return self._request("POST", f"/harvest-batches/{batch_id}/cancel", {}, headers)

    # --- quotes & orders ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", {}, headers)

    def list_quote_orders(self, quote_id, headers, params=None):
        return self._request(
            "GET", f"/quotes/{quote_id}/orders", headers=headers, params=params
        )

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def dispatch_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/dispatch", {}, headers)

    def mark_delivered(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/mark-delivered", payload, headers)

    def install_start(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/install-start", {}, headers)

    def install_complete(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/install-complete", {}, headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/close", {}, headers)

    def create_delivery_check(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/delivery-checks", {}, headers)

    def list_delivery_checks(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/delivery-checks", headers=headers, params=params
        )

    def create_payment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/payments", payload, headers)

    def list_payments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/payments", headers=headers, params=params
        )

    # --- crew referral & scheduling ---
    def create_crew_referral(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/crew-referrals", payload, headers)

    def list_order_crew_referrals(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/crew-referrals", headers=headers, params=params
        )

    def schedule_crew(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/crew-schedule", payload, headers)

    # --- warranty ---
    def create_warranty_claim(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/warranty-claims", payload, headers)

    def list_order_warranty_claims(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/warranty-claims", headers=headers, params=params
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def create_watering_log(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/watering-logs", payload, headers
        )

    def list_watering_logs(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/warranty-claims/{claim_id}/watering-logs", headers=headers, params=params
        )

    def evaluate_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/evaluate", {}, headers)

    # --- fleet ---
    def create_truck_block(self, payload, headers):
        return self._request("POST", "/truck-blocks", payload, headers)

    def list_truck_blocks(self, headers, params=None):
        return self._request("GET", "/truck-blocks", headers=headers, params=params)

    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
