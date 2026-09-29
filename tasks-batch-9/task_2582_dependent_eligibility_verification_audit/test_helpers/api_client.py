"""One method per declared endpoint of the dependent eligibility audit API."""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Json

Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """A thin typed wrapper: arguments follow the order of the path segments."""

    # -------------------------------------------------------------- logical clock
    def set_clock(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------ employees
    def create_employee(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def create_dependent(
        self, employee_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/employees/{employee_id}/dependents", payload, headers
        )

    def list_employee_dependents(
        self, employee_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/employees/{employee_id}/dependents", headers=headers, params=params
        )

    # ----------------------------------------------------------------- dependents
    def get_dependent(self, dependent_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/dependents/{dependent_id}", headers=headers)

    def create_paid_claim(
        self, dependent_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/dependents/{dependent_id}/paid-claims", payload, headers
        )

    def list_paid_claims(
        self, dependent_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/dependents/{dependent_id}/paid-claims", headers=headers, params=params
        )

    def list_dependent_amnesty_removals(
        self, dependent_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/dependents/{dependent_id}/amnesty-removals",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------------------- audit programs
    def create_program(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/audit-programs", payload, headers)

    def get_program(self, program_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/audit-programs/{program_id}", headers=headers)

    def list_programs(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/audit-programs", headers=headers, params=params)

    def create_documentation_rule(
        self, program_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit-programs/{program_id}/documentation-rules", payload, headers
        )

    def list_documentation_rules(
        self, program_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/audit-programs/{program_id}/documentation-rules",
            headers=headers,
            params=params,
        )

    def list_program_dependents(
        self, program_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/audit-programs/{program_id}/dependents",
            headers=headers,
            params=params,
        )

    def run_scope(
        self, program_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit-programs/{program_id}/scope", payload, headers
        )

    def communicate(
        self, program_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit-programs/{program_id}/communicate", payload, headers
        )

    def run_sweep(
        self, program_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit-programs/{program_id}/run-sweep", payload, headers
        )

    def measure_savings(
        self, program_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit-programs/{program_id}/measure-savings", payload, headers
        )

    def close_program(
        self, program_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit-programs/{program_id}/close", payload, headers
        )

    # ----------------------------------------------------------------- audit cases
    def get_case(self, case_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/audit-cases/{case_id}", headers=headers)

    def list_cases(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/audit-cases", headers=headers, params=params)

    def send_reminder(
        self, case_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit-cases/{case_id}/reminders", payload, headers
        )

    def list_case_communications(
        self, case_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/audit-cases/{case_id}/communications", headers=headers, params=params
        )

    def list_case_amnesty_removals(
        self, case_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/audit-cases/{case_id}/amnesty-removals",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------- proof submissions
    def create_proof_submission(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/proof-submissions", payload, headers)

    def get_proof_submission(
        self, submission_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/proof-submissions/{submission_id}", headers=headers
        )

    def list_proof_submissions(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/proof-submissions", headers=headers, params=params)

    def decide_proof_submission(
        self, submission_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/proof-submissions/{submission_id}/decision", payload, headers
        )

    def upload_redaction(
        self, submission_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/proof-submissions/{submission_id}/redaction", payload, headers
        )

    # ------------------------------------------------------------ amnesty removals
    def create_amnesty_removal(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/amnesty-removals", payload, headers)

    # -------------------------------------------------------------------- appeals
    def create_appeal(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/appeals", headers=headers, params=params)

    def assign_appeal(
        self, appeal_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/assign", payload, headers)

    def decide_appeal(
        self, appeal_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/decision", payload, headers)

    def resubmit_appeal(
        self, appeal_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/resubmit", payload, headers)

    # --------------------------------------------------------- termination notices
    def get_notice(self, notice_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/termination-notices/{notice_id}", headers=headers)

    def list_notices(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request(
            "GET", "/termination-notices", headers=headers, params=params
        )

    def continuation_election(
        self, notice_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/termination-notices/{notice_id}/continuation-election",
            payload,
            headers,
        )

    # ------------------------------------------------------------ claim recoveries
    def create_claim_recovery(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/claim-recoveries", payload, headers)

    def get_claim_recovery(
        self, recovery_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/claim-recoveries/{recovery_id}", headers=headers)

    def list_claim_recoveries(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/claim-recoveries", headers=headers, params=params)

    def issue_demand(
        self, recovery_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/claim-recoveries/{recovery_id}/issue-demand", payload, headers
        )

    def record_payment(
        self, recovery_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/claim-recoveries/{recovery_id}/payments", payload, headers
        )
