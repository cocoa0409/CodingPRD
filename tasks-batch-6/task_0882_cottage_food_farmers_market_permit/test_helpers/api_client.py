"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/cottage-food"


class ApiClient(GenericApiClient):
    # ---- Producer ----
    def create_producer(self, payload, headers):
        return self._request("POST", f"{BASE}/producers", payload, headers)

    def list_producers(self, headers, params=None):
        return self._request("GET", f"{BASE}/producers", headers=headers, params=params)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"{BASE}/producers/{producer_id}", headers=headers)

    def verify_producer(self, producer_id, payload, headers):
        return self._request("POST", f"{BASE}/producers/{producer_id}/verify", payload, headers)

    def reinstate_producer(self, producer_id, headers):
        return self._request("POST", f"{BASE}/producers/{producer_id}/reinstate", {}, headers)

    def get_compliance_summary(self, producer_id, headers):
        return self._request("GET", f"{BASE}/producers/{producer_id}/compliance-summary", headers=headers)

    # ---- AllowedFoodPolicy ----
    def create_policy(self, payload, headers):
        return self._request("POST", f"{BASE}/allowed-food-policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", f"{BASE}/allowed-food-policies", headers=headers, params=params)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", f"{BASE}/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{BASE}/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{BASE}/products/{product_id}", headers=headers)

    def review_food(self, product_id, payload, headers):
        return self._request("POST", f"{BASE}/products/{product_id}/review-food", payload, headers)

    def review_label(self, product_id, payload, headers):
        return self._request("POST", f"{BASE}/products/{product_id}/review-label", payload, headers)

    # ---- Permit ----
    def create_permit(self, payload, headers):
        return self._request("POST", f"{BASE}/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", f"{BASE}/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{BASE}/permits/{permit_id}", headers=headers)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"{BASE}/permits/{permit_id}/submit", {}, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"{BASE}/permits/{permit_id}/issue", {}, headers)

    def renew_permit(self, permit_id, payload, headers):
        return self._request("POST", f"{BASE}/permits/{permit_id}/renew", payload, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"{BASE}/permits/{permit_id}/revoke", {}, headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{BASE}/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", f"{BASE}/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"{BASE}/inspections/{inspection_id}", headers=headers)

    def close_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"{BASE}/inspections/{inspection_id}/close", payload, headers)

    # ---- Complaint ----
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{BASE}/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", f"{BASE}/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{BASE}/complaints/{complaint_id}", headers=headers)

    def review_complaint(self, complaint_id, headers):
        return self._request("POST", f"{BASE}/complaints/{complaint_id}/review", {}, headers)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"{BASE}/complaints/{complaint_id}/resolve", payload, headers)

    # ---- FarmersMarket ----
    def create_market(self, payload, headers):
        return self._request("POST", f"{BASE}/farmers-markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", f"{BASE}/farmers-markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"{BASE}/farmers-markets/{market_id}", headers=headers)

    # ---- MarketManifest ----
    def create_manifest(self, payload, headers):
        return self._request("POST", f"{BASE}/market-manifests", payload, headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", f"{BASE}/market-manifests", headers=headers, params=params)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"{BASE}/market-manifests/{manifest_id}", headers=headers)

    def submit_manifest(self, manifest_id, headers):
        return self._request("POST", f"{BASE}/market-manifests/{manifest_id}/submit", {}, headers)

    def approve_manifest(self, manifest_id, payload, headers):
        return self._request("POST", f"{BASE}/market-manifests/{manifest_id}/approve", payload, headers)

    def reject_manifest(self, manifest_id, headers):
        return self._request("POST", f"{BASE}/market-manifests/{manifest_id}/reject", {}, headers)

    def checkin_manifest(self, manifest_id, headers):
        return self._request("POST", f"{BASE}/market-manifests/{manifest_id}/check-in", {}, headers)

    def withdraw_manifest(self, manifest_id, headers):
        return self._request("POST", f"{BASE}/market-manifests/{manifest_id}/withdraw", {}, headers)

    # ---- SalesRecord ----
    def create_sales_record(self, payload, headers):
        return self._request("POST", f"{BASE}/sales-records", payload, headers)

    def list_sales_records(self, headers, params=None):
        return self._request("GET", f"{BASE}/sales-records", headers=headers, params=params)

    def get_sales_record(self, record_id, headers):
        return self._request("GET", f"{BASE}/sales-records/{record_id}", headers=headers)

    def void_sales_record(self, record_id, headers):
        return self._request("POST", f"{BASE}/sales-records/{record_id}/void", {}, headers)

    # ---- RecallEvent ----
    def create_recall(self, payload, headers):
        return self._request("POST", f"{BASE}/recall-events", payload, headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", f"{BASE}/recall-events", headers=headers, params=params)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"{BASE}/recall-events/{recall_id}", headers=headers)

    def resolve_recall(self, recall_id, payload, headers):
        return self._request("POST", f"{BASE}/recall-events/{recall_id}/resolve", payload, headers)

    # ---- Clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
