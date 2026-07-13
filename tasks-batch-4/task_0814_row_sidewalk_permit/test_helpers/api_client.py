"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Applicant ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ---- StreetSegment ----
    def create_street_segment(self, payload, headers):
        return self._request("POST", "/street-segments", payload, headers)

    def get_street_segment(self, segment_id, headers):
        return self._request("GET", f"/street-segments/{segment_id}", headers=headers)

    def list_segment_lane_closures(self, segment_id, headers, params=None):
        return self._request(
            "GET", f"/street-segments/{segment_id}/lane-closures", headers=headers, params=params
        )

    # ---- SidewalkSpan ----
    def create_sidewalk_span(self, payload, headers):
        return self._request("POST", "/sidewalk-spans", payload, headers)

    def get_sidewalk_span(self, span_id, headers):
        return self._request("GET", f"/sidewalk-spans/{span_id}", headers=headers)

    def list_span_obstructions(self, span_id, headers, params=None):
        return self._request(
            "GET", f"/sidewalk-spans/{span_id}/obstructions", headers=headers, params=params
        )

    # ---- Permit lifecycle ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/submit", {}, headers)

    def decide_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/decision", payload, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    def close_out_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/close-out", {}, headers)

    def expire_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/expire", {}, headers)

    # ---- TrafficControlPlan ----
    def create_traffic_control_plan(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permits/{permit_id}/traffic-control-plan", payload, headers
        )

    def list_traffic_control_plans(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"/permits/{permit_id}/traffic-control-plans", headers=headers, params=params
        )

    def decide_traffic_control_plan(self, tcp_id, payload, headers):
        return self._request(
            "POST", f"/traffic-control-plans/{tcp_id}/decision", payload, headers
        )

    # ---- RestorationBond ----
    def post_bond(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/bond", payload, headers)

    def list_bond(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"/permits/{permit_id}/bond", headers=headers, params=params
        )

    def release_bond(self, bond_id, headers):
        return self._request("POST", f"/bonds/{bond_id}/release", {}, headers)

    # ---- LaneClosure ----
    def create_lane_closure(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/lane-closures", payload, headers)

    def list_lane_closures(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"/permits/{permit_id}/lane-closures", headers=headers, params=params
        )

    def activate_lane_closure(self, closure_id, headers):
        return self._request("POST", f"/lane-closures/{closure_id}/activate", {}, headers)

    def request_restoration(self, closure_id, payload, headers):
        return self._request(
            "POST", f"/lane-closures/{closure_id}/request-restoration", payload, headers
        )

    def sign_off(self, closure_id, payload, headers):
        return self._request("POST", f"/lane-closures/{closure_id}/sign-off", payload, headers)

    # ---- SidewalkObstruction ----
    def create_sidewalk_obstruction(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permits/{permit_id}/sidewalk-obstructions", payload, headers
        )

    def list_sidewalk_obstructions(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"/permits/{permit_id}/sidewalk-obstructions", headers=headers, params=params
        )

    def complete_restoration(self, obstruction_id, headers):
        return self._request(
            "POST", f"/sidewalk-obstructions/{obstruction_id}/complete-restoration", {}, headers
        )

    # ---- EncroachmentAgreement ----
    def create_encroachment_agreement(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permits/{permit_id}/encroachment-agreement", payload, headers
        )

    def list_encroachment_agreements(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"/permits/{permit_id}/encroachment-agreements", headers=headers, params=params
        )

    def execute_encroachment_agreement(self, ea_id, headers):
        return self._request(
            "POST", f"/encroachment-agreements/{ea_id}/execute", {}, headers
        )

    # ---- ViolationNotice ----
    def create_violation(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/violations", payload, headers)

    def list_violations(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"/permits/{permit_id}/violations", headers=headers, params=params
        )

    # ---- Test-driving logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
