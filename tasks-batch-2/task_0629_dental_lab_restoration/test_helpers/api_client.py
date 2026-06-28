"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Doctor ----
    def create_doctor(self, payload, headers):
        return self._request("POST", "/doctors", payload, headers)

    def get_doctor(self, doctor_id, headers):
        return self._request("GET", f"/doctors/{doctor_id}", headers=headers)

    def list_doctors(self, headers, params=None):
        return self._request("GET", "/doctors", headers=headers, params=params)

    def list_doctor_cases(self, doctor_id, headers, params=None):
        return self._request("GET", f"/doctors/{doctor_id}/cases",
                             headers=headers, params=params)

    # ---- Material ----
    def create_material(self, payload, headers):
        return self._request("POST", "/materials", payload, headers)

    def get_material(self, material_id, headers):
        return self._request("GET", f"/materials/{material_id}", headers=headers)

    def list_materials(self, headers, params=None):
        return self._request("GET", "/materials", headers=headers, params=params)

    def list_material_restorations(self, material_id, headers, params=None):
        return self._request("GET", f"/materials/{material_id}/restorations",
                             headers=headers, params=params)

    # ---- MillMachine ----
    def create_mill_machine(self, payload, headers):
        return self._request("POST", "/mill-machines", payload, headers)

    def get_mill_machine(self, machine_id, headers):
        return self._request("GET", f"/mill-machines/{machine_id}", headers=headers)

    def list_machine_mill_jobs(self, machine_id, headers, params=None):
        return self._request("GET", f"/mill-machines/{machine_id}/mill-jobs",
                             headers=headers, params=params)

    def machine_maintenance(self, machine_id, headers):
        return self._request("POST", f"/mill-machines/{machine_id}/maintenance",
                             headers=headers)

    def machine_release(self, machine_id, headers):
        return self._request("POST", f"/mill-machines/{machine_id}/release",
                             headers=headers)

    # ---- CourierRoute ----
    def create_courier_route(self, payload, headers):
        return self._request("POST", "/courier-routes", payload, headers)

    def get_courier_route(self, route_id, headers):
        return self._request("GET", f"/courier-routes/{route_id}", headers=headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/courier-routes/{route_id}/route-stops",
                             headers=headers, params=params)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def create_restoration(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/restorations", payload, headers)

    def list_case_restorations(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/restorations",
                             headers=headers, params=params)

    def get_restoration(self, restoration_id, headers):
        return self._request("GET", f"/restorations/{restoration_id}", headers=headers)

    def list_restoration_units(self, restoration_id, headers, params=None):
        return self._request("GET", f"/restorations/{restoration_id}/fabrication-units",
                             headers=headers, params=params)

    def list_restoration_shade_records(self, restoration_id, headers, params=None):
        return self._request("GET", f"/restorations/{restoration_id}/shade-records",
                             headers=headers, params=params)

    def get_fabrication_unit(self, unit_id, headers):
        return self._request("GET", f"/fabrication-units/{unit_id}", headers=headers)

    def list_unit_remakes(self, unit_id, headers, params=None):
        return self._request("GET", f"/fabrication-units/{unit_id}/remakes",
                             headers=headers, params=params)

    def list_unit_remake_requests(self, unit_id, headers, params=None):
        return self._request("GET", f"/fabrication-units/{unit_id}/remake-requests",
                             headers=headers, params=params)

    def list_unit_mill_jobs(self, unit_id, headers, params=None):
        return self._request("GET", f"/fabrication-units/{unit_id}/mill-jobs",
                             headers=headers, params=params)

    def submit_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/submit", headers=headers)

    def start_fabrication(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/start-fabrication", headers=headers)

    def ready_tryin(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/ready-tryin", headers=headers)

    def tryin_verdict(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/tryin-verdict", payload, headers)

    def confirm_delivery(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/confirm-delivery", headers=headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/cancel", headers=headers)

    def get_case_invoice(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/invoice",
                             headers=headers, params=params)

    def list_case_credit_memos(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/credit-memos",
                             headers=headers, params=params)

    def list_case_remake_requests(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/remake-requests",
                             headers=headers, params=params)

    def list_case_route_stops(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/route-stops",
                             headers=headers, params=params)

    # ---- MillJob ----
    def create_mill_job(self, payload, headers):
        return self._request("POST", "/mill-jobs", payload, headers)

    def get_mill_job(self, job_id, headers):
        return self._request("GET", f"/mill-jobs/{job_id}", headers=headers)

    def start_mill_job(self, job_id, payload, headers):
        return self._request("POST", f"/mill-jobs/{job_id}/start", payload, headers)

    def complete_mill_job(self, job_id, headers):
        return self._request("POST", f"/mill-jobs/{job_id}/complete", headers=headers)

    def cancel_mill_job(self, job_id, headers):
        return self._request("POST", f"/mill-jobs/{job_id}/cancel", headers=headers)

    # ---- RouteStop ----
    def create_route_stop(self, payload, headers):
        return self._request("POST", "/route-stops", payload, headers)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def complete_route_stop(self, stop_id, headers):
        return self._request("POST", f"/route-stops/{stop_id}/complete", headers=headers)

    # ---- Invoice ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoice_credit_memos(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/credit-memos",
                             headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", headers=headers)

    # ---- RemakeRequest (warranty) ----
    def create_remake_request(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/remake-requests", payload, headers)

    def get_remake_request(self, request_id, headers):
        return self._request("GET", f"/remake-requests/{request_id}", headers=headers)

    def approve_remake_request(self, request_id, headers):
        return self._request("POST", f"/remake-requests/{request_id}/approve", headers=headers)

    def deny_remake_request(self, request_id, headers):
        return self._request("POST", f"/remake-requests/{request_id}/deny", headers=headers)

    # ---- CreditMemo ----
    def void_credit_memo(self, memo_id, headers):
        return self._request("POST", f"/credit-memos/{memo_id}/void", headers=headers)

    def get_credit_memo(self, memo_id, headers):
        return self._request("GET", f"/credit-memos/{memo_id}", headers=headers)


api_client = ApiClient()
