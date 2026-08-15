"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock (PRD §2.5) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/science-fair/_clock/set_current_utc", payload, headers)

    # ---- FairEdition ----
    def create_fair_edition(self, payload, headers):
        return self._request("POST", "/science-fair/fair-editions", payload, headers)

    def list_fair_editions(self, headers, params=None):
        return self._request("GET", "/science-fair/fair-editions", headers=headers, params=params)

    def get_fair_edition(self, edition_id, headers):
        return self._request("GET", f"/science-fair/fair-editions/{edition_id}", headers=headers)

    def open_registration(self, edition_id, headers):
        return self._request("POST", f"/science-fair/fair-editions/{edition_id}/open-registration", {}, headers)

    def close_registration(self, edition_id, headers):
        return self._request("POST", f"/science-fair/fair-editions/{edition_id}/close-registration", {}, headers)

    def begin_judging(self, edition_id, headers):
        return self._request("POST", f"/science-fair/fair-editions/{edition_id}/begin-judging", {}, headers)

    def publish_advancement(self, edition_id, payload, headers):
        return self._request("POST", f"/science-fair/fair-editions/{edition_id}/publish-advancement", payload, headers)

    def finalize_awards(self, edition_id, headers):
        return self._request("POST", f"/science-fair/fair-editions/{edition_id}/finalize-awards", {}, headers)

    def archive_fair_edition(self, edition_id, headers):
        return self._request("POST", f"/science-fair/fair-editions/{edition_id}/archive", {}, headers)

    # ---- Category ----
    def create_category(self, payload, headers):
        return self._request("POST", "/science-fair/categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/science-fair/categories", headers=headers, params=params)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/science-fair/categories/{category_id}", headers=headers)

    def update_category(self, category_id, payload, headers):
        return self._request("PATCH", f"/science-fair/categories/{category_id}", payload, headers)

    # ---- Mentor ----
    def create_mentor(self, payload, headers):
        return self._request("POST", "/science-fair/mentors", payload, headers)

    def list_mentors(self, headers, params=None):
        return self._request("GET", "/science-fair/mentors", headers=headers, params=params)

    def get_mentor(self, mentor_id, headers):
        return self._request("GET", f"/science-fair/mentors/{mentor_id}", headers=headers)

    # ---- Project ----
    def create_project(self, payload, headers):
        return self._request("POST", "/science-fair/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/science-fair/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/science-fair/projects/{project_id}", headers=headers)

    def update_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/science-fair/projects/{project_id}", payload, headers)

    def submit_project(self, project_id, headers):
        return self._request("POST", f"/science-fair/projects/{project_id}/submit", {}, headers)

    def withdraw_project(self, project_id, headers):
        return self._request("POST", f"/science-fair/projects/{project_id}/withdraw", {}, headers)

    # ---- ResearchPlan ----
    def create_research_plan(self, payload, headers):
        return self._request("POST", "/science-fair/research-plans", payload, headers)

    def list_research_plans(self, headers, params=None):
        return self._request("GET", "/science-fair/research-plans", headers=headers, params=params)

    def get_research_plan(self, plan_id, headers):
        return self._request("GET", f"/science-fair/research-plans/{plan_id}", headers=headers)

    def update_research_plan(self, plan_id, payload, headers):
        return self._request("PUT", f"/science-fair/research-plans/{plan_id}", payload, headers)

    def submit_research_plan(self, plan_id, headers):
        return self._request("POST", f"/science-fair/research-plans/{plan_id}/submit", {}, headers)

    def begin_review(self, plan_id, headers):
        return self._request("POST", f"/science-fair/research-plans/{plan_id}/begin-review", {}, headers)

    def record_ethics_decision(self, plan_id, payload, headers):
        return self._request("POST", f"/science-fair/research-plans/{plan_id}/decisions", payload, headers)

    # ---- EthicsReview readback ----
    def list_ethics_reviews(self, headers, params=None):
        return self._request("GET", "/science-fair/ethics-reviews", headers=headers, params=params)

    def get_ethics_review(self, review_id, headers):
        return self._request("GET", f"/science-fair/ethics-reviews/{review_id}", headers=headers)

    # ---- Judge ----
    def create_judge(self, payload, headers):
        return self._request("POST", "/science-fair/judges", payload, headers)

    def list_judges(self, headers, params=None):
        return self._request("GET", "/science-fair/judges", headers=headers, params=params)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"/science-fair/judges/{judge_id}", headers=headers)

    def activate_judge(self, judge_id, headers):
        return self._request("POST", f"/science-fair/judges/{judge_id}/activate", {}, headers)

    def deactivate_judge(self, judge_id, headers):
        return self._request("POST", f"/science-fair/judges/{judge_id}/deactivate", {}, headers)

    # ---- JudgeConflict ----
    def declare_conflict(self, judge_id, payload, headers):
        return self._request("POST", f"/science-fair/judges/{judge_id}/conflicts", payload, headers)

    def list_judge_conflicts(self, judge_id, headers, params=None):
        return self._request("GET", f"/science-fair/judges/{judge_id}/conflicts", headers=headers, params=params)

    def list_all_judge_conflicts(self, headers, params=None):
        return self._request("GET", "/science-fair/judge-conflicts", headers=headers, params=params)

    def get_judge_conflict(self, conflict_id, headers):
        return self._request("GET", f"/science-fair/judge-conflicts/{conflict_id}", headers=headers)

    # ---- JudgingAssignment ----
    def create_judging_assignment(self, project_id, payload, headers):
        return self._request("POST", f"/science-fair/projects/{project_id}/judging-assignments", payload, headers)

    def list_judging_assignments(self, headers, params=None):
        return self._request("GET", "/science-fair/judging-assignments", headers=headers, params=params)

    def get_judging_assignment(self, assignment_id, headers):
        return self._request("GET", f"/science-fair/judging-assignments/{assignment_id}", headers=headers)

    def submit_score_sheet(self, assignment_id, payload, headers):
        return self._request("POST", f"/science-fair/judging-assignments/{assignment_id}/score-sheets", payload, headers)

    def recuse_assignment(self, assignment_id, headers):
        return self._request("POST", f"/science-fair/judging-assignments/{assignment_id}/recuse", {}, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/science-fair/judging-assignments/{assignment_id}/release", {}, headers)

    # ---- ScoreSheet readback ----
    def list_score_sheets(self, headers, params=None):
        return self._request("GET", "/science-fair/score-sheets", headers=headers, params=params)

    def get_score_sheet(self, sheet_id, headers):
        return self._request("GET", f"/science-fair/score-sheets/{sheet_id}", headers=headers)

    # ---- BoothAssignment / inspection ----
    def create_booth_assignment(self, project_id, payload, headers):
        return self._request("POST", f"/science-fair/projects/{project_id}/booth-assignments", payload, headers)

    def list_booth_assignments(self, headers, params=None):
        return self._request("GET", "/science-fair/booth-assignments", headers=headers, params=params)

    def get_booth_assignment(self, booth_id, headers):
        return self._request("GET", f"/science-fair/booth-assignments/{booth_id}", headers=headers)

    def record_inspection_result(self, project_id, payload, headers):
        return self._request("POST", f"/science-fair/projects/{project_id}/inspection-result", payload, headers)

    # ---- Award / ScholarshipPool ----
    def create_award(self, payload, headers):
        return self._request("POST", "/science-fair/awards", payload, headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/science-fair/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/science-fair/awards/{award_id}", headers=headers)

    def revoke_award(self, award_id, headers):
        return self._request("POST", f"/science-fair/awards/{award_id}/revoke", {}, headers)

    def create_scholarship_pool(self, payload, headers):
        return self._request("POST", "/science-fair/scholarship-pools", payload, headers)

    def list_scholarship_pools(self, headers, params=None):
        return self._request("GET", "/science-fair/scholarship-pools", headers=headers, params=params)

    def get_scholarship_pool(self, pool_id, headers):
        return self._request("GET", f"/science-fair/scholarship-pools/{pool_id}", headers=headers)


api_client = ApiClient()
