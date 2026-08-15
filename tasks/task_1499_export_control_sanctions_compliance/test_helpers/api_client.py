"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/compliance/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/compliance/products/{product_id}", headers=headers)

    # --- Classifications ---
    def create_classification(self, payload, headers):
        return self._request("POST", "/compliance/classifications", payload, headers)

    def get_classification(self, classification_id, headers):
        return self._request(
            "GET", f"/compliance/classifications/{classification_id}", headers=headers
        )

    def list_classifications(self, headers, params=None):
        return self._request("GET", "/compliance/classifications", headers=headers, params=params)

    def submit_classification(self, classification_id, headers):
        return self._request(
            "POST", f"/compliance/classifications/{classification_id}/submit", {}, headers
        )

    def review_classification(self, classification_id, payload, headers):
        return self._request(
            "POST", f"/compliance/classifications/{classification_id}/review", payload, headers
        )

    def revise_classification(self, classification_id, headers):
        return self._request(
            "POST", f"/compliance/classifications/{classification_id}/revise", {}, headers
        )

    # --- Parties ---
    def create_party(self, payload, headers):
        return self._request("POST", "/compliance/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/compliance/parties/{party_id}", headers=headers)

    def list_parties(self, headers, params=None):
        return self._request("GET", "/compliance/parties", headers=headers, params=params)

    def screen_party(self, party_id, headers):
        return self._request("POST", f"/compliance/parties/{party_id}/screen", {}, headers)

    # --- Screening list entries ---
    def create_screening_list_entry(self, payload, headers):
        return self._request("POST", "/compliance/screening-list-entries", payload, headers)

    def set_screening_list_entry_status(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/compliance/screening-list-entries/{entry_id}/set-status", payload, headers
        )

    # --- Screening results ---
    def get_screening_result(self, result_id, headers):
        return self._request(
            "GET", f"/compliance/screening-results/{result_id}", headers=headers
        )

    def list_screening_results(self, headers, params=None):
        return self._request("GET", "/compliance/screening-results", headers=headers, params=params)

    def resolve_screening_result(self, result_id, payload, headers):
        return self._request(
            "POST", f"/compliance/screening-results/{result_id}/resolve", payload, headers
        )

    # --- Export orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/compliance/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/compliance/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/compliance/orders", headers=headers, params=params)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/compliance/orders/{order_id}/submit", {}, headers)

    def release_order_hold(self, order_id, headers):
        return self._request("POST", f"/compliance/orders/{order_id}/release-hold", {}, headers)

    def attach_license_to_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/compliance/orders/{order_id}/attach-license", payload, headers
        )

    def release_order(self, order_id, headers):
        return self._request("POST", f"/compliance/orders/{order_id}/release", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/compliance/orders/{order_id}/cancel", {}, headers)

    # --- Licenses ---
    def create_license(self, payload, headers):
        return self._request("POST", "/compliance/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/compliance/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/compliance/licenses", headers=headers, params=params)

    def submit_license(self, license_id, headers):
        return self._request("POST", f"/compliance/licenses/{license_id}/submit", {}, headers)

    def review_license(self, license_id, payload, headers):
        return self._request("POST", f"/compliance/licenses/{license_id}/review", payload, headers)

    def revoke_license(self, license_id, headers):
        return self._request("POST", f"/compliance/licenses/{license_id}/revoke", {}, headers)

    # --- Shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/compliance/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/compliance/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/compliance/shipments", headers=headers, params=params)

    def screen_shipment(self, shipment_id, headers):
        return self._request("POST", f"/compliance/shipments/{shipment_id}/screen", {}, headers)

    def release_shipment(self, shipment_id, headers):
        return self._request("POST", f"/compliance/shipments/{shipment_id}/release", {}, headers)

    def advance_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/compliance/shipments/{shipment_id}/advance", payload, headers
        )

    # --- Technology control plans ---
    def create_tcp(self, payload, headers):
        return self._request("POST", "/compliance/tcps", payload, headers)

    def get_tcp(self, tcp_id, headers):
        return self._request("GET", f"/compliance/tcps/{tcp_id}", headers=headers)

    def list_tcps(self, headers, params=None):
        return self._request("GET", "/compliance/tcps", headers=headers, params=params)

    def set_tcp_status(self, tcp_id, payload, headers):
        return self._request("POST", f"/compliance/tcps/{tcp_id}/set-status", payload, headers)

    # --- Access grants ---
    def create_access_grant(self, payload, headers):
        return self._request("POST", "/compliance/access-grants", payload, headers)

    def get_access_grant(self, grant_id, headers):
        return self._request("GET", f"/compliance/access-grants/{grant_id}", headers=headers)

    def list_access_grants(self, headers, params=None):
        return self._request("GET", "/compliance/access-grants", headers=headers, params=params)

    def review_access_grant(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/compliance/access-grants/{grant_id}/review", payload, headers
        )

    def activate_access_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/compliance/access-grants/{grant_id}/activate", {}, headers
        )

    def revoke_access_grant(self, grant_id, headers):
        return self._request("POST", f"/compliance/access-grants/{grant_id}/revoke", {}, headers)

    # --- Violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/compliance/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/compliance/violations/{violation_id}", headers=headers)

    def advance_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"/compliance/violations/{violation_id}/advance", payload, headers
        )

    def submit_violation_disclosure(self, violation_id, headers):
        return self._request(
            "POST", f"/compliance/violations/{violation_id}/submit-disclosure", {}, headers
        )

    # --- Audit records ---
    def list_audit_records(self, headers, params=None):
        return self._request("GET", "/compliance/audit-records", headers=headers, params=params)

    def purge_audit_records(self, headers):
        return self._request("POST", "/compliance/audit-records/purge", {}, headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/compliance/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
