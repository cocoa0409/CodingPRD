"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_logical_clock(self, payload, headers):
        return self._request("POST", "/pop/_clock/set_current_utc", payload, headers)

    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/pop/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/pop/clients/{client_id}", headers=headers)

    def list_client_programs(self, client_id, headers, params=None):
        return self._request("GET", f"/pop/clients/{client_id}/programs",
                             headers=headers, params=params)

    # --- RetailerProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/pop/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/pop/programs/{program_id}", headers=headers)

    def start_design(self, program_id, headers):
        return self._request("POST", f"/pop/programs/{program_id}/start-design",
                             headers=headers)

    def authorize_production(self, program_id, headers):
        return self._request("POST", f"/pop/programs/{program_id}/authorize-production",
                             headers=headers)

    def start_fulfillment(self, program_id, headers):
        return self._request("POST", f"/pop/programs/{program_id}/start-fulfillment",
                             headers=headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/pop/programs/{program_id}/close", headers=headers)

    def cancel_program(self, program_id, headers):
        return self._request("POST", f"/pop/programs/{program_id}/cancel", headers=headers)

    def get_program_recap(self, program_id, headers, params=None):
        return self._request("GET", f"/pop/programs/{program_id}/recap",
                             headers=headers, params=params)

    # --- ComplianceRule ---
    def create_compliance_rule(self, program_id, payload, headers):
        return self._request("POST", f"/pop/programs/{program_id}/compliance-rules",
                             payload, headers)

    def list_compliance_rules(self, program_id, headers, params=None):
        return self._request("GET", f"/pop/programs/{program_id}/compliance-rules",
                             headers=headers, params=params)

    # --- DisplayDesign ---
    def create_design(self, payload, headers):
        return self._request("POST", "/pop/designs", payload, headers)

    def get_design(self, design_id, headers):
        return self._request("GET", f"/pop/designs/{design_id}", headers=headers)

    def list_program_designs(self, program_id, headers, params=None):
        return self._request("GET", f"/pop/programs/{program_id}/designs",
                             headers=headers, params=params)

    def submit_design(self, design_id, headers):
        return self._request("POST", f"/pop/designs/{design_id}/submit", headers=headers)

    def begin_review(self, design_id, headers):
        return self._request("POST", f"/pop/designs/{design_id}/begin-review",
                             headers=headers)

    def approve_design(self, design_id, payload, headers):
        return self._request("POST", f"/pop/designs/{design_id}/approve",
                             payload, headers)

    def reject_design(self, design_id, headers):
        return self._request("POST", f"/pop/designs/{design_id}/reject", headers=headers)

    def revise_design(self, design_id, headers):
        return self._request("POST", f"/pop/designs/{design_id}/revise", headers=headers)

    def lock_design(self, design_id, headers):
        return self._request("POST", f"/pop/designs/{design_id}/lock", headers=headers)

    # --- ProductionRun ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/pop/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/pop/production-runs/{run_id}", headers=headers)

    def list_program_production_runs(self, program_id, headers, params=None):
        return self._request("GET", f"/pop/programs/{program_id}/production-runs",
                             headers=headers, params=params)

    def list_design_production_runs(self, design_id, headers, params=None):
        return self._request("GET", f"/pop/designs/{design_id}/production-runs",
                             headers=headers, params=params)

    def authorize_run(self, run_id, headers):
        return self._request("POST", f"/pop/production-runs/{run_id}/authorize",
                             headers=headers)

    def mark_produced(self, run_id, headers):
        return self._request("POST", f"/pop/production-runs/{run_id}/mark-produced",
                             headers=headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/pop/production-runs/{run_id}/cancel",
                             headers=headers)

    # --- Store ---
    def create_store(self, payload, headers):
        return self._request("POST", "/pop/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/pop/stores/{store_id}", headers=headers)

    def list_program_stores(self, program_id, headers, params=None):
        return self._request("GET", f"/pop/programs/{program_id}/stores",
                             headers=headers, params=params)

    # --- Kit ---
    def create_kit(self, payload, headers):
        return self._request("POST", "/pop/kits", payload, headers)

    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/pop/kits/{kit_id}", headers=headers)

    def list_run_kits(self, run_id, headers, params=None):
        return self._request("GET", f"/pop/production-runs/{run_id}/kits",
                             headers=headers, params=params)

    def list_store_kits(self, store_id, headers, params=None):
        return self._request("GET", f"/pop/stores/{store_id}/kits",
                             headers=headers, params=params)

    def mark_kitted(self, kit_id, headers):
        return self._request("POST", f"/pop/kits/{kit_id}/mark-kitted", headers=headers)

    # --- Shipment ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/pop/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/pop/shipments/{shipment_id}", headers=headers)

    def list_kit_shipments(self, kit_id, headers, params=None):
        return self._request("GET", f"/pop/kits/{kit_id}/shipments",
                             headers=headers, params=params)

    def set_appointment(self, shipment_id, payload, headers):
        return self._request("POST", f"/pop/shipments/{shipment_id}/set-appointment",
                             payload, headers)

    def ship_shipment(self, shipment_id, headers):
        return self._request("POST", f"/pop/shipments/{shipment_id}/ship", headers=headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/pop/shipments/{shipment_id}/deliver",
                             headers=headers)

    def fail_shipment(self, shipment_id, headers):
        return self._request("POST", f"/pop/shipments/{shipment_id}/fail", headers=headers)

    # --- DamageClaim ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/pop/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/pop/damage-claims/{claim_id}", headers=headers)

    def list_kit_damage_claims(self, kit_id, headers, params=None):
        return self._request("GET", f"/pop/kits/{kit_id}/damage-claims",
                             headers=headers, params=params)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/pop/damage-claims/{claim_id}/approve",
                             headers=headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/pop/damage-claims/{claim_id}/reject",
                             headers=headers)

    def fulfill_claim(self, claim_id, headers):
        return self._request("POST", f"/pop/damage-claims/{claim_id}/fulfill",
                             headers=headers)

    # --- FieldServiceRequest ---
    def create_field_service_request(self, payload, headers):
        return self._request("POST", "/pop/field-service-requests", payload, headers)

    def get_field_service_request(self, fsr_id, headers):
        return self._request("GET", f"/pop/field-service-requests/{fsr_id}",
                             headers=headers)

    def list_store_field_service_requests(self, store_id, headers, params=None):
        return self._request("GET", f"/pop/stores/{store_id}/field-service-requests",
                             headers=headers, params=params)

    def list_program_field_service_requests(self, program_id, headers, params=None):
        return self._request("GET", f"/pop/programs/{program_id}/field-service-requests",
                             headers=headers, params=params)

    def dispatch_field_service_request(self, fsr_id, headers):
        return self._request("POST", f"/pop/field-service-requests/{fsr_id}/dispatch",
                             headers=headers)

    def resolve_field_service_request(self, fsr_id, headers):
        return self._request("POST", f"/pop/field-service-requests/{fsr_id}/resolve",
                             headers=headers)


api_client = ApiClient()
