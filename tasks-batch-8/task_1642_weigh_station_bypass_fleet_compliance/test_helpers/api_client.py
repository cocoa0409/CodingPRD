"""API client: one method per endpoint defined in the PRD.

All resources are served under the /api prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

API = "/api"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{API}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", f"{API}/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{API}/carriers/{carrier_id}", headers=headers)

    def transition_carrier(self, carrier_id, to_status, headers):
        return self._request("POST", f"{API}/carriers/{carrier_id}/transition",
                             {"to_status": to_status}, headers)

    def close_billing_period(self, carrier_id, period_year, period_month, headers):
        return self._request("POST", f"{API}/carriers/{carrier_id}/close-billing-period",
                             {"period_year": period_year, "period_month": period_month},
                             headers)

    def get_invoice_preview(self, carrier_id, headers, params=None):
        return self._request("GET", f"{API}/carriers/{carrier_id}/invoice-preview",
                             headers=headers, params=params)

    def get_roi_report(self, carrier_id, headers, params=None):
        return self._request("GET", f"{API}/carriers/{carrier_id}/roi-report",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # State program configs & stations
    # ------------------------------------------------------------------
    def create_config(self, payload, headers):
        return self._request("POST", f"{API}/state-program-configs", payload, headers)

    def get_config(self, config_id, headers):
        return self._request("GET", f"{API}/state-program-configs/{config_id}",
                             headers=headers)

    def patch_config(self, config_id, payload, headers):
        return self._request("PATCH", f"{API}/state-program-configs/{config_id}",
                             payload, headers)

    def create_station(self, payload, headers):
        return self._request("POST", f"{API}/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", f"{API}/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"{API}/stations/{station_id}", headers=headers)

    def patch_station(self, station_id, payload, headers):
        return self._request("PATCH", f"{API}/stations/{station_id}", payload, headers)

    # ------------------------------------------------------------------
    # Vehicles
    # ------------------------------------------------------------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", f"{API}/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", f"{API}/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"{API}/vehicles/{vehicle_id}", headers=headers)

    def patch_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"{API}/vehicles/{vehicle_id}", payload, headers)

    # ------------------------------------------------------------------
    # Bypass credentials
    # ------------------------------------------------------------------
    def create_credential(self, payload, headers):
        return self._request("POST", f"{API}/bypass-credentials", payload, headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", f"{API}/bypass-credentials", headers=headers,
                             params=params)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"{API}/bypass-credentials/{credential_id}",
                             headers=headers)

    def transition_credential(self, credential_id, to_status, headers):
        return self._request("POST",
                             f"{API}/bypass-credentials/{credential_id}/transition",
                             {"to_status": to_status}, headers)

    # ------------------------------------------------------------------
    # Safety score snapshots
    # ------------------------------------------------------------------
    def create_snapshot(self, payload, headers):
        return self._request("POST", f"{API}/safety-score-snapshots", payload, headers)

    def list_snapshots(self, headers, params=None):
        return self._request("GET", f"{API}/safety-score-snapshots", headers=headers,
                             params=params)

    def get_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"{API}/safety-score-snapshots/{snapshot_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Bypass events
    # ------------------------------------------------------------------
    def create_event(self, payload, headers):
        return self._request("POST", f"{API}/bypass-events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", f"{API}/bypass-events", headers=headers,
                             params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"{API}/bypass-events/{event_id}", headers=headers)

    # ------------------------------------------------------------------
    # Bypass disputes
    # ------------------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", f"{API}/bypass-disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", f"{API}/bypass-disputes", headers=headers,
                             params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"{API}/bypass-disputes/{dispute_id}",
                             headers=headers)

    def adjudicate_dispute(self, dispute_id, payload, headers):
        return self._request("POST",
                             f"{API}/bypass-disputes/{dispute_id}/adjudicate",
                             payload, headers)

    def appeal_dispute(self, dispute_id, headers):
        return self._request("POST", f"{API}/bypass-disputes/{dispute_id}/appeal",
                             {}, headers)

    # ------------------------------------------------------------------
    # Eligibility overrides
    # ------------------------------------------------------------------
    def create_override(self, payload, headers):
        return self._request("POST", f"{API}/eligibility-overrides", payload, headers)

    def list_overrides(self, headers, params=None):
        return self._request("GET", f"{API}/eligibility-overrides", headers=headers,
                             params=params)

    def get_override(self, override_id, headers):
        return self._request("GET", f"{API}/eligibility-overrides/{override_id}",
                             headers=headers)

    def decide_override(self, override_id, outcome, headers):
        return self._request("POST",
                             f"{API}/eligibility-overrides/{override_id}/decide",
                             {"outcome": outcome}, headers)

    # ------------------------------------------------------------------
    # Vehicle subscriptions
    # ------------------------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", f"{API}/vehicle-subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", f"{API}/vehicle-subscriptions", headers=headers,
                             params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"{API}/vehicle-subscriptions/{subscription_id}",
                             headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST",
                             f"{API}/vehicle-subscriptions/{subscription_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{API}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{API}/invoices/{invoice_id}", headers=headers)

    def record_payment(self, invoice_id, amount_cents, headers):
        return self._request("POST", f"{API}/invoices/{invoice_id}/record-payment",
                             {"amount_cents": amount_cents}, headers)

    # ------------------------------------------------------------------
    # Inspection reports
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{API}/inspection-reports", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", f"{API}/inspection-reports", headers=headers,
                             params=params)

    def get_inspection(self, report_id, headers):
        return self._request("GET", f"{API}/inspection-reports/{report_id}",
                             headers=headers)


api_client = ApiClient()
