"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Logical clock ----------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------- Adjuster ----------
    def create_adjuster(self, payload, headers):
        return self._request("POST", "/adjusters", payload, headers)

    def list_adjusters(self, headers, params=None):
        return self._request("GET", "/adjusters", headers=headers, params=params)

    def get_adjuster(self, adjuster_id, headers):
        return self._request("GET", f"/adjusters/{adjuster_id}", headers=headers)

    # ---------- AdjusterLicense ----------
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def activate_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/activate", {}, headers)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/suspend", {}, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/reinstate", {}, headers)

    # ---------- CatEvent ----------
    def create_cat_event(self, payload, headers):
        return self._request("POST", "/cat-events", payload, headers)

    def list_cat_events(self, headers, params=None):
        return self._request("GET", "/cat-events", headers=headers, params=params)

    def get_cat_event(self, cat_event_id, headers):
        return self._request("GET", f"/cat-events/{cat_event_id}", headers=headers)

    def close_cat_event(self, cat_event_id, headers):
        return self._request("POST", f"/cat-events/{cat_event_id}/close", {}, headers)

    # ---------- Deployment ----------
    def create_deployment(self, payload, headers):
        return self._request("POST", "/deployments", payload, headers)

    def list_deployments(self, headers, params=None):
        return self._request("GET", "/deployments", headers=headers, params=params)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"/deployments/{deployment_id}", headers=headers)

    def confirm_deployment(self, deployment_id, headers):
        return self._request("POST", f"/deployments/{deployment_id}/confirm", {}, headers)

    def activate_deployment(self, deployment_id, headers):
        return self._request("POST", f"/deployments/{deployment_id}/activate", {}, headers)

    def complete_deployment(self, deployment_id, headers):
        return self._request("POST", f"/deployments/{deployment_id}/complete", {}, headers)

    def withdraw_deployment(self, deployment_id, headers):
        return self._request("POST", f"/deployments/{deployment_id}/withdraw", {}, headers)

    # ---------- Claim ----------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reopen", {}, headers)

    # ---------- Assignment ----------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline", {}, headers)

    # ---------- Inspection ----------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/start", {}, headers)

    def complete_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/complete", {}, headers)

    # ---------- Estimate ----------
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def approve_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/approve", {}, headers)

    # ---------- Report ----------
    def create_report(self, payload, headers):
        return self._request("POST", "/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/submit", {}, headers)

    def qa_decision_report(self, report_id, payload, headers):
        return self._request("POST", f"/reports/{report_id}/qa-decision", payload, headers)

    # ---------- TimeEntry ----------
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/time-entries", payload, headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/time-entries/{time_entry_id}", headers=headers)

    # ---------- FeeSchedule ----------
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)

    # ---------- FeeBill ----------
    def create_fee_bill(self, payload, headers):
        return self._request("POST", "/fee-bills", payload, headers)

    def list_fee_bills(self, headers, params=None):
        return self._request("GET", "/fee-bills", headers=headers, params=params)

    def get_fee_bill(self, fee_bill_id, headers):
        return self._request("GET", f"/fee-bills/{fee_bill_id}", headers=headers)

    def submit_fee_bill(self, fee_bill_id, headers):
        return self._request("POST", f"/fee-bills/{fee_bill_id}/submit", {}, headers)

    def approve_fee_bill(self, fee_bill_id, headers):
        return self._request("POST", f"/fee-bills/{fee_bill_id}/approve", {}, headers)

    def reject_fee_bill(self, fee_bill_id, headers):
        return self._request("POST", f"/fee-bills/{fee_bill_id}/reject", {}, headers)

    def void_fee_bill(self, fee_bill_id, headers):
        return self._request("POST", f"/fee-bills/{fee_bill_id}/void", {}, headers)

    def pay_fee_bill(self, fee_bill_id, payload, headers):
        return self._request("POST", f"/fee-bills/{fee_bill_id}/pay", payload, headers)

    # ---------- Payment ----------
    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)


api_client = ApiClient()
