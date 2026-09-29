"""Typed client for the Drive-Thru Speed-Of-Service API (PRD §4).

One method per declared endpoint. Every method returns the raw
`requests.Response` so tests can assert status codes and envelopes themselves.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class DriveThruApiClient(GenericApiClient):
    """All 64 declared endpoints, grouped by resource."""

    # ------------------------------------------------------------------ clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------ restaurants
    def register_restaurant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/restaurants", payload, headers)

    def get_restaurant(self, restaurant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/restaurants/{restaurant_id}", None, headers
        )

    def patch_restaurant(
        self, restaurant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/restaurants/{restaurant_id}", payload, headers
        )

    def freeze_restaurant(
        self, restaurant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/restaurants/{restaurant_id}/freeze", payload, headers
        )

    def unfreeze_restaurant(
        self,
        restaurant_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/restaurants/{restaurant_id}/unfreeze",
            payload or {},
            headers,
        )

    def award_merge_slot(
        self,
        restaurant_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/restaurants/{restaurant_id}/merge-award",
            payload or {},
            headers,
        )

    # --------------------------------------------------- volume tier policies
    def create_volume_tier_policy(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/volume-tier-policies", payload, headers
        )

    def list_volume_tier_policies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/volume-tier-policies", params, headers
        )

    # -------------------------------------------------------- daypart profiles
    def create_daypart_profile(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/daypart-profiles", payload, headers)

    def activate_daypart_profile(
        self,
        profile_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/daypart-profiles/{profile_id}/activate",
            payload or {},
            headers,
        )

    def retire_daypart_profile(
        self,
        profile_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/daypart-profiles/{profile_id}/retire",
            payload or {},
            headers,
        )

    def list_daypart_profiles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/daypart-profiles", params, headers)

    def get_daypart_profile(self, profile_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/daypart-profiles/{profile_id}", None, headers
        )

    # ----------------------------------------------------------- staff members
    def create_staff_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/staff-members", payload, headers)

    def list_staff_members(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/staff-members", params, headers)

    def get_staff_member(self, staff_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/staff-members/{staff_id}", None, headers
        )

    # --------------------------------------------------- order-taker deployments
    def create_deployment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/order-taker-deployments", payload, headers
        )

    def activate_deployment(
        self,
        deployment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/order-taker-deployments/{deployment_id}/activate",
            payload or {},
            headers,
        )

    def release_deployment(
        self,
        deployment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/order-taker-deployments/{deployment_id}/release",
            payload or {},
            headers,
        )

    def abort_deployment(
        self, deployment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/order-taker-deployments/{deployment_id}/abort",
            payload,
            headers,
        )

    def list_deployments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/order-taker-deployments", params, headers
        )

    def get_deployment(self, deployment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{API_PREFIX}/order-taker-deployments/{deployment_id}",
            None,
            headers,
        )

    # -------------------------------------------------------------- timer loops
    def create_timer_loop(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/timer-loops", payload, headers)

    def greet_timer_loop(
        self,
        loop_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{API_PREFIX}/timer-loops/{loop_id}/greet", payload or {}, headers
        )

    def complete_order(
        self, loop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/timer-loops/{loop_id}/order-complete",
            payload,
            headers,
        )

    def window_arrive(
        self,
        loop_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/timer-loops/{loop_id}/window-arrive",
            payload or {},
            headers,
        )

    def depart_timer_loop(
        self,
        loop_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{API_PREFIX}/timer-loops/{loop_id}/depart", payload or {}, headers
        )

    def abandon_timer_loop(
        self, loop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/timer-loops/{loop_id}/abandon", payload, headers
        )

    def list_timer_loops(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/timer-loops", params, headers)

    def get_timer_loop(self, loop_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/timer-loops/{loop_id}", None, headers
        )

    # -------------------------------------------------------------- merge slots
    def commit_merge_slot(
        self,
        slot_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{API_PREFIX}/merge-slots/{slot_id}/commit", payload or {}, headers
        )

    def list_merge_slots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/merge-slots", params, headers)

    def get_merge_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/merge-slots/{slot_id}", None, headers
        )

    # ------------------------------------------------------ pull-forward orders
    def create_pull_forward_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/pull-forward-orders", payload, headers
        )

    def park_pull_forward_order(
        self,
        pull_forward_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/pull-forward-orders/{pull_forward_id}/park",
            payload or {},
            headers,
        )

    def reissue_pull_forward_order(
        self,
        pull_forward_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/pull-forward-orders/{pull_forward_id}/reissue",
            payload or {},
            headers,
        )

    def clear_pull_forward_order(
        self,
        pull_forward_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/pull-forward-orders/{pull_forward_id}/clear",
            payload or {},
            headers,
        )

    def list_pull_forward_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/pull-forward-orders", params, headers
        )

    def get_pull_forward_order(self, pull_forward_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/pull-forward-orders/{pull_forward_id}", None, headers
        )

    # -------------------------------------------------------- accuracy incidents
    def create_accuracy_incident(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/accuracy-incidents", payload, headers
        )

    def deliver_remake(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/accuracy-incidents/{incident_id}/deliver-remake",
            payload,
            headers,
        )

    def close_accuracy_incident(
        self,
        incident_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/accuracy-incidents/{incident_id}/close",
            payload or {},
            headers,
        )

    def waive_accuracy_incident(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/accuracy-incidents/{incident_id}/waive",
            payload,
            headers,
        )

    def list_accuracy_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/accuracy-incidents", params, headers)

    def get_accuracy_incident(self, incident_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/accuracy-incidents/{incident_id}", None, headers
        )

    # -------------------------------------------------------- throughput reports
    def create_throughput_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/throughput-reports", payload, headers
        )

    def publish_throughput_report(
        self,
        report_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/throughput-reports/{report_id}/publish",
            payload or {},
            headers,
        )

    def retract_throughput_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/throughput-reports/{report_id}/retract",
            payload,
            headers,
        )

    def list_throughput_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/throughput-reports", params, headers)

    def get_throughput_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/throughput-reports/{report_id}", None, headers
        )

    # ---------------------------------------------------- coaching interventions
    def create_coaching_intervention(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/coaching-interventions", payload, headers
        )

    def issue_coaching_intervention(
        self,
        coaching_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/coaching-interventions/{coaching_id}/issue",
            payload or {},
            headers,
        )

    def acknowledge_coaching_intervention(
        self,
        coaching_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/coaching-interventions/{coaching_id}/acknowledge",
            payload or {},
            headers,
        )

    def contest_coaching_intervention(
        self, coaching_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/coaching-interventions/{coaching_id}/contest",
            payload,
            headers,
        )

    def close_coaching_intervention(
        self, coaching_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/coaching-interventions/{coaching_id}/close",
            payload,
            headers,
        )

    def list_coaching_interventions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/coaching-interventions", params, headers
        )

    def get_coaching_intervention(self, coaching_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/coaching-interventions/{coaching_id}", None, headers
        )

    # -------------------------------------------------------- forecast overrides
    def create_forecast_override(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/forecast-overrides", payload, headers
        )

    def approve_forecast_override(
        self,
        override_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/forecast-overrides/{override_id}/approve",
            payload or {},
            headers,
        )

    def reject_forecast_override(
        self, override_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/forecast-overrides/{override_id}/reject",
            payload,
            headers,
        )

    def apply_forecast_override(
        self,
        override_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/forecast-overrides/{override_id}/apply",
            payload or {},
            headers,
        )

    def list_forecast_overrides(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{API_PREFIX}/forecast-overrides", params, headers)

    def get_forecast_override(self, override_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/forecast-overrides/{override_id}", None, headers
        )
