"""Typed client exposing one method per endpoint of the API under test."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per documented endpoint. Every method returns the raw response."""

    # ------------------------------------------------------------------
    # Business lines
    # ------------------------------------------------------------------
    def create_business_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/business-lines", payload, headers)

    def get_business_line(self, business_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/business-lines/{business_line_id}", None, headers)

    def review_business_line(
        self, business_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/business-lines/{business_line_id}/review", payload, headers
        )

    def launch_business_line(
        self,
        business_line_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/business-lines/{business_line_id}/launch", payload or {}, headers
        )

    def get_outcome_summary(
        self,
        business_line_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/business-lines/{business_line_id}/outcome-summary",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Referral partners
    # ------------------------------------------------------------------
    def create_referral_partner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/referral-partners", payload, headers)

    def get_referral_partner(self, referral_partner_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/referral-partners/{referral_partner_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------
    def create_referral(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/referrals/{referral_id}", None, headers)

    def list_referrals(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/referrals", params, headers)

    def screen_referral(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/screen", payload, headers
        )

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def create_participant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/participants/{participant_id}", None, headers)

    def list_participants(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/participants", params, headers)

    def certify_readiness(
        self,
        participant_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/participants/{participant_id}/certify-readiness",
            payload or {},
            headers,
        )

    def graduate_participant(
        self,
        participant_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/participants/{participant_id}/graduate", payload or {}, headers
        )

    def re_enter_participant(
        self, participant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/participants/{participant_id}/re-enter", payload, headers
        )

    # ------------------------------------------------------------------
    # Work shifts
    # ------------------------------------------------------------------
    def create_work_shift(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/work-shifts", payload, headers)

    def get_work_shift(self, work_shift_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/work-shifts/{work_shift_id}", None, headers)

    def list_work_shifts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/work-shifts", params, headers)

    # ------------------------------------------------------------------
    # Shift assignments
    # ------------------------------------------------------------------
    def create_shift_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shift-assignments", payload, headers)

    def get_shift_assignment(self, shift_assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/shift-assignments/{shift_assignment_id}", None, headers
        )

    def list_shift_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/shift-assignments", params, headers)

    def complete_shift_assignment(
        self, shift_assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shift-assignments/{shift_assignment_id}/complete",
            payload,
            headers,
        )

    def release_shift_assignment(
        self,
        shift_assignment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/shift-assignments/{shift_assignment_id}/release",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Support activities
    # ------------------------------------------------------------------
    def create_support_activity(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/support-activities", payload, headers)

    def get_support_activity(self, support_activity_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/support-activities/{support_activity_id}", None, headers
        )

    def list_support_activities(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/support-activities", params, headers)

    def deliver_support_activity(
        self,
        support_activity_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/support-activities/{support_activity_id}/deliver",
            payload or {},
            headers,
        )

    def void_support_activity(
        self, support_activity_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/support-activities/{support_activity_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Employers
    # ------------------------------------------------------------------
    def create_employer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/employers/{employer_id}", None, headers)

    # ------------------------------------------------------------------
    # Placements
    # ------------------------------------------------------------------
    def create_placement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/placements/{placement_id}", None, headers)

    def list_placements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/placements", params, headers)

    def list_retention_checkpoints(
        self,
        placement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/placements/{placement_id}/retention-checkpoints", params, headers
        )

    def record_wage_verification(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/placements/{placement_id}/wage-verification", payload, headers
        )

    def separate_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/placements/{placement_id}/separate", payload, headers
        )

    # ------------------------------------------------------------------
    # Retention checkpoints and the ops sweep
    # ------------------------------------------------------------------
    def confirm_retention_checkpoint(
        self,
        retention_checkpoint_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/retention-checkpoints/{retention_checkpoint_id}/confirm",
            payload,
            headers,
        )

    def run_retention_sweep(
        self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request("POST", "/retention-sweeps", payload or {}, headers)

    # ------------------------------------------------------------------
    # Subsidy periods
    # ------------------------------------------------------------------
    def create_subsidy_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/subsidy-periods", payload, headers)

    def get_subsidy_period(self, subsidy_period_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/subsidy-periods/{subsidy_period_id}", None, headers
        )

    def list_subsidy_periods(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/subsidy-periods", params, headers)

    def get_true_cost_analysis(
        self,
        subsidy_period_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/subsidy-periods/{subsidy_period_id}/true-cost-analysis",
            params,
            headers,
        )

    def close_subsidy_period(
        self, subsidy_period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/subsidy-periods/{subsidy_period_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Cost entries
    # ------------------------------------------------------------------
    def create_cost_entry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cost-entries", payload, headers)

    def get_cost_entry(self, cost_entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cost-entries/{cost_entry_id}", None, headers)

    def list_cost_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/cost-entries", params, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )
