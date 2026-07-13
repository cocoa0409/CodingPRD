"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- FleetAccount ---
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/fleet-accounts", payload, headers)

    def get_fleet_account(self, account_id, headers):
        return self._request("GET", f"/fleet-accounts/{account_id}", headers=headers)

    def get_fleet_account_summary(self, account_id, headers):
        return self._request("GET", f"/fleet-accounts/{account_id}/summary", headers=headers)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle_mpg(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/mpg", headers=headers, params=params)

    def retire_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/retire", {}, headers)

    # --- Driver ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    # --- FuelCard ---
    def create_fuel_card(self, payload, headers):
        return self._request("POST", "/fuel-cards", payload, headers)

    def get_fuel_card(self, card_id, headers):
        return self._request("GET", f"/fuel-cards/{card_id}", headers=headers)

    def list_fuel_cards(self, headers, params=None):
        return self._request("GET", "/fuel-cards", headers=headers, params=params)

    def activate_fuel_card(self, card_id, headers):
        return self._request("POST", f"/fuel-cards/{card_id}/activate", {}, headers)

    def suspend_fuel_card(self, card_id, headers):
        return self._request("POST", f"/fuel-cards/{card_id}/suspend", {}, headers)

    def cancel_fuel_card(self, card_id, headers):
        return self._request("POST", f"/fuel-cards/{card_id}/cancel", {}, headers)

    # --- CardAssignment ---
    def create_card_assignment(self, payload, headers):
        return self._request("POST", "/card-assignments", payload, headers)

    def get_card_assignment(self, assignment_id, headers):
        return self._request("GET", f"/card-assignments/{assignment_id}", headers=headers)

    def list_card_assignments(self, headers, params=None):
        return self._request("GET", "/card-assignments", headers=headers, params=params)

    def end_card_assignment(self, assignment_id, headers):
        return self._request("POST", f"/card-assignments/{assignment_id}/end", {}, headers)

    # --- Transaction ---
    def authorize_transaction(self, payload, headers):
        return self._request("POST", "/transactions/authorize", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def capture_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/capture", {}, headers)

    def settle_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/settle", {}, headers)

    def void_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/void", {}, headers)

    # --- FraudAlert ---
    def get_fraud_alert(self, alert_id, headers):
        return self._request("GET", f"/fraud-alerts/{alert_id}", headers=headers)

    def list_fraud_alerts(self, headers, params=None):
        return self._request("GET", "/fraud-alerts", headers=headers, params=params)

    def investigate_fraud_alert(self, alert_id, headers):
        return self._request("POST", f"/fraud-alerts/{alert_id}/investigate", {}, headers)

    def confirm_fraud_alert(self, alert_id, headers, payload=None):
        return self._request("POST", f"/fraud-alerts/{alert_id}/confirm", payload or {}, headers)

    def dismiss_fraud_alert(self, alert_id, headers, payload=None):
        return self._request("POST", f"/fraud-alerts/{alert_id}/dismiss", payload or {}, headers)

    def reopen_fraud_alert(self, alert_id, headers, payload=None):
        return self._request("POST", f"/fraud-alerts/{alert_id}/reopen", payload or {}, headers)

    # --- TelematicsFault ---
    def create_telematics_fault(self, payload, headers):
        return self._request("POST", "/telematics-faults", payload, headers)

    def get_telematics_fault(self, fault_id, headers):
        return self._request("GET", f"/telematics-faults/{fault_id}", headers=headers)

    def list_telematics_faults(self, headers, params=None):
        return self._request("GET", "/telematics-faults", headers=headers, params=params)

    def complete_maintenance(self, fault_id, headers):
        return self._request("POST", f"/telematics-faults/{fault_id}/complete-maintenance", {}, headers)

    def clear_telematics_fault(self, fault_id, headers):
        return self._request("POST", f"/telematics-faults/{fault_id}/clear", {}, headers)

    # --- IftaReport ---
    def create_ifta_report(self, payload, headers):
        return self._request("POST", "/ifta-reports", payload, headers)

    def get_ifta_report(self, report_id, headers):
        return self._request("GET", f"/ifta-reports/{report_id}", headers=headers)

    def list_ifta_reports(self, headers, params=None):
        return self._request("GET", "/ifta-reports", headers=headers, params=params)

    def file_ifta_report(self, report_id, headers):
        return self._request("POST", f"/ifta-reports/{report_id}/file", {}, headers)


api_client = ApiClient()
