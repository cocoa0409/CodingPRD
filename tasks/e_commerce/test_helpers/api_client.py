"""
API client for the e-commerce marketplace.

Wraps every endpoint from the scaffold (38 total) as a thin method that
delegates to GenericApiClient._request().
"""

from typing import Any, Dict, Optional

from prd_bench_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """E-commerce marketplace API client (38 endpoints)."""

    # ------------------------------------------------------------------
    # Shop Management (8)
    # ------------------------------------------------------------------

    def create_shop(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shops", payload, headers)

    def list_shops(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/shops", headers=headers, params=params)

    def get_shop(self, shop_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    def update_shop(
        self, shop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PUT", f"/shops/{shop_id}", payload, headers)

    def approve_shop(self, shop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/shops/{shop_id}/approve", headers=headers)

    def suspend_shop(self, shop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/shops/{shop_id}/suspend", headers=headers)

    def reinstate_shop(self, shop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/shops/{shop_id}/reinstate", headers=headers)

    def close_shop(self, shop_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/shops/{shop_id}/close", headers=headers)

    # ------------------------------------------------------------------
    # Product Management (7)
    # ------------------------------------------------------------------

    def create_product(
        self, shop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shops/{shop_id}/products", payload, headers
        )

    def list_products(
        self, shop_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/shops/{shop_id}/products", headers=headers, params=params
        )

    def get_product(
        self, shop_id: str, product_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/shops/{shop_id}/products/{product_id}", headers=headers
        )

    def update_product(
        self,
        shop_id: str,
        product_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PUT", f"/shops/{shop_id}/products/{product_id}", payload, headers
        )

    def list_product(
        self, shop_id: str, product_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shops/{shop_id}/products/{product_id}/list", headers=headers
        )

    def delist_product(
        self, shop_id: str, product_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shops/{shop_id}/products/{product_id}/delist", headers=headers
        )

    def archive_product(
        self, shop_id: str, product_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shops/{shop_id}/products/{product_id}/archive", headers=headers
        )

    # ------------------------------------------------------------------
    # Promotion Management (6)
    # ------------------------------------------------------------------

    def create_promotion(
        self, shop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shops/{shop_id}/promotions", payload, headers
        )

    def list_promotions(
        self, shop_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/shops/{shop_id}/promotions", headers=headers, params=params
        )

    def get_promotion(
        self, shop_id: str, promotion_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"/shops/{shop_id}/promotions/{promotion_id}",
            headers=headers,
        )

    def activate_promotion(
        self, shop_id: str, promotion_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shops/{shop_id}/promotions/{promotion_id}/activate",
            headers=headers,
        )

    def pause_promotion(
        self, shop_id: str, promotion_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shops/{shop_id}/promotions/{promotion_id}/pause",
            headers=headers,
        )

    def cancel_promotion(
        self, shop_id: str, promotion_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shops/{shop_id}/promotions/{promotion_id}/cancel",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Order Lifecycle (11)
    # ------------------------------------------------------------------

    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def cancel_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/cancel", headers=headers
        )

    def pay_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/orders/{order_id}/pay", payload, headers
        )

    def confirm_payment(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/confirm-payment", headers=headers
        )

    def payment_failed(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/payment-failed", headers=headers
        )

    def start_processing(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/start-processing", headers=headers
        )

    def ship_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/ship", headers=headers
        )

    def deliver_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/deliver", headers=headers
        )

    # ------------------------------------------------------------------
    # Refund Management (6)
    # ------------------------------------------------------------------

    def create_refund(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/orders/{order_id}/refunds", payload, headers
        )

    def list_refunds(
        self, order_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/orders/{order_id}/refunds", headers=headers, params=params
        )

    def get_refund(
        self, order_id: str, refund_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"/orders/{order_id}/refunds/{refund_id}",
            headers=headers,
        )

    def approve_refund(
        self, order_id: str, refund_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/orders/{order_id}/refunds/{refund_id}/approve",
            headers=headers,
        )

    def reject_refund(
        self, order_id: str, refund_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/orders/{order_id}/refunds/{refund_id}/reject",
            headers=headers,
        )

    def process_refund(
        self, order_id: str, refund_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/orders/{order_id}/refunds/{refund_id}/process",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Settlement Management (8)
    # ------------------------------------------------------------------

    def create_settlement(
        self, shop_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/shops/{shop_id}/settlements", payload, headers
        )

    def list_settlements(
        self, shop_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/shops/{shop_id}/settlements", headers=headers, params=params
        )

    def get_settlement(
        self, shop_id: str, settlement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"/shops/{shop_id}/settlements/{settlement_id}",
            headers=headers,
        )

    def submit_settlement(
        self, shop_id: str, settlement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shops/{shop_id}/settlements/{settlement_id}/submit",
            headers=headers,
        )

    def approve_settlement(
        self, shop_id: str, settlement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shops/{shop_id}/settlements/{settlement_id}/approve",
            headers=headers,
        )

    def mark_settlement_paid(
        self, shop_id: str, settlement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shops/{shop_id}/settlements/{settlement_id}/mark-paid",
            headers=headers,
        )

    def dispute_settlement(
        self, shop_id: str, settlement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shops/{shop_id}/settlements/{settlement_id}/dispute",
            headers=headers,
        )

    def resolve_settlement_dispute(
        self, shop_id: str, settlement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/shops/{shop_id}/settlements/{settlement_id}/resolve-dispute",
            headers=headers,
        )


api_client = ApiClient()
