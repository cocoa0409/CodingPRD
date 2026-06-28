"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate", headers=headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", headers=headers)

    def get_impact_report(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}/impact-report", headers=headers)

    # ---- Employee ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def suspend_employee(self, employee_id, headers):
        return self._request("POST", f"/employees/{employee_id}/suspend", headers=headers)

    def reinstate_employee(self, employee_id, headers):
        return self._request("POST", f"/employees/{employee_id}/reinstate", headers=headers)

    def terminate_employee(self, employee_id, headers):
        return self._request("POST", f"/employees/{employee_id}/terminate", headers=headers)

    def create_tax_statement(self, employee_id, headers):
        return self._request("POST", f"/employees/{employee_id}/tax-statement", headers=headers)

    def get_tax_statement(self, statement_id, headers):
        return self._request("GET", f"/tax-statements/{statement_id}", headers=headers)

    def list_tax_statements(self, headers, params=None):
        return self._request("GET", "/tax-statements", headers=headers, params=params)

    # ---- Charity ----
    def create_charity(self, payload, headers):
        return self._request("POST", "/charities", payload, headers)

    def get_charity(self, charity_id, headers):
        return self._request("GET", f"/charities/{charity_id}", headers=headers)

    def list_charities(self, headers, params=None):
        return self._request("GET", "/charities", headers=headers, params=params)

    def start_review_charity(self, charity_id, headers):
        return self._request("POST", f"/charities/{charity_id}/start-review", headers=headers)

    def request_info_charity(self, charity_id, headers):
        return self._request("POST", f"/charities/{charity_id}/request-info", headers=headers)

    def approve_charity(self, charity_id, headers):
        return self._request("POST", f"/charities/{charity_id}/approve", headers=headers)

    def reject_charity(self, charity_id, headers):
        return self._request("POST", f"/charities/{charity_id}/reject", headers=headers)

    def suspend_charity(self, charity_id, headers):
        return self._request("POST", f"/charities/{charity_id}/suspend", headers=headers)

    def reinstate_charity(self, charity_id, headers):
        return self._request("POST", f"/charities/{charity_id}/reinstate", headers=headers)

    # ---- Campaign ----
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def launch_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/launch", headers=headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/pause", headers=headers)

    def resume_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/resume", headers=headers)

    def end_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/end", headers=headers)

    # ---- Donation ----
    def create_donation(self, payload, headers):
        return self._request("POST", "/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/donations", headers=headers, params=params)

    def authorize_donation(self, donation_id, headers):
        return self._request("POST", f"/donations/{donation_id}/authorize", headers=headers)

    def settle_donation(self, donation_id, headers):
        return self._request("POST", f"/donations/{donation_id}/settle", headers=headers)

    def cancel_donation(self, donation_id, headers):
        return self._request("POST", f"/donations/{donation_id}/cancel", headers=headers)

    def refund_donation(self, donation_id, headers):
        return self._request("POST", f"/donations/{donation_id}/refund", headers=headers)

    # ---- PayrollDeductionSchedule ----
    def create_payroll_schedule(self, payload, headers):
        return self._request("POST", "/payroll-schedules", payload, headers)

    def get_payroll_schedule(self, schedule_id, headers):
        return self._request("GET", f"/payroll-schedules/{schedule_id}", headers=headers)

    def list_payroll_schedules(self, headers, params=None):
        return self._request("GET", "/payroll-schedules", headers=headers, params=params)

    def pause_payroll_schedule(self, schedule_id, headers):
        return self._request("POST", f"/payroll-schedules/{schedule_id}/pause", headers=headers)

    def resume_payroll_schedule(self, schedule_id, headers):
        return self._request("POST", f"/payroll-schedules/{schedule_id}/resume", headers=headers)

    def cancel_payroll_schedule(self, schedule_id, headers):
        return self._request("POST", f"/payroll-schedules/{schedule_id}/cancel", headers=headers)

    def run_cycle_payroll_schedule(self, schedule_id, headers):
        return self._request("POST", f"/payroll-schedules/{schedule_id}/run-cycle", headers=headers)

    # ---- MatchingGift ----
    def get_matching_gift(self, match_id, headers):
        return self._request("GET", f"/matching-gifts/{match_id}", headers=headers)

    def list_matching_gifts(self, headers, params=None):
        return self._request("GET", "/matching-gifts", headers=headers, params=params)

    # ---- VolunteerLog ----
    def create_volunteer_log(self, payload, headers):
        return self._request("POST", "/volunteer-logs", payload, headers)

    def get_volunteer_log(self, log_id, headers):
        return self._request("GET", f"/volunteer-logs/{log_id}", headers=headers)

    def list_volunteer_logs(self, headers, params=None):
        return self._request("GET", "/volunteer-logs", headers=headers, params=params)

    def approve_volunteer_log(self, log_id, headers):
        return self._request("POST", f"/volunteer-logs/{log_id}/approve", headers=headers)

    def reject_volunteer_log(self, log_id, headers):
        return self._request("POST", f"/volunteer-logs/{log_id}/reject", headers=headers)

    def reverse_volunteer_log(self, log_id, headers):
        return self._request("POST", f"/volunteer-logs/{log_id}/reverse", headers=headers)

    # ---- DisbursementBatch + Grant ----
    def create_disbursement_batch(self, payload, headers):
        return self._request("POST", "/disbursement-batches", payload, headers)

    def get_disbursement_batch(self, batch_id, headers):
        return self._request("GET", f"/disbursement-batches/{batch_id}", headers=headers)

    def list_disbursement_batches(self, headers, params=None):
        return self._request("GET", "/disbursement-batches", headers=headers, params=params)

    def stage_grant(self, batch_id, payload, headers):
        return self._request("POST", f"/disbursement-batches/{batch_id}/grants", payload, headers)

    def list_batch_grants(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/disbursement-batches/{batch_id}/grants", headers=headers, params=params
        )

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def lock_disbursement_batch(self, batch_id, headers):
        return self._request("POST", f"/disbursement-batches/{batch_id}/lock", headers=headers)

    def settle_disbursement_batch(self, batch_id, headers):
        return self._request("POST", f"/disbursement-batches/{batch_id}/settle", headers=headers)

    def void_disbursement_batch(self, batch_id, headers):
        return self._request("POST", f"/disbursement-batches/{batch_id}/void", headers=headers)


api_client = ApiClient()
