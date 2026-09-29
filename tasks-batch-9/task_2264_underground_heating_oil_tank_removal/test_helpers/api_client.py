"""API client: one method per endpoint the PRD's routing table declares.

All collections are mounted at the service root and every relationship travels
as an identifier field inside the request body, so no method here builds a nested
URL segment.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ properties #
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # --------------------------------------------------------- tank projects #
    def create_tank_project(self, payload, headers):
        return self._request("POST", "/tank-projects", payload, headers)

    def list_tank_projects(self, headers, params=None):
        return self._request("GET", "/tank-projects", headers=headers, params=params)

    def get_tank_project(self, project_id, headers):
        return self._request("GET", f"/tank-projects/{project_id}", headers=headers)

    def get_tank_project_summary(self, project_id, headers):
        return self._request(
            "GET", f"/tank-projects/{project_id}/summary", headers=headers
        )

    def record_sweep_survey(self, project_id, payload, headers):
        return self._request(
            "POST", f"/tank-projects/{project_id}/sweep-survey", payload, headers
        )

    # ----------------------------------------------------------- disclosures #
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/disclosures", payload, headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/disclosures", headers=headers, params=params)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/disclosures/{disclosure_id}", headers=headers)

    def respond_to_disclosure(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/disclosures/{disclosure_id}/respond", payload, headers
        )

    # --------------------------------------------------------------- permits #
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def decide_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permits/{permit_id}/decision", payload, headers
        )

    # ----------------------------------------------------------------- crews #
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # ----------------------------------------------------------- work orders #
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def create_field_event(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/field-events", payload, headers
        )

    def create_billing_event(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/billing-events", payload, headers
        )

    # ---------------------------------------------------------- laboratories #
    def create_laboratory(self, payload, headers):
        return self._request("POST", "/laboratories", payload, headers)

    def get_laboratory(self, laboratory_id, headers):
        return self._request("GET", f"/laboratories/{laboratory_id}", headers=headers)

    # ----------------------------------------------------------- soil samples #
    def create_soil_sample(self, payload, headers):
        return self._request("POST", "/soil-samples", payload, headers)

    def list_soil_samples(self, headers, params=None):
        return self._request("GET", "/soil-samples", headers=headers, params=params)

    def get_soil_sample(self, sample_id, headers):
        return self._request("GET", f"/soil-samples/{sample_id}", headers=headers)

    def create_custody_event(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/soil-samples/{sample_id}/chain-of-custody", payload, headers
        )

    def report_result(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/soil-samples/{sample_id}/result", payload, headers
        )

    def retract_result(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/soil-samples/{sample_id}/retract-result", payload, headers
        )

    # ---------------------------------------------------------- change orders #
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def get_change_order(self, change_order_id, headers):
        return self._request(
            "GET", f"/change-orders/{change_order_id}", headers=headers
        )

    def submit_change_order(self, change_order_id, headers, payload=None):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/submit", payload or {}, headers
        )

    def decide_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/decision", payload, headers
        )

    # ------------------------------------------------------ trust-fund claims #
    def create_trust_fund_claim(self, payload, headers):
        return self._request("POST", "/trust-fund-claims", payload, headers)

    def list_trust_fund_claims(self, headers, params=None):
        return self._request(
            "GET", "/trust-fund-claims", headers=headers, params=params
        )

    def get_trust_fund_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/trust-fund-claims/{claim_id}", headers=headers
        )

    def submit_trust_fund_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/trust-fund-claims/{claim_id}/submit", payload or {}, headers
        )

    def decide_trust_fund_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/trust-fund-claims/{claim_id}/decision", payload, headers
        )

    # ----------------------------------------------------------- NFA letters #
    def create_nfa_letter(self, payload, headers):
        return self._request("POST", "/nfa-letters", payload, headers)

    def list_nfa_letters(self, headers, params=None):
        return self._request("GET", "/nfa-letters", headers=headers, params=params)

    def get_nfa_letter(self, letter_id, headers):
        return self._request("GET", f"/nfa-letters/{letter_id}", headers=headers)

    def issue_nfa_letter(self, letter_id, headers, payload=None):
        return self._request(
            "POST", f"/nfa-letters/{letter_id}/issue", payload or {}, headers
        )

    def rescind_nfa_letter(self, letter_id, payload, headers):
        return self._request(
            "POST", f"/nfa-letters/{letter_id}/rescind", payload, headers
        )

    # --------------------------------------------- insurance notifications #
    def create_insurance_notification(self, payload, headers):
        return self._request("POST", "/insurance-notifications", payload, headers)

    def list_insurance_notifications(self, headers, params=None):
        return self._request(
            "GET", "/insurance-notifications", headers=headers, params=params
        )

    def get_insurance_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/insurance-notifications/{notification_id}", headers=headers
        )

    # ------------------------------------------------------- the logical clock #
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
