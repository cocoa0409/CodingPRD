"""API client: one method per endpoint defined in the PRD (PRD §4).

Subclasses the framework's `GenericApiClient` to inherit HTTP plumbing; this
module supplies the per-endpoint thin wrappers.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Employer (PRD §3.1) ─────────────────────────────────────
    def create_employer(self, payload, headers):
        return self._request("POST", "/leave/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request(
            "GET", f"/leave/employers/{employer_id}", headers=headers
        )

    # ─── Employee (PRD §3.3) ─────────────────────────────────────
    def create_employee(self, payload, headers):
        return self._request("POST", "/leave/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request(
            "GET", f"/leave/employees/{employee_id}", headers=headers
        )

    def list_employees(self, headers, params=None):
        return self._request("GET", "/leave/employees", headers=headers, params=params)

    def patch_employee_health_enrollment(self, employee_id, payload, headers):
        return self._request(
            "PATCH",
            f"/leave/employees/{employee_id}/health-enrollment",
            payload,
            headers,
        )

    def terminate_employee(self, employee_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/employees/{employee_id}/terminate",
            payload if payload is not None else {},
            headers,
        )

    # ─── HealthcareProvider (PRD §3.5) ───────────────────────────
    def create_provider(self, payload, headers):
        return self._request("POST", "/leave/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request(
            "GET", f"/leave/providers/{provider_id}", headers=headers
        )

    # ─── LeaveCase (PRD §3.4) ────────────────────────────────────
    def create_case(self, payload, headers):
        return self._request("POST", "/leave/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/leave/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/leave/cases", headers=headers, params=params)

    def evaluate_eligibility(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/cases/{case_id}/evaluate-eligibility",
            payload if payload is not None else {},
            headers,
        )

    def approve_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/leave/cases/{case_id}/approve", payload, headers
        )

    def deny_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/cases/{case_id}/deny",
            payload if payload is not None else {},
            headers,
        )

    def complete_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/cases/{case_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def restore_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/cases/{case_id}/restore",
            payload if payload is not None else {},
            headers,
        )

    def forfeit_restoration(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/cases/{case_id}/forfeit-restoration",
            payload if payload is not None else {},
            headers,
        )

    def request_recertification(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/cases/{case_id}/request-recertification",
            payload if payload is not None else {},
            headers,
        )

    # ─── CertificationRecord (PRD §3.5) ──────────────────────────
    def create_certification(self, payload, headers):
        return self._request("POST", "/leave/certifications", payload, headers)

    def get_certification(self, cert_id, headers):
        return self._request(
            "GET", f"/leave/certifications/{cert_id}", headers=headers
        )

    def list_certifications(self, headers, params=None):
        return self._request(
            "GET", "/leave/certifications", headers=headers, params=params
        )

    def receive_certification(self, cert_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/certifications/{cert_id}/receive",
            payload if payload is not None else {},
            headers,
        )

    def mark_certification_complete(self, cert_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/certifications/{cert_id}/mark-complete",
            payload if payload is not None else {},
            headers,
        )

    def mark_certification_insufficient(self, cert_id, payload, headers):
        return self._request(
            "POST",
            f"/leave/certifications/{cert_id}/mark-insufficient",
            payload,
            headers,
        )

    # ─── LeaveInterval (PRD §3.6) ────────────────────────────────
    def create_interval(self, payload, headers):
        return self._request("POST", "/leave/intervals", payload, headers)

    def get_interval(self, interval_id, headers):
        return self._request(
            "GET", f"/leave/intervals/{interval_id}", headers=headers
        )

    def list_intervals(self, headers, params=None):
        return self._request(
            "GET", "/leave/intervals", headers=headers, params=params
        )

    def reverse_interval(self, interval_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leave/intervals/{interval_id}/reverse",
            payload if payload is not None else {},
            headers,
        )

    # ─── BenefitContinuationLedger (PRD §3.7) ────────────────────
    def get_benefit_ledger(self, ledger_id, headers):
        return self._request(
            "GET", f"/leave/benefit-ledgers/{ledger_id}", headers=headers
        )

    def list_benefit_ledgers(self, headers, params=None):
        return self._request(
            "GET", "/leave/benefit-ledgers", headers=headers, params=params
        )

    def apply_payment(self, ledger_id, payload, headers):
        return self._request(
            "POST",
            f"/leave/benefit-ledgers/{ledger_id}/apply-payment",
            payload,
            headers,
        )

    # ─── Notice (PRD §2.10) ──────────────────────────────────────
    def get_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/leave/notices/{notice_id}", headers=headers
        )

    def list_notices(self, headers, params=None):
        return self._request("GET", "/leave/notices", headers=headers, params=params)

    # ─── Test-driving (PRD §3.8) ─────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def seed_historic_interval(self, payload, headers):
        return self._request("POST", "/_intervals/seed-historic", payload, headers)


api_client = ApiClient()
