"""API client: one method per endpoint defined in the PRD.

Every endpoint is mounted under the /srts prefix.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/srts"


class ApiClient(GenericApiClient):
    """Typed wrapper over the Safe Routes to School HTTP surface."""

    # ------------------------------------------------------------------
    # Schools
    # ------------------------------------------------------------------
    def create_school(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/schools", payload, headers)

    def get_school(self, school_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    def list_school_intersections(self, school_id: str, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/schools/{school_id}/intersections",
                             headers=headers, params=params)

    def list_school_walking_routes(self, school_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/schools/{school_id}/walking-routes",
                             headers=headers, params=params)

    def create_mode_share_survey(self, school_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/schools/{school_id}/mode-share-surveys",
                             payload, headers)

    # ------------------------------------------------------------------
    # Intersections
    # ------------------------------------------------------------------
    def create_intersection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/intersections", payload, headers)

    def get_intersection(self, intersection_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/intersections/{intersection_id}",
                             headers=headers)

    def create_crash_record(self, intersection_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST",
                             f"{PREFIX}/intersections/{intersection_id}/crash-records",
                             payload, headers)

    def list_intersection_warrant_studies(self, intersection_id: str,
                                          headers: Dict[str, str],
                                          params: Optional[Dict] = None):
        return self._request("GET",
                             f"{PREFIX}/intersections/{intersection_id}/warrant-studies",
                             headers=headers, params=params)

    def list_intersection_guard_posts(self, intersection_id: str,
                                      headers: Dict[str, str],
                                      params: Optional[Dict] = None):
        return self._request("GET",
                             f"{PREFIX}/intersections/{intersection_id}/guard-posts",
                             headers=headers, params=params)

    def list_intersection_complaints(self, intersection_id: str,
                                     headers: Dict[str, str],
                                     params: Optional[Dict] = None):
        return self._request("GET",
                             f"{PREFIX}/intersections/{intersection_id}/complaints",
                             headers=headers, params=params)

    def create_complaint(self, intersection_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST",
                             f"{PREFIX}/intersections/{intersection_id}/complaints",
                             payload, headers)

    # ------------------------------------------------------------------
    # Warrant studies
    # ------------------------------------------------------------------
    def create_warrant_study(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/warrant-studies", payload, headers)

    def get_warrant_study(self, study_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/warrant-studies/{study_id}",
                             headers=headers)

    def create_count_session(self, study_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST",
                             f"{PREFIX}/warrant-studies/{study_id}/count-sessions",
                             payload, headers)

    def analyze_warrant_study(self, study_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/warrant-studies/{study_id}/analyze",
                             payload or {}, headers)

    def finalize_warrant_study(self, study_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/warrant-studies/{study_id}/finalize",
                             payload or {}, headers)

    def reopen_counting(self, study_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST",
                             f"{PREFIX}/warrant-studies/{study_id}/reopen-counting",
                             payload, headers)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def create_guard(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/guards", payload, headers)

    def get_guard(self, guard_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/guards/{guard_id}", headers=headers)

    def record_training(self, guard_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/guards/{guard_id}/training",
                             payload, headers)

    def issue_equipment(self, guard_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/guards/{guard_id}/equipment",
                             payload, headers)

    def certify_guard(self, guard_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/guards/{guard_id}/certify",
                             payload, headers)

    def set_duty_status(self, guard_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/guards/{guard_id}/duty-status",
                             payload, headers)

    # ------------------------------------------------------------------
    # Guard posts and assignments
    # ------------------------------------------------------------------
    def create_guard_post(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/guard-posts", payload, headers)

    def get_guard_post(self, post_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/guard-posts/{post_id}", headers=headers)

    def activate_guard_post(self, post_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/guard-posts/{post_id}/activate",
                             payload or {}, headers)

    def create_assignment(self, post_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/guard-posts/{post_id}/assignments",
                             payload, headers)

    def get_post_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/post-assignments/{assignment_id}",
                             headers=headers)

    def list_post_assignments(self, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/post-assignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Absence reports and substitute dispatch
    # ------------------------------------------------------------------
    def create_absence_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/absence-reports", payload, headers)

    def get_absence_report(self, absence_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/absence-reports/{absence_id}",
                             headers=headers)

    def list_absence_reports(self, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/absence-reports",
                             headers=headers, params=params)

    def dispatch_absence_report(self, absence_id: str, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/absence-reports/{absence_id}/dispatch",
                             payload or {}, headers)

    def respond_to_offer(self, absence_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST",
                             f"{PREFIX}/absence-reports/{absence_id}/offer-response",
                             payload, headers)

    def rescind_absence_report(self, absence_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/absence-reports/{absence_id}/rescind",
                             payload, headers)

    # ------------------------------------------------------------------
    # Walking routes
    # ------------------------------------------------------------------
    def create_walking_route(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/walking-routes", payload, headers)

    def get_walking_route(self, route_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/walking-routes/{route_id}",
                             headers=headers)

    def publish_walking_route(self, route_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"{PREFIX}/walking-routes/{route_id}/publish",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/complaints/{complaint_id}",
                             headers=headers)

    def triage_complaint(self, complaint_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/triage",
                             payload, headers)

    # ------------------------------------------------------------------
    # Grant programs and infrastructure projects
    # ------------------------------------------------------------------
    def create_grant_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/grant-programs", payload, headers)

    def get_grant_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/grant-programs/{program_id}",
                             headers=headers)

    def create_infrastructure_project(self, payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/infrastructure-projects",
                             payload, headers)

    def get_infrastructure_project(self, project_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/infrastructure-projects/{project_id}",
                             headers=headers)

    def list_infrastructure_projects(self, headers: Dict[str, str],
                                     params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/infrastructure-projects",
                             headers=headers, params=params)

    def score_project(self, project_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request("POST",
                             f"{PREFIX}/infrastructure-projects/{project_id}/score",
                             payload or {}, headers)

    def fund_project(self, project_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST",
                             f"{PREFIX}/infrastructure-projects/{project_id}/fund",
                             payload, headers)

    def withdraw_funding(self, project_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/infrastructure-projects/{project_id}/withdraw-funding",
            payload, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
