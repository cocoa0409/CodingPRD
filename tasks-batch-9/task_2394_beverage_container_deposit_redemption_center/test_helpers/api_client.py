"""One method per endpoint of the deposit-redemption API.

Every path is absolute; the API is not mounted under a version or service
prefix. Methods return the raw ``requests.Response`` so tests can assert on
status codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed façade over the 49 endpoints of the programme API."""

    # ─── Distributors ────────────────────────────────────────────────────────
    def create_distributor(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(
        self, distributor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/distributors/{distributor_id}", None, headers)

    def create_deposit_initiation(
        self,
        distributor_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> requests.Response:
        return self._request(
            "POST", f"/distributors/{distributor_id}/deposit-initiations", payload, headers
        )

    def list_deposit_initiations(
        self,
        distributor_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/distributors/{distributor_id}/deposit-initiations",
            params,
            headers,
        )

    # ─── Beverage products (labels) ──────────────────────────────────────────
    def create_beverage_product(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/beverage-products", payload, headers)

    def get_beverage_product(
        self, product_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/beverage-products/{product_id}", None, headers)

    def list_beverage_products(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/beverage-products", params, headers)

    def post_registration_action(
        self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/beverage-products/{product_id}/registration-actions", payload, headers
        )

    def list_product_container_lots(
        self,
        product_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/beverage-products/{product_id}/container-lots", params, headers
        )

    # ─── Redemption centres ─────────────────────────────────────────────────
    def create_redemption_center(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/redemption-centers", payload, headers)

    def get_redemption_center(
        self, center_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/redemption-centers/{center_id}", None, headers)

    def list_redemption_centers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/redemption-centers", params, headers)

    def post_center_status_change(
        self, center_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/redemption-centers/{center_id}/status-changes", payload, headers
        )

    def create_machine(
        self, center_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/redemption-centers/{center_id}/machines", payload, headers
        )

    def list_center_machines(
        self,
        center_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/redemption-centers/{center_id}/machines", params, headers
        )

    # ─── Reverse vending machines ───────────────────────────────────────────
    def get_machine(
        self, machine_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/reverse-vending-machines/{machine_id}", None, headers
        )

    def post_machine_event(
        self, machine_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/reverse-vending-machines/{machine_id}/machine-events",
            payload,
            headers,
        )

    # ─── Redeemer accounts ──────────────────────────────────────────────────
    def create_redeemer_account(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/redeemer-accounts", payload, headers)

    def get_redeemer_account(
        self, account_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/redeemer-accounts/{account_id}", None, headers)

    def post_credit_action(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/redeemer-accounts/{account_id}/credit-actions", payload, headers
        )

    def post_account_status_change(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/redeemer-accounts/{account_id}/status-changes", payload, headers
        )

    def list_credit_entries(
        self,
        account_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/redeemer-accounts/{account_id}/credit-entries", params, headers
        )

    # ─── Redemption visits ──────────────────────────────────────────────────
    def create_redemption_visit(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/redemption-visits", payload, headers)

    def get_redemption_visit(
        self, visit_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/redemption-visits/{visit_id}", None, headers)

    def list_redemption_visits(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/redemption-visits", params, headers)

    def create_container_lot(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/redemption-visits/{visit_id}/lots", payload, headers
        )

    def list_visit_lots(
        self,
        visit_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/redemption-visits/{visit_id}/lots", params, headers
        )

    def close_count(
        self,
        visit_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/redemption-visits/{visit_id}/close-count", payload or {}, headers
        )

    def post_payout_action(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/redemption-visits/{visit_id}/payout-actions", payload, headers
        )

    # ─── Bag drops ──────────────────────────────────────────────────────────
    def create_bag_drop(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/bag-drops", payload, headers)

    def get_bag_drop(
        self, bag_drop_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/bag-drops/{bag_drop_id}", None, headers)

    def list_bag_drops(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/bag-drops", params, headers)

    def post_bag_drop_count_result(
        self, bag_drop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/bag-drops/{bag_drop_id}/count-results", payload, headers
        )

    def post_bag_drop_settlement_action(
        self, bag_drop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/bag-drops/{bag_drop_id}/settlement-actions", payload, headers
        )

    # ─── Commodity batches ──────────────────────────────────────────────────
    def create_commodity_batch(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/commodity-batches", payload, headers)

    def get_commodity_batch(
        self, batch_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/commodity-batches/{batch_id}", None, headers)

    def list_commodity_batches(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/commodity-batches", params, headers)

    def post_batch_processing_action(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/commodity-batches/{batch_id}/processing-actions", payload, headers
        )

    def sell_commodity_batch(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/commodity-batches/{batch_id}/sale", payload, headers
        )

    # ─── Retailers ──────────────────────────────────────────────────────────
    def create_retailer(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(
        self, retailer_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/retailers/{retailer_id}", None, headers)

    def list_retailers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/retailers", params, headers)

    def post_exemption_action(
        self, retailer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/retailers/{retailer_id}/exemption-actions", payload, headers
        )

    # ─── Program periods ────────────────────────────────────────────────────
    def create_program_period(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/program-periods", payload, headers)

    def get_program_period(
        self, period_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/program-periods/{period_id}", None, headers)

    def list_program_periods(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/program-periods", params, headers)

    def post_period_action(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/program-periods/{period_id}/period-actions", payload, headers
        )

    def list_ledger_entries(
        self,
        period_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/program-periods/{period_id}/ledger-entries", params, headers
        )

    # ─── Logical clock ──────────────────────────────────────────────────────
    def set_clock(
        self, to_iso8601: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
