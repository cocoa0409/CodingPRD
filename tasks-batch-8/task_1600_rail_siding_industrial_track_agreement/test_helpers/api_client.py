"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- TrackAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def submit_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/submit", headers=headers
        )

    def countersign_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/countersign", headers=headers
        )

    def offer_renewal(self, agreement_id, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/renewal-offer", headers=headers
        )

    def accept_renewal(self, agreement_id, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/accept-renewal", headers=headers
        )

    def terminate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/agreements/{agreement_id}/terminate", payload, headers
        )

    def file_abandonment_notice(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/agreements/{agreement_id}/file-abandonment-notice",
            payload,
            headers,
        )

    def verify_removal(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/verify-removal", payload, headers
        )

    # --- Amendment ---
    def create_amendment(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/amendments", payload, headers
        )

    def list_amendments(self, headers, params=None):
        return self._request("GET", "/amendments", headers=headers, params=params)

    def get_amendment(self, amendment_id, headers):
        return self._request("GET", f"/amendments/{amendment_id}", headers=headers)

    def respond_amendment(self, amendment_id, payload, headers):
        return self._request(
            "POST", f"/amendments/{amendment_id}/respond", payload, headers
        )

    # --- ConstructionProject ---
    def create_project(self, payload, headers):
        return self._request("POST", "/construction-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request(
            "GET", "/construction-projects", headers=headers, params=params
        )

    def get_project(self, project_id, headers):
        return self._request(
            "GET", f"/construction-projects/{project_id}", headers=headers
        )

    def submit_spec(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{project_id}/submit-spec",
            payload,
            headers,
        )

    def approve_spec(self, project_id, headers):
        return self._request(
            "POST", f"/construction-projects/{project_id}/approve-spec", headers=headers
        )

    def reject_spec(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/construction-projects/{project_id}/reject-spec",
            payload,
            headers,
        )

    def complete_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{project_id}/complete", payload, headers
        )

    def settle_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/construction-projects/{project_id}/settle", payload, headers
        )

    # --- TrackSegment ---
    def create_segment(self, payload, headers):
        return self._request("POST", "/segments", payload, headers)

    def list_segments(self, headers, params=None):
        return self._request("GET", "/segments", headers=headers, params=params)

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"/segments/{segment_id}", headers=headers)

    def take_out_of_service(self, segment_id, headers):
        return self._request(
            "POST", f"/segments/{segment_id}/take-out-of-service", headers=headers
        )

    def return_to_service(self, segment_id, headers):
        return self._request(
            "POST", f"/segments/{segment_id}/return-to-service", headers=headers
        )

    # --- SafetyInspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def record_result(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"/inspections/{inspection_id}/record-result",
            payload,
            headers,
        )

    # --- DerailDevice ---
    def create_device(self, payload, headers):
        return self._request("POST", "/derail-devices", payload, headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/derail-devices", headers=headers, params=params)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/derail-devices/{device_id}", headers=headers)

    def approve_device(self, device_id, headers):
        return self._request(
            "POST", f"/derail-devices/{device_id}/approve", headers=headers
        )

    def mark_installed(self, device_id, headers, payload=None):
        return self._request(
            "POST", f"/derail-devices/{device_id}/mark-installed", payload, headers
        )

    # --- ServiceOrder ---
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def complete_service_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/service-orders/{order_id}/complete", payload, headers
        )

    # --- CarDwell ---
    def create_car_dwell(self, payload, headers):
        return self._request("POST", "/car-dwells", payload, headers)

    def list_car_dwells(self, headers, params=None):
        return self._request("GET", "/car-dwells", headers=headers, params=params)

    def get_car_dwell(self, dwell_id, headers):
        return self._request("GET", f"/car-dwells/{dwell_id}", headers=headers)

    def release_car_dwell(self, dwell_id, payload, headers):
        return self._request(
            "POST", f"/car-dwells/{dwell_id}/release", payload, headers
        )

    # --- StoragePlacement ---
    def create_storage_placement(self, payload, headers):
        return self._request("POST", "/storage-placements", payload, headers)

    def list_storage_placements(self, headers, params=None):
        return self._request(
            "GET", "/storage-placements", headers=headers, params=params
        )

    def get_storage_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/storage-placements/{placement_id}", headers=headers
        )

    def release_storage_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/storage-placements/{placement_id}/release", payload, headers
        )

    # --- LiabilityClaim ---
    def create_liability_claim(self, payload, headers):
        return self._request("POST", "/liability-claims", payload, headers)

    def list_liability_claims(self, headers, params=None):
        return self._request(
            "GET", "/liability-claims", headers=headers, params=params
        )

    def get_liability_claim(self, claim_id, headers):
        return self._request("GET", f"/liability-claims/{claim_id}", headers=headers)

    def apportion_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/liability-claims/{claim_id}/apportion", payload, headers
        )

    def accept_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/liability-claims/{claim_id}/accept", headers=headers
        )

    def dispute_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/liability-claims/{claim_id}/dispute", payload, headers
        )

    # --- Logical clock (PRD §2.4) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
