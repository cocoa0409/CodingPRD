"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Private Road Association API."""

    # ---------------- Associations ----------------

    def create_association(self, payload, headers):
        return self._request("POST", "/associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request("GET", f"/associations/{association_id}", headers=headers)

    # ---------------- Road segments ----------------

    def create_road_segment(self, payload, headers):
        return self._request("POST", "/road-segments", payload, headers)

    def get_road_segment(self, segment_id, headers):
        return self._request("GET", f"/road-segments/{segment_id}", headers=headers)

    def list_road_segments(self, headers, params=None):
        return self._request("GET", "/road-segments", headers=headers, params=params)

    def create_access_inspection(self, segment_id, payload, headers):
        return self._request(
            "POST", f"/road-segments/{segment_id}/access-inspections", payload, headers
        )

    # ---------------- Parcels ----------------

    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def reclassify_parcel(self, parcel_id, payload, headers):
        return self._request("PATCH", f"/parcels/{parcel_id}", payload, headers)

    def subdivide_parcel(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/subdivide", payload, headers)

    def list_parcel_connection_requests(self, parcel_id, headers, params=None):
        return self._request(
            "GET", f"/parcels/{parcel_id}/connection-requests", headers=headers, params=params
        )

    # ---------------- Members ----------------

    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def verify_deed(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/verify-deed", payload, headers)

    def list_member_ballots(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/ballots", headers=headers, params=params
        )

    def list_member_delinquency_actions(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/delinquency-actions", headers=headers, params=params
        )

    # ---------------- Assessment rolls ----------------

    def create_assessment_roll(self, payload, headers):
        return self._request("POST", "/assessment-rolls", payload, headers)

    def get_assessment_roll(self, roll_id, headers):
        return self._request("GET", f"/assessment-rolls/{roll_id}", headers=headers)

    def list_assessment_rolls(self, headers, params=None):
        return self._request("GET", "/assessment-rolls", headers=headers, params=params)

    def get_method_comparison(self, roll_id, headers):
        return self._request(
            "GET", f"/assessment-rolls/{roll_id}/method-comparison", headers=headers
        )

    def certify_roll(self, roll_id, headers, payload=None):
        return self._request(
            "POST", f"/assessment-rolls/{roll_id}/certify", payload or {}, headers
        )

    def recall_roll(self, roll_id, payload, headers):
        return self._request("POST", f"/assessment-rolls/{roll_id}/recall", payload, headers)

    def levy_roll(self, roll_id, headers, payload=None):
        return self._request(
            "POST", f"/assessment-rolls/{roll_id}/levy", payload or {}, headers
        )

    # ---------------- Assessment charges ----------------

    def get_assessment_charge(self, charge_id, headers):
        return self._request("GET", f"/assessment-charges/{charge_id}", headers=headers)

    def list_assessment_charges(self, headers, params=None):
        return self._request("GET", "/assessment-charges", headers=headers, params=params)

    def create_payment(self, charge_id, payload, headers):
        return self._request(
            "POST", f"/assessment-charges/{charge_id}/payments", payload, headers
        )

    def list_charge_delinquency_actions(self, charge_id, headers, params=None):
        return self._request(
            "GET",
            f"/assessment-charges/{charge_id}/delinquency-actions",
            headers=headers,
            params=params,
        )

    def create_delinquency_action(self, charge_id, payload, headers):
        return self._request(
            "POST", f"/assessment-charges/{charge_id}/delinquency-actions", payload, headers
        )

    # ---------------- Delinquency actions ----------------

    def list_delinquency_actions(self, headers, params=None):
        return self._request("GET", "/delinquency-actions", headers=headers, params=params)

    def get_delinquency_action(self, action_id, headers):
        return self._request("GET", f"/delinquency-actions/{action_id}", headers=headers)

    def effectuate_delinquency_action(self, action_id, headers, payload=None):
        return self._request(
            "POST", f"/delinquency-actions/{action_id}/effectuate", payload or {}, headers
        )

    def release_delinquency_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"/delinquency-actions/{action_id}/release", payload, headers
        )

    # ---------------- Special assessment proposals ----------------

    def create_proposal(self, payload, headers):
        return self._request("POST", "/special-assessment-proposals", payload, headers)

    def get_proposal(self, proposal_id, headers):
        return self._request(
            "GET", f"/special-assessment-proposals/{proposal_id}", headers=headers
        )

    def list_proposals(self, headers, params=None):
        return self._request(
            "GET", "/special-assessment-proposals", headers=headers, params=params
        )

    def open_balloting(self, proposal_id, payload, headers):
        return self._request(
            "POST",
            f"/special-assessment-proposals/{proposal_id}/open-balloting",
            payload,
            headers,
        )

    def tally_proposal(self, proposal_id, headers, payload=None):
        return self._request(
            "POST",
            f"/special-assessment-proposals/{proposal_id}/tally",
            payload or {},
            headers,
        )

    def list_proposal_ballots(self, proposal_id, headers, params=None):
        return self._request(
            "GET",
            f"/special-assessment-proposals/{proposal_id}/ballots",
            headers=headers,
            params=params,
        )

    # ---------------- Ballots ----------------

    def create_ballot(self, payload, headers):
        return self._request("POST", "/ballots", payload, headers)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/ballots/{ballot_id}", headers=headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/ballots", headers=headers, params=params)

    def revoke_ballot(self, ballot_id, payload, headers):
        return self._request("POST", f"/ballots/{ballot_id}/revoke", payload, headers)

    # ---------------- Maintenance projects ----------------

    def create_maintenance_project(self, payload, headers):
        return self._request("POST", "/maintenance-projects", payload, headers)

    def get_maintenance_project(self, project_id, headers):
        return self._request("GET", f"/maintenance-projects/{project_id}", headers=headers)

    def list_maintenance_projects(self, headers, params=None):
        return self._request("GET", "/maintenance-projects", headers=headers, params=params)

    def create_contractor_bid(self, project_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-projects/{project_id}/contractor-bids", payload, headers
        )

    def list_project_bids(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/maintenance-projects/{project_id}/contractor-bids",
            headers=headers,
            params=params,
        )

    def award_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-projects/{project_id}/award", payload, headers
        )

    def complete_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-projects/{project_id}/complete", payload, headers
        )

    def cancel_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-projects/{project_id}/cancel", payload, headers
        )

    # ---------------- Contractor bids ----------------

    def get_contractor_bid(self, bid_id, headers):
        return self._request("GET", f"/contractor-bids/{bid_id}", headers=headers)

    def list_contractor_bids(self, headers, params=None):
        return self._request("GET", "/contractor-bids", headers=headers, params=params)

    def withdraw_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/contractor-bids/{bid_id}/withdraw", payload, headers)

    # ---------------- Connection requests ----------------

    def create_connection_request(self, payload, headers):
        return self._request("POST", "/connection-requests", payload, headers)

    def get_connection_request(self, request_id, headers):
        return self._request("GET", f"/connection-requests/{request_id}", headers=headers)

    def list_connection_requests(self, headers, params=None):
        return self._request("GET", "/connection-requests", headers=headers, params=params)

    def decide_connection_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/connection-requests/{request_id}/decide", payload, headers
        )

    def resolve_connection_dispute(self, request_id, payload, headers):
        return self._request(
            "POST", f"/connection-requests/{request_id}/resolve-dispute", payload, headers
        )

    # ---------------- Logical clock ----------------

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
