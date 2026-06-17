"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- container models ----
    def create_container_model(self, payload, headers):
        return self._request("POST", "/container-models", payload, headers)

    def get_container_model(self, model_id, headers):
        return self._request("GET", f"/container-models/{model_id}", headers=headers)

    def list_container_models(self, headers, params=None):
        return self._request("GET", "/container-models", headers=headers, params=params)

    # ---- protection plans ----
    def create_protection_plan(self, payload, headers):
        return self._request("POST", "/protection-plans", payload, headers)

    def get_protection_plan(self, plan_id, headers):
        return self._request("GET", f"/protection-plans/{plan_id}", headers=headers)

    def list_protection_plans(self, headers, params=None):
        return self._request("GET", "/protection-plans", headers=headers, params=params)

    # ---- depots ----
    def create_depot(self, payload, headers):
        return self._request("POST", "/depots", payload, headers)

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"/depots/{depot_id}", headers=headers)

    # ---- depot inventory ----
    def create_depot_inventory(self, payload, headers):
        return self._request("POST", "/depot-inventory", payload, headers)

    def get_depot_inventory(self, inv_id, headers):
        return self._request("GET", f"/depot-inventory/{inv_id}", headers=headers)

    def list_depot_inventory(self, headers, params=None):
        return self._request("GET", "/depot-inventory", headers=headers, params=params)

    # ---- crews ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/crews", headers=headers, params=params)

    # ---- trucks ----
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/trucks", headers=headers, params=params)

    # ---- customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_agreements(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/rental-agreements", headers=headers, params=params
        )

    # ---- rental agreements ----
    def create_rental_agreement(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def get_rental_agreement(self, agreement_id, headers):
        return self._request("GET", f"/rental-agreements/{agreement_id}", headers=headers)

    def list_rental_agreements(self, headers, params=None):
        return self._request("GET", "/rental-agreements", headers=headers, params=params)

    def reserve_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/rental-agreements/{agreement_id}/reserve", payload, headers
        )

    def hold_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/hold", headers=headers)

    def resume_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/resume", headers=headers)

    def request_closeout(self, agreement_id, headers):
        return self._request(
            "POST", f"/rental-agreements/{agreement_id}/request-closeout", headers=headers
        )

    def close_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/close", headers=headers)

    def cancel_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/cancel", headers=headers)

    def post_payment(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/rental-agreements/{agreement_id}/payments", payload, headers
        )

    def list_charges(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/rental-agreements/{agreement_id}/charges", headers=headers, params=params
        )

    def list_agreement_container_units(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/rental-agreements/{agreement_id}/container-units",
            headers=headers, params=params,
        )

    def list_agreement_delivery_jobs(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/rental-agreements/{agreement_id}/delivery-jobs",
            headers=headers, params=params,
        )

    def list_agreement_move_orders(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/rental-agreements/{agreement_id}/move-orders",
            headers=headers, params=params,
        )

    def list_agreement_access_visits(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/rental-agreements/{agreement_id}/access-visits",
            headers=headers, params=params,
        )

    def list_agreement_packing_supply_orders(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/rental-agreements/{agreement_id}/packing-supply-orders",
            headers=headers, params=params,
        )

    # ---- container units ----
    def get_container_unit(self, unit_id, headers):
        return self._request("GET", f"/container-units/{unit_id}", headers=headers)

    def list_container_units(self, headers, params=None):
        return self._request("GET", "/container-units", headers=headers, params=params)

    def return_to_depot(self, unit_id, headers):
        return self._request("POST", f"/container-units/{unit_id}/return-to-depot", headers=headers)

    # ---- delivery jobs ----
    def create_delivery_job(self, payload, headers):
        return self._request("POST", "/delivery-jobs", payload, headers)

    def get_delivery_job(self, job_id, headers):
        return self._request("GET", f"/delivery-jobs/{job_id}", headers=headers)

    def list_delivery_jobs(self, headers, params=None):
        return self._request("GET", "/delivery-jobs", headers=headers, params=params)

    def complete_delivery_job(self, job_id, headers):
        return self._request("POST", f"/delivery-jobs/{job_id}/complete", headers=headers)

    def cancel_delivery_job(self, job_id, headers):
        return self._request("POST", f"/delivery-jobs/{job_id}/cancel", headers=headers)

    # ---- move orders ----
    def create_move_order(self, payload, headers):
        return self._request("POST", "/move-orders", payload, headers)

    def get_move_order(self, move_id, headers):
        return self._request("GET", f"/move-orders/{move_id}", headers=headers)

    def list_move_orders(self, headers, params=None):
        return self._request("GET", "/move-orders", headers=headers, params=params)

    def dispatch_move_order(self, move_id, headers):
        return self._request("POST", f"/move-orders/{move_id}/dispatch", headers=headers)

    def complete_move_order(self, move_id, headers):
        return self._request("POST", f"/move-orders/{move_id}/complete", headers=headers)

    def cancel_move_order(self, move_id, headers):
        return self._request("POST", f"/move-orders/{move_id}/cancel", headers=headers)

    # ---- access visits ----
    def create_access_visit(self, payload, headers):
        return self._request("POST", "/access-visits", payload, headers)

    def get_access_visit(self, visit_id, headers):
        return self._request("GET", f"/access-visits/{visit_id}", headers=headers)

    def list_access_visits(self, headers, params=None):
        return self._request("GET", "/access-visits", headers=headers, params=params)

    def fulfill_access_visit(self, visit_id, headers):
        return self._request("POST", f"/access-visits/{visit_id}/fulfill", headers=headers)

    def cancel_access_visit(self, visit_id, headers):
        return self._request("POST", f"/access-visits/{visit_id}/cancel", headers=headers)

    # ---- packing supply orders ----
    def create_packing_supply_order(self, payload, headers):
        return self._request("POST", "/packing-supply-orders", payload, headers)

    def get_packing_supply_order(self, order_id, headers):
        return self._request("GET", f"/packing-supply-orders/{order_id}", headers=headers)

    # ---- billing sweeps + clock (operator/test-driving) ----
    def run_late_sweep(self, headers):
        return self._request("POST", "/_billing/run-late-sweep", {}, headers)

    def run_monthly_cycle(self, headers):
        return self._request("POST", "/_billing/run-monthly-cycle", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
