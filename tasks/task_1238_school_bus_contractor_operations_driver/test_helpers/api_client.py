"""API client: one method per endpoint defined in the PRD (all under /busops)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving / platform ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/busops/_clock/set_current_utc", payload, headers)

    # ---- District ----
    def create_district(self, payload, headers):
        return self._request("POST", "/busops/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/busops/districts/{district_id}", headers=headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/busops/districts", headers=headers, params=params)

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/busops/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/busops/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/busops/contracts", headers=headers, params=params)

    def submit_contract(self, contract_id, headers):
        return self._request("POST", f"/busops/contracts/{contract_id}/submit", {}, headers)

    def award_contract(self, contract_id, headers):
        return self._request("POST", f"/busops/contracts/{contract_id}/award", {}, headers)

    def mark_contract_lost(self, contract_id, headers):
        return self._request("POST", f"/busops/contracts/{contract_id}/mark-lost", {}, headers)

    def withdraw_contract(self, contract_id, headers):
        return self._request("POST", f"/busops/contracts/{contract_id}/withdraw", {}, headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/busops/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/busops/contracts/{contract_id}/terminate", payload, headers)

    def amend_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/busops/contracts/{contract_id}/amendments", payload, headers)

    # ---- Route ----
    def create_route(self, payload, headers):
        return self._request("POST", "/busops/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/busops/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/busops/routes", headers=headers, params=params)

    def deactivate_route(self, route_id, payload, headers):
        return self._request("POST", f"/busops/routes/{route_id}/deactivate", payload, headers)

    def reactivate_route(self, route_id, headers):
        return self._request("POST", f"/busops/routes/{route_id}/reactivate", {}, headers)

    # ---- Driver ----
    def create_driver(self, payload, headers):
        return self._request("POST", "/busops/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/busops/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/busops/drivers", headers=headers, params=params)

    def post_driver_event(self, driver_id, payload, headers):
        return self._request("POST", f"/busops/drivers/{driver_id}/events", payload, headers)

    def post_driver_discipline(self, driver_id, payload, headers):
        return self._request("POST", f"/busops/drivers/{driver_id}/discipline", payload, headers)

    # ---- TrainingEvent ----
    def create_training_event(self, payload, headers):
        return self._request("POST", "/busops/training-events", payload, headers)

    def get_training_event(self, event_id, headers):
        return self._request("GET", f"/busops/training-events/{event_id}", headers=headers)

    def list_training_events(self, headers, params=None):
        return self._request("GET", "/busops/training-events", headers=headers, params=params)

    # ---- Credential ----
    def create_credential(self, payload, headers):
        return self._request("POST", "/busops/credentials", payload, headers)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/busops/credentials/{credential_id}", headers=headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/busops/credentials", headers=headers, params=params)

    def revoke_credential(self, credential_id, payload, headers):
        return self._request("POST", f"/busops/credentials/{credential_id}/revoke", payload, headers)

    # ---- Bus ----
    def create_bus(self, payload, headers):
        return self._request("POST", "/busops/buses", payload, headers)

    def get_bus(self, bus_id, headers):
        return self._request("GET", f"/busops/buses/{bus_id}", headers=headers)

    def list_buses(self, headers, params=None):
        return self._request("GET", "/busops/buses", headers=headers, params=params)

    def post_bus_event(self, bus_id, payload, headers):
        return self._request("POST", f"/busops/buses/{bus_id}/events", payload, headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/busops/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/busops/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/busops/inspections", headers=headers, params=params)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request("POST", f"/busops/inspections/{inspection_id}/record-result", payload, headers)

    def reschedule_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/busops/inspections/{inspection_id}/reschedule", payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/busops/inspections/{inspection_id}/cancel", {}, headers)

    # ---- WorkOrder ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/busops/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/busops/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/busops/work-orders", headers=headers, params=params)

    def post_work_order_event(self, work_order_id, payload, headers):
        return self._request("POST", f"/busops/work-orders/{work_order_id}/events", payload, headers)

    # ---- ServiceDay ----
    def create_service_day(self, payload, headers):
        return self._request("POST", "/busops/service-days", payload, headers)

    def get_service_day(self, service_day_id, headers):
        return self._request("GET", f"/busops/service-days/{service_day_id}", headers=headers)

    def list_service_days(self, headers, params=None):
        return self._request("GET", "/busops/service-days", headers=headers, params=params)

    def open_dispatch(self, service_day_id, headers):
        return self._request("POST", f"/busops/service-days/{service_day_id}/open-dispatch", {}, headers)

    def lock_service_day(self, service_day_id, payload, headers):
        return self._request("POST", f"/busops/service-days/{service_day_id}/lock", payload, headers)

    def reconcile_service_day(self, service_day_id, headers):
        return self._request("POST", f"/busops/service-days/{service_day_id}/reconcile", {}, headers)

    def cancel_service_day(self, service_day_id, payload, headers):
        return self._request("POST", f"/busops/service-days/{service_day_id}/cancel", payload, headers)

    def post_doubling_decision(self, service_day_id, payload, headers):
        return self._request("POST", f"/busops/service-days/{service_day_id}/doubling-decisions", payload, headers)

    def get_district_report(self, service_day_id, headers):
        return self._request("GET", f"/busops/service-days/{service_day_id}/district-report", headers=headers)

    # ---- Assignment ----
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/busops/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/busops/assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/busops/assignments/{assignment_id}/confirm", payload, headers)

    def start_assignment(self, assignment_id, headers):
        return self._request("POST", f"/busops/assignments/{assignment_id}/start", {}, headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/busops/assignments/{assignment_id}/complete", payload, headers)

    def no_show_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/busops/assignments/{assignment_id}/no-show", payload, headers)

    def cancel_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/busops/assignments/{assignment_id}/cancel", payload, headers)

    # ---- CharterTrip ----
    def create_charter_trip(self, payload, headers):
        return self._request("POST", "/busops/charter-trips", payload, headers)

    def get_charter_trip(self, charter_id, headers):
        return self._request("GET", f"/busops/charter-trips/{charter_id}", headers=headers)

    def list_charter_trips(self, headers, params=None):
        return self._request("GET", "/busops/charter-trips", headers=headers, params=params)

    def quote_charter(self, charter_id, headers):
        return self._request("POST", f"/busops/charter-trips/{charter_id}/quote", {}, headers)

    def approve_charter(self, charter_id, payload, headers):
        return self._request("POST", f"/busops/charter-trips/{charter_id}/approve", payload, headers)

    def decline_charter(self, charter_id, payload, headers):
        return self._request("POST", f"/busops/charter-trips/{charter_id}/decline", payload, headers)

    def schedule_charter(self, charter_id, payload, headers):
        return self._request("POST", f"/busops/charter-trips/{charter_id}/schedule", payload, headers)

    def start_charter(self, charter_id, headers):
        return self._request("POST", f"/busops/charter-trips/{charter_id}/start", {}, headers)

    def complete_charter(self, charter_id, payload, headers):
        return self._request("POST", f"/busops/charter-trips/{charter_id}/complete", payload, headers)

    def cancel_charter(self, charter_id, payload, headers):
        return self._request("POST", f"/busops/charter-trips/{charter_id}/cancel", payload, headers)

    # ---- FuelPriceEntry ----
    def create_fuel_price_entry(self, payload, headers):
        return self._request("POST", "/busops/fuel-price-entries", payload, headers)

    def get_fuel_price_entry(self, entry_id, headers):
        return self._request("GET", f"/busops/fuel-price-entries/{entry_id}", headers=headers)

    def list_fuel_price_entries(self, headers, params=None):
        return self._request("GET", "/busops/fuel-price-entries", headers=headers, params=params)

    # ---- Invoice ----
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/busops/invoices/generate", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/busops/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/busops/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/busops/invoices/{invoice_id}/issue", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/busops/invoices/{invoice_id}/dispute", payload, headers)

    def reissue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/busops/invoices/{invoice_id}/reissue", payload, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/busops/invoices/{invoice_id}/pay", {}, headers)

    def write_off_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/busops/invoices/{invoice_id}/write-off", payload, headers)

    # ---- Incident ----
    def create_incident(self, payload, headers):
        return self._request("POST", "/busops/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/busops/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/busops/incidents", headers=headers, params=params)

    def submit_incident(self, incident_id, headers):
        return self._request("POST", f"/busops/incidents/{incident_id}/submit", {}, headers)

    def acknowledge_incident(self, incident_id, headers):
        return self._request("POST", f"/busops/incidents/{incident_id}/acknowledge", {}, headers)

    def return_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/busops/incidents/{incident_id}/return", payload, headers)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/busops/incidents/{incident_id}/close", payload, headers)

    # ---- RidershipReport ----
    def create_ridership_report(self, payload, headers):
        return self._request("POST", "/busops/ridership-reports", payload, headers)

    def get_ridership_report(self, report_id, headers):
        return self._request("GET", f"/busops/ridership-reports/{report_id}", headers=headers)

    def list_ridership_reports(self, headers, params=None):
        return self._request("GET", "/busops/ridership-reports", headers=headers, params=params)


api_client = ApiClient()
