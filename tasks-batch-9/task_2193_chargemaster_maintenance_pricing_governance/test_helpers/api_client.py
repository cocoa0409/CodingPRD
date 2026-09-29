"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

P = "/chargemaster"


class ApiClient(GenericApiClient):
    # ---------------- Facilities ----------------
    def create_facility(self, payload, headers):
        return self._request("POST", f"{P}/facilities", payload, headers=headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{P}/facilities/{facility_id}", headers=headers)

    def update_facility(self, facility_id, payload, headers):
        return self._request("PATCH", f"{P}/facilities/{facility_id}", payload, headers=headers)

    # ---------------- Revenue codes ----------------
    def create_revenue_code(self, payload, headers):
        return self._request("POST", f"{P}/revenue-codes", payload, headers=headers)

    def list_revenue_codes(self, headers, params=None):
        return self._request("GET", f"{P}/revenue-codes", headers=headers, params=params)

    def get_revenue_code(self, revenue_code_id, headers):
        return self._request("GET", f"{P}/revenue-codes/{revenue_code_id}", headers=headers)

    def retire_revenue_code(self, revenue_code_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/revenue-codes/{revenue_code_id}/retire", payload or {}, headers=headers
        )

    # ---------------- Departments ----------------
    def create_department(self, payload, headers):
        return self._request("POST", f"{P}/departments", payload, headers=headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", f"{P}/departments", headers=headers, params=params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"{P}/departments/{department_id}", headers=headers)

    # ---------------- Price rules ----------------
    def create_price_rule(self, payload, headers):
        return self._request("POST", f"{P}/price-rules", payload, headers=headers)

    def list_price_rules(self, headers, params=None):
        return self._request("GET", f"{P}/price-rules", headers=headers, params=params)

    def get_price_rule(self, price_rule_id, headers):
        return self._request("GET", f"{P}/price-rules/{price_rule_id}", headers=headers)

    # ---------------- Payer contracts ----------------
    def create_payer_contract(self, payload, headers):
        return self._request("POST", f"{P}/payer-contracts", payload, headers=headers)

    def list_payer_contracts(self, headers, params=None):
        return self._request("GET", f"{P}/payer-contracts", headers=headers, params=params)

    def get_payer_contract(self, payer_contract_id, headers):
        return self._request("GET", f"{P}/payer-contracts/{payer_contract_id}", headers=headers)

    def terminate_payer_contract(self, payer_contract_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/payer-contracts/{payer_contract_id}/terminate", payload or {},
            headers=headers,
        )

    # ---------------- Charge items ----------------
    def create_charge_item(self, payload, headers):
        return self._request("POST", f"{P}/charge-items", payload, headers=headers)

    def list_charge_items(self, headers, params=None):
        return self._request("GET", f"{P}/charge-items", headers=headers, params=params)

    def get_charge_item(self, charge_item_id, headers):
        return self._request("GET", f"{P}/charge-items/{charge_item_id}", headers=headers)

    def get_duplicate_candidates(self, charge_item_id, headers, params=None):
        return self._request(
            "GET", f"{P}/charge-items/{charge_item_id}/duplicate-candidates",
            headers=headers, params=params,
        )

    def reprice_charge_item(self, charge_item_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/charge-items/{charge_item_id}/reprice", payload or {}, headers=headers
        )

    def charge_item_lifecycle(self, charge_item_id, payload, headers):
        return self._request(
            "POST", f"{P}/charge-items/{charge_item_id}/lifecycle", payload, headers=headers
        )

    # ---------------- Change requests ----------------
    def create_change_request(self, payload, headers):
        return self._request("POST", f"{P}/change-requests", payload, headers=headers)

    def list_change_requests(self, headers, params=None):
        return self._request("GET", f"{P}/change-requests", headers=headers, params=params)

    def get_change_request(self, change_request_id, headers):
        return self._request("GET", f"{P}/change-requests/{change_request_id}", headers=headers)

    def change_request_decision(self, change_request_id, payload, headers):
        return self._request(
            "POST", f"{P}/change-requests/{change_request_id}/decisions", payload, headers=headers
        )

    def approve_change_request(self, change_request_id, payload, headers):
        return self._request(
            "POST", f"{P}/change-requests/{change_request_id}/approve", payload, headers=headers
        )

    def resubmit_change_request(self, change_request_id, payload, headers):
        return self._request(
            "POST", f"{P}/change-requests/{change_request_id}/resubmit", payload, headers=headers
        )

    def implement_change_request(self, change_request_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/change-requests/{change_request_id}/implement", payload or {},
            headers=headers,
        )

    # ---------------- Code update cycles ----------------
    def create_code_update_cycle(self, payload, headers):
        return self._request("POST", f"{P}/code-update-cycles", payload, headers=headers)

    def list_code_update_cycles(self, headers, params=None):
        return self._request("GET", f"{P}/code-update-cycles", headers=headers, params=params)

    def get_code_update_cycle(self, cycle_id, headers):
        return self._request("GET", f"{P}/code-update-cycles/{cycle_id}", headers=headers)

    def create_code_update_entry(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{P}/code-update-cycles/{cycle_id}/entries", payload, headers=headers
        )

    def code_update_cycle_lifecycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{P}/code-update-cycles/{cycle_id}/lifecycle", payload, headers=headers
        )

    def list_code_update_entries(self, headers, params=None):
        return self._request("GET", f"{P}/code-update-entries", headers=headers, params=params)

    def get_code_update_entry(self, entry_id, headers):
        return self._request("GET", f"{P}/code-update-entries/{entry_id}", headers=headers)

    def disposition_code_update_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{P}/code-update-entries/{entry_id}/disposition", payload, headers=headers
        )

    # ---------------- Charge capture ----------------
    def create_charge_capture_batch(self, payload, headers):
        return self._request("POST", f"{P}/charge-capture-batches", payload, headers=headers)

    def list_charge_capture_batches(self, headers, params=None):
        return self._request("GET", f"{P}/charge-capture-batches", headers=headers, params=params)

    def get_charge_capture_batch(self, batch_id, headers):
        return self._request("GET", f"{P}/charge-capture-batches/{batch_id}", headers=headers)

    def create_captured_charge(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{P}/charge-capture-batches/{batch_id}/lines", payload, headers=headers
        )

    def reconcile_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/charge-capture-batches/{batch_id}/reconcile", payload or {},
            headers=headers,
        )

    def batch_lifecycle(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{P}/charge-capture-batches/{batch_id}/lifecycle", payload, headers=headers
        )

    def list_captured_charges(self, headers, params=None):
        return self._request("GET", f"{P}/captured-charges", headers=headers, params=params)

    def get_captured_charge(self, captured_charge_id, headers):
        return self._request("GET", f"{P}/captured-charges/{captured_charge_id}", headers=headers)

    def list_missing_charge_findings(self, headers, params=None):
        return self._request("GET", f"{P}/missing-charge-findings", headers=headers, params=params)

    def get_missing_charge_finding(self, finding_id, headers):
        return self._request("GET", f"{P}/missing-charge-findings/{finding_id}", headers=headers)

    def disposition_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{P}/missing-charge-findings/{finding_id}/disposition", payload,
            headers=headers,
        )

    # ---------------- Impact analyses ----------------
    def create_price_change_analysis(self, payload, headers):
        return self._request("POST", f"{P}/price-change-analyses", payload, headers=headers)

    def list_price_change_analyses(self, headers, params=None):
        return self._request("GET", f"{P}/price-change-analyses", headers=headers, params=params)

    def get_price_change_analysis(self, analysis_id, headers):
        return self._request("GET", f"{P}/price-change-analyses/{analysis_id}", headers=headers)

    def sign_off_price_change_analysis(self, analysis_id, headers, payload=None):
        return self._request(
            "POST", f"{P}/price-change-analyses/{analysis_id}/sign-off", payload or {},
            headers=headers,
        )

    # ---------------- Transparency files ----------------
    def create_transparency_file(self, payload, headers):
        return self._request("POST", f"{P}/transparency-files", payload, headers=headers)

    def list_transparency_files(self, headers, params=None):
        return self._request("GET", f"{P}/transparency-files", headers=headers, params=params)

    def get_transparency_file(self, file_id, headers):
        return self._request("GET", f"{P}/transparency-files/{file_id}", headers=headers)

    def transparency_file_lifecycle(self, file_id, payload, headers):
        return self._request(
            "POST", f"{P}/transparency-files/{file_id}/lifecycle", payload, headers=headers
        )

    # ---------------- Logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )


api_client = ApiClient()
