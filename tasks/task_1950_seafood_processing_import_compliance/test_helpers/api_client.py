"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Foreign suppliers & FSVP
    # ------------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/seafood/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/seafood/suppliers/{supplier_id}",
                             headers=headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/seafood/suppliers/{supplier_id}/suspend",
                             {}, headers)

    def create_supplier_evaluation(self, payload, headers):
        return self._request("POST", "/seafood/supplier-evaluations",
                             payload, headers)

    def get_supplier_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/seafood/supplier-evaluations/{evaluation_id}",
            headers=headers)

    def list_supplier_evaluations(self, headers, params=None):
        return self._request("GET", "/seafood/supplier-evaluations",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Import entries & FDA prior notice
    # ------------------------------------------------------------------
    def create_import_entry(self, payload, headers):
        return self._request("POST", "/seafood/import-entries", payload, headers)

    def get_import_entry(self, entry_id, headers):
        return self._request("GET", f"/seafood/import-entries/{entry_id}",
                             headers=headers)

    def list_import_entries(self, headers, params=None):
        return self._request("GET", "/seafood/import-entries",
                             headers=headers, params=params)

    def file_prior_notice(self, entry_id, headers):
        return self._request(
            "POST", f"/seafood/import-entries/{entry_id}/file-prior-notice",
            {}, headers)

    def file_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/seafood/import-entries/{entry_id}/file-entry",
            {}, headers)

    def fda_disposition(self, entry_id, outcome, headers):
        return self._request(
            "POST", f"/seafood/import-entries/{entry_id}/fda-disposition",
            {"outcome": outcome}, headers)

    # ------------------------------------------------------------------
    # Receipt lots & catch documentation
    # ------------------------------------------------------------------
    def create_receipt_lot(self, payload, headers):
        return self._request("POST", "/seafood/receipt-lots", payload, headers)

    def get_receipt_lot(self, lot_id, headers):
        return self._request("GET", f"/seafood/receipt-lots/{lot_id}",
                             headers=headers)

    def list_receipt_lots(self, headers, params=None):
        return self._request("GET", "/seafood/receipt-lots",
                             headers=headers, params=params)

    def accept_receipt_lot(self, lot_id, headers):
        return self._request("POST", f"/seafood/receipt-lots/{lot_id}/accept",
                             {}, headers)

    def reject_receipt_lot(self, lot_id, reason, headers):
        return self._request("POST", f"/seafood/receipt-lots/{lot_id}/reject",
                             {"reason": reason}, headers)

    def quarantine_receipt_lot(self, lot_id, reason, headers):
        return self._request("POST", f"/seafood/receipt-lots/{lot_id}/quarantine",
                             {"reason": reason}, headers)

    def quarantine_release_receipt_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/seafood/receipt-lots/{lot_id}/quarantine-release",
            {}, headers)

    # ------------------------------------------------------------------
    # Species verification & mislabeling
    # ------------------------------------------------------------------
    def create_species_verification(self, payload, headers):
        return self._request("POST", "/seafood/species-verifications",
                             payload, headers)

    def get_species_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/seafood/species-verifications/{verification_id}",
            headers=headers)

    def list_species_verifications(self, headers, params=None):
        return self._request("GET", "/seafood/species-verifications",
                             headers=headers, params=params)

    def resolve_species_verification(self, verification_id, resolution, headers):
        return self._request(
            "POST", f"/seafood/species-verifications/{verification_id}/resolve",
            {"resolution": resolution}, headers)

    # ------------------------------------------------------------------
    # Processing batches, inputs, yield
    # ------------------------------------------------------------------
    def create_processing_batch(self, payload, headers):
        return self._request("POST", "/seafood/processing-batches",
                             payload, headers)

    def get_processing_batch(self, batch_id, headers):
        return self._request("GET", f"/seafood/processing-batches/{batch_id}",
                             headers=headers)

    def add_batch_input(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/seafood/processing-batches/{batch_id}/inputs",
            payload, headers)

    def delete_batch_input(self, input_id, headers):
        return self._request("DELETE", f"/seafood/batch-input-lots/{input_id}",
                             headers=headers)

    def get_batch_input(self, input_id, headers):
        return self._request("GET", f"/seafood/batch-input-lots/{input_id}",
                             headers=headers)

    def list_batch_inputs(self, headers, params=None):
        return self._request("GET", "/seafood/batch-input-lots",
                             headers=headers, params=params)

    def complete_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/seafood/processing-batches/{batch_id}/complete",
            payload, headers)

    def reopen_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/seafood/processing-batches/{batch_id}/reopen",
            {}, headers)

    def reconcile_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/seafood/processing-batches/{batch_id}/reconcile",
            {}, headers)

    # ------------------------------------------------------------------
    # Cold chain / freezing records
    # ------------------------------------------------------------------
    def create_temperature_log(self, payload, headers):
        return self._request("POST", "/seafood/temperature-logs",
                             payload, headers)

    def get_temperature_log(self, log_id, headers):
        return self._request("GET", f"/seafood/temperature-logs/{log_id}",
                             headers=headers)

    def list_temperature_logs(self, headers, params=None):
        return self._request("GET", "/seafood/temperature-logs",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # HACCP monitoring
    # ------------------------------------------------------------------
    def create_haccp_record(self, payload, headers):
        return self._request("POST", "/seafood/haccp-monitoring-records",
                             payload, headers)

    def get_haccp_record(self, record_id, headers):
        return self._request("GET", f"/seafood/haccp-monitoring-records/{record_id}",
                             headers=headers)

    def list_haccp_records(self, headers, params=None):
        return self._request("GET", "/seafood/haccp-monitoring-records",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Corrective actions
    # ------------------------------------------------------------------
    def create_corrective_action(self, payload, headers):
        return self._request("POST", "/seafood/corrective-actions",
                             payload, headers)

    def get_corrective_action(self, ca_id, headers):
        return self._request("GET", f"/seafood/corrective-actions/{ca_id}",
                             headers=headers)

    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/seafood/corrective-actions",
                             headers=headers, params=params)

    def investigate_corrective_action(self, ca_id, headers):
        return self._request(
            "POST", f"/seafood/corrective-actions/{ca_id}/investigate",
            {}, headers)

    def resolve_corrective_action(self, ca_id, resolution_note, headers):
        return self._request(
            "POST", f"/seafood/corrective-actions/{ca_id}/resolve",
            {"resolution_note": resolution_note}, headers)

    def escalate_corrective_action(self, ca_id, reason, scope_lot_ids, headers):
        return self._request(
            "POST", f"/seafood/corrective-actions/{ca_id}/escalate",
            {"reason": reason, "scope_lot_ids": scope_lot_ids}, headers)

    # ------------------------------------------------------------------
    # Labeling (allergen + COOL)
    # ------------------------------------------------------------------
    def create_product_label(self, payload, headers):
        return self._request("POST", "/seafood/product-labels", payload, headers)

    def get_product_label(self, label_id, headers):
        return self._request("GET", f"/seafood/product-labels/{label_id}",
                             headers=headers)

    def list_product_labels(self, headers, params=None):
        return self._request("GET", "/seafood/product-labels",
                             headers=headers, params=params)

    def approve_product_label(self, label_id, headers):
        return self._request(
            "POST", f"/seafood/product-labels/{label_id}/approve",
            {}, headers)

    # ------------------------------------------------------------------
    # Finished product lots
    # ------------------------------------------------------------------
    def create_finished_lot(self, payload, headers):
        return self._request("POST", "/seafood/finished-product-lots",
                             payload, headers)

    def get_finished_lot(self, lot_id, headers):
        return self._request("GET", f"/seafood/finished-product-lots/{lot_id}",
                             headers=headers)

    def list_finished_lots(self, headers, params=None):
        return self._request("GET", "/seafood/finished-product-lots",
                             headers=headers, params=params)

    def apply_label(self, lot_id, product_label_id, headers):
        return self._request(
            "POST", f"/seafood/finished-product-lots/{lot_id}/apply-label",
            {"product_label_id": product_label_id}, headers)

    def release_finished_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/seafood/finished-product-lots/{lot_id}/release",
            {}, headers)

    # ------------------------------------------------------------------
    # Recalls
    # ------------------------------------------------------------------
    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/seafood/recalls/{recall_id}",
                             headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/seafood/recalls",
                             headers=headers, params=params)

    def notify_recall(self, recall_id, headers):
        return self._request("POST", f"/seafood/recalls/{recall_id}/notify",
                             {}, headers)


api_client = ApiClient()
