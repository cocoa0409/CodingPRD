"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/ops/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Terminals ---
    def create_terminal(self, payload, headers):
        return self._request("POST", "/ops/terminals", payload, headers)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/ops/terminals/{terminal_id}", headers=headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", "/ops/terminals", headers=headers, params=params)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/ops/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/ops/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/ops/products", headers=headers, params=params)

    # --- Tanks ---
    def create_tank(self, payload, headers):
        return self._request("POST", "/ops/tanks", payload, headers)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/ops/tanks/{tank_id}", headers=headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/ops/tanks", headers=headers, params=params)

    # --- Contractors ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/ops/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/ops/contractors/{contractor_id}", headers=headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/ops/contractors", headers=headers, params=params)

    def qualify_contractor(self, contractor_id, payload, headers):
        return self._request("POST", f"/ops/contractors/{contractor_id}/qualify",
                             payload, headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/ops/contractors/{contractor_id}/suspend",
                             {}, headers)

    def reinstate_contractor(self, contractor_id, payload, headers):
        return self._request("POST", f"/ops/contractors/{contractor_id}/reinstate",
                             payload, headers)

    def bar_contractor(self, contractor_id, headers):
        return self._request("POST", f"/ops/contractors/{contractor_id}/bar",
                             {}, headers)

    # --- Safety events ---
    def create_safety_event(self, payload, headers):
        return self._request("POST", "/ops/safety-events", payload, headers)

    def get_safety_event(self, event_id, headers):
        return self._request("GET", f"/ops/safety-events/{event_id}", headers=headers)

    def list_safety_events(self, headers, params=None):
        return self._request("GET", "/ops/safety-events", headers=headers, params=params)

    # --- Cleaning jobs ---
    def create_cleaning_job(self, payload, headers):
        return self._request("POST", "/ops/cleaning-jobs", payload, headers)

    def get_cleaning_job(self, job_id, headers):
        return self._request("GET", f"/ops/cleaning-jobs/{job_id}", headers=headers)

    def list_cleaning_jobs(self, headers, params=None):
        return self._request("GET", "/ops/cleaning-jobs", headers=headers, params=params)

    def patch_cleaning_job(self, job_id, payload, headers):
        return self._request("PATCH", f"/ops/cleaning-jobs/{job_id}", payload, headers)

    def schedule_job(self, job_id, payload, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/schedule",
                             payload, headers)

    def take_out_of_service(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/take-out-of-service",
                             {}, headers)

    def record_heel_removal(self, job_id, payload, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/record-heel-removal",
                             payload, headers)

    def record_sludge_removal(self, job_id, payload, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/record-sludge-removal",
                             payload, headers)

    def request_gas_free(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/request-gas-free",
                             {}, headers)

    def begin_entry(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/begin-entry",
                             {}, headers)

    def complete_entry(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/complete-entry",
                             {}, headers)

    def order_rework(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/order-rework",
                             {}, headers)

    def begin_flush(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/begin-flush",
                             {}, headers)

    def verify_flush(self, job_id, payload, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/verify-flush",
                             payload, headers)

    def request_rts(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/request-rts",
                             {}, headers)

    def return_to_service(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/return-to-service",
                             {}, headers)

    def resume_job(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/resume", {}, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/ops/cleaning-jobs/{job_id}/cancel", {}, headers)

    # --- Service windows ---
    def create_service_window(self, payload, headers):
        return self._request("POST", "/ops/service-windows", payload, headers)

    def get_service_window(self, window_id, headers):
        return self._request("GET", f"/ops/service-windows/{window_id}", headers=headers)

    def list_service_windows(self, headers, params=None):
        return self._request("GET", "/ops/service-windows", headers=headers, params=params)

    def activate_window(self, window_id, headers):
        return self._request("POST", f"/ops/service-windows/{window_id}/activate",
                             {}, headers)

    def complete_window(self, window_id, headers):
        return self._request("POST", f"/ops/service-windows/{window_id}/complete",
                             {}, headers)

    def cancel_window(self, window_id, headers):
        return self._request("POST", f"/ops/service-windows/{window_id}/cancel",
                             {}, headers)

    # --- Waste profiles ---
    def create_waste_profile(self, payload, headers):
        return self._request("POST", "/ops/waste-profiles", payload, headers)

    def get_waste_profile(self, profile_id, headers):
        return self._request("GET", f"/ops/waste-profiles/{profile_id}", headers=headers)

    def list_waste_profiles(self, headers, params=None):
        return self._request("GET", "/ops/waste-profiles", headers=headers, params=params)

    def submit_waste_profile(self, profile_id, headers):
        return self._request("POST", f"/ops/waste-profiles/{profile_id}/submit",
                             {}, headers)

    def approve_waste_profile(self, profile_id, headers):
        return self._request("POST", f"/ops/waste-profiles/{profile_id}/approve",
                             {}, headers)

    def reject_waste_profile(self, profile_id, headers):
        return self._request("POST", f"/ops/waste-profiles/{profile_id}/reject",
                             {}, headers)

    def reclassify_waste_profile(self, profile_id, payload, headers):
        return self._request("POST", f"/ops/waste-profiles/{profile_id}/reclassify",
                             payload, headers)

    # --- Waste shipments ---
    def create_waste_shipment(self, payload, headers):
        return self._request("POST", "/ops/waste-shipments", payload, headers)

    def get_waste_shipment(self, shipment_id, headers):
        return self._request("GET", f"/ops/waste-shipments/{shipment_id}", headers=headers)

    def list_waste_shipments(self, headers, params=None):
        return self._request("GET", "/ops/waste-shipments", headers=headers, params=params)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/ops/waste-shipments/{shipment_id}/dispatch",
                             {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/ops/waste-shipments/{shipment_id}/deliver",
                             {}, headers)

    def reconcile_shipment(self, shipment_id, headers):
        return self._request("POST", f"/ops/waste-shipments/{shipment_id}/reconcile",
                             {}, headers)

    def void_shipment(self, shipment_id, headers):
        return self._request("POST", f"/ops/waste-shipments/{shipment_id}/void",
                             {}, headers)

    # --- Gas-free certificates ---
    def create_gas_free_certificate(self, payload, headers):
        return self._request("POST", "/ops/gas-free-certificates", payload, headers)

    def get_gas_free_certificate(self, cert_id, headers):
        return self._request("GET", f"/ops/gas-free-certificates/{cert_id}",
                             headers=headers)

    def list_gas_free_certificates(self, headers, params=None):
        return self._request("GET", "/ops/gas-free-certificates",
                             headers=headers, params=params)

    def revalidate_certificate(self, cert_id, headers):
        return self._request("POST", f"/ops/gas-free-certificates/{cert_id}/revalidate",
                             {}, headers)

    def revoke_certificate(self, cert_id, headers):
        return self._request("POST", f"/ops/gas-free-certificates/{cert_id}/revoke",
                             {}, headers)

    # --- Entry permits ---
    def create_entry_permit(self, payload, headers):
        return self._request("POST", "/ops/entry-permits", payload, headers)

    def get_entry_permit(self, permit_id, headers):
        return self._request("GET", f"/ops/entry-permits/{permit_id}", headers=headers)

    def list_entry_permits(self, headers, params=None):
        return self._request("GET", "/ops/entry-permits", headers=headers, params=params)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/issue", {}, headers)

    def activate_permit(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/activate",
                             {}, headers)

    def suspend_permit(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/suspend",
                             {}, headers)

    def resume_permit(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/resume",
                             {}, headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/close", {}, headers)

    def void_permit(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/void", {}, headers)

    def raise_alarm(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/raise-alarm",
                             {}, headers)

    def resolve_alarm(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/resolve-alarm",
                             {}, headers)

    def clear_atmosphere(self, permit_id, headers):
        return self._request("POST", f"/ops/entry-permits/{permit_id}/clear-atmosphere",
                             {}, headers)

    # --- Inspectors ---
    def create_inspector(self, payload, headers):
        return self._request("POST", "/ops/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/ops/inspectors/{inspector_id}", headers=headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/ops/inspectors", headers=headers, params=params)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/ops/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/ops/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/ops/inspections", headers=headers, params=params)

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/start",
                             {}, headers)

    def report_inspection(self, inspection_id, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/report",
                             {}, headers)

    def accept_inspection(self, inspection_id, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/accept",
                             {}, headers)

    def reject_inspection(self, inspection_id, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/reject",
                             {}, headers)

    def amend_inspection(self, inspection_id, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/amend",
                             {}, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/ops/inspections/{inspection_id}/cancel",
                             {}, headers)

    # --- Inspection findings ---
    def create_inspection_finding(self, payload, headers):
        return self._request("POST", "/ops/inspection-findings", payload, headers)

    def get_inspection_finding(self, finding_id, headers):
        return self._request("GET", f"/ops/inspection-findings/{finding_id}",
                             headers=headers)

    def list_inspection_findings(self, headers, params=None):
        return self._request("GET", "/ops/inspection-findings",
                             headers=headers, params=params)

    def accept_risk_finding(self, finding_id, headers):
        return self._request("POST", f"/ops/inspection-findings/{finding_id}/accept-risk",
                             {}, headers)

    # --- Repair orders ---
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/ops/repair-orders", payload, headers)

    def get_repair_order(self, repair_id, headers):
        return self._request("GET", f"/ops/repair-orders/{repair_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/ops/repair-orders", headers=headers, params=params)

    def start_repair(self, repair_id, headers):
        return self._request("POST", f"/ops/repair-orders/{repair_id}/start", {}, headers)

    def complete_repair(self, repair_id, headers):
        return self._request("POST", f"/ops/repair-orders/{repair_id}/complete",
                             {}, headers)

    def verify_repair(self, repair_id, headers):
        return self._request("POST", f"/ops/repair-orders/{repair_id}/verify", {}, headers)

    def reject_repair(self, repair_id, headers):
        return self._request("POST", f"/ops/repair-orders/{repair_id}/reject", {}, headers)

    # --- Wastewater batches ---
    def create_wastewater_batch(self, payload, headers):
        return self._request("POST", "/ops/wastewater-batches", payload, headers)

    def get_wastewater_batch(self, batch_id, headers):
        return self._request("GET", f"/ops/wastewater-batches/{batch_id}", headers=headers)

    def list_wastewater_batches(self, headers, params=None):
        return self._request("GET", "/ops/wastewater-batches",
                             headers=headers, params=params)

    def submit_lab_results(self, batch_id, payload, headers):
        return self._request("POST", f"/ops/wastewater-batches/{batch_id}/submit-lab",
                             payload, headers)

    def authorize_batch(self, batch_id, headers):
        return self._request("POST", f"/ops/wastewater-batches/{batch_id}/authorize",
                             {}, headers)

    def discharge_batch(self, batch_id, headers):
        return self._request("POST", f"/ops/wastewater-batches/{batch_id}/discharge",
                             {}, headers)

    def reject_batch(self, batch_id, headers):
        return self._request("POST", f"/ops/wastewater-batches/{batch_id}/reject",
                             {}, headers)

    def void_authorization(self, batch_id, headers):
        return self._request("POST",
                             f"/ops/wastewater-batches/{batch_id}/void-authorization",
                             {}, headers)

    def return_batch_to_storage(self, batch_id, headers):
        return self._request("POST",
                             f"/ops/wastewater-batches/{batch_id}/return-to-storage",
                             {}, headers)


api_client = ApiClient()
