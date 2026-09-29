"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Mill ────────────────────────────────────────────────────────────
    def create_mill(self, payload, headers):
        return self._request("POST", "/mills", payload, headers)

    def get_mill(self, mill_id, headers):
        return self._request("GET", f"/mills/{mill_id}", headers=headers)

    def patch_mill(self, mill_id, payload, headers):
        return self._request("PATCH", f"/mills/{mill_id}", payload, headers)

    # ─── MillContract ────────────────────────────────────────────────────
    def create_mill_contract(self, payload, headers):
        return self._request("POST", "/mill-contracts", payload, headers)

    def get_mill_contract(self, contract_id, headers):
        return self._request("GET", f"/mill-contracts/{contract_id}", headers=headers)

    def list_mill_contracts(self, headers, params=None):
        return self._request("GET", "/mill-contracts", headers=headers, params=params)

    def patch_mill_contract(self, contract_id, payload, headers):
        return self._request(
            "PATCH", f"/mill-contracts/{contract_id}", payload, headers
        )

    # ─── HaulContractor ──────────────────────────────────────────────────
    def create_haul_contractor(self, payload, headers):
        return self._request("POST", "/haul-contractors", payload, headers)

    def get_haul_contractor(self, contractor_id, headers):
        return self._request(
            "GET", f"/haul-contractors/{contractor_id}", headers=headers
        )

    def suspend_haul_contractor(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/haul-contractors/{contractor_id}/suspend", payload, headers
        )

    def reinstate_haul_contractor(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/haul-contractors/{contractor_id}/reinstate", payload, headers
        )

    # ─── InsuranceCertificate ────────────────────────────────────────────
    def create_insurance_certificate(self, contractor_id, payload, headers):
        return self._request(
            "POST",
            f"/haul-contractors/{contractor_id}/insurance-certificates",
            payload,
            headers,
        )

    def list_insurance_certificates(self, contractor_id, headers, params=None):
        return self._request(
            "GET",
            f"/haul-contractors/{contractor_id}/insurance-certificates",
            headers=headers,
            params=params,
        )

    def revoke_insurance_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/insurance-certificates/{certificate_id}/revoke", payload, headers
        )

    # ─── SafetyFinding ───────────────────────────────────────────────────
    def create_safety_finding(self, contractor_id, payload, headers):
        return self._request(
            "POST",
            f"/haul-contractors/{contractor_id}/safety-findings",
            payload,
            headers,
        )

    def list_safety_findings(self, contractor_id, headers, params=None):
        return self._request(
            "GET",
            f"/haul-contractors/{contractor_id}/safety-findings",
            headers=headers,
            params=params,
        )

    # ─── Truck ───────────────────────────────────────────────────────────
    def create_truck(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/haul-contractors/{contractor_id}/trucks", payload, headers
        )

    def list_trucks(self, contractor_id, headers, params=None):
        return self._request(
            "GET",
            f"/haul-contractors/{contractor_id}/trucks",
            headers=headers,
            params=params,
        )

    # ─── Tract ───────────────────────────────────────────────────────────
    def create_tract(self, payload, headers):
        return self._request("POST", "/tracts", payload, headers)

    def get_tract(self, tract_id, headers):
        return self._request("GET", f"/tracts/{tract_id}", headers=headers)

    def mobilize_tract(self, tract_id, headers):
        return self._request("POST", f"/tracts/{tract_id}/mobilize", {}, headers)

    def activate_tract(self, tract_id, headers):
        return self._request("POST", f"/tracts/{tract_id}/activate", {}, headers)

    def complete_tract(self, tract_id, headers):
        return self._request("POST", f"/tracts/{tract_id}/complete", {}, headers)

    # ─── ProductionPlan ──────────────────────────────────────────────────
    def create_production_plan(self, tract_id, payload, headers):
        return self._request(
            "POST", f"/tracts/{tract_id}/production-plans", payload, headers
        )

    def list_production_plans(self, tract_id, headers, params=None):
        return self._request(
            "GET",
            f"/tracts/{tract_id}/production-plans",
            headers=headers,
            params=params,
        )

    def approve_production_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/production-plans/{plan_id}/approve", {}, headers
        )

    # ─── Crew and CrewAssignment ─────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def create_crew_assignment(self, tract_id, payload, headers):
        return self._request(
            "POST", f"/tracts/{tract_id}/crew-assignments", payload, headers
        )

    def get_crew_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/crew-assignments/{assignment_id}", headers=headers
        )

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    # ─── ShutdownOrder ───────────────────────────────────────────────────
    def create_shutdown_order(self, tract_id, payload, headers):
        return self._request(
            "POST", f"/tracts/{tract_id}/shutdown-orders", payload, headers
        )

    def list_shutdown_orders(self, tract_id, headers, params=None):
        return self._request(
            "GET", f"/tracts/{tract_id}/shutdown-orders", headers=headers, params=params
        )

    def lift_shutdown_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/shutdown-orders/{order_id}/lift", payload, headers
        )

    # ─── HaulRoute ───────────────────────────────────────────────────────
    def create_haul_route(self, payload, headers):
        return self._request("POST", "/haul-routes", payload, headers)

    def get_haul_route(self, route_id, headers):
        return self._request("GET", f"/haul-routes/{route_id}", headers=headers)

    def list_haul_routes(self, headers, params=None):
        return self._request("GET", "/haul-routes", headers=headers, params=params)

    # ─── Load ────────────────────────────────────────────────────────────
    def create_load(self, payload, headers):
        return self._request("POST", "/loads", payload, headers)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/loads/{load_id}", headers=headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/loads", headers=headers, params=params)

    def depart_load(self, load_id, headers):
        return self._request("POST", f"/loads/{load_id}/depart", {}, headers)

    def arrive_load(self, load_id, headers):
        return self._request("POST", f"/loads/{load_id}/arrive", {}, headers)

    def cancel_load(self, load_id, payload, headers):
        return self._request("POST", f"/loads/{load_id}/cancel", payload, headers)

    # ─── DeliveryTicket ──────────────────────────────────────────────────
    def create_delivery_ticket(self, load_id, payload, headers):
        return self._request(
            "POST", f"/loads/{load_id}/delivery-tickets", payload, headers
        )

    def get_delivery_ticket(self, ticket_id, headers):
        return self._request("GET", f"/delivery-tickets/{ticket_id}", headers=headers)

    def list_delivery_tickets(self, headers, params=None):
        return self._request("GET", "/delivery-tickets", headers=headers, params=params)

    def certify_delivery_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/delivery-tickets/{ticket_id}/certify", {}, headers
        )

    def reject_delivery_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/delivery-tickets/{ticket_id}/reject", payload, headers
        )

    # ─── SettlementStatement ─────────────────────────────────────────────
    def create_settlement_statement(self, payload, headers):
        return self._request("POST", "/settlement-statements", payload, headers)

    def get_settlement_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/settlement-statements/{statement_id}", headers=headers
        )

    def list_settlement_statements(self, headers, params=None):
        return self._request(
            "GET", "/settlement-statements", headers=headers, params=params
        )

    def submit_settlement_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/submit", {}, headers
        )

    def approve_settlement_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/approve", {}, headers
        )

    def dispute_settlement_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/dispute", payload, headers
        )

    def revise_settlement_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/revise", payload, headers
        )

    def pay_settlement_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/settlement-statements/{statement_id}/pay", payload, headers
        )


api_client = ApiClient()
