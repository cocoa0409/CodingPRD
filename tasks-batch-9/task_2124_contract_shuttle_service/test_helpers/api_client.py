"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical service clock ────────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Service contracts ────────────────────────────────────────────────────

    def create_contract(self, payload, headers):
        return self._request("POST", "/service-contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/service-contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/service-contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/service-contracts/{contract_id}/activate", {}, headers
        )

    def terminate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/service-contracts/{contract_id}/terminate", payload, headers
        )

    # ─── Routes ───────────────────────────────────────────────────────────────

    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def publish_route(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/publish", payload, headers)

    def republish_route(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/republish", payload, headers)

    # ─── Vehicles ─────────────────────────────────────────────────────────────

    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def brand_vehicle(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/brand", payload, headers)

    def list_vehicle_maintenance_orders(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/maintenance-orders",
            headers=headers, params=params,
        )

    # ─── Drivers ──────────────────────────────────────────────────────────────

    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    # ─── Trips ────────────────────────────────────────────────────────────────

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trips", headers=headers, params=params)

    def list_trip_ridership_counts(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"/trips/{trip_id}/ridership-counts", headers=headers, params=params
        )

    def assign_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/assign", payload, headers)

    def unassign_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/unassign", {}, headers)

    def start_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/start", payload, headers)

    def complete_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/complete", payload, headers)

    def mark_trip_missed(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/mark-missed", payload, headers)

    # ─── Ridership counts ─────────────────────────────────────────────────────

    def create_ridership_count(self, payload, headers):
        return self._request("POST", "/ridership-counts", payload, headers)

    # ─── On-demand requests ───────────────────────────────────────────────────

    def create_on_demand_request(self, payload, headers):
        return self._request("POST", "/on-demand-requests", payload, headers)

    def get_on_demand_request(self, request_id, headers):
        return self._request("GET", f"/on-demand-requests/{request_id}", headers=headers)

    def list_on_demand_requests(self, headers, params=None):
        return self._request("GET", "/on-demand-requests", headers=headers, params=params)

    def match_on_demand_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/on-demand-requests/{request_id}/match", payload, headers
        )

    def serve_on_demand_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/on-demand-requests/{request_id}/serve", payload, headers
        )

    # ─── Maintenance orders ───────────────────────────────────────────────────

    def create_maintenance_order(self, payload, headers):
        return self._request("POST", "/maintenance-orders", payload, headers)

    def close_maintenance_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-orders/{order_id}/close", payload, headers
        )

    # ─── Service period reports ───────────────────────────────────────────────

    def create_report(self, payload, headers):
        return self._request("POST", "/service-period-reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/service-period-reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/service-period-reports", headers=headers, params=params)

    def submit_report(self, report_id, headers):
        return self._request(
            "POST", f"/service-period-reports/{report_id}/submit", {}, headers
        )

    def approve_report(self, report_id, headers):
        return self._request(
            "POST", f"/service-period-reports/{report_id}/approve", {}, headers
        )

    def dispute_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/service-period-reports/{report_id}/dispute", payload, headers
        )

    # ─── Credit memos ─────────────────────────────────────────────────────────

    def create_credit_memo(self, payload, headers):
        return self._request("POST", "/credit-memos", payload, headers)

    def get_credit_memo(self, memo_id, headers):
        return self._request("GET", f"/credit-memos/{memo_id}", headers=headers)

    def list_credit_memos(self, headers, params=None):
        return self._request("GET", "/credit-memos", headers=headers, params=params)

    def void_credit_memo(self, memo_id, payload, headers):
        return self._request("POST", f"/credit-memos/{memo_id}/void", payload, headers)

    # ─── Renewal offers ───────────────────────────────────────────────────────

    def create_renewal_offer(self, payload, headers):
        return self._request("POST", "/renewal-offers", payload, headers)

    def get_renewal_offer(self, offer_id, headers):
        return self._request("GET", f"/renewal-offers/{offer_id}", headers=headers)

    def list_renewal_offers(self, headers, params=None):
        return self._request("GET", "/renewal-offers", headers=headers, params=params)

    def counter_renewal_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/renewal-offers/{offer_id}/counter", payload, headers
        )

    def respond_renewal_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/renewal-offers/{offer_id}/respond", payload, headers
        )


api_client = ApiClient()
