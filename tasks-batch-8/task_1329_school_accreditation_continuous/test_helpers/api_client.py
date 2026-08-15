"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.8)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/accreditation/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Institution systems (PRD §3.1)
    # ------------------------------------------------------------------
    def create_system(self, payload, headers):
        return self._request("POST", "/accreditation/systems", payload, headers)

    def list_systems(self, headers, params=None):
        return self._request("GET", "/accreditation/systems", headers=headers, params=params)

    def get_system(self, system_id, headers):
        return self._request("GET", f"/accreditation/systems/{system_id}", headers=headers)

    def get_system_dashboard(self, system_id, headers):
        return self._request("GET", f"/accreditation/systems/{system_id}/dashboard",
                             headers=headers)

    # ------------------------------------------------------------------
    # Campuses (PRD §3.1)
    # ------------------------------------------------------------------
    def create_campus(self, system_id, payload, headers):
        return self._request("POST", f"/accreditation/systems/{system_id}/campuses",
                             payload, headers)

    def list_campuses(self, system_id, headers, params=None):
        return self._request("GET", f"/accreditation/systems/{system_id}/campuses",
                             headers=headers, params=params)

    def get_campus(self, campus_id, headers):
        return self._request("GET", f"/accreditation/campuses/{campus_id}", headers=headers)

    def scope_out_campus(self, campus_id, headers):
        return self._request("POST", f"/accreditation/campuses/{campus_id}/scope-out",
                             {}, headers)

    def scope_in_campus(self, campus_id, headers):
        return self._request("POST", f"/accreditation/campuses/{campus_id}/scope-in",
                             {}, headers)

    def withdraw_campus(self, campus_id, headers):
        return self._request("POST", f"/accreditation/campuses/{campus_id}/withdraw",
                             {}, headers)

    def list_campus_ratings(self, campus_id, headers, params=None):
        return self._request("GET", f"/accreditation/campuses/{campus_id}/ratings",
                             headers=headers, params=params)

    def list_campus_survey_windows(self, campus_id, headers, params=None):
        return self._request("GET", f"/accreditation/campuses/{campus_id}/survey-windows",
                             headers=headers, params=params)

    def list_campus_goals(self, campus_id, headers, params=None):
        return self._request("GET", f"/accreditation/campuses/{campus_id}/goals",
                             headers=headers, params=params)

    def list_campus_visits(self, campus_id, headers, params=None):
        return self._request("GET", f"/accreditation/campuses/{campus_id}/visits",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Standards (PRD §2.7, §3.3)
    # ------------------------------------------------------------------
    def create_standard(self, payload, headers):
        return self._request("POST", "/accreditation/standards", payload, headers)

    def list_standards(self, headers, params=None):
        return self._request("GET", "/accreditation/standards", headers=headers, params=params)

    def get_standard(self, standard_id, headers):
        return self._request("GET", f"/accreditation/standards/{standard_id}", headers=headers)

    def list_standard_ratings(self, standard_id, headers, params=None):
        return self._request("GET", f"/accreditation/standards/{standard_id}/ratings",
                             headers=headers, params=params)

    def list_standard_goals(self, standard_id, headers, params=None):
        return self._request("GET", f"/accreditation/standards/{standard_id}/goals",
                             headers=headers, params=params)

    def list_standard_findings(self, standard_id, headers, params=None):
        return self._request("GET", f"/accreditation/standards/{standard_id}/findings",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Accreditation terms (PRD §3.2)
    # ------------------------------------------------------------------
    def create_term(self, system_id, payload, headers):
        return self._request("POST", f"/accreditation/systems/{system_id}/terms",
                             payload, headers)

    def list_terms(self, system_id, headers, params=None):
        return self._request("GET", f"/accreditation/systems/{system_id}/terms",
                             headers=headers, params=params)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/accreditation/terms/{term_id}", headers=headers)

    def advance_term(self, term_id, headers):
        return self._request("POST", f"/accreditation/terms/{term_id}/advance", {}, headers)

    def decide_term(self, term_id, payload, headers):
        return self._request("POST", f"/accreditation/terms/{term_id}/decide", payload, headers)

    def close_term(self, term_id, headers):
        return self._request("POST", f"/accreditation/terms/{term_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Self-study ratings and evidence (PRD §3.3)
    # ------------------------------------------------------------------
    def create_rating(self, payload, headers):
        return self._request("POST", "/accreditation/ratings", payload, headers)

    def list_term_ratings(self, term_id, headers, params=None):
        return self._request("GET", f"/accreditation/terms/{term_id}/ratings",
                             headers=headers, params=params)

    def get_rating(self, rating_id, headers):
        return self._request("GET", f"/accreditation/ratings/{rating_id}", headers=headers)

    def submit_rating(self, rating_id, headers):
        return self._request("POST", f"/accreditation/ratings/{rating_id}/submit", {}, headers)

    def finalize_rating(self, rating_id, headers):
        return self._request("POST", f"/accreditation/ratings/{rating_id}/finalize", {}, headers)

    def reopen_rating(self, rating_id, headers):
        return self._request("POST", f"/accreditation/ratings/{rating_id}/reopen", {}, headers)

    def create_evidence(self, rating_id, payload, headers):
        return self._request("POST", f"/accreditation/ratings/{rating_id}/evidence",
                             payload, headers)

    def list_evidence(self, rating_id, headers, params=None):
        return self._request("GET", f"/accreditation/ratings/{rating_id}/evidence",
                             headers=headers, params=params)

    def review_evidence(self, evidence_id, payload, headers):
        return self._request("POST", f"/accreditation/evidence/{evidence_id}/review",
                             payload, headers)

    def resubmit_evidence(self, evidence_id, headers):
        return self._request("POST", f"/accreditation/evidence/{evidence_id}/resubmit",
                             {}, headers)

    # ------------------------------------------------------------------
    # Survey instruments, windows, responses (PRD §3.4)
    # ------------------------------------------------------------------
    def create_survey_instrument(self, payload, headers):
        return self._request("POST", "/accreditation/survey-instruments", payload, headers)

    def list_survey_instruments(self, headers, params=None):
        return self._request("GET", "/accreditation/survey-instruments",
                             headers=headers, params=params)

    def get_survey_instrument(self, instrument_id, headers):
        return self._request("GET", f"/accreditation/survey-instruments/{instrument_id}",
                             headers=headers)

    def list_instrument_survey_windows(self, instrument_id, headers, params=None):
        return self._request("GET",
                             f"/accreditation/survey-instruments/{instrument_id}/survey-windows",
                             headers=headers, params=params)

    def create_survey_window(self, term_id, payload, headers):
        return self._request("POST", f"/accreditation/terms/{term_id}/survey-windows",
                             payload, headers)

    def list_term_survey_windows(self, term_id, headers, params=None):
        return self._request("GET", f"/accreditation/terms/{term_id}/survey-windows",
                             headers=headers, params=params)

    def get_survey_window(self, window_id, headers):
        return self._request("GET", f"/accreditation/survey-windows/{window_id}",
                             headers=headers)

    def submit_survey_response(self, window_id, payload, headers):
        return self._request("POST", f"/accreditation/survey-windows/{window_id}/responses",
                             payload, headers)

    def list_survey_responses(self, window_id, headers, params=None):
        return self._request("GET", f"/accreditation/survey-windows/{window_id}/responses",
                             headers=headers, params=params)

    def close_survey_window(self, window_id, headers):
        return self._request("POST", f"/accreditation/survey-windows/{window_id}/close",
                             {}, headers)

    def invalidate_survey_window(self, window_id, headers):
        return self._request("POST", f"/accreditation/survey-windows/{window_id}/invalidate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Improvement goals and progress indicators (PRD §3.5)
    # ------------------------------------------------------------------
    def create_goal(self, term_id, payload, headers):
        return self._request("POST", f"/accreditation/terms/{term_id}/goals", payload, headers)

    def list_term_goals(self, term_id, headers, params=None):
        return self._request("GET", f"/accreditation/terms/{term_id}/goals",
                             headers=headers, params=params)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"/accreditation/goals/{goal_id}", headers=headers)

    def adopt_goal(self, goal_id, headers):
        return self._request("POST", f"/accreditation/goals/{goal_id}/adopt", {}, headers)

    def create_indicator(self, goal_id, payload, headers):
        return self._request("POST", f"/accreditation/goals/{goal_id}/indicators",
                             payload, headers)

    def list_indicators(self, goal_id, headers, params=None):
        return self._request("GET", f"/accreditation/goals/{goal_id}/indicators",
                             headers=headers, params=params)

    def mark_goal_achieved(self, goal_id, headers):
        return self._request("POST", f"/accreditation/goals/{goal_id}/mark-achieved",
                             {}, headers)

    def abandon_goal(self, goal_id, headers):
        return self._request("POST", f"/accreditation/goals/{goal_id}/abandon", {}, headers)

    # ------------------------------------------------------------------
    # Reviewers (PRD §3.6)
    # ------------------------------------------------------------------
    def create_reviewer(self, payload, headers):
        return self._request("POST", "/accreditation/reviewers", payload, headers)

    def list_reviewers(self, headers, params=None):
        return self._request("GET", "/accreditation/reviewers", headers=headers, params=params)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/accreditation/reviewers/{reviewer_id}", headers=headers)

    def deactivate_reviewer(self, reviewer_id, headers):
        return self._request("POST", f"/accreditation/reviewers/{reviewer_id}/deactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Visit events, assignments, findings (PRD §3.6)
    # ------------------------------------------------------------------
    def create_visit(self, term_id, payload, headers):
        return self._request("POST", f"/accreditation/terms/{term_id}/visits", payload, headers)

    def list_term_visits(self, term_id, headers, params=None):
        return self._request("GET", f"/accreditation/terms/{term_id}/visits",
                             headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/accreditation/visits/{visit_id}", headers=headers)

    def create_visit_assignment(self, visit_id, payload, headers):
        return self._request("POST", f"/accreditation/visits/{visit_id}/assignments",
                             payload, headers)

    def list_visit_assignments(self, visit_id, headers, params=None):
        return self._request("GET", f"/accreditation/visits/{visit_id}/assignments",
                             headers=headers, params=params)

    def list_reviewer_assignments(self, reviewer_id, headers, params=None):
        return self._request("GET", f"/accreditation/reviewers/{reviewer_id}/assignments",
                             headers=headers, params=params)

    def list_reviewer_visits(self, reviewer_id, headers, params=None):
        return self._request("GET", f"/accreditation/reviewers/{reviewer_id}/visits",
                             headers=headers, params=params)

    def confirm_visit(self, visit_id, headers):
        return self._request("POST", f"/accreditation/visits/{visit_id}/confirm", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/accreditation/visits/{visit_id}/cancel", {}, headers)

    def issue_visit_report(self, visit_id, headers):
        return self._request("POST", f"/accreditation/visits/{visit_id}/issue-report",
                             {}, headers)

    def create_finding(self, visit_id, payload, headers):
        return self._request("POST", f"/accreditation/visits/{visit_id}/findings",
                             payload, headers)

    def list_visit_findings(self, visit_id, headers, params=None):
        return self._request("GET", f"/accreditation/visits/{visit_id}/findings",
                             headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/accreditation/findings/{finding_id}", headers=headers)

    def issue_finding(self, finding_id, headers):
        return self._request("POST", f"/accreditation/findings/{finding_id}/issue", {}, headers)

    def supersede_finding(self, finding_id, headers):
        return self._request("POST", f"/accreditation/findings/{finding_id}/supersede",
                             {}, headers)

    # ------------------------------------------------------------------
    # Required action items (PRD §3.6)
    # ------------------------------------------------------------------
    def list_finding_action_items(self, finding_id, headers, params=None):
        return self._request("GET", f"/accreditation/findings/{finding_id}/action-items",
                             headers=headers, params=params)

    def list_term_action_items(self, term_id, headers, params=None):
        return self._request("GET", f"/accreditation/terms/{term_id}/action-items",
                             headers=headers, params=params)

    def get_action_item(self, item_id, headers):
        return self._request("GET", f"/accreditation/action-items/{item_id}", headers=headers)

    def submit_action_item_evidence(self, item_id, payload, headers):
        return self._request("POST", f"/accreditation/action-items/{item_id}/submit-evidence",
                             payload, headers)

    def verify_action_item(self, item_id, headers):
        return self._request("POST", f"/accreditation/action-items/{item_id}/verify",
                             {}, headers)

    def return_action_item(self, item_id, headers):
        return self._request("POST", f"/accreditation/action-items/{item_id}/return",
                             {}, headers)

    def waive_action_item(self, item_id, headers):
        return self._request("POST", f"/accreditation/action-items/{item_id}/waive",
                             {}, headers)

    # ------------------------------------------------------------------
    # Interim reports (PRD §3.7)
    # ------------------------------------------------------------------
    def create_interim_report(self, term_id, payload, headers):
        return self._request("POST", f"/accreditation/terms/{term_id}/interim-reports",
                             payload, headers)

    def list_interim_reports(self, term_id, headers, params=None):
        return self._request("GET", f"/accreditation/terms/{term_id}/interim-reports",
                             headers=headers, params=params)

    def submit_interim_report(self, report_id, headers):
        return self._request("POST", f"/accreditation/interim-reports/{report_id}/submit",
                             {}, headers)

    def accept_interim_report(self, report_id, headers):
        return self._request("POST", f"/accreditation/interim-reports/{report_id}/accept",
                             {}, headers)

    def return_interim_report(self, report_id, headers):
        return self._request("POST", f"/accreditation/interim-reports/{report_id}/return",
                             {}, headers)

    # ------------------------------------------------------------------
    # Fee schedules, invoices, payments (PRD §3.8)
    # ------------------------------------------------------------------
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/accreditation/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/accreditation/fee-schedules",
                             headers=headers, params=params)

    def create_invoice(self, system_id, payload, headers):
        return self._request("POST", f"/accreditation/systems/{system_id}/invoices",
                             payload, headers)

    def list_system_invoices(self, system_id, headers, params=None):
        return self._request("GET", f"/accreditation/systems/{system_id}/invoices",
                             headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/accreditation/invoices/{invoice_id}", headers=headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/accreditation/invoices/{invoice_id}/payments",
                             payload, headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/accreditation/invoices/{invoice_id}/payments",
                             headers=headers, params=params)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/accreditation/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
