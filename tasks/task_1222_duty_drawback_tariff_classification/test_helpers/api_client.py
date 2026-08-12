"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Duty Drawback & Tariff Classification API."""

    # --- Ops & clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/_clock/set_current_utc", payload, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/customs/ops/run_sweep", {}, headers)

    # --- Clients ---
    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/clients/{client_id}", headers=headers)

    def list_clients(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/clients", headers=headers, params=params)

    def patch_client(self, client_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/customs/clients/{client_id}", payload, headers)

    # --- Classifications ---
    def create_classification(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/classifications", payload, headers)

    def get_classification(self, classification_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/customs/classifications/{classification_id}", headers=headers
        )

    def list_classifications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/classifications", headers=headers, params=params)

    def submit_classification(self, classification_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/classifications/{classification_id}/submit", {}, headers
        )

    def review_classification(
        self, classification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/customs/classifications/{classification_id}/review-decision",
            payload,
            headers,
        )

    def supersede_classification(
        self, classification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/customs/classifications/{classification_id}/supersede",
            payload,
            headers,
        )

    # --- Binding rulings ---
    def create_binding_ruling(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/binding-rulings", payload, headers)

    def get_binding_ruling(self, ruling_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/binding-rulings/{ruling_id}", headers=headers)

    def list_binding_rulings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/binding-rulings", headers=headers, params=params)

    def ruling_outcome(
        self, ruling_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/customs/binding-rulings/{ruling_id}/outcome", payload, headers
        )

    # --- Import entries ---
    def create_import_entry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/import-entries", payload, headers)

    def get_import_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/import-entries/{entry_id}", headers=headers)

    def list_import_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/import-entries", headers=headers, params=params)

    def correct_import_entry(
        self, entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/customs/import-entries/{entry_id}/correct", payload, headers
        )

    # --- Export shipments ---
    def create_export_shipment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/export-shipments", payload, headers)

    def get_export_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/customs/export-shipments/{shipment_id}", headers=headers
        )

    def list_export_shipments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/export-shipments", headers=headers, params=params)

    # --- Drawback claims ---
    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/claims/{claim_id}", headers=headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/claims", headers=headers, params=params)

    def update_claim(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PUT", f"/customs/claims/{claim_id}", payload, headers)

    def add_claim_line(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/customs/claims/{claim_id}/lines", payload, headers)

    def void_claim_line(self, claim_id: str, line_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/customs/claims/{claim_id}/lines/{line_id}", headers=headers
        )

    def get_claim_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/claim-lines/{line_id}", headers=headers)

    def list_claim_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/claim-lines", headers=headers, params=params)

    def file_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/customs/claims/{claim_id}/file", {}, headers)

    def review_claim(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/customs/claims/{claim_id}/review", payload, headers)

    def deficiency_response(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/claims/{claim_id}/deficiency-response", {}, headers
        )

    def record_payment(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/claims/{claim_id}/record-payment", payload, headers
        )

    def cancel_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/customs/claims/{claim_id}/cancel", {}, headers)

    # --- Tariff measures ---
    def create_tariff_measure(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/tariff-measures", payload, headers)

    def get_tariff_measure(self, measure_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/tariff-measures/{measure_id}", headers=headers)

    def list_tariff_measures(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/tariff-measures", headers=headers, params=params)

    def revoke_tariff_measure(self, measure_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/tariff-measures/{measure_id}/revoke", {}, headers
        )

    # --- Invoices ---
    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/invoices/{invoice_id}/payments", payload, headers
        )

    def void_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/customs/invoices/{invoice_id}/void", {}, headers)

    # --- Audit cases ---
    def create_audit_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customs/audit-cases", payload, headers)

    def get_audit_case(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/audit-cases/{audit_id}", headers=headers)

    def list_audit_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/audit-cases", headers=headers, params=params)

    def advance_audit(self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/customs/audit-cases/{audit_id}/advance", payload, headers
        )

    # --- Compliance records ---
    def get_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customs/records/{record_id}", headers=headers)

    def list_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/customs/records", headers=headers, params=params)

    def destroy_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/customs/records/{record_id}/destroy", {}, headers)


api_client = ApiClient()
