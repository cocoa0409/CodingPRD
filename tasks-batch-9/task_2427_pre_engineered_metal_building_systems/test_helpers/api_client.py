"""API client: one method per endpoint in the PRD endpoint table.

Every method returns the raw ``requests.Response`` so tests can assert status
codes and envelope contents through the framework validators.  Action endpoints
take an optional payload because several of them declare an empty input list.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ logical clock --
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ jurisdictions --
    def create_jurisdiction(self, payload: dict, headers: dict):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: dict):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}", headers=headers
        )

    def list_jurisdictions(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    def publish_loading_criteria(
        self, jurisdiction_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/jurisdictions/{jurisdiction_id}/loading-criteria",
            payload,
            headers,
        )

    # ----------------------------------------------------------------- builders --
    def create_builder(self, payload: dict, headers: dict):
        return self._request("POST", "/builders", payload, headers)

    def get_builder(self, builder_id: str, headers: dict):
        return self._request("GET", f"/builders/{builder_id}", headers=headers)

    def list_builders(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/builders", headers=headers, params=params)

    def authorize_builder(
        self, builder_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/builders/{builder_id}/authorize",
            payload if payload is not None else {},
            headers,
        )

    def suspend_builder(
        self, builder_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/builders/{builder_id}/suspend",
            payload if payload is not None else {},
            headers,
        )

    # --------------------------------------------------- building configurations --
    def create_configuration(self, payload: dict, headers: dict):
        return self._request("POST", "/building-configurations", payload, headers)

    def get_configuration(self, configuration_id: str, headers: dict):
        return self._request(
            "GET", f"/building-configurations/{configuration_id}", headers=headers
        )

    def list_configurations(self, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/building-configurations", headers=headers, params=params
        )

    def lock_configuration(
        self, configuration_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/building-configurations/{configuration_id}/lock",
            payload if payload is not None else {},
            headers,
        )

    def create_accessory_kit(self, configuration_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/building-configurations/{configuration_id}/accessory-kits",
            payload,
            headers,
        )

    def list_accessory_kits(
        self, configuration_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/building-configurations/{configuration_id}/accessory-kits",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------- quotes --
    def create_quote(self, payload: dict, headers: dict):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id: str, headers: dict):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def issue_quote(self, quote_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"/quotes/{quote_id}/issue",
            payload if payload is not None else {},
            headers,
        )

    def accept_quote(self, quote_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/quotes/{quote_id}/accept", payload, headers)

    # ------------------------------------------------------- engineering designs --
    def create_design(self, payload: dict, headers: dict):
        return self._request("POST", "/engineering-designs", payload, headers)

    def get_design(self, design_id: str, headers: dict):
        return self._request("GET", f"/engineering-designs/{design_id}", headers=headers)

    def list_designs(self, headers: dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/engineering-designs", headers=headers, params=params
        )

    def create_design_component(self, design_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/engineering-designs/{design_id}/components", payload, headers
        )

    def list_design_components(
        self, design_id: str, headers: dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/engineering-designs/{design_id}/components",
            headers=headers,
            params=params,
        )

    def submit_design(
        self, design_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/engineering-designs/{design_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_design(self, design_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/engineering-designs/{design_id}/review", payload, headers
        )

    def revise_design(
        self, design_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/engineering-designs/{design_id}/revise",
            payload if payload is not None else {},
            headers,
        )

    # ---------------------------------------------------------- drawing packages --
    def create_drawing_package(self, payload: dict, headers: dict):
        return self._request("POST", "/drawing-packages", payload, headers)

    def get_drawing_package(self, package_id: str, headers: dict):
        return self._request("GET", f"/drawing-packages/{package_id}", headers=headers)

    def list_drawing_packages(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/drawing-packages", headers=headers, params=params)

    def seal_drawing_package(
        self, package_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/drawing-packages/{package_id}/seal",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------- orders --
    def get_order(self, order_id: str, headers: dict):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def release_order_to_fabrication(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/orders/{order_id}/release-to-fabrication", payload, headers
        )

    def cancel_order_release(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/orders/{order_id}/cancel-release", payload, headers
        )

    def get_erection_sequence(self, order_id: str, headers: dict):
        return self._request(
            "GET", f"/orders/{order_id}/erection-sequence", headers=headers
        )

    # ---------------------------------------------------------- production lines --
    def create_production_line(self, payload: dict, headers: dict):
        return self._request("POST", "/production-lines", payload, headers)

    def get_production_line(self, line_id: str, headers: dict):
        return self._request("GET", f"/production-lines/{line_id}", headers=headers)

    # ----------------------------------------------------------- production lots --
    def create_production_lot(self, payload: dict, headers: dict):
        return self._request("POST", "/production-lots", payload, headers)

    def get_production_lot(self, lot_id: str, headers: dict):
        return self._request("GET", f"/production-lots/{lot_id}", headers=headers)

    def list_production_lots(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/production-lots", headers=headers, params=params)

    def complete_production_lot(
        self, lot_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/production-lots/{lot_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_production_lot(
        self, lot_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/production-lots/{lot_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------ shipment loads --
    def create_shipment_load(self, payload: dict, headers: dict):
        return self._request("POST", "/shipment-loads", payload, headers)

    def get_shipment_load(self, load_id: str, headers: dict):
        return self._request("GET", f"/shipment-loads/{load_id}", headers=headers)

    def list_shipment_loads(self, headers: dict, params: Optional[Dict] = None):
        return self._request("GET", "/shipment-loads", headers=headers, params=params)

    def dispatch_shipment_load(
        self, load_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/shipment-loads/{load_id}/dispatch",
            payload if payload is not None else {},
            headers,
        )

    def cancel_shipment_load(
        self, load_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"/shipment-loads/{load_id}/cancel",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
