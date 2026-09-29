"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Small Engine & Outdoor Power Equipment Plant API."""

    # -- Logical plant clock -------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- Certification families ---------------------------------------------

    def create_certification_family(self, payload, headers):
        return self._request("POST", "/certification-families", payload, headers)

    def get_certification_family(self, family_id, headers):
        return self._request(
            "GET", f"/certification-families/{family_id}", headers=headers
        )

    def list_family_engine_platforms(self, family_id, headers, params=None):
        return self._request(
            "GET",
            f"/certification-families/{family_id}/engine-platforms",
            headers=headers,
            params=params,
        )

    def submit_certification_family(self, family_id, headers, payload=None):
        return self._request(
            "POST",
            f"/certification-families/{family_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def certify_certification_family(self, family_id, headers, payload=None):
        return self._request(
            "POST",
            f"/certification-families/{family_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    # -- Engine platforms ---------------------------------------------------

    def create_engine_platform(self, payload, headers):
        return self._request("POST", "/engine-platforms", payload, headers)

    def get_engine_platform(self, platform_id, headers):
        return self._request("GET", f"/engine-platforms/{platform_id}", headers=headers)

    def list_platform_product_models(self, platform_id, headers, params=None):
        return self._request(
            "GET",
            f"/engine-platforms/{platform_id}/product-models",
            headers=headers,
            params=params,
        )

    # -- Durability test runs -----------------------------------------------

    def create_durability_test(self, payload, headers):
        return self._request("POST", "/durability-tests", payload, headers)

    def get_durability_test(self, run_id, headers):
        return self._request("GET", f"/durability-tests/{run_id}", headers=headers)

    def list_durability_tests(self, headers, params=None):
        return self._request("GET", "/durability-tests", headers=headers, params=params)

    def complete_durability_test(self, run_id, payload, headers):
        return self._request(
            "POST", f"/durability-tests/{run_id}/complete", payload, headers
        )

    # -- Product models and safety certifications ---------------------------

    def create_product_model(self, payload, headers):
        return self._request("POST", "/product-models", payload, headers)

    def get_product_model(self, model_id, headers):
        return self._request("GET", f"/product-models/{model_id}", headers=headers)

    def list_model_safety_certifications(self, model_id, headers, params=None):
        return self._request(
            "GET",
            f"/product-models/{model_id}/safety-certifications",
            headers=headers,
            params=params,
        )

    def create_safety_certification(self, payload, headers):
        return self._request("POST", "/safety-certifications", payload, headers)

    def release_product_model(self, model_id, headers, payload=None):
        return self._request(
            "POST",
            f"/product-models/{model_id}/release",
            payload if payload is not None else {},
            headers,
        )

    # -- Suppliers and component lots ---------------------------------------

    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier_scorecard(self, supplier_id, headers):
        return self._request(
            "GET", f"/suppliers/{supplier_id}/scorecard", headers=headers
        )

    def create_component_lot(self, payload, headers):
        return self._request("POST", "/component-lots", payload, headers)

    def get_component_lot(self, lot_id, headers):
        return self._request("GET", f"/component-lots/{lot_id}", headers=headers)

    def list_component_lots(self, headers, params=None):
        return self._request("GET", "/component-lots", headers=headers, params=params)

    def inspect_component_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/component-lots/{lot_id}/inspect", payload, headers
        )

    def deviation_accept_component_lot(self, lot_id, headers, payload=None):
        return self._request(
            "POST",
            f"/component-lots/{lot_id}/deviation-accept",
            payload if payload is not None else {},
            headers,
        )

    # -- Machining runs -----------------------------------------------------

    def create_machining_run(self, payload, headers):
        return self._request("POST", "/machining-runs", payload, headers)

    def get_machining_run(self, run_id, headers):
        return self._request("GET", f"/machining-runs/{run_id}", headers=headers)

    def list_machining_runs(self, headers, params=None):
        return self._request("GET", "/machining-runs", headers=headers, params=params)

    def close_machining_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/machining-runs/{run_id}/close", payload, headers
        )

    # -- Assembly lines -----------------------------------------------------

    def create_assembly_line(self, payload, headers):
        return self._request("POST", "/assembly-lines", payload, headers)

    # -- Build orders -------------------------------------------------------

    def create_build_order(self, payload, headers):
        return self._request("POST", "/build-orders", payload, headers)

    def get_build_order(self, order_id, headers):
        return self._request("GET", f"/build-orders/{order_id}", headers=headers)

    def list_build_orders(self, headers, params=None):
        return self._request("GET", "/build-orders", headers=headers, params=params)

    def release_build_order(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/build-orders/{order_id}/release",
            payload if payload is not None else {},
            headers,
        )

    def run_build_order_allocations(self, order_id, payload, headers):
        return self._request(
            "POST", f"/build-orders/{order_id}/allocations/run", payload, headers
        )

    def reset_build_order_allocations(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/build-orders/{order_id}/allocations/reset",
            payload if payload is not None else {},
            headers,
        )

    # -- Production line audits --------------------------------------------

    def create_line_audit(self, order_id, payload, headers):
        return self._request(
            "POST", f"/build-orders/{order_id}/line-audits", payload, headers
        )

    def list_line_audits(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"/build-orders/{order_id}/line-audits",
            headers=headers,
            params=params,
        )

    def record_line_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/line-audits/{audit_id}/record", payload, headers
        )

    # -- Engine units -------------------------------------------------------

    def create_engine_unit(self, payload, headers):
        return self._request("POST", "/engine-units", payload, headers)

    def get_engine_unit(self, unit_id, headers):
        return self._request("GET", f"/engine-units/{unit_id}", headers=headers)

    def list_engine_units(self, headers, params=None):
        return self._request("GET", "/engine-units", headers=headers, params=params)

    def torque_record_engine_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/engine-units/{unit_id}/torque-record", payload, headers
        )

    def hot_test_engine_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/engine-units/{unit_id}/hot-test", payload, headers
        )

    def release_engine_unit(self, unit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/engine-units/{unit_id}/release",
            payload if payload is not None else {},
            headers,
        )

    def rework_engine_unit(self, unit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/engine-units/{unit_id}/rework",
            payload if payload is not None else {},
            headers,
        )

    def cancel_engine_unit(self, unit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/engine-units/{unit_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # -- Service parts and fulfillment requests ----------------------------

    def create_service_part(self, payload, headers):
        return self._request("POST", "/service-parts", payload, headers)

    def get_service_part(self, part_id, headers):
        return self._request("GET", f"/service-parts/{part_id}", headers=headers)

    def list_service_parts(self, headers, params=None):
        return self._request("GET", "/service-parts", headers=headers, params=params)

    def supersede_service_part(self, part_id, payload, headers):
        return self._request(
            "POST", f"/service-parts/{part_id}/supersede", payload, headers
        )

    def obsolete_service_part(self, part_id, headers, payload=None):
        return self._request(
            "POST",
            f"/service-parts/{part_id}/obsolete",
            payload if payload is not None else {},
            headers,
        )

    def list_service_part_requests(self, part_id, headers, params=None):
        return self._request(
            "GET", f"/service-parts/{part_id}/requests", headers=headers, params=params
        )

    def create_parts_request(self, payload, headers):
        return self._request("POST", "/parts-requests", payload, headers)

    # -- Raw helpers used by header/authentication tests -------------------

    def raw_post(self, path: str, payload: Optional[dict], headers: Optional[dict]):
        return self._request("POST", path, payload, headers)

    def raw_get(
        self, path: str, headers: Optional[dict], params: Optional[dict] = None
    ):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
