"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Org units & clock ---
    def create_org_unit(self, payload, headers):
        return self._request("POST", "/hr-org-units", payload, headers)

    def get_org_unit(self, ou_id, headers):
        return self._request("GET", f"/hr-org-units/{ou_id}", headers=headers)

    def set_clock(self, ou_id, payload, headers):
        return self._request(
            "POST", f"/hr-org-units/{ou_id}/_clock/set_current_utc", payload, headers
        )

    # --- Employees ---
    def create_employee(self, ou_id, payload, headers):
        return self._request("POST", f"/hr-org-units/{ou_id}/employees", payload, headers)

    def get_employee(self, ou_id, emp_id, headers):
        return self._request(
            "GET", f"/hr-org-units/{ou_id}/employees/{emp_id}", headers=headers
        )

    def list_employees(self, ou_id, headers, params=None):
        return self._request(
            "GET", f"/hr-org-units/{ou_id}/employees", headers=headers, params=params
        )

    # --- Coaching log ---
    def create_coaching_log_entry(self, ou_id, emp_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/coaching-log-entries",
            payload,
            headers,
        )

    def list_coaching_log_entries(self, ou_id, emp_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/coaching-log-entries",
            headers=headers,
            params=params,
        )

    # --- Performance concerns ---
    def create_concern(self, ou_id, emp_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/performance-concerns",
            payload,
            headers,
        )

    def list_concerns(self, ou_id, emp_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/performance-concerns",
            headers=headers,
            params=params,
        )

    def get_concern(self, ou_id, emp_id, concern_id, headers):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/performance-concerns/{concern_id}",
            headers=headers,
        )

    def submit_concern(self, ou_id, emp_id, concern_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/performance-concerns/{concern_id}/submit",
            {},
            headers,
        )

    def accept_concern(self, ou_id, emp_id, concern_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/performance-concerns/{concern_id}/accept",
            {},
            headers,
        )

    def reject_concern(self, ou_id, emp_id, concern_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/performance-concerns/{concern_id}/reject",
            {},
            headers,
        )

    # --- PIP templates ---
    def create_pip_template(self, ou_id, payload, headers):
        return self._request(
            "POST", f"/hr-org-units/{ou_id}/pip-templates", payload, headers
        )

    def list_pip_templates(self, ou_id, headers, params=None):
        return self._request(
            "GET", f"/hr-org-units/{ou_id}/pip-templates", headers=headers, params=params
        )

    def get_pip_template(self, ou_id, template_id, headers):
        return self._request(
            "GET", f"/hr-org-units/{ou_id}/pip-templates/{template_id}", headers=headers
        )

    def publish_pip_template(self, ou_id, template_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/pip-templates/{template_id}/publish",
            {},
            headers,
        )

    def retire_pip_template(self, ou_id, template_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/pip-templates/{template_id}/retire",
            {},
            headers,
        )

    # --- PIPs ---
    def create_pip(self, ou_id, emp_id, payload, headers):
        return self._request(
            "POST", f"/hr-org-units/{ou_id}/employees/{emp_id}/pips", payload, headers
        )

    def list_pips(self, ou_id, emp_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips",
            headers=headers,
            params=params,
        )

    def get_pip(self, ou_id, emp_id, pip_id, headers):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}",
            headers=headers,
        )

    def list_pip_goals(self, ou_id, emp_id, pip_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/goals",
            headers=headers,
            params=params,
        )

    def issue_pip(self, ou_id, emp_id, pip_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/issue",
            payload,
            headers,
        )

    def withdraw_pip(self, ou_id, emp_id, pip_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/withdraw",
            {},
            headers,
        )

    # --- Check-ins ---
    def create_check_in(self, ou_id, emp_id, pip_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/check-ins",
            payload,
            headers,
        )

    def list_check_ins(self, ou_id, emp_id, pip_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/check-ins",
            headers=headers,
            params=params,
        )

    def mark_check_in_held(self, ou_id, emp_id, pip_id, check_in_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/check-ins/{check_in_id}/mark-held",
            payload,
            headers,
        )

    # --- Evidence ---
    def submit_evidence(self, ou_id, emp_id, pip_id, check_in_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/check-ins/{check_in_id}/evidence",
            payload,
            headers,
        )

    def list_evidence(self, ou_id, emp_id, pip_id, check_in_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/check-ins/{check_in_id}/evidence",
            headers=headers,
            params=params,
        )

    def admit_evidence(self, ou_id, emp_id, pip_id, check_in_id, evidence_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/check-ins/{check_in_id}/evidence/{evidence_id}/admit",
            {},
            headers,
        )

    def exclude_evidence(self, ou_id, emp_id, pip_id, check_in_id, evidence_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/check-ins/{check_in_id}/evidence/{evidence_id}/exclude",
            {},
            headers,
        )

    # --- Legal reviews ---
    def create_legal_review(self, ou_id, emp_id, pip_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/legal-reviews",
            payload,
            headers,
        )

    def list_legal_reviews(self, ou_id, emp_id, pip_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/legal-reviews",
            headers=headers,
            params=params,
        )

    def claim_legal_review(self, ou_id, emp_id, pip_id, review_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/legal-reviews/{review_id}/claim",
            {},
            headers,
        )

    def submit_legal_review(self, ou_id, emp_id, pip_id, review_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/legal-reviews/{review_id}/submit",
            payload,
            headers,
        )

    def override_legal_review(self, ou_id, emp_id, pip_id, review_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/legal-reviews/{review_id}/override",
            {},
            headers,
        )

    # --- Outcome decisions ---
    def create_outcome_decision(self, ou_id, emp_id, pip_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/outcome-decisions",
            payload,
            headers,
        )

    def list_outcome_decisions(self, ou_id, emp_id, pip_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/outcome-decisions",
            headers=headers,
            params=params,
        )

    def approve_outcome_decision(
        self, ou_id, emp_id, pip_id, decision_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/outcome-decisions/{decision_id}/approve",
            payload,
            headers,
        )

    def reject_outcome_decision(self, ou_id, emp_id, pip_id, decision_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/outcome-decisions/{decision_id}/reject",
            {},
            headers,
        )

    # --- Rebuttals ---
    def create_rebuttal(self, ou_id, emp_id, pip_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/rebuttals",
            payload,
            headers,
        )

    def list_rebuttals(self, ou_id, emp_id, pip_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/rebuttals",
            headers=headers,
            params=params,
        )

    def start_rebuttal_review(self, ou_id, emp_id, pip_id, rebuttal_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/rebuttals/{rebuttal_id}/start-review",
            {},
            headers,
        )

    def resolve_rebuttal(self, ou_id, emp_id, pip_id, rebuttal_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/rebuttals/{rebuttal_id}/resolve",
            payload,
            headers,
        )

    # --- Rating cycles ---
    def create_rating_cycle(self, ou_id, payload, headers):
        return self._request(
            "POST", f"/hr-org-units/{ou_id}/rating-cycles", payload, headers
        )

    def list_rating_cycles(self, ou_id, headers, params=None):
        return self._request(
            "GET", f"/hr-org-units/{ou_id}/rating-cycles", headers=headers, params=params
        )

    def calibrate_rating_cycle(self, ou_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/rating-cycles/{cycle_id}/calibrate",
            {},
            headers,
        )

    def publish_rating_cycle(self, ou_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/rating-cycles/{cycle_id}/publish",
            {},
            headers,
        )

    def archive_rating_cycle(self, ou_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/rating-cycles/{cycle_id}/archive",
            {},
            headers,
        )

    # --- Rating-cycle outcome links ---
    def list_rating_cycle_outcome_links(
        self, ou_id, emp_id, pip_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/employees/{emp_id}/pips/{pip_id}/rating-cycle-outcome-links",
            headers=headers,
            params=params,
        )

    # --- Consistency reviews ---
    def create_consistency_review(self, ou_id, payload, headers):
        return self._request(
            "POST", f"/hr-org-units/{ou_id}/consistency-reviews", payload, headers
        )

    def list_consistency_reviews(self, ou_id, headers, params=None):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/consistency-reviews",
            headers=headers,
            params=params,
        )

    def get_consistency_review(self, ou_id, review_id, headers):
        return self._request(
            "GET",
            f"/hr-org-units/{ou_id}/consistency-reviews/{review_id}",
            headers=headers,
        )

    def adjudicate_consistency_review(self, ou_id, review_id, payload, headers):
        return self._request(
            "POST",
            f"/hr-org-units/{ou_id}/consistency-reviews/{review_id}/adjudicate",
            payload,
            headers,
        )

    # --- Flat read paths (reverse-reachability) ---
    def flat_get_employee(self, emp_id, headers):
        return self._request("GET", f"/hr-org-units/employees/{emp_id}", headers=headers)

    def flat_list_employees(self, headers, params=None):
        return self._request("GET", "/hr-org-units/employees", headers=headers, params=params)

    def flat_get_rating_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"/hr-org-units/rating-cycles/{cycle_id}", headers=headers
        )

    def flat_list_rating_cycles(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/rating-cycles", headers=headers, params=params
        )

    def flat_get_coaching_log_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/hr-org-units/coaching-log-entries/{entry_id}", headers=headers
        )

    def flat_list_coaching_log_entries(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/coaching-log-entries", headers=headers, params=params
        )

    def flat_get_concern(self, concern_id, headers):
        return self._request(
            "GET", f"/hr-org-units/performance-concerns/{concern_id}", headers=headers
        )

    def flat_list_concerns(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/performance-concerns", headers=headers, params=params
        )

    def flat_get_pip_template(self, template_id, headers):
        return self._request(
            "GET", f"/hr-org-units/pip-templates/{template_id}", headers=headers
        )

    def flat_list_pip_templates(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/pip-templates", headers=headers, params=params
        )

    def flat_get_pip(self, pip_id, headers):
        return self._request("GET", f"/hr-org-units/pips/{pip_id}", headers=headers)

    def flat_list_pips(self, headers, params=None):
        return self._request("GET", "/hr-org-units/pips", headers=headers, params=params)

    def flat_get_pip_goal(self, goal_id, headers):
        return self._request("GET", f"/hr-org-units/pip-goals/{goal_id}", headers=headers)

    def flat_list_pip_goals(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/pip-goals", headers=headers, params=params
        )

    def flat_get_check_in(self, check_in_id, headers):
        return self._request(
            "GET", f"/hr-org-units/check-ins/{check_in_id}", headers=headers
        )

    def flat_list_check_ins(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/check-ins", headers=headers, params=params
        )

    def flat_get_evidence_item(self, evidence_id, headers):
        return self._request(
            "GET", f"/hr-org-units/evidence-items/{evidence_id}", headers=headers
        )

    def flat_list_evidence_items(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/evidence-items", headers=headers, params=params
        )

    def flat_get_legal_review(self, review_id, headers):
        return self._request(
            "GET", f"/hr-org-units/legal-reviews/{review_id}", headers=headers
        )

    def flat_list_legal_reviews(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/legal-reviews", headers=headers, params=params
        )

    def flat_get_outcome_decision(self, decision_id, headers):
        return self._request(
            "GET", f"/hr-org-units/outcome-decisions/{decision_id}", headers=headers
        )

    def flat_list_outcome_decisions(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/outcome-decisions", headers=headers, params=params
        )

    def flat_get_rebuttal(self, rebuttal_id, headers):
        return self._request("GET", f"/hr-org-units/rebuttals/{rebuttal_id}", headers=headers)

    def flat_list_rebuttals(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/rebuttals", headers=headers, params=params
        )

    def flat_get_consistency_review(self, review_id, headers):
        return self._request(
            "GET", f"/hr-org-units/consistency-review-items/{review_id}", headers=headers
        )

    def flat_list_consistency_reviews(self, headers, params=None):
        return self._request(
            "GET", "/hr-org-units/consistency-review-items", headers=headers, params=params
        )

    def flat_get_rating_cycle_outcome_link(self, link_id, headers):
        return self._request(
            "GET",
            f"/hr-org-units/rating-cycle-outcome-links/{link_id}",
            headers=headers,
        )

    def flat_list_rating_cycle_outcome_links(self, headers, params=None):
        return self._request(
            "GET",
            "/hr-org-units/rating-cycle-outcome-links",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
