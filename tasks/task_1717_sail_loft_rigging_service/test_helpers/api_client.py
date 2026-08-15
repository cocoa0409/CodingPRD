"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/lofts/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/lofts/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/lofts/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/lofts/customers/{customer_id}/suspend", {}, headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/lofts/customers/{customer_id}/reinstate", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/lofts/customers/{customer_id}/close", {}, headers)

    def record_payment(self, customer_id, payload, headers):
        return self._request("POST", f"/lofts/customers/{customer_id}/payments", payload, headers)

    # --- Boat ---
    def create_boat(self, customer_id, payload, headers):
        return self._request("POST", f"/lofts/customers/{customer_id}/boats", payload, headers)

    def list_customer_boats(self, customer_id, headers, params=None):
        return self._request("GET", f"/lofts/customers/{customer_id}/boats", headers=headers, params=params)

    def list_boats(self, headers, params=None):
        return self._request("GET", "/lofts/boats", headers=headers, params=params)

    def get_boat(self, boat_id, headers):
        return self._request("GET", f"/lofts/boats/{boat_id}", headers=headers)

    # --- MeasurementSheet ---
    def create_measurement_sheet(self, boat_id, payload, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/measurement-sheets", payload, headers)

    def list_measurement_sheets(self, boat_id, headers, params=None):
        return self._request("GET", f"/lofts/boats/{boat_id}/measurement-sheets", headers=headers, params=params)

    def list_all_measurement_sheets(self, headers, params=None):
        return self._request("GET", "/lofts/measurement-sheets", headers=headers, params=params)

    def get_measurement_sheet(self, sheet_id, headers):
        return self._request("GET", f"/lofts/measurement-sheets/{sheet_id}", headers=headers)

    def freeze_measurement_sheet(self, boat_id, sheet_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/measurement-sheets/{sheet_id}/freeze", {}, headers)

    # --- SailDesign ---
    def create_sail_design(self, boat_id, payload, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/sail-designs", payload, headers)

    def list_sail_designs(self, boat_id, headers, params=None):
        return self._request("GET", f"/lofts/boats/{boat_id}/sail-designs", headers=headers, params=params)

    def list_all_sail_designs(self, headers, params=None):
        return self._request("GET", "/lofts/sail-designs", headers=headers, params=params)

    def get_sail_design(self, design_id, headers):
        return self._request("GET", f"/lofts/sail-designs/{design_id}", headers=headers)

    def submit_sail_design(self, boat_id, design_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/sail-designs/{design_id}/submit", {}, headers)

    def approve_sail_design(self, boat_id, design_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/sail-designs/{design_id}/approve", {}, headers)

    def request_design_revision(self, boat_id, design_id, payload, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/sail-designs/{design_id}/request-revision", payload, headers)

    def redraft_sail_design(self, boat_id, design_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/sail-designs/{design_id}/redraft", {}, headers)

    # --- LoftWorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/lofts/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/lofts/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/lofts/work-orders/{work_order_id}", headers=headers)

    def lock_design(self, work_order_id, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/lock-design", {}, headers)

    def confirm_delivery(self, work_order_id, payload, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/confirm-delivery", payload, headers)

    def open_warranty_claim(self, work_order_id, payload, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/open-warranty-claim", payload, headers)

    def rule_warranty(self, work_order_id, payload, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/rule-warranty", payload, headers)

    def close_work_order(self, work_order_id, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/close", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/cancel", {}, headers)

    # --- ProductionJob ---
    def create_production_job(self, work_order_id, payload, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/production-jobs", payload, headers)

    def list_production_jobs(self, work_order_id, headers, params=None):
        return self._request("GET", f"/lofts/work-orders/{work_order_id}/production-jobs", headers=headers, params=params)

    def list_all_production_jobs(self, headers, params=None):
        return self._request("GET", "/lofts/production-jobs", headers=headers, params=params)

    def get_production_job(self, job_id, headers):
        return self._request("GET", f"/lofts/production-jobs/{job_id}", headers=headers)

    def start_cutting(self, work_order_id, job_id, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/production-jobs/{job_id}/start-cutting", {}, headers)

    def advance_job(self, work_order_id, job_id, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/production-jobs/{job_id}/advance", {}, headers)

    def qc_pass(self, work_order_id, job_id, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/production-jobs/{job_id}/qc-pass", {}, headers)

    def qc_fail(self, work_order_id, job_id, payload, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/production-jobs/{job_id}/qc-fail", payload, headers)

    def reschedule_job(self, work_order_id, job_id, payload, headers):
        return self._request("POST", f"/lofts/work-orders/{work_order_id}/production-jobs/{job_id}/reschedule", payload, headers)

    # --- ClothLedgerEntry ---
    def create_cloth_bolt(self, payload, headers):
        return self._request("POST", "/lofts/cloth-ledger", payload, headers)

    def list_cloth_bolts(self, headers, params=None):
        return self._request("GET", "/lofts/cloth-ledger", headers=headers, params=params)

    def get_cloth_bolt(self, bolt_id, headers):
        return self._request("GET", f"/lofts/cloth-ledger/{bolt_id}", headers=headers)

    # --- RiggingInspection ---
    def create_rigging_inspection(self, boat_id, payload, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/rigging-inspections", payload, headers)

    def list_rigging_inspections(self, boat_id, headers, params=None):
        return self._request("GET", f"/lofts/boats/{boat_id}/rigging-inspections", headers=headers, params=params)

    def list_all_rigging_inspections(self, headers, params=None):
        return self._request("GET", "/lofts/rigging-inspections", headers=headers, params=params)

    def get_rigging_inspection(self, inspection_id, headers):
        return self._request("GET", f"/lofts/rigging-inspections/{inspection_id}", headers=headers)

    def report_inspection(self, boat_id, inspection_id, payload, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/rigging-inspections/{inspection_id}/report", payload, headers)

    def close_inspection(self, boat_id, inspection_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/rigging-inspections/{inspection_id}/close", {}, headers)

    # --- MastServiceEvent ---
    def create_mast_service_event(self, boat_id, payload, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/mast-service-events", payload, headers)

    def list_mast_service_events(self, boat_id, headers, params=None):
        return self._request("GET", f"/lofts/boats/{boat_id}/mast-service-events", headers=headers, params=params)

    def list_all_mast_service_events(self, headers, params=None):
        return self._request("GET", "/lofts/mast-service-events", headers=headers, params=params)

    def get_mast_service_event(self, event_id, headers):
        return self._request("GET", f"/lofts/mast-service-events/{event_id}", headers=headers)

    def start_mast_event(self, boat_id, event_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/mast-service-events/{event_id}/start", {}, headers)

    def complete_mast_event(self, boat_id, event_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/mast-service-events/{event_id}/complete", {}, headers)

    def cancel_mast_event(self, boat_id, event_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/mast-service-events/{event_id}/cancel", {}, headers)

    # --- StorageContract ---
    def create_storage_contract(self, boat_id, payload, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/storage-contracts", payload, headers)

    def list_storage_contracts(self, boat_id, headers, params=None):
        return self._request("GET", f"/lofts/boats/{boat_id}/storage-contracts", headers=headers, params=params)

    def list_all_storage_contracts(self, headers, params=None):
        return self._request("GET", "/lofts/storage-contracts", headers=headers, params=params)

    def get_storage_contract(self, contract_id, headers):
        return self._request("GET", f"/lofts/storage-contracts/{contract_id}", headers=headers)

    def receive_storage_contract(self, boat_id, contract_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/storage-contracts/{contract_id}/receive", {}, headers)

    def complete_wash(self, boat_id, contract_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/storage-contracts/{contract_id}/complete-wash", {}, headers)

    def rack_store(self, boat_id, contract_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/storage-contracts/{contract_id}/rack-store", {}, headers)

    def stage_delivery(self, boat_id, contract_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/storage-contracts/{contract_id}/stage-delivery", {}, headers)

    def confirm_return(self, boat_id, contract_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/storage-contracts/{contract_id}/confirm-return", {}, headers)

    def cancel_storage_contract(self, boat_id, contract_id, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/storage-contracts/{contract_id}/cancel", {}, headers)

    # --- ClassCertificate ---
    def create_class_certificate(self, boat_id, payload, headers):
        return self._request("POST", f"/lofts/boats/{boat_id}/class-certificates", payload, headers)

    def list_class_certificates(self, boat_id, headers, params=None):
        return self._request("GET", f"/lofts/boats/{boat_id}/class-certificates", headers=headers, params=params)

    def list_all_class_certificates(self, headers, params=None):
        return self._request("GET", "/lofts/class-certificates", headers=headers, params=params)

    def get_class_certificate(self, cert_id, headers):
        return self._request("GET", f"/lofts/class-certificates/{cert_id}", headers=headers)


api_client = ApiClient()
