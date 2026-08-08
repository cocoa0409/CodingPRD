"""API client: one method per endpoint in the Community-Service & Work-Crew API.

Subclasses the framework's GenericApiClient; the base ``_request`` handles transport.
GET methods pass query parameters via ``params``; POST methods pass a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- participants ----
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    # ---- sites ----
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def activate_site(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/activate", {}, headers)

    def pause_site(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/pause", {}, headers)

    # ---- insurance policies ----
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    def verify_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/verify", {}, headers)

    def reject_insurance_policy(self, policy_id, headers, payload=None):
        return self._request("POST", f"/insurance-policies/{policy_id}/reject",
                             payload or {}, headers)

    # ---- supervisors ----
    def create_supervisor(self, payload, headers):
        return self._request("POST", "/supervisors", payload, headers)

    def get_supervisor(self, supervisor_id, headers):
        return self._request("GET", f"/supervisors/{supervisor_id}", headers=headers)

    def list_supervisors(self, headers, params=None):
        return self._request("GET", "/supervisors", headers=headers, params=params)

    # ---- referrals ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral_summary(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}/summary", headers=headers)

    def reinstate_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/reinstate", {}, headers)

    def terminate_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/referrals/{referral_id}/terminate",
                             payload or {}, headers)

    # ---- placements ----
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def sign_waiver(self, placement_id, payload, headers):
        return self._request("POST", f"/placements/{placement_id}/sign-waiver",
                             payload, headers)

    def activate_placement(self, placement_id, headers):
        return self._request("POST", f"/placements/{placement_id}/activate", {}, headers)

    def terminate_placement(self, placement_id, headers, payload=None):
        return self._request("POST", f"/placements/{placement_id}/terminate",
                             payload or {}, headers)

    # ---- work sessions ----
    def create_work_session(self, payload, headers):
        return self._request("POST", "/work-sessions", payload, headers)

    def get_work_session(self, session_id, headers):
        return self._request("GET", f"/work-sessions/{session_id}", headers=headers)

    def list_work_sessions(self, headers, params=None):
        return self._request("GET", "/work-sessions", headers=headers, params=params)

    def check_in(self, session_id, headers, payload=None):
        return self._request("POST", f"/work-sessions/{session_id}/check-in",
                             payload or {}, headers)

    def check_out(self, session_id, headers, payload=None):
        return self._request("POST", f"/work-sessions/{session_id}/check-out",
                             payload or {}, headers)

    def verify_work_session(self, session_id, payload, headers):
        return self._request("POST", f"/work-sessions/{session_id}/verify",
                             payload, headers)

    def void_work_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/work-sessions/{session_id}/void",
                             payload or {}, headers)

    # ---- fee conversions ----
    def create_fee_conversion(self, payload, headers):
        return self._request("POST", "/fee-conversions", payload, headers)

    def get_fee_conversion(self, fee_id, headers):
        return self._request("GET", f"/fee-conversions/{fee_id}", headers=headers)

    def list_fee_conversions(self, headers, params=None):
        return self._request("GET", "/fee-conversions", headers=headers, params=params)

    def approve_fee_conversion(self, fee_id, headers):
        return self._request("POST", f"/fee-conversions/{fee_id}/approve", {}, headers)

    def deny_fee_conversion(self, fee_id, headers, payload=None):
        return self._request("POST", f"/fee-conversions/{fee_id}/deny",
                             payload or {}, headers)

    def pay_fee_conversion(self, fee_id, payload, headers):
        return self._request("POST", f"/fee-conversions/{fee_id}/pay", payload, headers)

    def reverse_fee_conversion(self, fee_id, headers, payload=None):
        return self._request("POST", f"/fee-conversions/{fee_id}/reverse",
                             payload or {}, headers)

    # ---- compliance actions ----
    def create_compliance_action(self, payload, headers):
        return self._request("POST", "/compliance-actions", payload, headers)

    def get_compliance_action(self, action_id, headers):
        return self._request("GET", f"/compliance-actions/{action_id}", headers=headers)

    def list_compliance_actions(self, headers, params=None):
        return self._request("GET", "/compliance-actions", headers=headers, params=params)

    # ---- certificates ----
    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)


api_client = ApiClient()
