"""API client: one method per endpoint defined in the PRD.

Every path is served under the ``/sfsp`` prefix. Resource creations return HTTP 201; every other
successful call, including all state transitions, all reads and the clock control, returns HTTP 200.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/sfsp"


class ApiClient(GenericApiClient):
    """Endpoint methods for the SFSP Sponsorship & Meal Sites API."""

    # --- Logical program clock ------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- Sponsors ------------------------------------------------------------

    def create_sponsor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/sponsors/{sponsor_id}", headers=headers)

    def submit_sponsor_application(self, sponsor_id: str, headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/sponsors/{sponsor_id}/application-submit",
                             payload if payload is not None else {}, headers)

    def decide_sponsor_application(self, sponsor_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/sponsors/{sponsor_id}/application-decision",
                             payload, headers)

    # --- Area eligibility records -------------------------------------------

    def create_area_eligibility_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/area-eligibility-records", payload, headers)

    def get_area_eligibility_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/area-eligibility-records/{record_id}",
                             headers=headers)

    # --- Sponsor budgets -----------------------------------------------------

    def create_sponsor_budget(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/sponsor-budgets", payload, headers)

    def get_sponsor_budget(self, budget_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/sponsor-budgets/{budget_id}", headers=headers)

    def list_sponsor_budgets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/sponsor-budgets", headers=headers, params=params)

    def submit_sponsor_budget(self, budget_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/sponsor-budgets/{budget_id}/submit",
                             payload if payload is not None else {}, headers)

    def decide_sponsor_budget(self, budget_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/sponsor-budgets/{budget_id}/decision",
                             payload, headers)

    # --- Advance payments ----------------------------------------------------

    def create_advance_payment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/advance-payments", payload, headers)

    def get_advance_payment(self, advance_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/advance-payments/{advance_id}", headers=headers)

    def list_advance_payments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/advance-payments", headers=headers, params=params)

    def decide_advance_payment(self, advance_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/advance-payments/{advance_id}/decision",
                             payload, headers)

    def disburse_advance_payment(self, advance_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/advance-payments/{advance_id}/disburse",
                             payload if payload is not None else {}, headers)

    def demand_advance_payment(self, advance_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/advance-payments/{advance_id}/demand",
                             payload if payload is not None else {}, headers)

    # --- Sites ---------------------------------------------------------------

    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def list_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def determine_site_eligibility(self, site_id: str, headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/eligibility-determination",
                             payload if payload is not None else {}, headers)

    def decide_site_approval(self, site_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/approval-decision",
                             payload, headers)

    def set_site_operating_status(self, site_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/operating-status",
                             payload, headers)

    def get_attendance_forecast(self, site_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/sites/{site_id}/attendance-forecast",
                             headers=headers, params=params)

    # --- Meal service days ---------------------------------------------------

    def create_meal_service_day(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-service-days", payload, headers)

    def get_meal_service_day(self, day_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/meal-service-days/{day_id}", headers=headers)

    def list_meal_service_days(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/meal-service-days", headers=headers, params=params)

    def open_meal_service_day(self, day_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-service-days/{day_id}/open",
                             payload, headers)

    def close_meal_service_day(self, day_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/meal-service-days/{day_id}/close",
                             payload if payload is not None else {}, headers)

    def finalize_meal_service_day(self, day_id: str, headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/meal-service-days/{day_id}/finalize",
                             payload if payload is not None else {}, headers)

    def void_meal_service_day(self, day_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-service-days/{day_id}/void",
                             payload, headers)

    # --- Meal count entries --------------------------------------------------

    def create_meal_count(self, day_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-service-days/{day_id}/meal-counts",
                             payload, headers)

    def get_meal_count_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/meal-count-entries/{entry_id}", headers=headers)

    def list_meal_count_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/meal-count-entries", headers=headers,
                             params=params)

    # --- Holding log entries -------------------------------------------------

    def create_holding_log(self, day_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-service-days/{day_id}/holding-logs",
                             payload, headers)

    def get_holding_log_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/holding-log-entries/{entry_id}", headers=headers)

    def list_holding_log_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/holding-log-entries", headers=headers,
                             params=params)

    # --- Monitoring visits ---------------------------------------------------

    def create_monitoring_visit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/monitoring-visits", payload, headers)

    def get_monitoring_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/monitoring-visits/{visit_id}", headers=headers)

    def list_monitoring_visits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/monitoring-visits", headers=headers, params=params)

    def conduct_monitoring_visit(self, visit_id: str, headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/monitoring-visits/{visit_id}/conduct",
                             payload if payload is not None else {}, headers)

    def report_monitoring_visit(self, visit_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/monitoring-visits/{visit_id}/report",
                             payload, headers)

    def cancel_monitoring_visit(self, visit_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/monitoring-visits/{visit_id}/cancel",
                             payload, headers)

    # --- Corrective actions --------------------------------------------------

    def get_corrective_action(self, action_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/corrective-actions/{action_id}", headers=headers)

    def list_corrective_actions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/corrective-actions", headers=headers,
                             params=params)

    def respond_corrective_action(self, action_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/corrective-actions/{action_id}/response",
                             payload, headers)

    def review_corrective_action(self, action_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/corrective-actions/{action_id}/review",
                             payload, headers)

    def escalate_corrective_action(self, action_id: str, headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/corrective-actions/{action_id}/escalate",
                             payload if payload is not None else {}, headers)

    # --- Meal claims ---------------------------------------------------------

    def create_meal_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-claims", payload, headers)

    def get_meal_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/meal-claims/{claim_id}", headers=headers)

    def list_meal_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/meal-claims", headers=headers, params=params)

    def create_claim_line_item(self, claim_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-claims/{claim_id}/line-items",
                             payload, headers)

    def get_claim_line_item(self, line_item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/claim-line-items/{line_item_id}", headers=headers)

    def list_claim_line_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/claim-line-items", headers=headers, params=params)

    def submit_meal_claim(self, claim_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-claims/{claim_id}/submit", payload, headers)

    def edit_check_meal_claim(self, claim_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/meal-claims/{claim_id}/edit-check",
                             payload if payload is not None else {}, headers)

    def pay_meal_claim(self, claim_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/meal-claims/{claim_id}/pay",
                             payload if payload is not None else {}, headers)

    def open_meal_claim_revision(self, claim_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/meal-claims/{claim_id}/open-revision",
                             payload, headers)

    def get_reimbursement_summary(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/meal-claims/{claim_id}/reimbursement-summary",
                             headers=headers)


api_client = ApiClient()
