"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ca/_clock/set_current_utc", payload, headers)

    # --- CaProject ---
    def create_project(self, payload, headers):
        return self._request("POST", "/ca/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/ca/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/ca/projects/{project_id}", headers=headers)

    def activate_project(self, project_id, headers):
        return self._request("POST", f"/ca/projects/{project_id}/activate", headers=headers)

    def achieve_substantial_completion(self, project_id, headers):
        return self._request("POST", f"/ca/projects/{project_id}/achieve-substantial-completion", headers=headers)

    def achieve_final_completion(self, project_id, headers):
        return self._request("POST", f"/ca/projects/{project_id}/achieve-final-completion", headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/ca/projects/{project_id}/close", headers=headers)

    # --- Submittal ---
    def create_submittal(self, payload, headers):
        return self._request("POST", "/ca/submittals", payload, headers)

    def list_submittals(self, headers, params=None):
        return self._request("GET", "/ca/submittals", headers=headers, params=params)

    def get_submittal(self, submittal_id, headers):
        return self._request("GET", f"/ca/submittals/{submittal_id}", headers=headers)

    def review_submittal(self, submittal_id, payload, headers):
        return self._request("POST", f"/ca/submittals/{submittal_id}/review", payload, headers)

    def resubmit_submittal(self, submittal_id, headers):
        return self._request("POST", f"/ca/submittals/{submittal_id}/resubmit", headers=headers)

    def vacate_submittal_review(self, submittal_id, headers):
        return self._request("POST", f"/ca/submittals/{submittal_id}/vacate-review", headers=headers)

    # --- SiteVisit ---
    def create_site_visit(self, payload, headers):
        return self._request("POST", "/ca/site-visits", payload, headers)

    def list_site_visits(self, headers, params=None):
        return self._request("GET", "/ca/site-visits", headers=headers, params=params)

    def get_site_visit(self, visit_id, headers):
        return self._request("GET", f"/ca/site-visits/{visit_id}", headers=headers)

    def perform_site_visit(self, visit_id, headers):
        return self._request("POST", f"/ca/site-visits/{visit_id}/perform", headers=headers)

    def cancel_site_visit(self, visit_id, headers):
        return self._request("POST", f"/ca/site-visits/{visit_id}/cancel", headers=headers)

    # --- FieldReport ---
    def create_field_report(self, payload, headers):
        return self._request("POST", "/ca/field-reports", payload, headers)

    def list_field_reports(self, headers, params=None):
        return self._request("GET", "/ca/field-reports", headers=headers, params=params)

    def get_field_report(self, report_id, headers):
        return self._request("GET", f"/ca/field-reports/{report_id}", headers=headers)

    def clear_nonconformance(self, report_id, payload, headers):
        return self._request("POST", f"/ca/field-reports/{report_id}/clear-nonconformance", payload, headers)

    # --- Rfi ---
    def create_rfi(self, payload, headers):
        return self._request("POST", "/ca/rfis", payload, headers)

    def list_rfis(self, headers, params=None):
        return self._request("GET", "/ca/rfis", headers=headers, params=params)

    def get_rfi(self, rfi_id, headers):
        return self._request("GET", f"/ca/rfis/{rfi_id}", headers=headers)

    def answer_rfi(self, rfi_id, payload, headers):
        return self._request("POST", f"/ca/rfis/{rfi_id}/answer", payload, headers)

    def close_rfi(self, rfi_id, headers):
        return self._request("POST", f"/ca/rfis/{rfi_id}/close", headers=headers)

    def withdraw_rfi(self, rfi_id, headers):
        return self._request("POST", f"/ca/rfis/{rfi_id}/withdraw", headers=headers)

    # --- ClarificationDrawing ---
    def create_clarification_drawing(self, payload, headers):
        return self._request("POST", "/ca/clarification-drawings", payload, headers)

    def list_clarification_drawings(self, headers, params=None):
        return self._request("GET", "/ca/clarification-drawings", headers=headers, params=params)

    def get_clarification_drawing(self, drawing_id, headers):
        return self._request("GET", f"/ca/clarification-drawings/{drawing_id}", headers=headers)

    # --- PaymentApplication ---
    def create_payment_application(self, payload, headers):
        return self._request("POST", "/ca/payment-applications", payload, headers)

    def list_payment_applications(self, headers, params=None):
        return self._request("GET", "/ca/payment-applications", headers=headers, params=params)

    def get_payment_application(self, application_id, headers):
        return self._request("GET", f"/ca/payment-applications/{application_id}", headers=headers)

    def certify_payment_application(self, application_id, headers):
        return self._request("POST", f"/ca/payment-applications/{application_id}/certify", headers=headers)

    def reject_payment_application(self, application_id, payload, headers):
        return self._request("POST", f"/ca/payment-applications/{application_id}/reject", payload, headers)

    def resubmit_payment_application(self, application_id, payload, headers):
        return self._request("POST", f"/ca/payment-applications/{application_id}/resubmit", payload, headers)

    def void_payment_application(self, application_id, headers):
        return self._request("POST", f"/ca/payment-applications/{application_id}/void", headers=headers)

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/ca/change-orders", payload, headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/ca/change-orders", headers=headers, params=params)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/ca/change-orders/{change_order_id}", headers=headers)

    def recommend_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/ca/change-orders/{change_order_id}/recommend", payload, headers)

    def decide_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/ca/change-orders/{change_order_id}/owner-decision", payload, headers)

    def incorporate_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/ca/change-orders/{change_order_id}/incorporate", payload, headers)

    # --- PunchListItem ---
    def create_punch_list_item(self, payload, headers):
        return self._request("POST", "/ca/punch-list-items", payload, headers)

    def list_punch_list_items(self, headers, params=None):
        return self._request("GET", "/ca/punch-list-items", headers=headers, params=params)

    def get_punch_list_item(self, item_id, headers):
        return self._request("GET", f"/ca/punch-list-items/{item_id}", headers=headers)

    def claim_punch_item_complete(self, item_id, headers):
        return self._request("POST", f"/ca/punch-list-items/{item_id}/claim-complete", headers=headers)

    def verify_punch_item(self, item_id, headers):
        return self._request("POST", f"/ca/punch-list-items/{item_id}/verify", headers=headers)

    def reopen_punch_item(self, item_id, payload, headers):
        return self._request("POST", f"/ca/punch-list-items/{item_id}/reopen", payload, headers)

    # --- RecordDocument ---
    def create_record_document(self, payload, headers):
        return self._request("POST", "/ca/record-documents", payload, headers)

    def list_record_documents(self, headers, params=None):
        return self._request("GET", "/ca/record-documents", headers=headers, params=params)

    def get_record_document(self, document_id, headers):
        return self._request("GET", f"/ca/record-documents/{document_id}", headers=headers)

    def review_record_document(self, document_id, payload, headers):
        return self._request("POST", f"/ca/record-documents/{document_id}/review", payload, headers)

    def resubmit_record_document(self, document_id, headers):
        return self._request("POST", f"/ca/record-documents/{document_id}/resubmit", headers=headers)

    # --- AdditionalServiceInvoice ---
    def create_additional_service_invoice(self, payload, headers):
        return self._request("POST", "/ca/additional-service-invoices", payload, headers)

    def list_additional_service_invoices(self, headers, params=None):
        return self._request("GET", "/ca/additional-service-invoices", headers=headers, params=params)

    def get_additional_service_invoice(self, invoice_id, headers):
        return self._request("GET", f"/ca/additional-service-invoices/{invoice_id}", headers=headers)

    def issue_additional_service_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ca/additional-service-invoices/{invoice_id}/issue", headers=headers)

    def decide_additional_service_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/ca/additional-service-invoices/{invoice_id}/owner-decision", payload, headers)

    def record_invoice_payment(self, invoice_id, headers):
        return self._request("POST", f"/ca/additional-service-invoices/{invoice_id}/record-payment", headers=headers)

    def cancel_additional_service_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ca/additional-service-invoices/{invoice_id}/cancel", headers=headers)


api_client = ApiClient()
