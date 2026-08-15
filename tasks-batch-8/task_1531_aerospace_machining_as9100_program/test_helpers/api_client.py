"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Long-term agreements ---
    def create_lta(self, payload, headers):
        return self._request("POST", "/api/ltas", payload, headers)

    def list_ltas(self, headers, params=None):
        return self._request("GET", "/api/ltas", headers=headers, params=params)

    def get_lta(self, lta_id, headers):
        return self._request("GET", f"/api/ltas/{lta_id}", headers=headers)

    def activate_lta(self, lta_id, headers):
        return self._request("POST", f"/api/ltas/{lta_id}/activate", {}, headers)

    def amend_lta(self, lta_id, payload, headers):
        return self._request("POST", f"/api/ltas/{lta_id}/amend", payload, headers)

    def close_lta(self, lta_id, headers):
        return self._request("POST", f"/api/ltas/{lta_id}/close", {}, headers)

    def reinstate_lta(self, lta_id, headers):
        return self._request("POST", f"/api/ltas/{lta_id}/reinstate", {}, headers)

    def run_rate_audit(self, lta_id, headers):
        return self._request("POST", f"/api/ltas/{lta_id}/run-rate-audit", {}, headers)

    def get_rebate_preview(self, lta_id, headers, params=None):
        return self._request(
            "GET", f"/api/ltas/{lta_id}/rebate-preview", headers=headers, params=params
        )

    # --- Purchase orders ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/api/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/purchase-orders", headers=headers, params=params
        )

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/api/purchase-orders/{po_id}", headers=headers)

    def accept_purchase_order(self, po_id, headers):
        return self._request(
            "POST", f"/api/purchase-orders/{po_id}/accept", {}, headers
        )

    def release_purchase_order(self, po_id, headers):
        return self._request(
            "POST", f"/api/purchase-orders/{po_id}/release", {}, headers
        )

    def cancel_purchase_order(self, po_id, headers):
        return self._request(
            "POST", f"/api/purchase-orders/{po_id}/cancel", {}, headers
        )

    # --- First-article inspections + ballooned characteristics ---
    def create_fai(self, payload, headers):
        return self._request("POST", "/api/first-articles", payload, headers)

    def list_fais(self, headers, params=None):
        return self._request("GET", "/api/first-articles", headers=headers, params=params)

    def get_fai(self, fai_id, headers):
        return self._request("GET", f"/api/first-articles/{fai_id}", headers=headers)

    def add_characteristic(self, fai_id, payload, headers):
        return self._request(
            "POST", f"/api/first-articles/{fai_id}/characteristics", payload, headers
        )

    def list_characteristics(self, fai_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/first-articles/{fai_id}/characteristics",
            headers=headers,
            params=params,
        )

    def submit_fai(self, fai_id, headers):
        return self._request(
            "POST", f"/api/first-articles/{fai_id}/submit", {}, headers
        )

    def approve_fai(self, fai_id, headers):
        return self._request(
            "POST", f"/api/first-articles/{fai_id}/approve", {}, headers
        )

    def reject_fai(self, fai_id, payload, headers):
        return self._request(
            "POST", f"/api/first-articles/{fai_id}/reject", payload, headers
        )

    def reopen_fai(self, fai_id, headers):
        return self._request(
            "POST", f"/api/first-articles/{fai_id}/reopen", {}, headers
        )

    def get_characteristic(self, char_id, headers):
        return self._request(
            "GET", f"/api/characteristics/{char_id}", headers=headers
        )

    def record_measurement(self, char_id, payload, headers):
        return self._request(
            "POST",
            f"/api/characteristics/{char_id}/record-measurement",
            payload,
            headers,
        )

    def list_characteristic_spc_measurements(self, char_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/characteristics/{char_id}/spc-measurements",
            headers=headers,
            params=params,
        )

    # --- Work orders, serials, SPC measurements ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/api/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/api/work-orders", headers=headers, params=params)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/api/work-orders/{wo_id}", headers=headers)

    def release_work_order(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/release", {}, headers
        )

    def create_serial_batch(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/serials", payload, headers
        )

    def list_wo_serials(self, wo_id, headers, params=None):
        return self._request(
            "GET", f"/api/work-orders/{wo_id}/serials", headers=headers, params=params
        )

    def record_spc_measurement(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/spc-measurements", payload, headers
        )

    def list_wo_spc_measurements(self, wo_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/work-orders/{wo_id}/spc-measurements",
            headers=headers,
            params=params,
        )

    def complete_work_order(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/complete", {}, headers
        )

    def accept_work_order(self, wo_id, headers):
        return self._request("POST", f"/api/work-orders/{wo_id}/accept", {}, headers)

    def cancel_work_order(self, wo_id, headers):
        return self._request("POST", f"/api/work-orders/{wo_id}/cancel", {}, headers)

    def release_hold_work_order(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/release-hold", {}, headers
        )

    def ship_all_work_order(self, wo_id, headers):
        return self._request(
            "POST", f"/api/work-orders/{wo_id}/ship-all", {}, headers
        )

    # --- Serial numbers ---
    def list_serials(self, headers, params=None):
        return self._request("GET", "/api/serials", headers=headers, params=params)

    def get_serial(self, serial_id, headers):
        return self._request("GET", f"/api/serials/{serial_id}", headers=headers)

    def ship_serial(self, serial_id, headers):
        return self._request("POST", f"/api/serials/{serial_id}/ship", {}, headers)

    # --- Material certifications ---
    def create_material_cert(self, payload, headers):
        return self._request("POST", "/api/material-certs", payload, headers)

    def list_material_certs(self, headers, params=None):
        return self._request(
            "GET", "/api/material-certs", headers=headers, params=params
        )

    def get_material_cert(self, cert_id, headers):
        return self._request(
            "GET", f"/api/material-certs/{cert_id}", headers=headers
        )

    def accept_material_cert(self, cert_id, headers):
        return self._request(
            "POST", f"/api/material-certs/{cert_id}/accept", {}, headers
        )

    def revoke_material_cert(self, cert_id, payload, headers):
        return self._request(
            "POST", f"/api/material-certs/{cert_id}/revoke", payload, headers
        )

    # --- Approved sources ---
    def create_source(self, payload, headers):
        return self._request("POST", "/api/sources", payload, headers)

    def list_sources(self, headers, params=None):
        return self._request("GET", "/api/sources", headers=headers, params=params)

    def get_source(self, source_id, headers):
        return self._request("GET", f"/api/sources/{source_id}", headers=headers)

    def approve_source(self, source_id, headers):
        return self._request("POST", f"/api/sources/{source_id}/approve", {}, headers)

    def disqualify_source(self, source_id, payload, headers):
        return self._request(
            "POST", f"/api/sources/{source_id}/disqualify", payload, headers
        )

    # --- Special-process approvals ---
    def create_process_approval(self, payload, headers):
        return self._request("POST", "/api/process-approvals", payload, headers)

    def list_process_approvals(self, headers, params=None):
        return self._request(
            "GET", "/api/process-approvals", headers=headers, params=params
        )

    def get_process_approval(self, pa_id, headers):
        return self._request(
            "GET", f"/api/process-approvals/{pa_id}", headers=headers
        )

    def suspend_process_approval(self, pa_id, headers):
        return self._request(
            "POST", f"/api/process-approvals/{pa_id}/suspend", {}, headers
        )

    def reinstate_process_approval(self, pa_id, headers):
        return self._request(
            "POST", f"/api/process-approvals/{pa_id}/reinstate", {}, headers
        )

    # --- Nonconformance reports ---
    def create_ncr(self, payload, headers):
        return self._request("POST", "/api/ncrs", payload, headers)

    def list_ncrs(self, headers, params=None):
        return self._request("GET", "/api/ncrs", headers=headers, params=params)

    def get_ncr(self, ncr_id, headers):
        return self._request("GET", f"/api/ncrs/{ncr_id}", headers=headers)

    def submit_ncr_mrb(self, ncr_id, headers):
        return self._request("POST", f"/api/ncrs/{ncr_id}/submit-mrb", {}, headers)

    def disposition_ncr(self, ncr_id, payload, headers):
        return self._request(
            "POST", f"/api/ncrs/{ncr_id}/disposition", payload, headers
        )

    def verify_ncr(self, ncr_id, payload, headers):
        return self._request("POST", f"/api/ncrs/{ncr_id}/verify", payload, headers)

    def close_ncr(self, ncr_id, headers):
        return self._request("POST", f"/api/ncrs/{ncr_id}/close", {}, headers)

    def kickback_ncr(self, ncr_id, payload, headers):
        return self._request("POST", f"/api/ncrs/{ncr_id}/kickback", payload, headers)

    def record_customer_concession(self, ncr_id, payload, headers):
        return self._request(
            "POST", f"/api/ncrs/{ncr_id}/customer-concession", payload, headers
        )

    # --- Escape reports ---
    def list_escape_reports(self, headers, params=None):
        return self._request(
            "GET", "/api/escape-reports", headers=headers, params=params
        )

    def get_escape_report(self, er_id, headers):
        return self._request("GET", f"/api/escape-reports/{er_id}", headers=headers)

    def submit_escape_report(self, er_id, headers):
        return self._request(
            "POST", f"/api/escape-reports/{er_id}/submit", {}, headers
        )

    def acknowledge_escape_report(self, er_id, payload, headers):
        return self._request(
            "POST", f"/api/escape-reports/{er_id}/acknowledge", payload, headers
        )

    # --- Delegated inspection authorities ---
    def create_delegation(self, payload, headers):
        return self._request("POST", "/api/delegations", payload, headers)

    def list_delegations(self, headers, params=None):
        return self._request("GET", "/api/delegations", headers=headers, params=params)

    def get_delegation(self, dia_id, headers):
        return self._request("GET", f"/api/delegations/{dia_id}", headers=headers)

    def revoke_delegation(self, dia_id, payload, headers):
        return self._request(
            "POST", f"/api/delegations/{dia_id}/revoke", payload, headers
        )

    # --- Logical clock test-driving ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
