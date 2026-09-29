"""HTTP client for the Employer-Sponsored Backup Child Care API.

One method per documented endpoint.  Every method returns the raw
requests.Response so tests can assert HTTP status codes directly.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/backup-care"


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the backup care API."""

    # ------------------------------------------------------------------
    # Logical clock / operations
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def run_daily_maintenance(
        self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_ops/run-daily-maintenance", payload or {}, headers)

    # ------------------------------------------------------------------
    # Employer
    # ------------------------------------------------------------------
    def create_employer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employers/{employer_id}", headers=headers)

    def list_employers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employers", headers=headers, params=params)

    def patch_employer(
        self, employer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/employers/{employer_id}", payload, headers)

    def list_employer_benefit_plans(
        self, employer_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/employers/{employer_id}/benefit-plans", headers=headers, params=params
        )

    def list_employer_employees(
        self, employer_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/employers/{employer_id}/employees", headers=headers, params=params
        )

    def list_employer_invoices(
        self, employer_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/employers/{employer_id}/invoices", headers=headers, params=params
        )

    def create_employer_invoice(
        self, employer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/employers/{employer_id}/invoices", payload, headers)

    def get_utilization_report(
        self, employer_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/employers/{employer_id}/utilization-report",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # BenefitPlan
    # ------------------------------------------------------------------
    def create_benefit_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/benefit-plans", payload, headers)

    def get_benefit_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/benefit-plans/{plan_id}", headers=headers)

    def list_benefit_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/benefit-plans", headers=headers, params=params)

    def patch_benefit_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/benefit-plans/{plan_id}", payload, headers)

    def activate_benefit_plan(
        self, plan_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/benefit-plans/{plan_id}/activate", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Employee
    # ------------------------------------------------------------------
    def create_employee(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employees/{employee_id}", headers=headers)

    def list_employees(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employees", headers=headers, params=params)

    def patch_employee(
        self, employee_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/employees/{employee_id}", payload, headers)

    def get_entitlement(self, employee_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employees/{employee_id}/entitlement", headers=headers)

    def list_dependents(
        self, employee_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/employees/{employee_id}/dependents", headers=headers, params=params
        )

    def create_dependent(
        self, employee_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/employees/{employee_id}/dependents", payload, headers)

    def list_employee_reservations(
        self, employee_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/employees/{employee_id}/reservations", headers=headers, params=params
        )

    def list_employee_ledger_entries(
        self, employee_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/employees/{employee_id}/ledger-entries", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Dependent
    # ------------------------------------------------------------------
    def get_dependent(self, dependent_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/dependents/{dependent_id}", headers=headers)

    def patch_dependent(
        self, dependent_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/dependents/{dependent_id}", payload, headers)

    # ------------------------------------------------------------------
    # Provider
    # ------------------------------------------------------------------
    def create_provider(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def get_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", headers=headers)

    def list_providers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/providers", headers=headers, params=params)

    def patch_provider(
        self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/providers/{provider_id}", payload, headers)

    def create_credential(
        self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/providers/{provider_id}/credentials", payload, headers)

    def list_credentials(
        self, provider_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/credentials", headers=headers, params=params
        )

    def credential_review(
        self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/credential-review", payload, headers
        )

    def set_network_status(
        self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/network-status", payload, headers
        )

    def create_capacity_block(
        self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/providers/{provider_id}/capacity-blocks", payload, headers
        )

    def list_capacity_blocks(
        self, provider_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/capacity-blocks", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Credential
    # ------------------------------------------------------------------
    def get_credential(self, credential_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/credentials/{credential_id}", headers=headers)

    def revoke_credential(
        self, credential_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/credentials/{credential_id}/revoke", payload, headers)

    # ------------------------------------------------------------------
    # CapacityBlock
    # ------------------------------------------------------------------
    def get_capacity_block(self, block_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/capacity-blocks/{block_id}", headers=headers)

    # ------------------------------------------------------------------
    # Reservation
    # ------------------------------------------------------------------
    def create_reservation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/reservations", payload, headers)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}", headers=headers)

    def list_reservations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/reservations", headers=headers, params=params)

    def match_reservation(
        self, reservation_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/match", payload or {}, headers
        )

    def reject_offer(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/reject-offer", payload, headers
        )

    def confirm_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/confirm", payload, headers
        )

    def cancel_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/cancel", payload, headers
        )

    def check_in_reservation(
        self, reservation_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/check-in", payload or {}, headers
        )

    def complete_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/complete", payload, headers
        )

    def no_show_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/no-show", payload, headers
        )

    def list_reservation_ledger_entries(
        self, reservation_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/reservations/{reservation_id}/ledger-entries",
            headers=headers,
            params=params,
        )

    def list_reservation_invoice_lines(
        self, reservation_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/reservations/{reservation_id}/invoice-lines",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # MatchOffer
    # ------------------------------------------------------------------
    def get_match_offer(self, offer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/match-offers/{offer_id}", headers=headers)

    def list_match_offers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/match-offers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # EmployerInvoice
    # ------------------------------------------------------------------
    def get_invoice(self, invoice_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/employer-invoices/{invoice_id}", headers=headers)

    def list_invoice_lines(
        self, invoice_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/employer-invoices/{invoice_id}/lines", headers=headers, params=params
        )

    def issue_invoice(
        self, invoice_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/employer-invoices/{invoice_id}/issue", payload or {}, headers
        )

    def pay_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/employer-invoices/{invoice_id}/payment", payload, headers
        )

    def void_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/employer-invoices/{invoice_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # IncidentReport
    # ------------------------------------------------------------------
    def create_incident_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/incident-reports", payload, headers)

    def get_incident_report(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/incident-reports/{incident_id}", headers=headers)

    def list_incident_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/incident-reports", headers=headers, params=params)

    def review_incident_report(
        self, incident_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/incident-reports/{incident_id}/review", payload or {}, headers
        )

    def substantiate_incident_report(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/incident-reports/{incident_id}/substantiate", payload, headers
        )

    def dismiss_incident_report(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/incident-reports/{incident_id}/dismiss", payload, headers
        )


api_client = ApiClient()
