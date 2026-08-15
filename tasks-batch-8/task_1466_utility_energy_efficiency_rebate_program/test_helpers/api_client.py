"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Program years
    # ------------------------------------------------------------------
    def create_program_year(self, payload, headers):
        return self._request("POST", "/program-years", payload, headers)

    def list_program_years(self, headers, params=None):
        return self._request("GET", "/program-years", headers=headers, params=params)

    def get_program_year(self, program_year_id, headers):
        return self._request(
            "GET", f"/program-years/{program_year_id}", headers=headers
        )

    def update_program_year(self, program_year_id, payload, headers):
        return self._request(
            "PUT", f"/program-years/{program_year_id}", payload, headers
        )

    def open_program_year(self, program_year_id, headers):
        return self._request(
            "POST", f"/program-years/{program_year_id}/open", {}, headers
        )

    def close_program_year(self, program_year_id, headers):
        return self._request(
            "POST", f"/program-years/{program_year_id}/close", {}, headers
        )

    def report_program_year(self, program_year_id, headers):
        return self._request(
            "POST", f"/program-years/{program_year_id}/report", {}, headers
        )

    # ------------------------------------------------------------------
    # Measures
    # ------------------------------------------------------------------
    def create_measure(self, payload, headers):
        return self._request("POST", "/measures", payload, headers)

    def list_measures(self, headers, params=None):
        return self._request("GET", "/measures", headers=headers, params=params)

    def get_measure(self, measure_id, headers):
        return self._request("GET", f"/measures/{measure_id}", headers=headers)

    # ------------------------------------------------------------------
    # Trade allies
    # ------------------------------------------------------------------
    def create_trade_ally(self, payload, headers):
        return self._request("POST", "/trade-allies", payload, headers)

    def list_trade_allies(self, headers, params=None):
        return self._request("GET", "/trade-allies", headers=headers, params=params)

    def get_trade_ally(self, ally_id, headers):
        return self._request("GET", f"/trade-allies/{ally_id}", headers=headers)

    def activate_trade_ally(self, ally_id, headers):
        return self._request("POST", f"/trade-allies/{ally_id}/activate", {}, headers)

    def suspend_trade_ally(self, ally_id, headers):
        return self._request("POST", f"/trade-allies/{ally_id}/suspend", {}, headers)

    def reinstate_trade_ally(self, ally_id, headers):
        return self._request("POST", f"/trade-allies/{ally_id}/reinstate", {}, headers)

    def terminate_trade_ally(self, ally_id, headers):
        return self._request("POST", f"/trade-allies/{ally_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Rebate applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit", {}, headers
        )

    def schedule_pre_inspection(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/schedule-pre-inspection",
            payload,
            headers,
        )

    def schedule_post_inspection(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/schedule-post-inspection",
            payload,
            headers,
        )

    def verify_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/verify", {}, headers
        )

    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/approve", {}, headers
        )

    def pay_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/pay", {}, headers)

    def reject_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/reject", {}, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", {}, headers
        )

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------
    def create_line_item(self, payload, headers):
        return self._request("POST", "/line-items", payload, headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    # ------------------------------------------------------------------
    # Savings claims
    # ------------------------------------------------------------------
    def create_savings_claim(self, payload, headers):
        return self._request("POST", "/savings-claims", payload, headers)

    def list_savings_claims(self, headers, params=None):
        return self._request("GET", "/savings-claims", headers=headers, params=params)

    def get_savings_claim(self, savings_claim_id, headers):
        return self._request(
            "GET", f"/savings-claims/{savings_claim_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Fraud flags
    # ------------------------------------------------------------------
    def list_fraud_flags(self, headers, params=None):
        return self._request("GET", "/fraud-flags", headers=headers, params=params)

    def get_fraud_flag(self, fraud_flag_id, headers):
        return self._request("GET", f"/fraud-flags/{fraud_flag_id}", headers=headers)

    # ------------------------------------------------------------------
    # Evaluation adjustments
    # ------------------------------------------------------------------
    def create_evaluation_adjustment(self, payload, headers):
        return self._request("POST", "/evaluation-adjustments", payload, headers)

    def list_evaluation_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/evaluation-adjustments", headers=headers, params=params
        )

    def get_evaluation_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/evaluation-adjustments/{adjustment_id}", headers=headers
        )


api_client = ApiClient()
