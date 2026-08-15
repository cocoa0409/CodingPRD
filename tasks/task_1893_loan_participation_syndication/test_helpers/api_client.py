"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Borrowers ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/api/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/api/borrowers/{borrower_id}", headers=headers)

    def list_borrower_facilities(self, borrower_id, headers, params=None):
        return self._request(
            "GET", f"/api/borrowers/{borrower_id}/facilities", headers=headers, params=params
        )

    # --- Facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/api/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/api/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/api/facilities", headers=headers, params=params)

    def terminate_facility(self, facility_id, headers):
        return self._request(
            "POST", f"/api/facilities/{facility_id}/terminate", {}, headers
        )

    def list_facility_participants(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/api/facilities/{facility_id}/participants", headers=headers, params=params
        )

    def list_facility_draws(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/api/facilities/{facility_id}/draws", headers=headers, params=params
        )

    def list_facility_payments(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/api/facilities/{facility_id}/payments", headers=headers, params=params
        )

    def list_facility_modification_requests(self, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/facilities/{facility_id}/modification_requests",
            headers=headers,
            params=params,
        )

    def list_facility_default_cases(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/api/facilities/{facility_id}/default_cases", headers=headers, params=params
        )

    # --- Participants ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/api/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/api/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/api/participants", headers=headers, params=params)

    def commit_participant(self, participant_id, headers):
        return self._request(
            "POST", f"/api/participants/{participant_id}/commit", {}, headers
        )

    def withdraw_participant(self, participant_id, headers):
        return self._request(
            "POST", f"/api/participants/{participant_id}/withdraw", {}, headers
        )

    # --- Draws ---
    def create_draw(self, payload, headers):
        return self._request("POST", "/api/draws", payload, headers)

    def list_draws(self, headers, params=None):
        return self._request("GET", "/api/draws", headers=headers, params=params)

    def get_draw(self, draw_id, headers):
        return self._request("GET", f"/api/draws/{draw_id}", headers=headers)

    def cancel_draw(self, draw_id, headers):
        return self._request("POST", f"/api/draws/{draw_id}/cancel", {}, headers)

    # --- Funding settlements ---
    def get_funding_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/api/funding_settlements/{settlement_id}", headers=headers
        )

    def list_funding_settlements(self, headers, params=None):
        return self._request(
            "GET", "/api/funding_settlements", headers=headers, params=params
        )

    def report_wire(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/api/funding_settlements/{settlement_id}/report_wire", payload, headers
        )

    def confirm_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/api/funding_settlements/{settlement_id}/confirm", payload, headers
        )

    def mark_settlement_defaulted(self, settlement_id, headers):
        return self._request(
            "POST", f"/api/funding_settlements/{settlement_id}/mark_defaulted", {}, headers
        )

    # --- Borrower payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/api/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/api/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/api/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/api/payments/{payment_id}/reverse", {}, headers)

    def create_distribution_run(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/api/payments/{payment_id}/distribution_runs", payload, headers
        )

    # --- Distribution runs & lines ---
    def get_distribution_run(self, run_id, headers):
        return self._request("GET", f"/api/distribution_runs/{run_id}", headers=headers)

    def list_distribution_runs(self, headers, params=None):
        return self._request("GET", "/api/distribution_runs", headers=headers, params=params)

    def remit_distribution_run(self, run_id, headers):
        return self._request(
            "POST", f"/api/distribution_runs/{run_id}/remit", {}, headers
        )

    def get_distribution_line(self, line_id, headers):
        return self._request("GET", f"/api/distribution_lines/{line_id}", headers=headers)

    def list_distribution_lines(self, headers, params=None):
        return self._request("GET", "/api/distribution_lines", headers=headers, params=params)

    # --- Modification requests & consent votes ---
    def create_modification_request(self, payload, headers):
        return self._request("POST", "/api/modification_requests", payload, headers)

    def get_modification_request(self, modification_id, headers):
        return self._request(
            "GET", f"/api/modification_requests/{modification_id}", headers=headers
        )

    def list_modification_requests(self, headers, params=None):
        return self._request(
            "GET", "/api/modification_requests", headers=headers, params=params
        )

    def solicit_modification(self, modification_id, headers):
        return self._request(
            "POST", f"/api/modification_requests/{modification_id}/solicit", {}, headers
        )

    def cast_consent_vote(self, modification_id, payload, headers):
        return self._request(
            "POST", f"/api/modification_requests/{modification_id}/votes", payload, headers
        )

    def tally_close_modification(self, modification_id, headers):
        return self._request(
            "POST", f"/api/modification_requests/{modification_id}/tally_close", {}, headers
        )

    def implement_modification(self, modification_id, headers):
        return self._request(
            "POST", f"/api/modification_requests/{modification_id}/implement", {}, headers
        )

    def withdraw_modification(self, modification_id, headers):
        return self._request(
            "POST", f"/api/modification_requests/{modification_id}/withdraw", {}, headers
        )

    def recast_consent_vote(self, vote_id, payload, headers):
        return self._request(
            "POST", f"/api/consent_votes/{vote_id}/recast", payload, headers
        )

    def get_consent_vote(self, vote_id, headers):
        return self._request("GET", f"/api/consent_votes/{vote_id}", headers=headers)

    def list_consent_votes(self, headers, params=None):
        return self._request("GET", "/api/consent_votes", headers=headers, params=params)

    # --- Default cases & votes ---
    def create_default_case(self, payload, headers):
        return self._request("POST", "/api/default_cases", payload, headers)

    def get_default_case(self, case_id, headers):
        return self._request("GET", f"/api/default_cases/{case_id}", headers=headers)

    def list_default_cases(self, headers, params=None):
        return self._request("GET", "/api/default_cases", headers=headers, params=params)

    def cast_default_vote(self, case_id, payload, headers):
        return self._request(
            "POST", f"/api/default_cases/{case_id}/votes", payload, headers
        )

    def cure_default_case(self, case_id, headers):
        return self._request("POST", f"/api/default_cases/{case_id}/cure", {}, headers)

    def accelerate_default_case(self, case_id, headers):
        return self._request(
            "POST", f"/api/default_cases/{case_id}/accelerate", {}, headers
        )

    def waive_default_case(self, case_id, headers):
        return self._request("POST", f"/api/default_cases/{case_id}/waive", {}, headers)

    def recast_default_vote(self, vote_id, payload, headers):
        return self._request(
            "POST", f"/api/default_votes/{vote_id}/recast", payload, headers
        )

    def get_default_vote(self, vote_id, headers):
        return self._request("GET", f"/api/default_votes/{vote_id}", headers=headers)

    def list_default_votes(self, headers, params=None):
        return self._request("GET", "/api/default_votes", headers=headers, params=params)

    # --- Financial statements ---
    def create_financial_statement(self, payload, headers):
        return self._request("POST", "/api/financial_statements", payload, headers)

    def get_financial_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/api/financial_statements/{statement_id}", headers=headers
        )

    def list_financial_statements(self, headers, params=None):
        return self._request(
            "GET", "/api/financial_statements", headers=headers, params=params
        )

    def receive_financial_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/api/financial_statements/{statement_id}/receive", {}, headers
        )

    def waive_financial_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/api/financial_statements/{statement_id}/waive", {}, headers
        )

    # --- Reporting packages ---
    def create_reporting_package(self, payload, headers):
        return self._request("POST", "/api/reporting_packages", payload, headers)

    def get_reporting_package(self, package_id, headers):
        return self._request("GET", f"/api/reporting_packages/{package_id}", headers=headers)

    def list_reporting_packages(self, headers, params=None):
        return self._request(
            "GET", "/api/reporting_packages", headers=headers, params=params
        )

    def assemble_reporting_package(self, package_id, headers):
        return self._request(
            "POST", f"/api/reporting_packages/{package_id}/assemble", {}, headers
        )

    def deliver_reporting_package(self, package_id, headers):
        return self._request(
            "POST", f"/api/reporting_packages/{package_id}/deliver", {}, headers
        )

    # --- Participation transfers ---
    def create_transfer(self, payload, headers):
        return self._request("POST", "/api/transfers", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/api/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/api/transfers", headers=headers, params=params)

    def approve_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/approve", {}, headers)

    def reject_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/reject", {}, headers)

    def settle_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/settle", payload, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/cancel", {}, headers)

    # --- Buyback demands ---
    def create_buyback_demand(self, payload, headers):
        return self._request("POST", "/api/buyback_demands", payload, headers)

    def get_buyback_demand(self, demand_id, headers):
        return self._request("GET", f"/api/buyback_demands/{demand_id}", headers=headers)

    def list_buyback_demands(self, headers, params=None):
        return self._request("GET", "/api/buyback_demands", headers=headers, params=params)

    def acknowledge_buyback_demand(self, demand_id, headers):
        return self._request(
            "POST", f"/api/buyback_demands/{demand_id}/acknowledge", {}, headers
        )

    def dispute_buyback_demand(self, demand_id, headers):
        return self._request(
            "POST", f"/api/buyback_demands/{demand_id}/dispute", {}, headers
        )

    def settle_buyback_demand(self, demand_id, headers):
        return self._request(
            "POST", f"/api/buyback_demands/{demand_id}/settle", {}, headers
        )

    def rescind_buyback_demand(self, demand_id, headers):
        return self._request(
            "POST", f"/api/buyback_demands/{demand_id}/rescind", {}, headers
        )


api_client = ApiClient()
