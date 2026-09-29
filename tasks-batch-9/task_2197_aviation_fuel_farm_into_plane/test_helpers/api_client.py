"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # --- fuel farms --------------------------------------------------------
    def create_fuel_farm(self, payload, headers):
        return self._request("POST", "/fuel-farms", payload, headers=headers)

    def get_fuel_farm(self, farm_id, headers):
        return self._request("GET", f"/fuel-farms/{farm_id}", headers=headers)

    # --- environmental permits --------------------------------------------
    def create_environmental_permit(self, farm_id, payload, headers):
        return self._request("POST", f"/fuel-farms/{farm_id}/environmental-permits",
                             payload, headers=headers)

    def list_environmental_permits(self, farm_id, headers, params=None):
        return self._request("GET", f"/fuel-farms/{farm_id}/environmental-permits",
                             headers=headers, params=params)

    def suspend_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/environmental-permits/{permit_id}/suspend",
                             payload, headers=headers)

    def reinstate_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/environmental-permits/{permit_id}/reinstate",
                             payload if payload is not None else {}, headers=headers)

    # --- storage tanks -----------------------------------------------------
    def create_storage_tank(self, farm_id, payload, headers):
        return self._request("POST", f"/fuel-farms/{farm_id}/storage-tanks",
                             payload, headers=headers)

    def list_storage_tanks(self, farm_id, headers, params=None):
        return self._request("GET", f"/fuel-farms/{farm_id}/storage-tanks",
                             headers=headers, params=params)

    def get_storage_tank(self, tank_id, headers):
        return self._request("GET", f"/storage-tanks/{tank_id}", headers=headers)

    def change_tank_service_status(self, tank_id, payload, headers):
        return self._request("POST", f"/storage-tanks/{tank_id}/service-status",
                             payload, headers=headers)

    def create_tank_sample(self, tank_id, headers, payload=None):
        return self._request("POST", f"/storage-tanks/{tank_id}/samples",
                             payload if payload is not None else {}, headers=headers)

    def release_tank_quality(self, tank_id, headers, payload=None):
        return self._request("POST", f"/storage-tanks/{tank_id}/quality-release",
                             payload if payload is not None else {}, headers=headers)

    def quarantine_tank(self, tank_id, headers, payload=None):
        return self._request("POST", f"/storage-tanks/{tank_id}/quarantine",
                             payload if payload is not None else {}, headers=headers)

    def create_gauge_measurement(self, tank_id, payload, headers):
        return self._request("POST", f"/storage-tanks/{tank_id}/gauge-measurements",
                             payload, headers=headers)

    # --- fuel receipts -----------------------------------------------------
    def create_fuel_receipt(self, payload, headers):
        return self._request("POST", "/fuel-receipts", payload, headers=headers)

    def list_fuel_receipts(self, headers, params=None):
        return self._request("GET", "/fuel-receipts", headers=headers, params=params)

    def get_fuel_receipt(self, receipt_id, headers):
        return self._request("GET", f"/fuel-receipts/{receipt_id}", headers=headers)

    def create_receipt_sample(self, receipt_id, headers, payload=None):
        return self._request("POST", f"/fuel-receipts/{receipt_id}/samples",
                             payload if payload is not None else {}, headers=headers)

    def post_test_results(self, sample_id, payload, headers):
        return self._request("POST", f"/quality-samples/{sample_id}/test-results",
                             payload, headers=headers)

    def list_quality_samples(self, headers, params=None):
        return self._request("GET", "/quality-samples", headers=headers, params=params)

    def get_quality_sample(self, sample_id, headers):
        return self._request("GET", f"/quality-samples/{sample_id}", headers=headers)

    def sign_receipt_verdict(self, receipt_id, payload, headers):
        return self._request("POST", f"/fuel-receipts/{receipt_id}/verdict",
                             payload, headers=headers)

    def reject_fuel_receipt(self, receipt_id, headers, payload=None):
        return self._request("POST", f"/fuel-receipts/{receipt_id}/reject",
                             payload if payload is not None else {}, headers=headers)

    # --- fueling assets ---------------------------------------------------
    def create_fueling_asset(self, farm_id, payload, headers):
        return self._request("POST", f"/fuel-farms/{farm_id}/fueling-assets",
                             payload, headers=headers)

    def list_fueling_assets(self, headers, params=None):
        return self._request("GET", "/fueling-assets", headers=headers, params=params)

    def get_fueling_asset(self, asset_id, headers):
        return self._request("GET", f"/fueling-assets/{asset_id}", headers=headers)

    def change_asset_status(self, asset_id, payload, headers):
        return self._request("POST", f"/fueling-assets/{asset_id}/status",
                             payload, headers=headers)

    def create_filter_change(self, asset_id, payload, headers):
        return self._request("POST", f"/fueling-assets/{asset_id}/filter-changes",
                             payload, headers=headers)

    def list_filter_changes(self, asset_id, headers, params=None):
        return self._request("GET", f"/fueling-assets/{asset_id}/filter-changes",
                             headers=headers, params=params)

    # --- hydrant pits -----------------------------------------------------
    def create_hydrant_pit(self, farm_id, payload, headers):
        return self._request("POST", f"/fuel-farms/{farm_id}/hydrant-pits",
                             payload, headers=headers)

    def list_farm_hydrant_pits(self, farm_id, headers, params=None):
        return self._request("GET", f"/fuel-farms/{farm_id}/hydrant-pits",
                             headers=headers, params=params)

    def list_hydrant_pits(self, headers, params=None):
        return self._request("GET", "/hydrant-pits", headers=headers, params=params)

    def get_hydrant_pit(self, pit_id, headers):
        return self._request("GET", f"/hydrant-pits/{pit_id}", headers=headers)

    # --- airline accounts, flights, authorizations ------------------------
    def create_airline_account(self, payload, headers):
        return self._request("POST", "/airline-accounts", payload, headers=headers)

    def get_airline_account(self, account_id, headers):
        return self._request("GET", f"/airline-accounts/{account_id}", headers=headers)

    def create_flight(self, payload, headers):
        return self._request("POST", "/flights", payload, headers=headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/flights", headers=headers, params=params)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/flights/{flight_id}", headers=headers)

    def create_fuel_authorization(self, payload, headers):
        return self._request("POST", "/fuel-authorizations", payload, headers=headers)

    def list_fuel_authorizations(self, headers, params=None):
        return self._request("GET", "/fuel-authorizations", headers=headers, params=params)

    def get_fuel_authorization(self, auth_id, headers):
        return self._request("GET", f"/fuel-authorizations/{auth_id}", headers=headers)

    def void_fuel_authorization(self, auth_id, headers, payload=None):
        return self._request("POST", f"/fuel-authorizations/{auth_id}/void",
                             payload if payload is not None else {}, headers=headers)

    # --- fueling orders ---------------------------------------------------
    def create_fueling_order(self, payload, headers):
        return self._request("POST", "/fueling-orders", payload, headers=headers)

    def list_fueling_orders(self, headers, params=None):
        return self._request("GET", "/fueling-orders", headers=headers, params=params)

    def get_fueling_order(self, order_id, headers):
        return self._request("GET", f"/fueling-orders/{order_id}", headers=headers)

    def authorize_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/fueling-orders/{order_id}/authorize",
                             payload if payload is not None else {}, headers=headers)

    def assign_order(self, order_id, payload, headers):
        return self._request("POST", f"/fueling-orders/{order_id}/assign",
                             payload, headers=headers)

    def unassign_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/fueling-orders/{order_id}/unassign",
                             payload if payload is not None else {}, headers=headers)

    def start_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/fueling-orders/{order_id}/start",
                             payload if payload is not None else {}, headers=headers)

    def create_uplift_record(self, order_id, payload, headers):
        return self._request("POST", f"/fueling-orders/{order_id}/uplift-records",
                             payload, headers=headers)

    def list_uplift_records(self, headers, params=None):
        return self._request("GET", "/uplift-records", headers=headers, params=params)

    def get_uplift_record(self, ticket_id, headers):
        return self._request("GET", f"/uplift-records/{ticket_id}", headers=headers)

    def complete_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/fueling-orders/{order_id}/complete",
                             payload if payload is not None else {}, headers=headers)

    def abort_order(self, order_id, payload, headers):
        return self._request("POST", f"/fueling-orders/{order_id}/abort",
                             payload, headers=headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/fueling-orders/{order_id}/cancel",
                             payload if payload is not None else {}, headers=headers)

    # --- spill incidents --------------------------------------------------
    def create_spill_incident(self, payload, headers):
        return self._request("POST", "/spill-incidents", payload, headers=headers)

    def list_spill_incidents(self, headers, params=None):
        return self._request("GET", "/spill-incidents", headers=headers, params=params)

    def get_spill_incident(self, spill_id, headers):
        return self._request("GET", f"/spill-incidents/{spill_id}", headers=headers)

    def escalate_spill(self, spill_id, payload, headers):
        return self._request("POST", f"/spill-incidents/{spill_id}/escalate",
                             payload, headers=headers)

    def contain_spill(self, spill_id, payload, headers):
        return self._request("POST", f"/spill-incidents/{spill_id}/contain",
                             payload, headers=headers)

    def remediate_spill(self, spill_id, headers, payload=None):
        return self._request("POST", f"/spill-incidents/{spill_id}/remediate",
                             payload if payload is not None else {}, headers=headers)

    def close_spill(self, spill_id, headers, payload=None):
        return self._request("POST", f"/spill-incidents/{spill_id}/close",
                             payload if payload is not None else {}, headers=headers)

    # --- reconciliation runs ---------------------------------------------
    def create_reconciliation_run(self, farm_id, payload, headers):
        return self._request("POST", f"/fuel-farms/{farm_id}/reconciliation-runs",
                             payload, headers=headers)

    def list_reconciliation_runs(self, farm_id, headers, params=None):
        return self._request("GET", f"/fuel-farms/{farm_id}/reconciliation-runs",
                             headers=headers, params=params)

    def measure_reconciliation_run(self, run_id, payload, headers):
        return self._request("POST", f"/reconciliation-runs/{run_id}/measure",
                             payload, headers=headers)

    def post_reconciliation_run(self, run_id, headers, payload=None):
        return self._request("POST", f"/reconciliation-runs/{run_id}/post",
                             payload if payload is not None else {}, headers=headers)

    # --- invoices ---------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/invoices/{invoice_id}/issue",
                             payload if payload is not None else {}, headers=headers)

    def dispute_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/invoices/{invoice_id}/dispute",
                             payload if payload is not None else {}, headers=headers)

    def resolve_invoice_dispute(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/invoices/{invoice_id}/resolve-dispute",
                             payload if payload is not None else {}, headers=headers)

    def void_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/invoices/{invoice_id}/void",
                             payload if payload is not None else {}, headers=headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments",
                             payload, headers=headers)


api_client = ApiClient()
