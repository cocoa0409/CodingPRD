"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the wire-and-cable manufacturing API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_current_utc_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # MetalPriceQuote
    # ------------------------------------------------------------------
    def create_metal_price_quote(self, payload, headers):
        return self._request("POST", "/metal-price-quotes", payload, headers)

    def list_metal_price_quotes(self, headers, params=None):
        return self._request("GET", "/metal-price-quotes", payload=params, headers=headers)

    # ------------------------------------------------------------------
    # RodPurchaseLot
    # ------------------------------------------------------------------
    def create_rod_purchase_lot(self, payload, headers):
        return self._request("POST", "/rod-purchase-lots", payload, headers)

    def get_rod_purchase_lot(self, rod_lot_id, headers):
        return self._request("GET", f"/rod-purchase-lots/{rod_lot_id}", headers=headers)

    def list_rod_purchase_lots(self, headers, params=None):
        return self._request("GET", "/rod-purchase-lots", payload=params, headers=headers)

    # ------------------------------------------------------------------
    # Compound
    # ------------------------------------------------------------------
    def create_compound(self, payload, headers):
        return self._request("POST", "/compounds", payload, headers)

    def get_compound(self, compound_id, headers):
        return self._request("GET", f"/compounds/{compound_id}", headers=headers)

    def qualify_compound(self, compound_id, headers, payload=None):
        return self._request(
            "POST", f"/compounds/{compound_id}/qualify", payload or {}, headers
        )

    def suspend_compound(self, compound_id, headers, payload=None):
        return self._request(
            "POST", f"/compounds/{compound_id}/suspend", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # ListingCertification / FactoryInspection
    # ------------------------------------------------------------------
    def create_listing_certification(self, payload, headers):
        return self._request("POST", "/listing-certifications", payload, headers)

    def get_listing_certification(self, certification_id, headers):
        return self._request(
            "GET", f"/listing-certifications/{certification_id}", headers=headers
        )

    def create_factory_inspection(self, certification_id, payload, headers):
        return self._request(
            "POST",
            f"/listing-certifications/{certification_id}/inspections",
            payload,
            headers,
        )

    def list_factory_inspections(self, certification_id, headers, params=None):
        return self._request(
            "GET",
            f"/listing-certifications/{certification_id}/inspections",
            payload=params,
            headers=headers,
        )

    def reinstate_listing_certification(self, certification_id, headers, payload=None):
        return self._request(
            "POST",
            f"/listing-certifications/{certification_id}/reinstate",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # CatalogProduct
    # ------------------------------------------------------------------
    def create_catalog_product(self, payload, headers):
        return self._request("POST", "/catalog-products", payload, headers)

    def get_catalog_product(self, product_id, headers):
        return self._request("GET", f"/catalog-products/{product_id}", headers=headers)

    def list_catalog_products(self, headers, params=None):
        return self._request("GET", "/catalog-products", payload=params, headers=headers)

    def release_catalog_product(self, product_id, headers, payload=None):
        return self._request(
            "POST", f"/catalog-products/{product_id}/release", payload or {}, headers
        )

    def reposition_inventory(self, payload, headers):
        return self._request("POST", "/inventory/reposition", payload, headers)

    # ------------------------------------------------------------------
    # Customer
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/customers/{customer_id}", payload, headers)

    # ------------------------------------------------------------------
    # CustomerOrder
    # ------------------------------------------------------------------
    def create_customer_order(self, payload, headers):
        return self._request("POST", "/customer-orders", payload, headers)

    def get_customer_order(self, order_id, headers):
        return self._request("GET", f"/customer-orders/{order_id}", headers=headers)

    def list_customer_orders(self, headers, params=None):
        return self._request("GET", "/customer-orders", payload=params, headers=headers)

    def price_lock_customer_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/customer-orders/{order_id}/price-lock", payload or {}, headers
        )

    def cancel_customer_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/customer-orders/{order_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # ProductionLot / CableTest
    # ------------------------------------------------------------------
    def create_production_lot(self, payload, headers):
        return self._request("POST", "/production-lots", payload, headers)

    def get_production_lot(self, lot_id, headers):
        return self._request("GET", f"/production-lots/{lot_id}", headers=headers)

    def list_production_lots(self, headers, params=None):
        return self._request("GET", "/production-lots", payload=params, headers=headers)

    def create_process_step(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/production-lots/{lot_id}/process-steps", payload, headers
        )

    def create_cable_test(self, lot_id, payload, headers):
        return self._request("POST", f"/production-lots/{lot_id}/tests", payload, headers)

    def list_cable_tests(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/production-lots/{lot_id}/tests", payload=params, headers=headers
        )

    def disposition_production_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/production-lots/{lot_id}/disposition", payload, headers
        )

    def release_production_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/production-lots/{lot_id}/release", payload, headers
        )

    # ------------------------------------------------------------------
    # Reel
    # ------------------------------------------------------------------
    def create_reel(self, payload, headers):
        return self._request("POST", "/reels", payload, headers)

    def get_reel(self, reel_id, headers):
        return self._request("GET", f"/reels/{reel_id}", headers=headers)

    def list_reels(self, headers, params=None):
        return self._request("GET", "/reels", payload=params, headers=headers)

    def load_reel(self, reel_id, payload, headers):
        return self._request("POST", f"/reels/{reel_id}/load", payload, headers)

    # ------------------------------------------------------------------
    # Shipment
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", payload=params, headers=headers)

    def invoice_shipment(self, shipment_id, headers, payload=None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/invoice", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # ReelReturn
    # ------------------------------------------------------------------
    def create_reel_return(self, reel_id, payload, headers):
        return self._request("POST", f"/reels/{reel_id}/returns", payload, headers)

    def list_reel_returns(self, reel_id, headers, params=None):
        return self._request(
            "GET", f"/reels/{reel_id}/returns", payload=params, headers=headers
        )

    def list_shipment_reel_returns(self, shipment_id, headers, params=None):
        return self._request(
            "GET",
            f"/shipments/{shipment_id}/reel-returns",
            payload=params,
            headers=headers,
        )


api_client = ApiClient()
