"""Thin typed wrapper over the season pass API surface.

One method per endpoint the PRD declares. Every method takes an explicit
`headers` mapping so that the caller's identity is always visible at the call
site, and returns the raw `requests.Response` so tests can assert on status
codes and on the response envelope.
"""

from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the season pass and blockout API."""

    # ------------------------------------------------------------ programmes --

    def create_pass_program(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/pass-programs", payload=payload, headers=headers)

    def list_pass_programs(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/pass-programs", headers=headers, params=params)

    def get_pass_program(
        self, program_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/pass-programs/{program_id}", headers=headers)

    def advance_program_status(
        self,
        program_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/pass-programs/{program_id}/advance-status", payload=payload, headers=headers
        )

    def get_revenue_summary(
        self, program_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/pass-programs/{program_id}/revenue-summary", headers=headers)

    def run_billing(
        self,
        program_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/pass-programs/{program_id}/billing-runs", payload=payload, headers=headers
        )

    # ----------------------------------------------------------------- tiers --

    def create_pass_tier(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/pass-tiers", payload=payload, headers=headers)

    def list_pass_tiers(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/pass-tiers", headers=headers, params=params)

    def get_pass_tier(
        self, tier_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/pass-tiers/{tier_id}", headers=headers)

    def set_tier_status(
        self,
        tier_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/pass-tiers/{tier_id}/status", payload=payload, headers=headers
        )

    # ------------------------------------------------------------- park days --

    def create_park_day(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/park-days", payload=payload, headers=headers)

    def list_park_days(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/park-days", headers=headers, params=params)

    def get_park_day(
        self, park_day_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/park-days/{park_day_id}", headers=headers)

    def forecast_park_day(
        self,
        park_day_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/park-days/{park_day_id}/forecast", payload=payload, headers=headers
        )

    # --------------------------------------------------- blockout assignments --

    def create_blockout_assignment(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/blockout-assignments", payload=payload, headers=headers)

    def list_blockout_assignments(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/blockout-assignments", headers=headers, params=params)

    def get_blockout_assignment(
        self, assignment_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/blockout-assignments/{assignment_id}", headers=headers)

    def lift_blockout_assignment(
        self,
        assignment_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/blockout-assignments/{assignment_id}/lift", payload=payload, headers=headers
        )

    # ----------------------------------------------------------- passholders --

    def create_passholder(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/passholders", payload=payload, headers=headers)

    def list_passholders(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/passholders", headers=headers, params=params)

    def get_passholder(
        self, passholder_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/passholders/{passholder_id}", headers=headers)

    # ---------------------------------------------------------- season passes --

    def create_season_pass(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/season-passes", payload=payload, headers=headers)

    def list_season_passes(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/season-passes", headers=headers, params=params)

    def get_season_pass(
        self, pass_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/season-passes/{pass_id}", headers=headers)

    def process_season_pass(
        self,
        pass_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/season-passes/{pass_id}/process", payload=payload, headers=headers
        )

    def create_payment_plan(
        self,
        pass_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/season-passes/{pass_id}/payment-plans", payload=payload, headers=headers
        )

    def reinstate_season_pass(
        self,
        pass_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/season-passes/{pass_id}/reinstate", payload=payload, headers=headers
        )

    def get_renewal_quote(
        self,
        pass_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/season-passes/{pass_id}/renewal-quote", headers=headers, params=params
        )

    def renew_season_pass(
        self,
        pass_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/season-passes/{pass_id}/renew", payload=payload, headers=headers
        )

    # ---------------------------------------------- payment plans / installments --

    def list_payment_plans(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/payment-plans", headers=headers, params=params)

    def get_payment_plan(
        self, plan_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/payment-plans/{plan_id}", headers=headers)

    def list_installments(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/installments", headers=headers, params=params)

    def get_installment(
        self, installment_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/installments/{installment_id}", headers=headers)

    def settle_installment(
        self,
        installment_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/installments/{installment_id}/settle", payload=payload, headers=headers
        )

    # ---------------------------------------------------------- reservations --

    def create_reservation(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/reservations", payload=payload, headers=headers)

    def list_reservations(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/reservations", headers=headers, params=params)

    def get_reservation(
        self, reservation_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def cancel_reservation(
        self,
        reservation_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/reservations/{reservation_id}/cancel",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ---------------------------------------------------------------- visits --

    def create_visit(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/visits", payload=payload, headers=headers)

    def list_visits(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/visits", headers=headers, params=params)

    def get_visit(
        self, visit_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def close_visit(
        self,
        visit_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/visits/{visit_id}/close", payload=payload, headers=headers)

    # --------------------------------------------------------- sharing cases --

    def create_sharing_case(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/sharing-cases", payload=payload, headers=headers)

    def list_sharing_cases(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/sharing-cases", headers=headers, params=params)

    def get_sharing_case(
        self, case_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/sharing-cases/{case_id}", headers=headers)

    def review_sharing_case(
        self,
        case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/sharing-cases/{case_id}/review",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def decide_sharing_case(
        self,
        case_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/sharing-cases/{case_id}/decide", payload=payload, headers=headers
        )

    def appeal_sharing_case(
        self,
        case_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/sharing-cases/{case_id}/appeal", payload=payload, headers=headers
        )

    # --------------------------------------------------------- upgrade orders --

    def create_upgrade_order(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/upgrade-orders", payload=payload, headers=headers)

    def list_upgrade_orders(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", "/upgrade-orders", headers=headers, params=params)

    def get_upgrade_order(
        self, upgrade_order_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/upgrade-orders/{upgrade_order_id}", headers=headers)

    def apply_upgrade_order(
        self,
        upgrade_order_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/upgrade-orders/{upgrade_order_id}/apply", payload=payload, headers=headers
        )

    def reverse_upgrade_order(
        self,
        upgrade_order_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/upgrade-orders/{upgrade_order_id}/reverse", payload=payload, headers=headers
        )

    # ------------------------------------------------------------ clock ------

    def set_clock(
        self, to_iso8601: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", payload={"to_iso8601": to_iso8601}, headers=headers
        )

    # -------------------------------------------------- raw escape hatches ---

    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET an arbitrary path, for malformed-identifier and filter probes."""
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """POST an arbitrary path with an arbitrary body."""
        return self._request("POST", path, payload=payload, headers=headers)


api_client = ApiClient()

__all__: List[str] = ["ApiClient", "api_client"]
