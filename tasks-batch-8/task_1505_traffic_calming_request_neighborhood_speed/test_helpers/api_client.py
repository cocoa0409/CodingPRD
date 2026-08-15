"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- StreetSegment ---
    def create_segment(self, payload, headers):
        return self._request("POST", "/api/segments", payload, headers)

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"/api/segments/{segment_id}", headers=headers)

    # --- Resident ---
    def create_resident(self, payload, headers):
        return self._request("POST", "/api/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/api/residents/{resident_id}", headers=headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/api/residents", headers=headers, params=params)

    # --- TrafficCalmingRequest ---
    def create_request(self, payload, headers):
        return self._request("POST", "/api/requests", payload, headers)

    def get_request(self, request_id, headers):
        return self._request("GET", f"/api/requests/{request_id}", headers=headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", "/api/requests", headers=headers, params=params)

    def open_petition(self, request_id, headers):
        return self._request(
            "POST", f"/api/requests/{request_id}/open-petition", headers=headers
        )

    def sign_petition(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/api/requests/{request_id}/petition-signatures",
            payload or {}, headers,
        )

    def list_request_signatures(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/api/requests/{request_id}/petition-signatures",
            headers=headers, params=params,
        )

    def list_resident_signatures(self, resident_id, headers, params=None):
        return self._request(
            "GET", f"/api/residents/{resident_id}/petition-signatures",
            headers=headers, params=params,
        )

    def retract_signature(self, signature_id, headers):
        return self._request(
            "DELETE", f"/api/petition-signatures/{signature_id}", headers=headers
        )

    # --- SpeedStudy & StudyObservation ---
    def create_speed_study(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/requests/{request_id}/speed-studies", payload, headers
        )

    def get_speed_study(self, study_id, headers):
        return self._request("GET", f"/api/speed-studies/{study_id}", headers=headers)

    def list_speed_studies(self, headers, params=None):
        return self._request("GET", "/api/speed-studies", headers=headers, params=params)

    def record_observation(self, study_id, payload, headers):
        return self._request(
            "POST", f"/api/speed-studies/{study_id}/observations", payload, headers
        )

    def list_observations(self, study_id, headers, params=None):
        return self._request(
            "GET", f"/api/speed-studies/{study_id}/observations",
            headers=headers, params=params,
        )

    def analyze_study(self, study_id, headers):
        return self._request(
            "POST", f"/api/speed-studies/{study_id}/analyze", headers=headers
        )

    def return_study_for_recollection(self, study_id, headers):
        return self._request(
            "POST", f"/api/speed-studies/{study_id}/return-for-recollection",
            headers=headers,
        )

    def certify_study(self, study_id, headers):
        return self._request(
            "POST", f"/api/speed-studies/{study_id}/certify", headers=headers
        )

    # --- TreatmentPlan ---
    def create_treatment_plan(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/requests/{request_id}/treatment-plans", payload, headers
        )

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/api/treatment-plans/{plan_id}", headers=headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/api/treatment-plans", headers=headers, params=params)

    def submit_plan_for_review(self, plan_id, headers):
        return self._request(
            "POST", f"/api/treatment-plans/{plan_id}/submit-for-review",
            headers=headers,
        )

    def approve_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/api/treatment-plans/{plan_id}/approve", headers=headers
        )

    def request_plan_revision(self, plan_id, headers):
        return self._request(
            "POST", f"/api/treatment-plans/{plan_id}/request-revision", headers=headers
        )

    # --- FundingCycle ---
    def create_funding_cycle(self, payload, headers):
        return self._request("POST", "/api/funding-cycles", payload, headers)

    def get_funding_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/funding-cycles/{cycle_id}", headers=headers)

    def get_cycle_ranking(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/api/funding-cycles/{cycle_id}/ranking",
            headers=headers, params=params,
        )

    def publish_ranking(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/api/funding-cycles/{cycle_id}/publish-ranking", payload, headers
        )

    def close_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/funding-cycles/{cycle_id}/close", headers=headers
        )

    # --- Ballot & BallotVote ---
    def create_ballot(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/requests/{request_id}/ballots", payload, headers
        )

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/api/ballots/{ballot_id}", headers=headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/api/ballots", headers=headers, params=params)

    def cast_vote(self, ballot_id, payload, headers):
        return self._request(
            "POST", f"/api/ballots/{ballot_id}/votes", payload, headers
        )

    def list_ballot_votes(self, ballot_id, headers, params=None):
        return self._request(
            "GET", f"/api/ballots/{ballot_id}/votes", headers=headers, params=params
        )

    def list_resident_votes(self, resident_id, headers, params=None):
        return self._request(
            "GET", f"/api/residents/{resident_id}/ballot-votes",
            headers=headers, params=params,
        )

    # --- InstallationWorkOrder ---
    def create_work_order(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/requests/{request_id}/installation-work-orders",
            payload, headers,
        )

    def get_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"/api/installation-work-orders/{work_order_id}", headers=headers
        )

    def list_work_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/installation-work-orders", headers=headers, params=params
        )

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/api/installation-work-orders/{work_order_id}/schedule",
            payload, headers,
        )

    def review_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/api/installation-work-orders/{work_order_id}/emergency-review",
            payload, headers,
        )

    def mark_work_order_installed(self, work_order_id, headers):
        return self._request(
            "POST", f"/api/installation-work-orders/{work_order_id}/mark-installed",
            headers=headers,
        )

    # --- RemovalRequest ---
    def create_removal_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/requests/{request_id}/removal-requests", payload, headers
        )

    def get_removal_request(self, removal_id, headers):
        return self._request(
            "GET", f"/api/removal-requests/{removal_id}", headers=headers
        )

    def list_removal_requests(self, headers, params=None):
        return self._request("GET", "/api/removal-requests", headers=headers, params=params)

    def approve_removal(self, removal_id, headers):
        return self._request(
            "POST", f"/api/removal-requests/{removal_id}/approve", headers=headers
        )

    def reject_removal(self, removal_id, headers):
        return self._request(
            "POST", f"/api/removal-requests/{removal_id}/reject", headers=headers
        )


api_client = ApiClient()
