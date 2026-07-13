"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Firm master data --------------------------------------------------
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers=headers)

    def create_consultant(self, payload, headers):
        return self._request("POST", "/consultants", payload, headers=headers)

    # ---- Project -----------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def set_project_state(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/state", payload, headers=headers)

    def list_project_phases(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/phases", headers=headers, params=params)

    def get_project_contract(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/contract", headers=headers, params=params)

    # ---- Contract ----------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers=headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def set_contract_state(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/state", payload, headers=headers)

    def list_contract_change_orders(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/change-orders", headers=headers, params=params
        )

    def list_contract_invoices(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/invoices", headers=headers, params=params
        )

    # ---- Phase -------------------------------------------------------------
    def create_phase(self, payload, headers):
        return self._request("POST", "/phases", payload, headers=headers)

    def get_phase(self, phase_id, headers):
        return self._request("GET", f"/phases/{phase_id}", headers=headers)

    def update_phase(self, phase_id, payload, headers):
        return self._request("PATCH", f"/phases/{phase_id}", payload, headers=headers)

    def set_phase_state(self, phase_id, payload, headers):
        return self._request("POST", f"/phases/{phase_id}/state", payload, headers=headers)

    def list_phase_drawings(self, phase_id, headers, params=None):
        return self._request("GET", f"/phases/{phase_id}/drawings", headers=headers, params=params)

    def list_phase_permit_reviews(self, phase_id, headers, params=None):
        return self._request(
            "GET", f"/phases/{phase_id}/permit-reviews", headers=headers, params=params
        )

    # ---- Drawing -----------------------------------------------------------
    def create_drawing(self, payload, headers):
        return self._request("POST", "/drawings", payload, headers=headers)

    def set_drawing_state(self, drawing_id, payload, headers):
        return self._request("POST", f"/drawings/{drawing_id}/state", payload, headers=headers)

    # ---- TimeEntry ---------------------------------------------------------
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/time-entries", payload, headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/time-entries/{time_entry_id}", headers=headers)

    def set_time_entry_state(self, time_entry_id, payload, headers):
        return self._request(
            "POST", f"/time-entries/{time_entry_id}/state", payload, headers=headers
        )

    # ---- Expense -----------------------------------------------------------
    def create_expense(self, payload, headers):
        return self._request("POST", "/expenses", payload, headers=headers)

    def list_expenses(self, headers, params=None):
        return self._request("GET", "/expenses", headers=headers, params=params)

    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/expenses/{expense_id}", headers=headers)

    def set_expense_state(self, expense_id, payload, headers):
        return self._request("POST", f"/expenses/{expense_id}/state", payload, headers=headers)

    # ---- RFI ---------------------------------------------------------------
    def create_rfi(self, payload, headers):
        return self._request("POST", "/rfis", payload, headers=headers)

    def list_rfis(self, headers, params=None):
        return self._request("GET", "/rfis", headers=headers, params=params)

    def get_rfi(self, rfi_id, headers):
        return self._request("GET", f"/rfis/{rfi_id}", headers=headers)

    def set_rfi_state(self, rfi_id, payload, headers):
        return self._request("POST", f"/rfis/{rfi_id}/state", payload, headers=headers)

    # ---- Submittal ---------------------------------------------------------
    def create_submittal(self, payload, headers):
        return self._request("POST", "/submittals", payload, headers=headers)

    def list_submittals(self, headers, params=None):
        return self._request("GET", "/submittals", headers=headers, params=params)

    def get_submittal(self, submittal_id, headers):
        return self._request("GET", f"/submittals/{submittal_id}", headers=headers)

    def set_submittal_state(self, submittal_id, payload, headers):
        return self._request("POST", f"/submittals/{submittal_id}/state", payload, headers=headers)

    # ---- ChangeOrder -------------------------------------------------------
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers=headers)

    def set_change_order_state(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/state", payload, headers=headers
        )

    def execute_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/execute", payload, headers=headers
        )

    # ---- Invoice -----------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers=headers)

    def set_invoice_state(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/state", payload, headers=headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers=headers)

    # ---- PermitReview ------------------------------------------------------
    def create_permit_review(self, payload, headers):
        return self._request("POST", "/permit-reviews", payload, headers=headers)

    def set_permit_review_state(self, permit_review_id, payload, headers):
        return self._request(
            "POST", f"/permit-reviews/{permit_review_id}/state", payload, headers=headers
        )

    # ---- FieldReport -------------------------------------------------------
    def create_field_report(self, payload, headers):
        return self._request("POST", "/field-reports", payload, headers=headers)

    def list_field_reports(self, headers, params=None):
        return self._request("GET", "/field-reports", headers=headers, params=params)

    def get_field_report(self, field_report_id, headers):
        return self._request("GET", f"/field-reports/{field_report_id}", headers=headers)

    # ---- Logical clock -----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
