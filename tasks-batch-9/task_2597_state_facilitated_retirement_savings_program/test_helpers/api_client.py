"""
HTTP client for the state-facilitated retirement savings program API.

One method per documented endpoint. Every method returns the raw
`requests.Response` so tests can assert on status codes as well as bodies.
Collection reads pass their filters through `params`; writes pass a JSON
`payload`. Auth headers are always explicit — the caller decides which role and
which identity is acting, which matters because employers and participants act
under their own row identifier.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import ApiResponse, Headers, JsonDict, Params


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the retirement savings program API."""

    # ------------------------------------------------------------------
    # Logical clock and scheduled batches
    # ------------------------------------------------------------------
    def set_current_utc(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_auto_enrollment(self, headers: Headers,
                            payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", "/_ops/auto-enrollment-run",
                            payload or {}, headers)

    def run_annual_escalation(self, headers: Headers,
                              payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", "/_ops/annual-escalation-run",
                            payload or {}, headers)

    def run_compliance_sweep(self, headers: Headers,
                             payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", "/_ops/compliance-sweep", payload or {}, headers)

    # ------------------------------------------------------------------
    # Program years
    # ------------------------------------------------------------------
    def create_program_year(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/program-years", payload, headers)

    def list_program_years(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/program-years", params, headers)

    # ------------------------------------------------------------------
    # Investment options
    # ------------------------------------------------------------------
    def create_investment_option(self, payload: JsonDict,
                                 headers: Headers) -> ApiResponse:
        return self._request("POST", "/investment-options", payload, headers)

    def list_investment_options(self, headers: Headers,
                                params: Params = None) -> ApiResponse:
        return self._request("GET", "/investment-options", params, headers)

    def get_investment_option(self, option_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/investment-options/{option_id}", None, headers)

    # ------------------------------------------------------------------
    # Employers
    # ------------------------------------------------------------------
    def create_employer(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/employers/{employer_id}", None, headers)

    def register_employer(self, employer_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("POST", f"/employers/{employer_id}/registration",
                            payload, headers)

    def recount_employees(self, employer_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/employers/{employer_id}/employee-count-recounts",
                            payload, headers)

    # ------------------------------------------------------------------
    # Exemption certifications
    # ------------------------------------------------------------------
    def create_exemption_certification(self, employer_id: str, payload: JsonDict,
                                       headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/employers/{employer_id}/exemption-certifications",
                            payload, headers)

    def list_employer_exemption_certifications(self, employer_id: str,
                                               headers: Headers,
                                               params: Params = None) -> ApiResponse:
        return self._request("GET",
                            f"/employers/{employer_id}/exemption-certifications",
                            params, headers)

    def get_exemption_certification(self, exemption_id: str,
                                    headers: Headers) -> ApiResponse:
        return self._request("GET", f"/exemption-certifications/{exemption_id}",
                            None, headers)

    def decide_exemption_certification(self, exemption_id: str, payload: JsonDict,
                                       headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/exemption-certifications/{exemption_id}/decision",
                            payload, headers)

    def revoke_exemption_certification(self, exemption_id: str, payload: JsonDict,
                                       headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/exemption-certifications/{exemption_id}/revoke",
                            payload, headers)

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def create_participant(self, payload: JsonDict, headers: Headers) -> ApiResponse:
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/participants/{participant_id}", None, headers)

    def list_participants(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/participants", params, headers)

    def update_participant(self, participant_id: str, payload: JsonDict,
                           headers: Headers) -> ApiResponse:
        return self._request("PATCH", f"/participants/{participant_id}",
                            payload, headers)

    # ------------------------------------------------------------------
    # Enrollments
    # ------------------------------------------------------------------
    def create_enrollment(self, employer_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("POST", f"/employers/{employer_id}/enrollments",
                            payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/enrollments/{enrollment_id}", None, headers)

    def list_enrollments(self, headers: Headers, params: Params = None) -> ApiResponse:
        return self._request("GET", "/enrollments", params, headers)

    def opt_out_enrollment(self, enrollment_id: str, payload: JsonDict,
                           headers: Headers) -> ApiResponse:
        return self._request("POST", f"/enrollments/{enrollment_id}/opt-out",
                            payload, headers)

    def reenroll(self, enrollment_id: str, headers: Headers,
                 payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/enrollments/{enrollment_id}/reenroll",
                            payload or {}, headers)

    def elect_contribution_rate(self, enrollment_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request("POST", f"/enrollments/{enrollment_id}/rate-election",
                            payload, headers)

    def update_employment(self, enrollment_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("PATCH", f"/enrollments/{enrollment_id}/employment",
                            payload, headers)

    def list_enrollment_remittance_lines(self, enrollment_id: str, headers: Headers,
                                         params: Params = None) -> ApiResponse:
        return self._request("GET",
                            f"/enrollments/{enrollment_id}/remittance-lines",
                            params, headers)

    # ------------------------------------------------------------------
    # Participant accounts
    # ------------------------------------------------------------------
    def get_participant_account(self, account_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/participant-accounts/{account_id}",
                            None, headers)

    def list_participant_accounts(self, headers: Headers,
                                  params: Params = None) -> ApiResponse:
        return self._request("GET", "/participant-accounts", params, headers)

    def create_investment_election(self, account_id: str, payload: JsonDict,
                                   headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/participant-accounts/{account_id}/investment-elections",
                            payload, headers)

    def list_investment_elections(self, account_id: str, headers: Headers,
                                  params: Params = None) -> ApiResponse:
        return self._request("GET",
                            f"/participant-accounts/{account_id}/investment-elections",
                            params, headers)

    def post_earnings(self, account_id: str, payload: JsonDict,
                      headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/participant-accounts/{account_id}/earnings-postings",
                            payload, headers)

    def request_account_closure(self, account_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/participant-accounts/{account_id}/closure-requests",
                            payload, headers)

    def complete_account_closure(self, account_id: str, headers: Headers,
                                 payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST",
                            f"/participant-accounts/{account_id}/closure-completion",
                            payload or {}, headers)

    def list_account_excess_cases(self, account_id: str, headers: Headers,
                                  params: Params = None) -> ApiResponse:
        return self._request(
            "GET",
            f"/participant-accounts/{account_id}/excess-contribution-cases",
            params, headers)

    # ------------------------------------------------------------------
    # Payroll remittances
    # ------------------------------------------------------------------
    def create_payroll_remittance(self, employer_id: str, payload: JsonDict,
                                  headers: Headers) -> ApiResponse:
        return self._request("POST", f"/employers/{employer_id}/payroll-remittances",
                            payload, headers)

    def get_payroll_remittance(self, remittance_id: str,
                               headers: Headers) -> ApiResponse:
        return self._request("GET", f"/payroll-remittances/{remittance_id}",
                            None, headers)

    def list_payroll_remittances(self, headers: Headers,
                                 params: Params = None) -> ApiResponse:
        return self._request("GET", "/payroll-remittances", params, headers)

    def list_employer_payroll_remittances(self, employer_id: str, headers: Headers,
                                          params: Params = None) -> ApiResponse:
        merged = dict(params or {})
        merged["employer_id"] = employer_id
        return self._request("GET", "/payroll-remittances", merged, headers)

    def create_remittance_line(self, remittance_id: str, payload: JsonDict,
                               headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/payroll-remittances/{remittance_id}/remittance-lines",
                            payload, headers)

    def list_remittance_lines(self, remittance_id: str, headers: Headers,
                              params: Params = None) -> ApiResponse:
        return self._request("GET",
                            f"/payroll-remittances/{remittance_id}/remittance-lines",
                            params, headers)

    def submit_remittance(self, remittance_id: str, headers: Headers,
                          payload: Optional[JsonDict] = None) -> ApiResponse:
        return self._request("POST", f"/payroll-remittances/{remittance_id}/submit",
                            payload or {}, headers)

    def post_remittance(self, remittance_id: str, payload: JsonDict,
                        headers: Headers) -> ApiResponse:
        return self._request("POST", f"/payroll-remittances/{remittance_id}/post",
                            payload, headers)

    def reject_remittance(self, remittance_id: str, payload: JsonDict,
                          headers: Headers) -> ApiResponse:
        return self._request("POST", f"/payroll-remittances/{remittance_id}/reject",
                            payload, headers)

    def reverse_remittance(self, remittance_id: str, payload: JsonDict,
                           headers: Headers) -> ApiResponse:
        return self._request("POST", f"/payroll-remittances/{remittance_id}/reverse",
                            payload, headers)

    # ------------------------------------------------------------------
    # Excess contribution cases
    # ------------------------------------------------------------------
    def get_excess_case(self, case_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/excess-contribution-cases/{case_id}",
                            None, headers)

    def elect_correction_method(self, case_id: str, payload: JsonDict,
                                headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/excess-contribution-cases/{case_id}/method-election",
                            payload, headers)

    def complete_excess_case(self, case_id: str, payload: JsonDict,
                             headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/excess-contribution-cases/{case_id}/completion",
                            payload, headers)

    # ------------------------------------------------------------------
    # Penalty assessments and enforcement referrals
    # ------------------------------------------------------------------
    def create_penalty_assessment(self, employer_id: str, payload: JsonDict,
                                  headers: Headers) -> ApiResponse:
        return self._request("POST", f"/employers/{employer_id}/penalty-assessments",
                            payload, headers)

    def list_employer_penalty_assessments(self, employer_id: str, headers: Headers,
                                          params: Params = None) -> ApiResponse:
        return self._request("GET", f"/employers/{employer_id}/penalty-assessments",
                            params, headers)

    def get_penalty_assessment(self, penalty_id: str, headers: Headers) -> ApiResponse:
        return self._request("GET", f"/penalty-assessments/{penalty_id}", None, headers)

    def dispose_penalty_assessment(self, penalty_id: str, payload: JsonDict,
                                   headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/penalty-assessments/{penalty_id}/disposition",
                            payload, headers)

    def create_enforcement_referral(self, penalty_id: str, payload: JsonDict,
                                    headers: Headers) -> ApiResponse:
        return self._request("POST",
                            f"/penalty-assessments/{penalty_id}/enforcement-referrals",
                            payload, headers)

    def list_enforcement_referrals(self, penalty_id: str, headers: Headers,
                                   params: Params = None) -> ApiResponse:
        return self._request("GET",
                            f"/penalty-assessments/{penalty_id}/enforcement-referrals",
                            params, headers)

    # ------------------------------------------------------------------
    # Portability transfers
    # ------------------------------------------------------------------
    def create_portability_transfer(self, payload: JsonDict,
                                    headers: Headers) -> ApiResponse:
        return self._request("POST", "/portability-transfers", payload, headers)

    def get_portability_transfer(self, transfer_id: str,
                                 headers: Headers) -> ApiResponse:
        return self._request("GET", f"/portability-transfers/{transfer_id}",
                            None, headers)

    def list_portability_transfers(self, headers: Headers,
                                   params: Params = None) -> ApiResponse:
        return self._request("GET", "/portability-transfers", params, headers)

    def settle_portability_transfer(self, transfer_id: str, payload: JsonDict,
                                    headers: Headers) -> ApiResponse:
        return self._request("POST", f"/portability-transfers/{transfer_id}/settle",
                            payload, headers)

    def return_portability_transfer(self, transfer_id: str, payload: JsonDict,
                                    headers: Headers) -> ApiResponse:
        return self._request("POST", f"/portability-transfers/{transfer_id}/return",
                            payload, headers)
