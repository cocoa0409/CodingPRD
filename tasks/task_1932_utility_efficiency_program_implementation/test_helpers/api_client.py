"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (PRD section 2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/efficiency/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/efficiency/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/efficiency/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/efficiency/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/efficiency/programs/{program_id}/activate", {}, headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/efficiency/programs/{program_id}/suspend", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/efficiency/programs/{program_id}/close", {}, headers)

    # --- Contractors ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/efficiency/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/efficiency/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/efficiency/contractors/{contractor_id}", headers=headers)

    def approve_contractor(self, contractor_id, headers):
        return self._request("POST", f"/efficiency/contractors/{contractor_id}/approve", {}, headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/efficiency/contractors/{contractor_id}/suspend", {}, headers)

    def reinstate_contractor(self, contractor_id, headers):
        return self._request("POST", f"/efficiency/contractors/{contractor_id}/reinstate", {}, headers)

    def terminate_contractor(self, contractor_id, headers):
        return self._request("POST", f"/efficiency/contractors/{contractor_id}/terminate", {}, headers)

    # --- Certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/efficiency/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/efficiency/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/efficiency/certifications/{certification_id}", headers=headers)

    def revoke_certification(self, certification_id, headers):
        return self._request("POST", f"/efficiency/certifications/{certification_id}/revoke", {}, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/efficiency/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/efficiency/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/efficiency/customers/{customer_id}", headers=headers)

    # --- Leads ---
    def create_lead(self, payload, headers):
        return self._request("POST", "/efficiency/leads", payload, headers)

    def list_leads(self, headers, params=None):
        return self._request("GET", "/efficiency/leads", headers=headers, params=params)

    def get_lead(self, lead_id, headers):
        return self._request("GET", f"/efficiency/leads/{lead_id}", headers=headers)

    def distribute_lead(self, lead_id, expected_lead_version, headers):
        return self._request(
            "POST", f"/efficiency/leads/{lead_id}/distribute",
            {"expected_lead_version": expected_lead_version}, headers,
        )

    def accept_lead(self, lead_id, headers):
        return self._request("POST", f"/efficiency/leads/{lead_id}/accept", {}, headers)

    def expire_lead(self, lead_id, headers):
        return self._request("POST", f"/efficiency/leads/{lead_id}/expire", {}, headers)

    def withdraw_lead(self, lead_id, headers):
        return self._request("POST", f"/efficiency/leads/{lead_id}/withdraw", {}, headers)

    # --- Projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/efficiency/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/efficiency/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/efficiency/projects/{project_id}", headers=headers)

    def approve_project(self, project_id, expected_program_version, headers):
        return self._request(
            "POST", f"/efficiency/projects/{project_id}/approve",
            {"expected_program_version": expected_program_version}, headers,
        )

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/efficiency/projects/{project_id}/cancel", {}, headers)

    def create_work_order(self, project_id, payload, headers):
        return self._request("POST", f"/efficiency/projects/{project_id}/work_orders", payload, headers)

    # --- Work Orders ---
    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/efficiency/work_orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/efficiency/work_orders/{work_order_id}", headers=headers)

    def schedule_work_order(self, work_order_id, headers):
        return self._request("POST", f"/efficiency/work_orders/{work_order_id}/schedule", {}, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/efficiency/work_orders/{work_order_id}/start", {}, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/efficiency/work_orders/{work_order_id}/complete", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/efficiency/work_orders/{work_order_id}/cancel", {}, headers)

    # --- Inspectors ---
    def create_inspector(self, payload, headers):
        return self._request("POST", "/efficiency/inspectors", payload, headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/efficiency/inspectors", headers=headers, params=params)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/efficiency/inspectors/{inspector_id}", headers=headers)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/efficiency/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/efficiency/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/efficiency/inspections/{inspection_id}", headers=headers)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/efficiency/inspections/{inspection_id}/record", payload, headers)

    def void_inspection(self, inspection_id, headers):
        return self._request("POST", f"/efficiency/inspections/{inspection_id}/void", {}, headers)

    # --- Incentive Payments ---
    def list_incentive_payments(self, headers, params=None):
        return self._request("GET", "/efficiency/incentive_payments", headers=headers, params=params)

    def get_incentive_payment(self, payment_id, headers):
        return self._request("GET", f"/efficiency/incentive_payments/{payment_id}", headers=headers)

    def disburse_payment(self, payment_id, headers):
        return self._request("POST", f"/efficiency/incentive_payments/{payment_id}/disburse", {}, headers)

    def reconcile_payment(self, payment_id, headers):
        return self._request("POST", f"/efficiency/incentive_payments/{payment_id}/reconcile", {}, headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/efficiency/incentive_payments/{payment_id}/void", {}, headers)

    # --- Complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/efficiency/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/efficiency/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/efficiency/complaints/{complaint_id}", headers=headers)

    def start_review_complaint(self, complaint_id, headers):
        return self._request("POST", f"/efficiency/complaints/{complaint_id}/start_review", {}, headers)

    def resolve_complaint(self, complaint_id, headers):
        return self._request("POST", f"/efficiency/complaints/{complaint_id}/resolve", {}, headers)

    def escalate_complaint(self, complaint_id, headers):
        return self._request("POST", f"/efficiency/complaints/{complaint_id}/escalate", {}, headers)

    # --- Cost Effectiveness Reports ---
    def create_report(self, payload, headers):
        return self._request("POST", "/efficiency/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/efficiency/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/efficiency/reports/{report_id}", headers=headers)

    def finalize_report(self, report_id, headers):
        return self._request("POST", f"/efficiency/reports/{report_id}/finalize", {}, headers)


api_client = ApiClient()
