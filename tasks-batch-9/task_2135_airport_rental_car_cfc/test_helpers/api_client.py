"""API client: one method per endpoint defined in the PRD (§4).

Every collection is mounted flat beneath /rac; there are no nested routes.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/rac"


class ApiClient(GenericApiClient):
    # ---------------- Facility ----------------
    def create_facility(self, payload, headers):
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", headers=headers)

    # ---------------- Concessionaire ----------------
    def create_concessionaire(self, payload, headers):
        return self._request("POST", f"{PREFIX}/concessionaires", payload, headers)

    def get_concessionaire(self, concessionaire_id, headers):
        return self._request(
            "GET", f"{PREFIX}/concessionaires/{concessionaire_id}", headers=headers
        )

    def list_concessionaires(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/concessionaires", headers=headers, params=params)

    # ---------------- ConcessionAgreement ----------------
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/concession-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/concession-agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/concession-agreements", headers=headers, params=params
        )

    def execute_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/concession-agreements/{agreement_id}/execute", {}, headers
        )

    def suspend_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/concession-agreements/{agreement_id}/suspend", {}, headers
        )

    def reinstate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/concession-agreements/{agreement_id}/reinstate", {}, headers
        )

    # ---------------- CounterSpace ----------------
    def create_counter_space(self, payload, headers):
        return self._request("POST", f"{PREFIX}/counter-spaces", payload, headers)

    def get_counter_space(self, counter_space_id, headers):
        return self._request(
            "GET", f"{PREFIX}/counter-spaces/{counter_space_id}", headers=headers
        )

    def list_counter_spaces(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/counter-spaces", headers=headers, params=params)

    # ---------------- CounterAssignment ----------------
    def create_counter_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/counter-assignments", payload, headers)

    def get_counter_assignment(self, counter_assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/counter-assignments/{counter_assignment_id}", headers=headers
        )

    def list_counter_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/counter-assignments", headers=headers, params=params
        )

    def activate_counter_assignment(self, counter_assignment_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/counter-assignments/{counter_assignment_id}/activate",
            {},
            headers,
        )

    def release_counter_assignment(self, counter_assignment_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/counter-assignments/{counter_assignment_id}/release",
            {},
            headers,
        )

    # ---------------- FleetParkingZone ----------------
    def create_fleet_zone(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fleet-parking-zones", payload, headers)

    def get_fleet_zone(self, zone_id, headers):
        return self._request("GET", f"{PREFIX}/fleet-parking-zones/{zone_id}", headers=headers)

    def list_fleet_zones(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fleet-parking-zones", headers=headers, params=params
        )

    # ---------------- FleetAllocation ----------------
    def create_fleet_allocation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fleet-allocations", payload, headers)

    def get_fleet_allocation(self, fleet_allocation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fleet-allocations/{fleet_allocation_id}", headers=headers
        )

    def list_fleet_allocations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fleet-allocations", headers=headers, params=params)

    def release_fleet_allocation(self, fleet_allocation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/fleet-allocations/{fleet_allocation_id}/release", {}, headers
        )

    # ---------------- TransactionDayReport ----------------
    def create_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transaction-day-reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transaction-day-reports/{report_id}", headers=headers
        )

    def list_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/transaction-day-reports", headers=headers, params=params
        )

    def submit_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transaction-day-reports/{report_id}/submit", {}, headers
        )

    def begin_audit_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transaction-day-reports/{report_id}/begin-audit", {}, headers
        )

    def accept_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transaction-day-reports/{report_id}/accept", payload, headers
        )

    def reject_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transaction-day-reports/{report_id}/reject", payload, headers
        )

    def reopen_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transaction-day-reports/{report_id}/reopen", {}, headers
        )

    # ---------------- CfcRemittance ----------------
    def create_remittance(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cfc-remittances", payload, headers)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"{PREFIX}/cfc-remittances/{remittance_id}", headers=headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cfc-remittances", headers=headers, params=params)

    def receive_remittance(self, remittance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cfc-remittances/{remittance_id}/receive", payload, headers
        )

    # ---------------- DebtServiceObligation ----------------
    def create_obligation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/debt-service-obligations", payload, headers)

    def get_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/debt-service-obligations/{obligation_id}", headers=headers
        )

    def list_obligations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/debt-service-obligations", headers=headers, params=params
        )

    def fund_obligation(self, obligation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/debt-service-obligations/{obligation_id}/fund", {}, headers
        )

    def pay_obligation(self, obligation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/debt-service-obligations/{obligation_id}/pay", {}, headers
        )

    # ---------------- ShuttleCostPeriod ----------------
    def create_shuttle_period(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shuttle-cost-periods", payload, headers)

    def get_shuttle_period(self, shuttle_period_id, headers):
        return self._request(
            "GET", f"{PREFIX}/shuttle-cost-periods/{shuttle_period_id}", headers=headers
        )

    def list_shuttle_periods(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/shuttle-cost-periods", headers=headers, params=params
        )

    def allocate_shuttle_period(self, shuttle_period_id, headers):
        return self._request(
            "POST", f"{PREFIX}/shuttle-cost-periods/{shuttle_period_id}/allocate", {}, headers
        )

    # ---------------- ShuttleCostAllocation ----------------
    def get_shuttle_allocation(self, shuttle_allocation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/shuttle-cost-allocations/{shuttle_allocation_id}", headers=headers
        )

    def list_shuttle_allocations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/shuttle-cost-allocations", headers=headers, params=params
        )

    # ---------------- CapitalProject ----------------
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/capital-projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/capital-projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/capital-projects", headers=headers, params=params)

    def approve_project(self, project_id, headers):
        return self._request(
            "POST", f"{PREFIX}/capital-projects/{project_id}/approve", {}, headers
        )

    def close_project(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/capital-projects/{project_id}/close", {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/capital-projects/{project_id}/cancel", {}, headers)

    # ---------------- CapitalDisbursement ----------------
    def create_disbursement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/capital-disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/capital-disbursements/{disbursement_id}", headers=headers
        )

    def list_disbursements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/capital-disbursements", headers=headers, params=params
        )

    def authorize_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/capital-disbursements/{disbursement_id}/authorize", {}, headers
        )

    def reject_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/capital-disbursements/{disbursement_id}/reject", {}, headers
        )

    def pay_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/capital-disbursements/{disbursement_id}/pay", {}, headers
        )

    def void_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/capital-disbursements/{disbursement_id}/void", {}, headers
        )

    # ---------------- TrueUpSettlement ----------------
    def create_settlement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/true-up-settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/true-up-settlements/{settlement_id}", headers=headers
        )

    def list_settlements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/true-up-settlements", headers=headers, params=params)

    def issue_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/true-up-settlements/{settlement_id}/issue", {}, headers
        )

    def dispute_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/true-up-settlements/{settlement_id}/dispute", {}, headers
        )

    def settle_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/true-up-settlements/{settlement_id}/settle", payload, headers
        )

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
