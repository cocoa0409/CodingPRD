"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Service areas ────────────────────────────────
    def create_service_area(self, payload, headers):
        return self._request("POST", "/service-areas", payload, headers)

    def get_service_area(self, area_id, headers):
        return self._request("GET", f"/service-areas/{area_id}", headers=headers)

    def get_surveillance_report(self, area_id, headers, params=None):
        return self._request(
            "GET", f"/service-areas/{area_id}/surveillance-report",
            headers=headers, params=params,
        )

    # ─── Protected-site registry ──────────────────────
    def create_sensitive_site(self, area_id, payload, headers):
        return self._request(
            "POST", f"/service-areas/{area_id}/sensitive-sites", payload, headers
        )

    def list_sensitive_sites(self, area_id, headers, params=None):
        return self._request(
            "GET", f"/service-areas/{area_id}/sensitive-sites",
            headers=headers, params=params,
        )

    # ─── Trap sites ───────────────────────────────────
    def create_trap_site(self, area_id, payload, headers):
        return self._request(
            "POST", f"/service-areas/{area_id}/trap-sites", payload, headers
        )

    def list_trap_sites(self, area_id, headers, params=None):
        return self._request(
            "GET", f"/service-areas/{area_id}/trap-sites", headers=headers, params=params
        )

    def get_trap_site(self, trap_site_id, headers):
        return self._request("GET", f"/trap-sites/{trap_site_id}", headers=headers)

    # ─── Trap collections ─────────────────────────────
    def create_trap_collection(self, trap_site_id, payload, headers):
        return self._request(
            "POST", f"/trap-sites/{trap_site_id}/collections", payload, headers
        )

    def list_trap_collections(self, headers, params=None):
        return self._request("GET", "/trap-collections", headers=headers, params=params)

    def get_trap_collection(self, collection_id, headers):
        return self._request(
            "GET", f"/trap-collections/{collection_id}", headers=headers
        )

    def transition_trap_collection(self, collection_id, payload, headers):
        return self._request(
            "POST", f"/trap-collections/{collection_id}/transitions", payload, headers
        )

    # ─── Laboratory pools ─────────────────────────────
    def create_lab_pool(self, collection_id, payload, headers):
        return self._request(
            "POST", f"/trap-collections/{collection_id}/lab-pools", payload, headers
        )

    def list_lab_pools(self, headers, params=None):
        return self._request("GET", "/lab-pools", headers=headers, params=params)

    def get_lab_pool(self, lab_pool_id, headers):
        return self._request("GET", f"/lab-pools/{lab_pool_id}", headers=headers)

    def transition_lab_pool(self, lab_pool_id, payload, headers):
        return self._request(
            "POST", f"/lab-pools/{lab_pool_id}/transitions", payload, headers
        )

    # ─── Larval inspections ───────────────────────────
    def create_larval_inspection(self, area_id, payload, headers):
        return self._request(
            "POST", f"/service-areas/{area_id}/larval-inspections", payload, headers
        )

    def list_larval_inspections(self, area_id, headers, params=None):
        return self._request(
            "GET", f"/service-areas/{area_id}/larval-inspections",
            headers=headers, params=params,
        )

    # ─── Weather observations ─────────────────────────
    def create_weather_observation(self, area_id, payload, headers):
        return self._request(
            "POST", f"/service-areas/{area_id}/weather-observations", payload, headers
        )

    def list_weather_observations(self, area_id, headers, params=None):
        return self._request(
            "GET", f"/service-areas/{area_id}/weather-observations",
            headers=headers, params=params,
        )

    # ─── Risk assessments ─────────────────────────────
    def create_risk_assessment(self, area_id, payload, headers):
        return self._request(
            "POST", f"/service-areas/{area_id}/risk-assessments", payload, headers
        )

    def list_risk_assessments(self, area_id, headers, params=None):
        return self._request(
            "GET", f"/service-areas/{area_id}/risk-assessments",
            headers=headers, params=params,
        )

    def get_risk_assessment(self, assessment_id, headers):
        return self._request("GET", f"/risk-assessments/{assessment_id}", headers=headers)

    def confirm_risk_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/risk-assessments/{assessment_id}/confirm", {}, headers
        )

    # ─── Pesticide products ───────────────────────────
    def create_pesticide_product(self, payload, headers):
        return self._request("POST", "/pesticide-products", payload, headers)

    def get_pesticide_product(self, product_id, headers):
        return self._request("GET", f"/pesticide-products/{product_id}", headers=headers)

    def create_stock_adjustment(self, product_id, payload, headers):
        return self._request(
            "POST", f"/pesticide-products/{product_id}/adjustments", payload, headers
        )

    # ─── Applicators ──────────────────────────────────
    def create_applicator(self, payload, headers):
        return self._request("POST", "/applicators", payload, headers)

    def get_applicator(self, applicator_id, headers):
        return self._request("GET", f"/applicators/{applicator_id}", headers=headers)

    def set_applicator_status(self, applicator_id, payload, headers):
        return self._request(
            "POST", f"/applicators/{applicator_id}/status", payload, headers
        )

    # ─── Treatment plans ──────────────────────────────
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def transition_treatment_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/treatment-plans/{plan_id}/transitions", payload, headers
        )

    # ─── Treatment routes ─────────────────────────────
    def create_treatment_route(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/treatment-plans/{plan_id}/routes", payload, headers
        )

    def list_treatment_routes(self, headers, params=None):
        return self._request("GET", "/treatment-routes", headers=headers, params=params)

    def get_treatment_route(self, route_id, headers):
        return self._request("GET", f"/treatment-routes/{route_id}", headers=headers)

    def transition_treatment_route(self, route_id, payload, headers):
        return self._request(
            "POST", f"/treatment-routes/{route_id}/transitions", payload, headers
        )

    # ─── Spray notices ────────────────────────────────
    def create_notification(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/treatment-plans/{plan_id}/notifications", payload, headers
        )

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/notifications", headers=headers, params=params)

    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/notifications/{notification_id}", headers=headers)

    def transition_notification(self, notification_id, payload, headers):
        return self._request(
            "POST", f"/notifications/{notification_id}/transitions", payload, headers
        )

    # ─── Public complaints ────────────────────────────
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def get_service_request(self, request_id, headers):
        return self._request("GET", f"/service-requests/{request_id}", headers=headers)

    def transition_service_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{request_id}/transitions", payload, headers
        )


api_client = ApiClient()
