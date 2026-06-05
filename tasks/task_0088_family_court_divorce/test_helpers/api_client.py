"""API client: one method per endpoint defined in the PRD (Family Court Divorce API).

All paths are prefixed with /api per the PRD's endpoint table (Section 4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- GuidelineSchedule -----
    def create_guideline_schedule(self, payload, headers):
        return self._request("POST", "/api/guideline-schedules", payload, headers)

    def get_guideline_schedule(self, schedule_id, headers):
        return self._request("GET", f"/api/guideline-schedules/{schedule_id}", headers=headers)

    # ----- Case -----
    def create_case(self, payload, headers):
        return self._request("POST", "/api/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/cases", headers=headers, params=params)

    def default_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/api/cases/{case_id}/default", payload or {}, headers)

    def advance_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/advance", payload, headers)

    def assign_mediator(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/assign-mediator", payload, headers)

    def dismiss_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/api/cases/{case_id}/dismiss", payload or {}, headers)

    # ----- Party -----
    def create_party(self, payload, headers):
        return self._request("POST", "/api/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/api/parties/{party_id}", headers=headers)

    def list_parties(self, headers, params=None):
        return self._request("GET", "/api/parties", headers=headers, params=params)

    # ----- Child -----
    def create_child(self, payload, headers):
        return self._request("POST", "/api/children", payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/api/children/{child_id}", headers=headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/api/children", headers=headers, params=params)

    # ----- Pleading -----
    def create_pleading(self, payload, headers):
        return self._request("POST", "/api/pleadings", payload, headers)

    def get_pleading(self, pleading_id, headers):
        return self._request("GET", f"/api/pleadings/{pleading_id}", headers=headers)

    def list_pleadings(self, headers, params=None):
        return self._request("GET", "/api/pleadings", headers=headers, params=params)

    def serve_pleading(self, pleading_id, headers, payload=None):
        return self._request("POST", f"/api/pleadings/{pleading_id}/serve", payload or {}, headers)

    # ----- FinancialDisclosure -----
    def create_financial_disclosure(self, payload, headers):
        return self._request("POST", "/api/financial-disclosures", payload, headers)

    def get_financial_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/api/financial-disclosures/{disclosure_id}", headers=headers)

    def list_financial_disclosures(self, headers, params=None):
        return self._request("GET", "/api/financial-disclosures", headers=headers, params=params)

    def submit_financial_disclosure(self, disclosure_id, headers, payload=None):
        return self._request("POST", f"/api/financial-disclosures/{disclosure_id}/submit", payload or {}, headers)

    def verify_financial_disclosure(self, disclosure_id, headers, payload=None):
        return self._request("POST", f"/api/financial-disclosures/{disclosure_id}/verify", payload or {}, headers)

    def return_financial_disclosure(self, disclosure_id, headers, payload=None):
        return self._request("POST", f"/api/financial-disclosures/{disclosure_id}/return", payload or {}, headers)

    # ----- ParentingPlan -----
    def create_parenting_plan(self, payload, headers):
        return self._request("POST", "/api/parenting-plans", payload, headers)

    def get_parenting_plan(self, plan_id, headers):
        return self._request("GET", f"/api/parenting-plans/{plan_id}", headers=headers)

    def list_parenting_plans(self, headers, params=None):
        return self._request("GET", "/api/parenting-plans", headers=headers, params=params)

    def dispute_parenting_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/api/parenting-plans/{plan_id}/dispute", payload or {}, headers)

    def revise_parenting_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/api/parenting-plans/{plan_id}/revise", payload, headers)

    def agree_parenting_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/api/parenting-plans/{plan_id}/agree", payload or {}, headers)

    # ----- MediationSession -----
    def create_mediation_session(self, payload, headers):
        return self._request("POST", "/api/mediation-sessions", payload, headers)

    def get_mediation_session(self, session_id, headers):
        return self._request("GET", f"/api/mediation-sessions/{session_id}", headers=headers)

    def list_mediation_sessions(self, headers, params=None):
        return self._request("GET", "/api/mediation-sessions", headers=headers, params=params)

    def start_mediation_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/api/mediation-sessions/{session_id}/start", payload or {}, headers)

    def conclude_mediation_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/mediation-sessions/{session_id}/conclude", payload, headers)

    # ----- SupportOrder -----
    def create_support_order(self, payload, headers):
        return self._request("POST", "/api/support-orders", payload, headers)

    def get_support_order(self, order_id, headers):
        return self._request("GET", f"/api/support-orders/{order_id}", headers=headers)

    def list_support_orders(self, headers, params=None):
        return self._request("GET", "/api/support-orders", headers=headers, params=params)

    # ----- CourtOrder -----
    def create_court_order(self, payload, headers):
        return self._request("POST", "/api/court-orders", payload, headers)

    def get_court_order(self, order_id, headers):
        return self._request("GET", f"/api/court-orders/{order_id}", headers=headers)

    def list_court_orders(self, headers, params=None):
        return self._request("GET", "/api/court-orders", headers=headers, params=params)

    def enter_court_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/court-orders/{order_id}/enter", payload, headers)

    # ----- Hearing -----
    def create_hearing(self, payload, headers):
        return self._request("POST", "/api/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/api/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/api/hearings", headers=headers, params=params)

    def hold_hearing(self, hearing_id, headers, payload=None):
        return self._request("POST", f"/api/hearings/{hearing_id}/hold", payload or {}, headers)

    def cancel_hearing(self, hearing_id, headers, payload=None):
        return self._request("POST", f"/api/hearings/{hearing_id}/cancel", payload or {}, headers)


api_client = ApiClient()
