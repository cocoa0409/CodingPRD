"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.10)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Client accounts
    # ------------------------------------------------------------------
    def create_client_account(self, payload, headers):
        return self._request("POST", "/bpo/client-accounts", payload, headers)

    def list_client_accounts(self, headers, params=None):
        return self._request("GET", "/bpo/client-accounts", headers=headers, params=params)

    def get_client_account(self, client_id, headers):
        return self._request("GET", f"/bpo/client-accounts/{client_id}", headers=headers)

    # ------------------------------------------------------------------
    # State regulations
    # ------------------------------------------------------------------
    def create_state_regulation(self, payload, headers):
        return self._request("POST", "/bpo/state-regulations", payload, headers)

    def list_state_regulations(self, headers, params=None):
        return self._request("GET", "/bpo/state-regulations", headers=headers, params=params)

    def get_state_regulation(self, state_code, headers):
        return self._request("GET", f"/bpo/state-regulations/{state_code}", headers=headers)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", "/bpo/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/bpo/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/bpo/properties/{property_id}", headers=headers)

    def list_property_comparables(self, property_id, headers, params=None):
        return self._request("GET", f"/bpo/properties/{property_id}/comparables",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Brokers and licenses
    # ------------------------------------------------------------------
    def create_broker(self, payload, headers):
        return self._request("POST", "/bpo/brokers", payload, headers)

    def list_brokers(self, headers, params=None):
        return self._request("GET", "/bpo/brokers", headers=headers, params=params)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/bpo/brokers/{broker_id}", headers=headers)

    def activate_broker(self, broker_id, headers):
        return self._request("POST", f"/bpo/brokers/{broker_id}/activate", {}, headers)

    def suspend_broker(self, broker_id, headers):
        return self._request("POST", f"/bpo/brokers/{broker_id}/suspend", {}, headers)

    def reinstate_broker(self, broker_id, headers):
        return self._request("POST", f"/bpo/brokers/{broker_id}/reinstate", {}, headers)

    def terminate_broker(self, broker_id, headers):
        return self._request("POST", f"/bpo/brokers/{broker_id}/terminate", {}, headers)

    def create_broker_license(self, broker_id, payload, headers):
        return self._request("POST", f"/bpo/brokers/{broker_id}/licenses", payload, headers)

    def list_broker_licenses(self, broker_id, headers, params=None):
        return self._request("GET", f"/bpo/brokers/{broker_id}/licenses",
                             headers=headers, params=params)

    def list_broker_photos(self, broker_id, headers, params=None):
        return self._request("GET", f"/bpo/brokers/{broker_id}/photos",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Valuation orders
    # ------------------------------------------------------------------
    def create_valuation_order(self, payload, headers):
        return self._request("POST", "/bpo/valuation-orders", payload, headers)

    def list_valuation_orders(self, headers, params=None):
        return self._request("GET", "/bpo/valuation-orders", headers=headers, params=params)

    def get_valuation_order(self, order_id, headers):
        return self._request("GET", f"/bpo/valuation-orders/{order_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/submit", {}, headers)

    def dispatch_order(self, order_id, payload, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/dispatch",
                             payload, headers)

    def accept_order(self, order_id, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/accept", {}, headers)

    def decline_order(self, order_id, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/decline", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Comparables
    # ------------------------------------------------------------------
    def create_comparable(self, order_id, payload, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/comparables",
                             payload, headers)

    def list_comparables(self, order_id, headers, params=None):
        return self._request("GET", f"/bpo/valuation-orders/{order_id}/comparables",
                             headers=headers, params=params)

    def select_comparable(self, order_id, comp_id, headers):
        return self._request(
            "POST", f"/bpo/valuation-orders/{order_id}/comparables/{comp_id}/select",
            {}, headers)

    def reject_comparable(self, order_id, comp_id, headers):
        return self._request(
            "POST", f"/bpo/valuation-orders/{order_id}/comparables/{comp_id}/reject",
            {}, headers)

    # ------------------------------------------------------------------
    # Photo evidence
    # ------------------------------------------------------------------
    def create_photo(self, order_id, payload, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/photos",
                             payload, headers)

    def list_photos(self, order_id, headers, params=None):
        return self._request("GET", f"/bpo/valuation-orders/{order_id}/photos",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fee lines
    # ------------------------------------------------------------------
    def create_fee_line(self, order_id, payload, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/fee-lines",
                             payload, headers)

    def list_fee_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/bpo/valuation-orders/{order_id}/fee-lines",
                             headers=headers, params=params)

    def confirm_fee_line(self, order_id, fee_id, headers):
        return self._request(
            "POST", f"/bpo/valuation-orders/{order_id}/fee-lines/{fee_id}/confirm",
            {}, headers)

    def cancel_fee_line(self, order_id, fee_id, headers):
        return self._request(
            "POST", f"/bpo/valuation-orders/{order_id}/fee-lines/{fee_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Report submission and quality control
    # ------------------------------------------------------------------
    def submit_report(self, order_id, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/report", {}, headers)

    def open_qc_review(self, order_id, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/qc/open", {}, headers)

    def list_qc_reviews(self, order_id, headers, params=None):
        return self._request("GET", f"/bpo/valuation-orders/{order_id}/qc",
                             headers=headers, params=params)

    def get_qc_review(self, qc_id, headers):
        return self._request("GET", f"/bpo/qc-reviews/{qc_id}", headers=headers)

    def list_qc_review_revisions(self, qc_id, headers, params=None):
        return self._request("GET", f"/bpo/qc-reviews/{qc_id}/revisions",
                             headers=headers, params=params)

    def record_qc_verdict(self, order_id, qc_id, payload, headers):
        return self._request(
            "POST", f"/bpo/valuation-orders/{order_id}/qc/{qc_id}/verdict",
            payload, headers)

    def list_order_revisions(self, order_id, headers, params=None):
        return self._request("GET", f"/bpo/valuation-orders/{order_id}/revisions",
                             headers=headers, params=params)

    def resubmit_revision(self, order_id, rev_id, headers):
        return self._request(
            "POST", f"/bpo/valuation-orders/{order_id}/revision/{rev_id}/resubmit",
            {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/bpo/valuation-orders/{order_id}/complete",
                             {}, headers)

    # ------------------------------------------------------------------
    # Payout batches
    # ------------------------------------------------------------------
    def create_payout_batch(self, payload, headers):
        return self._request("POST", "/bpo/payout-batches", payload, headers)

    def list_payout_batches(self, headers, params=None):
        return self._request("GET", "/bpo/payout-batches", headers=headers, params=params)

    def get_payout_batch(self, batch_id, headers):
        return self._request("GET", f"/bpo/payout-batches/{batch_id}", headers=headers)

    def approve_payout_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/bpo/payout-batches/{batch_id}/approve",
                             payload, headers)

    def disburse_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/bpo/payout-batches/{batch_id}/disburse", {}, headers)

    def void_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/bpo/payout-batches/{batch_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Volume forecasts
    # ------------------------------------------------------------------
    def create_volume_forecast(self, payload, headers):
        return self._request("POST", "/bpo/volume-forecasts", payload, headers)

    def list_volume_forecasts(self, headers, params=None):
        return self._request("GET", "/bpo/volume-forecasts", headers=headers, params=params)


api_client = ApiClient()
