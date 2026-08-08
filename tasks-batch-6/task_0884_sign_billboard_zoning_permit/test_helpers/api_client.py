"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Parcels ---
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    # --- Applicants / Inspectors ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    # --- Sign applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit", {}, headers
        )

    def review_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/review", payload, headers
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/decide", payload, headers
        )

    # --- Variances ---
    def create_variance(self, payload, headers):
        return self._request("POST", "/variances", payload, headers)

    def get_variance(self, variance_id, headers):
        return self._request("GET", f"/variances/{variance_id}", headers=headers)

    def list_variances(self, headers, params=None):
        return self._request("GET", "/variances", headers=headers, params=params)

    def recommend_variance(self, variance_id, payload, headers):
        return self._request(
            "POST", f"/variances/{variance_id}/recommend", payload, headers
        )

    def decide_variance(self, variance_id, payload, headers):
        return self._request(
            "POST", f"/variances/{variance_id}/decide", payload, headers
        )

    # --- Permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def pay_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/pay", payload, headers)

    def renew_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/renew", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/record", payload, headers
        )

    # --- Non-conforming registry ---
    def create_non_conforming(self, payload, headers):
        return self._request("POST", "/non-conforming", payload, headers)

    def get_non_conforming(self, ncr_id, headers):
        return self._request("GET", f"/non-conforming/{ncr_id}", headers=headers)

    def list_non_conforming(self, headers, params=None):
        return self._request("GET", "/non-conforming", headers=headers, params=params)

    # --- Violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def cure_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/cure", {}, headers)

    def escalate_violation(self, violation_id, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/escalate", {}, headers
        )

    # --- Removal orders ---
    def get_removal_order(self, removal_order_id, headers):
        return self._request(
            "GET", f"/removal-orders/{removal_order_id}", headers=headers
        )

    def list_removal_orders(self, headers, params=None):
        return self._request("GET", "/removal-orders", headers=headers, params=params)

    # --- Billboards ---
    def create_billboard(self, payload, headers):
        return self._request("POST", "/billboards", payload, headers)

    def get_billboard(self, billboard_id, headers):
        return self._request("GET", f"/billboards/{billboard_id}", headers=headers)

    def list_billboards(self, headers, params=None):
        return self._request("GET", "/billboards", headers=headers, params=params)

    def register_billboard(self, billboard_id, payload, headers):
        return self._request(
            "POST", f"/billboards/{billboard_id}/register", payload, headers
        )

    # --- Billboard leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/billboard-leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/billboard-leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/billboard-leases", headers=headers, params=params)

    def terminate_lease(self, lease_id, headers):
        return self._request(
            "POST", f"/billboard-leases/{lease_id}/terminate", {}, headers
        )


api_client = ApiClient()
