"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Platform / logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Scanner units
    # ------------------------------------------------------------------
    def create_scanner_unit(self, payload, headers):
        return self._request("POST", "/scanner-units", payload, headers)

    def list_scanner_units(self, headers, params=None):
        return self._request("GET", "/scanner-units", headers=headers, params=params)

    def get_scanner_unit(self, scanner_id, headers):
        return self._request("GET", f"/scanner-units/{scanner_id}", headers=headers)

    def set_scanner_maintenance(self, scanner_id, payload, headers):
        return self._request("POST", f"/scanner-units/{scanner_id}/maintenance", payload, headers)

    def list_scanner_unit_sessions(self, scanner_id, headers, params=None):
        return self._request("GET", f"/scanner-units/{scanner_id}/scan-sessions", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Shelf slots
    # ------------------------------------------------------------------
    def create_shelf_slot(self, payload, headers):
        return self._request("POST", "/shelf-slots", payload, headers)

    def list_shelf_slots(self, headers, params=None):
        return self._request("GET", "/shelf-slots", headers=headers, params=params)

    def get_shelf_slot(self, slot_id, headers):
        return self._request("GET", f"/shelf-slots/{slot_id}", headers=headers)

    def list_shelf_slot_assignments(self, slot_id, headers, params=None):
        return self._request("GET", f"/shelf-slots/{slot_id}/shelf-assignments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Clients / agreements
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", {}, headers)

    def reactivate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/reactivate", {}, headers)

    def create_service_agreement(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/service-agreements", payload, headers)

    def list_service_agreements(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/service-agreements", headers=headers, params=params)

    def get_service_agreement(self, agreement_id, headers):
        return self._request("GET", f"/service-agreements/{agreement_id}", headers=headers)

    def list_client_batches(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/batches", headers=headers, params=params)

    def list_client_access_grants(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/access-grants", headers=headers, params=params)

    def create_access_grant(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/access-grants", payload, headers)

    def list_client_invoices(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/invoices", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def start_prep(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/start-prep", {}, headers)

    def start_scan(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/start-scan", {}, headers)

    def submit_qa(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/submit-qa", {}, headers)

    def pass_qa(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/pass-qa", {}, headers)

    def fail_qa(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/fail-qa", {}, headers)

    def deliver_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/deliver", {}, headers)

    def close_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/close", {}, headers)

    def list_batch_boxes(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/boxes", headers=headers, params=params)

    def list_batch_documents(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/documents", headers=headers, params=params)

    def list_batch_index_records(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/index-records", headers=headers, params=params)

    def list_batch_scan_sessions(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/scan-sessions", headers=headers, params=params)

    def list_batch_page_logs(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/page-logs", headers=headers, params=params)

    def list_batch_access_grants(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/access-grants", headers=headers, params=params)

    def list_batch_destruction_certificates(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/destruction-certificates", headers=headers, params=params)

    def list_batch_invoices(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/invoices", headers=headers, params=params)

    def create_qa_review(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/qa-reviews", payload, headers)

    # ------------------------------------------------------------------
    # Boxes
    # ------------------------------------------------------------------
    def create_box(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/boxes", payload, headers)

    def get_box(self, box_id, headers):
        return self._request("GET", f"/boxes/{box_id}", headers=headers)

    def request_return(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/request-return", {}, headers)

    def create_custody_event(self, box_id, payload, headers):
        return self._request("POST", f"/boxes/{box_id}/custody-events", payload, headers)

    def list_custody_events(self, box_id, headers, params=None):
        return self._request("GET", f"/boxes/{box_id}/custody-events", headers=headers, params=params)

    def clear_custody_flag(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/clear-custody-flag", {}, headers)

    def begin_destruction(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/begin-destruction", {}, headers)

    def create_destruction_certificate(self, box_id, payload, headers):
        return self._request("POST", f"/boxes/{box_id}/destruction-certificates", payload, headers)

    def get_box_destruction_certificates(self, box_id, headers):
        return self._request("GET", f"/boxes/{box_id}/destruction-certificates", headers=headers)

    def mark_returned(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/mark-returned", {}, headers)

    # ------------------------------------------------------------------
    # Shelf assignments
    # ------------------------------------------------------------------
    def create_shelf_assignment(self, box_id, payload, headers):
        return self._request("POST", f"/boxes/{box_id}/shelf-assignments", payload, headers)

    def list_box_shelf_assignments(self, box_id, headers, params=None):
        return self._request("GET", f"/boxes/{box_id}/shelf-assignments", headers=headers, params=params)

    def get_shelf_assignment(self, assignment_id, headers):
        return self._request("GET", f"/shelf-assignments/{assignment_id}", headers=headers)

    def release_shelf_assignment(self, assignment_id, headers):
        return self._request("POST", f"/shelf-assignments/{assignment_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Documents & index records
    # ------------------------------------------------------------------
    def create_document(self, box_id, payload, headers):
        return self._request("POST", f"/boxes/{box_id}/documents", payload, headers)

    def list_box_documents(self, box_id, headers, params=None):
        return self._request("GET", f"/boxes/{box_id}/documents", headers=headers, params=params)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/documents/{document_id}", headers=headers)

    def create_index_record(self, document_id, payload, headers):
        return self._request("POST", f"/documents/{document_id}/index-records", payload, headers)

    def get_document_index_records(self, document_id, headers):
        return self._request("GET", f"/documents/{document_id}/index-records", headers=headers)

    def get_index_record(self, record_id, headers):
        return self._request("GET", f"/index-records/{record_id}", headers=headers)

    def list_document_page_logs(self, document_id, headers, params=None):
        return self._request("GET", f"/documents/{document_id}/page-logs", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Scan sessions
    # ------------------------------------------------------------------
    def create_scan_session(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/scan-sessions", payload, headers)

    def get_scan_session(self, session_id, headers):
        return self._request("GET", f"/scan-sessions/{session_id}", headers=headers)

    def create_page_log(self, session_id, payload, headers):
        return self._request("POST", f"/scan-sessions/{session_id}/page-logs", payload, headers)

    def list_session_page_logs(self, session_id, headers, params=None):
        return self._request("GET", f"/scan-sessions/{session_id}/page-logs", headers=headers, params=params)

    def get_page_log(self, page_log_id, headers):
        return self._request("GET", f"/page-logs/{page_log_id}", headers=headers)

    def commit_scan_session(self, session_id, payload, headers):
        return self._request("POST", f"/scan-sessions/{session_id}/commit", payload, headers)

    def void_scan_session(self, session_id, headers):
        return self._request("POST", f"/scan-sessions/{session_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Access grants / download
    # ------------------------------------------------------------------
    def get_access_grant(self, grant_id, headers):
        return self._request("GET", f"/access-grants/{grant_id}", headers=headers)

    def revoke_access_grant(self, grant_id, headers):
        return self._request("POST", f"/access-grants/{grant_id}/revoke", {}, headers)

    def list_grant_documents(self, grant_id, headers, params=None):
        return self._request("GET", f"/access-grants/{grant_id}/documents", headers=headers, params=params)

    def download_grant_document(self, grant_id, document_id, headers):
        return self._request("GET", f"/access-grants/{grant_id}/documents/{document_id}/download", headers=headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)


api_client = ApiClient()
