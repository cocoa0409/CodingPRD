"""API client: one method per endpoint defined in the Pharmacy Compounding PRD.

Subclasses the framework GenericApiClient; the base _request() handles the HTTP
plumbing. Every method returns the raw requests.Response so tests assert status.
"""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/pharmacy-compounding"


class ApiClient(GenericApiClient):
    # --- Facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", f"{BASE}/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", f"{BASE}/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{BASE}/facilities/{facility_id}", headers=headers)

    def set_clock(self, facility_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/facilities/{facility_id}/_clock/set", payload, headers
        )

    # --- Master Formulation Records ---
    def create_mfr(self, payload, headers):
        return self._request("POST", f"{BASE}/master-formulation-records", payload, headers)

    def list_mfrs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/master-formulation-records", headers=headers, params=params
        )

    def get_mfr(self, mfr_id, headers):
        return self._request(
            "GET", f"{BASE}/master-formulation-records/{mfr_id}", headers=headers
        )

    def retire_mfr(self, mfr_id, headers):
        return self._request(
            "POST", f"{BASE}/master-formulation-records/{mfr_id}/retire", {}, headers
        )

    def get_anticipatory_ledger_for_mfr(self, mfr_id, headers):
        return self._request(
            "GET",
            f"{BASE}/master-formulation-records/{mfr_id}/anticipatory-ledger",
            headers=headers,
        )

    # --- Anticipatory Ledgers ---
    def list_anticipatory_ledgers(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/anticipatory-ledgers", headers=headers, params=params
        )

    def get_anticipatory_ledger(self, ledger_id, headers):
        return self._request(
            "GET", f"{BASE}/anticipatory-ledgers/{ledger_id}", headers=headers
        )

    # --- Ingredient Lots ---
    def create_ingredient_lot(self, payload, headers):
        return self._request("POST", f"{BASE}/ingredient-lots", payload, headers)

    def list_ingredient_lots(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/ingredient-lots", headers=headers, params=params
        )

    def get_ingredient_lot(self, lot_id, headers):
        return self._request(
            "GET", f"{BASE}/ingredient-lots/{lot_id}", headers=headers
        )

    def release_quarantine_lot(self, lot_id, headers):
        return self._request(
            "POST", f"{BASE}/ingredient-lots/{lot_id}/release-quarantine", {}, headers
        )

    # --- Environmental Logs ---
    def create_environmental_log(self, payload, headers):
        return self._request("POST", f"{BASE}/environmental-logs", payload, headers)

    def list_environmental_logs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/environmental-logs", headers=headers, params=params
        )

    def get_environmental_log(self, log_id, headers):
        return self._request(
            "GET", f"{BASE}/environmental-logs/{log_id}", headers=headers
        )

    # --- Prescriptions ---
    def create_prescription(self, payload, headers):
        return self._request("POST", f"{BASE}/prescriptions", payload, headers)

    def list_prescriptions(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/prescriptions", headers=headers, params=params
        )

    def get_prescription(self, rx_id, headers):
        return self._request("GET", f"{BASE}/prescriptions/{rx_id}", headers=headers)

    def cancel_prescription(self, rx_id, headers):
        return self._request(
            "POST", f"{BASE}/prescriptions/{rx_id}/cancel", {}, headers
        )

    # --- Compounding Batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", f"{BASE}/compounding-batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/compounding-batches", headers=headers, params=params
        )

    def get_batch(self, batch_id, headers):
        return self._request(
            "GET", f"{BASE}/compounding-batches/{batch_id}", headers=headers
        )

    def start_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{BASE}/compounding-batches/{batch_id}/start", {}, headers
        )

    def compile_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/compounding-batches/{batch_id}/compile", payload, headers
        )

    def quarantine_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{BASE}/compounding-batches/{batch_id}/quarantine", {}, headers
        )

    def reprocess_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{BASE}/compounding-batches/{batch_id}/reprocess", {}, headers
        )

    def release_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/compounding-batches/{batch_id}/release", payload, headers
        )

    def reject_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{BASE}/compounding-batches/{batch_id}/reject", {}, headers
        )

    # --- Batch Ingredient Usages ---
    def create_batch_ingredient_usage(self, payload, headers):
        return self._request("POST", f"{BASE}/batch-ingredient-usages", payload, headers)

    def list_batch_ingredient_usages(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/batch-ingredient-usages", headers=headers, params=params
        )

    def get_batch_ingredient_usage(self, usage_id, headers):
        return self._request(
            "GET", f"{BASE}/batch-ingredient-usages/{usage_id}", headers=headers
        )

    # --- QC Tests ---
    def create_qc_test(self, payload, headers):
        return self._request("POST", f"{BASE}/qc-tests", payload, headers)

    def list_qc_tests(self, headers, params=None):
        return self._request("GET", f"{BASE}/qc-tests", headers=headers, params=params)

    def get_qc_test(self, qc_id, headers):
        return self._request("GET", f"{BASE}/qc-tests/{qc_id}", headers=headers)

    def begin_qc_test(self, qc_id, headers):
        return self._request("POST", f"{BASE}/qc-tests/{qc_id}/begin", {}, headers)

    def record_qc_test(self, qc_id, payload, headers):
        return self._request("POST", f"{BASE}/qc-tests/{qc_id}/record", payload, headers)

    # --- Finished Preparations ---
    def list_finished_preparations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/finished-preparations", headers=headers, params=params
        )

    def get_finished_preparation(self, prep_id, headers):
        return self._request(
            "GET", f"{BASE}/finished-preparations/{prep_id}", headers=headers
        )

    # --- Dispenses ---
    def create_dispense(self, payload, headers):
        return self._request("POST", f"{BASE}/dispenses", payload, headers)

    def list_dispenses(self, headers, params=None):
        return self._request("GET", f"{BASE}/dispenses", headers=headers, params=params)

    def get_dispense(self, dispense_id, headers):
        return self._request("GET", f"{BASE}/dispenses/{dispense_id}", headers=headers)

    # --- Recalls ---
    def create_recall(self, payload, headers):
        return self._request("POST", f"{BASE}/recalls", payload, headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", f"{BASE}/recalls", headers=headers, params=params)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"{BASE}/recalls/{recall_id}", headers=headers)

    def advance_recall(self, recall_id, headers):
        return self._request(
            "POST", f"{BASE}/recalls/{recall_id}/advance", {}, headers
        )

    def reconcile_recall(self, recall_id, headers):
        return self._request(
            "POST", f"{BASE}/recalls/{recall_id}/reconcile", {}, headers
        )

    def reopen_recall(self, recall_id, headers):
        return self._request(
            "POST", f"{BASE}/recalls/{recall_id}/reopen", {}, headers
        )

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"{BASE}/recalls/{recall_id}/close", {}, headers)


api_client = ApiClient()
