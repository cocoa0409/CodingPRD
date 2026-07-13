"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- administrative ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers=headers)

    def create_storage_bin(self, payload, headers):
        return self._request("POST", "/storage-bins", payload, headers=headers)

    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers=headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def authorize_payment(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/authorize-payment", {}, headers=headers)

    def capture_payment(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/capture-payment", {}, headers=headers)

    def receive_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/receive", {}, headers=headers)

    def create_media_item(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/media-items", payload, headers=headers)

    # --- media items ---
    def get_media_item(self, item_id, headers):
        return self._request("GET", f"/media-items/{item_id}", headers=headers)

    def list_media_items(self, headers, params=None):
        return self._request("GET", "/media-items", headers=headers, params=params)

    def complete_scan(self, item_id, payload, headers):
        return self._request(
            "POST", f"/media-items/{item_id}/complete-scan", payload, headers=headers
        )

    def qc_review(self, item_id, payload, headers):
        return self._request("POST", f"/media-items/{item_id}/qc-review", payload, headers=headers)

    def list_qc_reviews(self, item_id, headers):
        return self._request("GET", f"/media-items/{item_id}/qc-reviews", headers=headers)

    def rescan(self, item_id, headers):
        return self._request("POST", f"/media-items/{item_id}/rescan", {}, headers=headers)

    def list_media_item_claims(self, item_id, headers):
        return self._request("GET", f"/media-items/{item_id}/damage-claims", headers=headers)

    # --- batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers=headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def load_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/load", payload, headers=headers)

    def run_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/run", {}, headers=headers)

    # --- output artifacts ---
    def create_output_artifact(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/output-artifacts", payload, headers=headers
        )

    def list_output_artifacts(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/output-artifacts", headers=headers)

    def get_output_artifact(self, artifact_id, headers):
        return self._request("GET", f"/output-artifacts/{artifact_id}", headers=headers)

    def download_artifact(self, artifact_id, headers):
        return self._request(
            "POST", f"/output-artifacts/{artifact_id}/download", {}, headers=headers
        )

    def list_downloads(self, artifact_id, headers):
        return self._request("GET", f"/output-artifacts/{artifact_id}/downloads", headers=headers)

    # --- damage claims ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers=headers)

    def list_order_claims(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/damage-claims", headers=headers)

    def review_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/review", payload, headers=headers)


api_client = ApiClient()
