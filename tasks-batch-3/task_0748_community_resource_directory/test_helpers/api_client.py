"""API client: one method per endpoint declared by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Clock ----------
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)

    # ---------- Funders ----------
    def create_funder(self, payload: dict, headers: dict):
        return self._request("POST", "/funders", payload, headers=headers)

    def get_funder(self, funder_id: str, headers: dict):
        return self._request("GET", f"/funders/{funder_id}", headers=headers)

    def list_funder_reports(self, funder_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/funders/{funder_id}/reports", headers=headers, params=params)

    def create_funder_report(self, funder_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/funders/{funder_id}/reports", payload, headers=headers)

    # ---------- Providers ----------
    def create_provider(self, payload: dict, headers: dict):
        return self._request("POST", "/providers", payload, headers=headers)

    def get_provider(self, provider_id: str, headers: dict):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_provider_programs(self, provider_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/providers/{provider_id}/programs", headers=headers, params=params)

    # ---------- Programs ----------
    def create_program(self, payload: dict, headers: dict):
        return self._request("POST", "/programs", payload, headers=headers)

    def get_program(self, program_id: str, headers: dict):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers: dict, params: dict = None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def patch_program(self, program_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/programs/{program_id}", payload, headers=headers)

    def create_availability_window(self, program_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/programs/{program_id}/availability-windows", payload, headers=headers)

    def list_availability_windows(self, program_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/programs/{program_id}/availability-windows", headers=headers, params=params)

    # ---------- Clients ----------
    def create_client(self, payload: dict, headers: dict):
        return self._request("POST", "/clients", payload, headers=headers)

    def get_client(self, client_id: str, headers: dict):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def create_intake(self, client_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/clients/{client_id}/intakes", payload, headers=headers)

    # ---------- Intakes ----------
    def get_intake(self, intake_id: str, headers: dict):
        return self._request("GET", f"/intakes/{intake_id}", headers=headers)

    def list_intakes(self, headers: dict, params: dict = None):
        return self._request("GET", "/intakes", headers=headers, params=params)

    def screen_intake(self, intake_id: str, headers: dict):
        return self._request("POST", f"/intakes/{intake_id}/screen", {}, headers=headers)

    def reopen_intake(self, intake_id: str, headers: dict):
        return self._request("POST", f"/intakes/{intake_id}/reopen", {}, headers=headers)

    def create_referral(self, intake_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/intakes/{intake_id}/referrals", payload, headers=headers)

    # ---------- Consent grants ----------
    def create_consent_grant(self, client_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/clients/{client_id}/consent-grants", payload, headers=headers)

    def get_consent_grant(self, consent_grant_id: str, headers: dict):
        return self._request("GET", f"/consent-grants/{consent_grant_id}", headers=headers)

    def list_consent_grants(self, headers: dict, params: dict = None):
        return self._request("GET", "/consent-grants", headers=headers, params=params)

    def revoke_consent_grant(self, consent_grant_id: str, headers: dict):
        return self._request("POST", f"/consent-grants/{consent_grant_id}/revoke", {}, headers=headers)

    # ---------- Referrals ----------
    def get_referral(self, referral_id: str, headers: dict):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers: dict, params: dict = None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def accept_referral(self, referral_id: str, headers: dict):
        return self._request("POST", f"/referrals/{referral_id}/accept", {}, headers=headers)

    def decline_referral(self, referral_id: str, headers: dict):
        return self._request("POST", f"/referrals/{referral_id}/decline", {}, headers=headers)

    def start_service(self, referral_id: str, headers: dict):
        return self._request("POST", f"/referrals/{referral_id}/start-service", {}, headers=headers)

    def complete_referral(self, referral_id: str, outcome_class: str, headers: dict):
        return self._request(
            "POST",
            f"/referrals/{referral_id}/complete",
            {"outcome_class": outcome_class},
            headers=headers,
        )

    def withdraw_referral(self, referral_id: str, headers: dict):
        return self._request("POST", f"/referrals/{referral_id}/withdraw", {}, headers=headers)

    def create_transport_plan(self, referral_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/referrals/{referral_id}/transport-plans", payload, headers=headers)

    def list_transport_plans(self, referral_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/referrals/{referral_id}/transport-plans", headers=headers, params=params)

    def create_outcome_report(self, referral_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/referrals/{referral_id}/outcome-reports", payload, headers=headers)

    def list_outcome_reports(self, referral_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/referrals/{referral_id}/outcome-reports", headers=headers, params=params)

    def reverse_outcome_report(self, outcome_report_id: str, headers: dict):
        return self._request("POST", f"/outcome-reports/{outcome_report_id}/reverse", {}, headers=headers)

    # ---------- Raw ----------
    def raw_post(self, path: str, payload: dict, headers: dict):
        """Escape-hatch for negative auth tests where headers may be missing."""
        return self._request("POST", path, payload, headers=headers)


api_client = ApiClient()
