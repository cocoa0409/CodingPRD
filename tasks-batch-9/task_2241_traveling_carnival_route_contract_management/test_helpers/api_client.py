"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to the Traveling Carnival Route Ops HTTP surface."""

    # ─── Jurisdictions ────────────────────────────────────────────────────────

    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # ─── Lots (venues) ────────────────────────────────────────────────────────

    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    # ─── Ride inventory ───────────────────────────────────────────────────────

    def create_ride(self, payload, headers):
        return self._request("POST", "/rides", payload, headers)

    def get_ride(self, ride_id, headers):
        return self._request("GET", f"/rides/{ride_id}", headers=headers)

    # ─── Workers ──────────────────────────────────────────────────────────────

    def create_worker(self, payload, headers):
        return self._request("POST", "/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/workers/{worker_id}", headers=headers)

    # ─── Routes ───────────────────────────────────────────────────────────────

    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def sequence_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"/routes/{route_id}/sequence", payload or {}, headers
        )

    def commit_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"/routes/{route_id}/commit", payload or {}, headers
        )

    # ─── Route stops (lots) ───────────────────────────────────────────────────

    def create_route_stop(self, payload, headers):
        return self._request("POST", "/route-stops", payload, headers)

    def get_route_stop(self, route_stop_id, headers):
        return self._request("GET", f"/route-stops/{route_stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    def begin_setup(self, route_stop_id, headers, payload=None):
        return self._request(
            "POST", f"/route-stops/{route_stop_id}/begin-setup", payload or {}, headers
        )

    def open_gates(self, route_stop_id, headers, payload=None):
        return self._request(
            "POST", f"/route-stops/{route_stop_id}/open-gates", payload or {}, headers
        )

    def teardown_route_stop(self, route_stop_id, headers, payload=None):
        return self._request(
            "POST", f"/route-stops/{route_stop_id}/teardown", payload or {}, headers
        )

    def cancel_route_stop(self, route_stop_id, headers, payload=None):
        return self._request(
            "POST", f"/route-stops/{route_stop_id}/cancel", payload or {}, headers
        )

    def get_readiness(self, route_stop_id, headers):
        return self._request(
            "GET", f"/route-stops/{route_stop_id}/readiness", headers=headers
        )

    # ─── Contracts ────────────────────────────────────────────────────────────

    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def send_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/send", payload or {}, headers
        )

    def counter_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/counter", payload, headers
        )

    def execute_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/contracts/{contract_id}/execute", payload or {}, headers
        )

    # ─── Ride allocations ─────────────────────────────────────────────────────

    def create_ride_allocation(self, payload, headers):
        return self._request("POST", "/ride-allocations", payload, headers)

    def get_ride_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/ride-allocations/{allocation_id}", headers=headers
        )

    def list_ride_allocations(self, headers, params=None):
        return self._request("GET", "/ride-allocations", headers=headers, params=params)

    def commit_ride_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/ride-allocations/{allocation_id}/commit", payload or {}, headers
        )

    def release_ride_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/ride-allocations/{allocation_id}/release", payload or {}, headers
        )

    # ─── Permit applications ──────────────────────────────────────────────────

    def create_permit_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers)

    def list_route_stop_permit_applications(self, route_stop_id, headers, params=None):
        return self._request(
            "GET",
            f"/route-stops/{route_stop_id}/permit-applications",
            headers=headers,
            params=params,
        )

    def submit_permit_application(self, permit_id, headers, payload=None):
        return self._request(
            "POST", f"/permit-applications/{permit_id}/submit", payload or {}, headers
        )

    def decide_permit_application(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permit-applications/{permit_id}/decision", payload, headers
        )

    # ─── Inspection orders ────────────────────────────────────────────────────

    def create_inspection_order(self, payload, headers):
        return self._request("POST", "/inspection-orders", payload, headers)

    def list_allocation_inspections(self, allocation_id, headers, params=None):
        return self._request(
            "GET",
            f"/ride-allocations/{allocation_id}/inspections",
            headers=headers,
            params=params,
        )

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspection-orders/{inspection_id}/result", payload, headers
        )

    # ─── Crew assignments ─────────────────────────────────────────────────────

    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/crew-assignments", payload, headers)

    def list_route_stop_crew_assignments(self, route_stop_id, headers, params=None):
        return self._request(
            "GET",
            f"/route-stops/{route_stop_id}/crew-assignments",
            headers=headers,
            params=params,
        )

    def list_worker_crew_assignments(self, worker_id, headers, params=None):
        return self._request(
            "GET",
            f"/workers/{worker_id}/crew-assignments",
            headers=headers,
            params=params,
        )

    def cancel_crew_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/cancel", payload or {}, headers
        )

    # ─── Ticket sales ─────────────────────────────────────────────────────────

    def create_ticket_sale(self, route_stop_id, payload, headers):
        return self._request(
            "POST", f"/route-stops/{route_stop_id}/ticket-sales", payload, headers
        )

    def list_route_stop_ticket_sales(self, route_stop_id, headers, params=None):
        return self._request(
            "GET",
            f"/route-stops/{route_stop_id}/ticket-sales",
            headers=headers,
            params=params,
        )

    # ─── Settlements ──────────────────────────────────────────────────────────

    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_contract_settlements(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/contracts/{contract_id}/settlements",
            headers=headers,
            params=params,
        )

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/dispute", payload, headers
        )

    def reconcile_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/reconcile", payload or {}, headers
        )

    def finalize_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/finalize", payload or {}, headers
        )

    # ─── Weather closures ─────────────────────────────────────────────────────

    def create_weather_closure(self, route_stop_id, payload, headers):
        return self._request(
            "POST", f"/route-stops/{route_stop_id}/weather-closures", payload, headers
        )

    def list_route_stop_weather_closures(self, route_stop_id, headers, params=None):
        return self._request(
            "GET",
            f"/route-stops/{route_stop_id}/weather-closures",
            headers=headers,
            params=params,
        )

    def get_weather_closure(self, closure_id, headers):
        return self._request(
            "GET", f"/weather-closures/{closure_id}", headers=headers
        )

    def adjudicate_weather_closure(self, closure_id, headers, payload=None):
        return self._request(
            "POST",
            f"/weather-closures/{closure_id}/adjudicate",
            payload or {},
            headers,
        )

    # ─── Make-good arrangements ───────────────────────────────────────────────

    def create_make_good(self, payload, headers):
        return self._request("POST", "/make-goods", payload, headers)

    def list_contract_make_goods(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/make-goods", headers=headers, params=params
        )

    def list_closure_make_goods(self, closure_id, headers, params=None):
        return self._request(
            "GET",
            f"/weather-closures/{closure_id}/make-goods",
            headers=headers,
            params=params,
        )

    def respond_make_good(self, make_good_id, payload, headers):
        return self._request(
            "POST", f"/make-goods/{make_good_id}/respond", payload, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
