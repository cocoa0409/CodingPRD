"""Typed HTTP client with one method per endpoint in the API contract."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint of the Minor League Affiliation API."""

    # ------------------------------------------------------------------
    # Affiliates
    # ------------------------------------------------------------------
    def create_affiliate(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/affiliates", payload, headers)

    def list_affiliates(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/affiliates", params or {}, headers)

    def get_affiliate(self, affiliate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/affiliates/{affiliate_id}", None, headers)

    # ------------------------------------------------------------------
    # Affiliation agreements
    # ------------------------------------------------------------------
    def create_agreement(self, affiliate_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/affiliates/{affiliate_id}/agreements", payload, headers)

    def list_agreements(self, affiliate_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/affiliates/{affiliate_id}/agreements", params or {}, headers)

    def dispose_agreement(self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/agreements/{agreement_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Facility standard reviews
    # ------------------------------------------------------------------
    def create_facility_review(self, affiliate_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/affiliates/{affiliate_id}/facility-reviews", payload, headers)

    def list_facility_reviews(self, affiliate_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/affiliates/{affiliate_id}/facility-reviews", params or {}, headers)

    def dispose_facility_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/facility-reviews/{review_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Staff members and allocations
    # ------------------------------------------------------------------
    def create_staff_member(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/staff-members", payload, headers)

    def list_staff_members(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/staff-members", params or {}, headers)

    def get_staff_member(self, staff_member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/staff-members/{staff_member_id}", None, headers)

    def create_staff_allocation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/staff-allocations", payload, headers)

    def list_staff_member_allocations(self, staff_member_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/staff-members/{staff_member_id}/allocations", params or {}, headers)

    def list_affiliate_staff_allocations(self, affiliate_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/affiliates/{affiliate_id}/staff-allocations", params or {}, headers)

    def dispose_staff_allocation(self, allocation_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/staff-allocations/{allocation_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Players and medical clearances
    # ------------------------------------------------------------------
    def create_player(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/players", payload, headers)

    def list_players(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/players", params or {}, headers)

    def get_player(self, player_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/players/{player_id}", None, headers)

    def create_medical_clearance(self, player_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/players/{player_id}/medical-clearances", payload, headers)

    def list_medical_clearances(self, player_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/players/{player_id}/medical-clearances", params or {}, headers)

    def dispose_medical_clearance(self, clearance_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/medical-clearances/{clearance_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def create_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/assignments", payload, headers)

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/assignments", params or {}, headers)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/assignments/{assignment_id}", None, headers)

    def dispose_assignment(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/assignments/{assignment_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Development plans
    # ------------------------------------------------------------------
    def create_development_plan(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/assignments/{assignment_id}/development-plans", payload, headers)

    def list_development_plans(self, assignment_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/assignments/{assignment_id}/development-plans", params or {}, headers)

    def dispose_development_plan(self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/development-plans/{plan_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Workload outings, option years, transaction reports
    # ------------------------------------------------------------------
    def create_workload_log(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/assignments/{assignment_id}/workload-logs", payload, headers)

    def list_workload_logs(self, assignment_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/assignments/{assignment_id}/workload-logs", params or {}, headers)

    def list_option_years(self, assignment_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/assignments/{assignment_id}/option-years", params or {}, headers)

    def list_transaction_reports(self, assignment_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/assignments/{assignment_id}/transaction-reports", params or {}, headers)

    def dispose_transaction_report(self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/transaction-reports/{report_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Signing pools and international signings
    # ------------------------------------------------------------------
    def create_signing_pool(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/signing-pools", payload, headers)

    def get_signing_pool(self, pool_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/signing-pools/{pool_id}", None, headers)

    def create_international_signing(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/international-signings", payload, headers)

    def list_international_signings(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/international-signings", params or {}, headers)

    def get_international_signing(self, signing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/international-signings/{signing_id}", None, headers)

    def dispose_international_signing(self, signing_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/international-signings/{signing_id}/disposition", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)
