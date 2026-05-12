"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient from the framework. Each method delegates to
_request and returns the raw Response object. Headers are passed explicitly
because every request must carry X-User-ID and X-User-Role.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint listed in the PRD's endpoint table."""

    # =======================================================================
    # Community
    # =======================================================================
    def create_community(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request("POST", "/communities", payload, headers)

    def get_community(self, community_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/communities/{community_id}", headers=headers,
        )

    # =======================================================================
    # Household
    # =======================================================================
    def create_household(
        self, community_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/communities/{community_id}/households",
            payload, headers,
        )

    def get_household(
        self, community_id: str, household_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/communities/{community_id}/households/{household_id}",
            headers=headers,
        )

    def list_households(
        self, community_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/communities/{community_id}/households",
            headers=headers, params=params,
        )

    # =======================================================================
    # Resident
    # =======================================================================
    def create_resident(
        self, community_id: str, household_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/communities/{community_id}/households/{household_id}/residents",
            payload, headers,
        )

    def verify_resident(
        self, community_id: str, household_id: str, resident_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/households/{household_id}"
                f"/residents/{resident_id}/verify"
            ),
            payload, headers,
        )

    def restrict_resident(
        self, community_id: str, household_id: str, resident_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/households/{household_id}"
                f"/residents/{resident_id}/restrict"
            ),
            payload, headers,
        )

    def get_resident(
        self, community_id: str, household_id: str, resident_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            (
                f"/communities/{community_id}/households/{household_id}"
                f"/residents/{resident_id}"
            ),
            headers=headers,
        )

    # =======================================================================
    # PointRule
    # =======================================================================
    def create_point_rule(
        self, community_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/communities/{community_id}/point-rules",
            payload, headers,
        )

    def activate_point_rule(
        self, community_id: str, rule_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/communities/{community_id}/point-rules/{rule_id}/activate",
            payload, headers,
        )

    def retire_point_rule(
        self, community_id: str, rule_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/communities/{community_id}/point-rules/{rule_id}/retire",
            {}, headers,
        )

    def get_point_rule_effectiveness(
        self, community_id: str, rule_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/communities/{community_id}/point-rules/{rule_id}/effectiveness",
            headers=headers,
        )

    def list_point_rules(
        self, community_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/communities/{community_id}/point-rules",
            headers=headers, params=params,
        )

    # =======================================================================
    # Disposal
    # =======================================================================
    def create_disposal(
        self, community_id: str, household_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/communities/{community_id}/households/{household_id}/disposals",
            payload, headers,
        )

    def correct_disposal(
        self, community_id: str, household_id: str, disposal_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/households/{household_id}"
                f"/disposals/{disposal_id}/correct"
            ),
            payload, headers,
        )

    def void_disposal(
        self, community_id: str, household_id: str, disposal_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/households/{household_id}"
                f"/disposals/{disposal_id}/void"
            ),
            payload, headers,
        )

    def list_disposals(
        self, community_id: str, household_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/communities/{community_id}/households/{household_id}/disposals",
            headers=headers, params=params,
        )

    def get_disposal(
        self, community_id: str, household_id: str, disposal_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            (
                f"/communities/{community_id}/households/{household_id}"
                f"/disposals/{disposal_id}"
            ),
            headers=headers,
        )

    # =======================================================================
    # PointsTransaction (read-only)
    # =======================================================================
    def list_points_transactions(
        self, community_id: str, household_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            (
                f"/communities/{community_id}/households/{household_id}"
                f"/points-transactions"
            ),
            headers=headers, params=params,
        )

    # =======================================================================
    # MallItem
    # =======================================================================
    def create_mall_item(
        self, community_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/communities/{community_id}/mall-items",
            payload, headers,
        )

    def patch_mall_item(
        self, community_id: str, item_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "PATCH",
            f"/communities/{community_id}/mall-items/{item_id}",
            payload, headers,
        )

    def list_mall_items(
        self, community_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/communities/{community_id}/mall-items",
            headers=headers, params=params,
        )

    # =======================================================================
    # RedemptionOrder
    # =======================================================================
    def submit_redemption_order(
        self, community_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/communities/{community_id}/redemption-orders",
            payload, headers,
        )

    def confirm_redemption_order(
        self, community_id: str, order_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/redemption-orders/"
                f"{order_id}/confirm"
            ),
            {}, headers,
        )

    def reject_redemption_order(
        self, community_id: str, order_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/redemption-orders/"
                f"{order_id}/reject"
            ),
            payload, headers,
        )

    def fulfill_redemption_order(
        self, community_id: str, order_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/redemption-orders/"
                f"{order_id}/fulfill"
            ),
            {}, headers,
        )

    def deliver_redemption_order(
        self, community_id: str, order_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/redemption-orders/"
                f"{order_id}/deliver"
            ),
            {}, headers,
        )

    def return_redemption_order(
        self, community_id: str, order_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/redemption-orders/"
                f"{order_id}/return"
            ),
            payload, headers,
        )

    def get_redemption_order(
        self, community_id: str, order_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/communities/{community_id}/redemption-orders/{order_id}",
            headers=headers,
        )

    def list_redemption_orders(
        self, community_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/communities/{community_id}/redemption-orders",
            headers=headers, params=params,
        )

    # =======================================================================
    # Violation
    # =======================================================================
    def create_violation(
        self, community_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/communities/{community_id}/violations",
            payload, headers,
        )

    def appeal_violation(
        self, community_id: str, violation_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/violations/"
                f"{violation_id}/appeal"
            ),
            payload, headers,
        )

    def accept_review_violation(
        self, community_id: str, violation_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/violations/"
                f"{violation_id}/accept-review"
            ),
            {}, headers,
        )

    def decide_violation(
        self, community_id: str, violation_id: str,
        payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/violations/"
                f"{violation_id}/decide"
            ),
            payload, headers,
        )

    def get_violation(
        self, community_id: str, violation_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/communities/{community_id}/violations/{violation_id}",
            headers=headers,
        )

    def list_violations(
        self, community_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/communities/{community_id}/violations",
            headers=headers, params=params,
        )

    # =======================================================================
    # RankingPeriod
    # =======================================================================
    def create_ranking_period(
        self, community_id: str, payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/communities/{community_id}/ranking-periods",
            payload, headers,
        )

    def close_ranking_period(
        self, community_id: str, period_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/ranking-periods/"
                f"{period_id}/close"
            ),
            {}, headers,
        )

    def publish_ranking_period(
        self, community_id: str, period_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            (
                f"/communities/{community_id}/ranking-periods/"
                f"{period_id}/publish"
            ),
            {}, headers,
        )

    def get_ranking_period(
        self, community_id: str, period_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/communities/{community_id}/ranking-periods/{period_id}",
            headers=headers,
        )

    def list_ranking_periods(
        self, community_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/communities/{community_id}/ranking-periods",
            headers=headers, params=params,
        )

    # =======================================================================
    # AuditLog (read-only)
    # =======================================================================
    def list_audit_logs(
        self, community_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/communities/{community_id}/audit-logs",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-only / operator capabilities
    # =======================================================================
    def advance_clock(
        self, to_iso: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_clock/advance", {"to": to_iso}, headers,
        )

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
