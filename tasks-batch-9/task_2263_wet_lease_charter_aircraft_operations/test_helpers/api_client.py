"""API client: one method per endpoint defined in the PRD.

Every resource is mounted under the ``/wetlease`` path prefix; the logical clock
endpoint is mounted at the root.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/wetlease"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock --
    def set_current_utc(self, current_utc: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # -------------------------------------------------------------- lessees --
    def create_lessee(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/lessees", payload, headers)

    def get_lessee(self, lessee_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/lessees/{lessee_id}", headers=headers)

    def suspend_lessee(self, lessee_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/lessees/{lessee_id}/suspend", {}, headers
        )

    def reinstate_lessee(self, lessee_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/lessees/{lessee_id}/reinstate", {}, headers
        )

    # ------------------------------------------------------------- aircraft --
    def create_aircraft(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/aircraft", headers=headers, params=params)

    def record_maintenance_event(self, aircraft_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/aircraft/{aircraft_id}/maintenance-events",
            payload,
            headers,
        )

    # --------------------------------------------------------- crew members --
    def create_crew_member(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/crew-members/{crew_member_id}", headers=headers
        )

    # -------------------------------------------------------------- leases ---
    def create_lease(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/leases", payload, headers)

    def get_lease(self, lease_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/leases/{lease_id}", headers=headers)

    def list_leases(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/leases", headers=headers, params=params)

    def submit_lease_for_approval(self, lease_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/submit-for-approval", payload, headers
        )

    def activate_lease(self, lease_id: str, headers=None):
        return self._request("POST", f"{PREFIX}/leases/{lease_id}/activate", {}, headers)

    def terminate_lease(self, lease_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/terminate", payload, headers
        )

    def withdraw_lease(self, lease_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/withdraw", payload, headers
        )

    def list_lease_regulatory_approvals(
        self, lease_id: str, headers=None, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/leases/{lease_id}/regulatory-approvals",
            headers=headers,
            params=params,
        )

    def list_lease_insurance_certificates(
        self, lease_id: str, headers=None, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/leases/{lease_id}/insurance-certificates",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------- regulatory approvals --
    def get_regulatory_approval(self, approval_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/regulatory-approvals/{approval_id}", headers=headers
        )

    def list_regulatory_approvals(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/regulatory-approvals", headers=headers, params=params
        )

    def record_determination(self, approval_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/regulatory-approvals/{approval_id}/decision",
            payload,
            headers,
        )

    def clear_approval_conditions(self, approval_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/regulatory-approvals/{approval_id}/clear-conditions",
            payload,
            headers,
        )

    def revoke_regulatory_approval(self, approval_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/regulatory-approvals/{approval_id}/revoke",
            payload,
            headers,
        )

    # ------------------------------------------------ insurance certificates --
    def create_insurance_certificate(self, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/insurance-certificates", payload, headers
        )

    def get_insurance_certificate(self, certificate_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/insurance-certificates/{certificate_id}", headers=headers
        )

    def list_insurance_certificates(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/insurance-certificates", headers=headers, params=params
        )

    def revoke_insurance_certificate(
        self, certificate_id: str, payload: dict, headers=None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/insurance-certificates/{certificate_id}/revoke",
            payload,
            headers,
        )

    # ------------------------------------------------- crew qualifications ---
    def create_crew_qualification(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/crew-qualifications", payload, headers)

    def get_crew_qualification(self, qualification_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/crew-qualifications/{qualification_id}", headers=headers
        )

    def list_crew_qualifications(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/crew-qualifications", headers=headers, params=params
        )

    def complete_checkride(self, qualification_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/crew-qualifications/{qualification_id}/complete-checkride",
            payload,
            headers,
        )

    # --------------------------------------------------------- flight legs ---
    def create_flight_leg(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/flight-legs", payload, headers)

    def get_flight_leg(self, leg_id: str, headers=None):
        return self._request("GET", f"{PREFIX}/flight-legs/{leg_id}", headers=headers)

    def list_flight_legs(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/flight-legs", headers=headers, params=params
        )

    def dispatch_flight_leg(self, leg_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/flight-legs/{leg_id}/dispatch", payload, headers
        )

    def complete_flight_leg(self, leg_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/flight-legs/{leg_id}/complete", payload, headers
        )

    def cancel_flight_leg(self, leg_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/flight-legs/{leg_id}/cancel", payload, headers
        )

    # ------------------------------------------------------- substitutions ---
    def create_substitution(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/substitutions", payload, headers)

    def get_substitution(self, substitution_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/substitutions/{substitution_id}", headers=headers
        )

    def list_substitutions(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/substitutions", headers=headers, params=params
        )

    def consent_substitution(self, substitution_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/substitutions/{substitution_id}/consent",
            payload,
            headers,
        )

    def effectuate_substitution(self, substitution_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/substitutions/{substitution_id}/effectuate", {}, headers
        )

    # -------------------------------------------------- utilization periods --
    def get_utilization_period(self, period_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/utilization-periods/{period_id}", headers=headers
        )

    def list_utilization_periods(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/utilization-periods", headers=headers, params=params
        )

    def get_settlement_preview(self, period_id: str, headers=None):
        return self._request(
            "GET",
            f"{PREFIX}/utilization-periods/{period_id}/settlement-preview",
            headers=headers,
        )

    def close_utilization_period(self, period_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/utilization-periods/{period_id}/close", {}, headers
        )

    def dispute_utilization_period(self, period_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/utilization-periods/{period_id}/dispute",
            payload,
            headers,
        )

    def resolve_dispute(self, period_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/utilization-periods/{period_id}/resolve-dispute",
            payload,
            headers,
        )

    # -------------------------------------------------- settlement invoices --
    def create_settlement_invoice(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/settlement-invoices", payload, headers)

    def get_settlement_invoice(self, invoice_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/settlement-invoices/{invoice_id}", headers=headers
        )

    def list_settlement_invoices(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/settlement-invoices", headers=headers, params=params
        )

    def approve_settlement_invoice(self, invoice_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/settlement-invoices/{invoice_id}/approve", {}, headers
        )

    def issue_settlement_invoice(self, invoice_id: str, headers=None):
        return self._request(
            "POST", f"{PREFIX}/settlement-invoices/{invoice_id}/issue", {}, headers
        )

    def void_settlement_invoice(self, invoice_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/settlement-invoices/{invoice_id}/void",
            payload,
            headers,
        )

    # --------------------------------------------------- reliability reports --
    def create_reliability_report(self, payload: dict, headers=None):
        return self._request("POST", f"{PREFIX}/reliability-reports", payload, headers)

    def get_reliability_report(self, report_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/reliability-reports/{report_id}", headers=headers
        )

    def list_reliability_reports(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/reliability-reports", headers=headers, params=params
        )

    def review_reliability_report(self, report_id: str, payload: dict, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/reliability-reports/{report_id}/review",
            payload,
            headers,
        )

    # ----------------------------------------------------- return conditions --
    def get_return_condition(self, return_id: str, headers=None):
        return self._request(
            "GET", f"{PREFIX}/return-conditions/{return_id}", headers=headers
        )

    def list_return_conditions(self, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/return-conditions", headers=headers, params=params
        )

    def inspect_return_condition(self, return_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/return-conditions/{return_id}/inspect", payload, headers
        )

    def close_return_condition(self, return_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"{PREFIX}/return-conditions/{return_id}/close", payload, headers
        )


api_client = ApiClient()
