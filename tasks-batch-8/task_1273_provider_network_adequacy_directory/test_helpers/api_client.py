"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ServiceRegion ---
    def create_region(self, payload, headers):
        return self._request("POST", "/network/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", "/network/regions", headers=headers, params=params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/network/regions/{region_id}", headers=headers)

    # --- NetworkStandard ---
    def create_standard(self, payload, headers):
        return self._request("POST", "/network/standards", payload, headers)

    def list_standards(self, headers, params=None):
        return self._request("GET", "/network/standards", headers=headers, params=params)

    def get_standard(self, standard_id, headers):
        return self._request("GET", f"/network/standards/{standard_id}", headers=headers)

    def update_standard(self, standard_id, payload, headers):
        return self._request("PUT", f"/network/standards/{standard_id}", payload, headers)

    # --- Provider ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/network/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/network/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/network/providers/{provider_id}", headers=headers)

    def patch_provider(self, provider_id, payload, headers):
        return self._request("PATCH", f"/network/providers/{provider_id}", payload, headers)

    # --- PracticeLocation ---
    def create_location(self, payload, headers):
        return self._request("POST", "/network/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/network/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/network/locations/{location_id}", headers=headers)

    def patch_location(self, location_id, payload, headers):
        return self._request("PATCH", f"/network/locations/{location_id}", payload, headers)

    # --- DirectoryListing ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/network/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/network/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/network/listings/{listing_id}", headers=headers)

    def publish_listing(self, listing_id, headers):
        return self._request("POST", f"/network/listings/{listing_id}/publish", headers=headers)

    def patch_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/network/listings/{listing_id}", payload, headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/network/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/network/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/network/members/{member_id}", headers=headers)

    def disenroll_member(self, member_id, headers):
        return self._request("POST", f"/network/members/{member_id}/disenroll", headers=headers)

    # --- AttestationCycle ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/network/attestation-cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/network/attestation-cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/network/attestation-cycles/{cycle_id}", headers=headers)

    def advance_cycle(self, cycle_id, headers):
        return self._request("POST", f"/network/attestation-cycles/{cycle_id}/advance", headers=headers)

    # --- AttestationRecord ---
    def list_attestation_records(self, headers, params=None):
        return self._request("GET", "/network/attestation-records", headers=headers, params=params)

    def get_attestation_record(self, record_id, headers):
        return self._request("GET", f"/network/attestation-records/{record_id}", headers=headers)

    def respond_attestation_record(self, record_id, payload, headers):
        return self._request("POST", f"/network/attestation-records/{record_id}/respond", payload, headers)

    # --- AvailabilityProbe ---
    def create_probe(self, payload, headers):
        return self._request("POST", "/network/probes", payload, headers)

    def list_probes(self, headers, params=None):
        return self._request("GET", "/network/probes", headers=headers, params=params)

    def get_probe(self, probe_id, headers):
        return self._request("GET", f"/network/probes/{probe_id}", headers=headers)

    def record_probe(self, probe_id, payload, headers):
        return self._request("POST", f"/network/probes/{probe_id}/record", payload, headers)

    # --- AdequacyEvaluation ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/network/evaluations", payload, headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/network/evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/network/evaluations/{evaluation_id}", headers=headers)

    def finalize_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/network/evaluations/{evaluation_id}/finalize", headers=headers)

    def get_penalty_summary(self, evaluation_id, headers):
        return self._request("GET", f"/network/evaluations/{evaluation_id}/penalty-summary", headers=headers)

    # --- RegionSpecialtyResult ---
    def list_results(self, headers, params=None):
        return self._request("GET", "/network/results", headers=headers, params=params)

    def get_result(self, result_id, headers):
        return self._request("GET", f"/network/results/{result_id}", headers=headers)

    # --- DeficiencyRecord ---
    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/network/deficiencies", headers=headers, params=params)

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/network/deficiencies/{deficiency_id}", headers=headers)

    # --- AccessPlanRequest ---
    def create_access_plan_request(self, deficiency_id, payload, headers):
        return self._request("POST", f"/network/deficiencies/{deficiency_id}/access-plan-requests", payload, headers)

    def list_access_plan_requests(self, headers, params=None):
        return self._request("GET", "/network/access-plan-requests", headers=headers, params=params)

    def get_access_plan_request(self, request_id, headers):
        return self._request("GET", f"/network/access-plan-requests/{request_id}", headers=headers)

    def submit_access_plan_request(self, request_id, headers):
        return self._request("POST", f"/network/access-plan-requests/{request_id}/submit", headers=headers)

    def decide_access_plan_request(self, request_id, payload, headers):
        return self._request("POST", f"/network/access-plan-requests/{request_id}/decide", payload, headers)

    # --- MemberComplaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/network/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/network/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/network/complaints/{complaint_id}", headers=headers)

    def adjudicate_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/network/complaints/{complaint_id}/adjudicate", payload, headers)

    # --- DirectoryCorrection ---
    def create_correction(self, payload, headers):
        return self._request("POST", "/network/corrections", payload, headers)

    def list_corrections(self, headers, params=None):
        return self._request("GET", "/network/corrections", headers=headers, params=params)

    def get_correction(self, correction_id, headers):
        return self._request("GET", f"/network/corrections/{correction_id}", headers=headers)

    def verify_correction(self, correction_id, payload, headers):
        return self._request("POST", f"/network/corrections/{correction_id}/verify", payload, headers)


api_client = ApiClient()
