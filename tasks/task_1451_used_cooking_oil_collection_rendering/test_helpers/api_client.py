"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/suspend", payload, headers
        )

    def reinstate_customer(self, customer_id, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/reinstate", {}, headers
        )

    def terminate_customer(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/terminate", payload, headers
        )

    # --- contracts ---
    def create_contract(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/contracts", payload, headers
        )

    def list_customer_contracts(self, customer_id, headers):
        return self._request(
            "GET", f"/api/customers/{customer_id}/contracts", headers=headers
        )

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/activate", {}, headers
        )

    def amend_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/amend", payload, headers
        )

    def offer_renewal(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/offer-renewal", payload, headers
        )

    def respond_renewal(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/respond-renewal", payload, headers
        )

    def flag_poach(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/flag-poach", payload, headers
        )

    def terminate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/terminate", payload, headers
        )

    # --- containers ---
    def create_container(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/containers", payload, headers
        )

    def list_customer_containers(self, customer_id, headers):
        return self._request(
            "GET", f"/api/customers/{customer_id}/containers", headers=headers
        )

    def get_container(self, container_id, headers):
        return self._request("GET", f"/api/containers/{container_id}", headers=headers)

    def unlock_container(self, container_id, headers):
        return self._request(
            "POST", f"/api/containers/{container_id}/unlock", {}, headers
        )

    def remove_container(self, container_id, headers):
        return self._request(
            "POST", f"/api/containers/{container_id}/remove", {}, headers
        )

    def list_container_pickup_visits(self, container_id, headers):
        return self._request(
            "GET", f"/api/containers/{container_id}/pickup-visits", headers=headers
        )

    def list_container_theft_incidents(self, container_id, headers):
        return self._request(
            "GET", f"/api/containers/{container_id}/theft-incidents", headers=headers
        )

    # --- market index quotes ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/api/market-index-quotes", payload, headers)

    def publish_quote(self, quote_id, headers):
        return self._request(
            "POST", f"/api/market-index-quotes/{quote_id}/publish", {}, headers
        )

    def list_quotes(self, headers, params=None):
        return self._request(
            "GET", "/api/market-index-quotes", headers=headers, params=params
        )

    # --- trucks ---
    def create_truck(self, payload, headers):
        return self._request("POST", "/api/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/api/trucks/{truck_id}", headers=headers)

    def set_truck_service_status(self, truck_id, payload, headers):
        return self._request(
            "POST", f"/api/trucks/{truck_id}/service-status", payload, headers
        )

    def list_truck_manifests(self, truck_id, headers):
        return self._request(
            "GET", f"/api/trucks/{truck_id}/manifests", headers=headers
        )

    # --- route manifests ---
    def create_manifest(self, payload, headers):
        return self._request("POST", "/api/route-manifests", payload, headers)

    def get_manifest(self, manifest_id, headers):
        return self._request(
            "GET", f"/api/route-manifests/{manifest_id}", headers=headers
        )

    def patch_manifest(self, manifest_id, payload, headers):
        return self._request(
            "PATCH", f"/api/route-manifests/{manifest_id}", payload, headers
        )

    def dispatch_manifest(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/api/route-manifests/{manifest_id}/dispatch", payload, headers
        )

    def complete_manifest(self, manifest_id, headers):
        return self._request(
            "POST", f"/api/route-manifests/{manifest_id}/complete", {}, headers
        )

    def reconcile_manifest(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/api/route-manifests/{manifest_id}/reconcile", payload, headers
        )

    def list_manifest_pickup_visits(self, manifest_id, headers):
        return self._request(
            "GET", f"/api/route-manifests/{manifest_id}/pickup-visits", headers=headers
        )

    def list_manifest_processing_batches(self, manifest_id, headers):
        return self._request(
            "GET",
            f"/api/route-manifests/{manifest_id}/processing-batches",
            headers=headers,
        )

    # --- pickup visits ---
    def get_pickup_visit(self, visit_id, headers):
        return self._request("GET", f"/api/pickup-visits/{visit_id}", headers=headers)

    def start_pickup_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/api/pickup-visits/{visit_id}/start", {}, headers
        )

    def complete_pickup_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/api/pickup-visits/{visit_id}/complete", payload, headers
        )

    def fail_pickup_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/api/pickup-visits/{visit_id}/fail", payload, headers
        )

    def void_pickup_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/api/pickup-visits/{visit_id}/void", payload, headers
        )

    def create_sample(self, visit_id, headers):
        return self._request(
            "POST", f"/api/pickup-visits/{visit_id}/samples", {}, headers
        )

    def list_visit_samples(self, visit_id, headers):
        return self._request(
            "GET", f"/api/pickup-visits/{visit_id}/samples", headers=headers
        )

    def list_visit_settlement_lines(self, visit_id, headers):
        return self._request(
            "GET", f"/api/pickup-visits/{visit_id}/settlement-lines", headers=headers
        )

    def list_visit_complaints(self, visit_id, headers):
        return self._request(
            "GET", f"/api/pickup-visits/{visit_id}/complaints", headers=headers
        )

    # --- quality samples ---
    def submit_sample(self, sample_id, headers):
        return self._request(
            "POST", f"/api/quality-samples/{sample_id}/submit", {}, headers
        )

    def grade_sample(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/api/quality-samples/{sample_id}/grade", payload, headers
        )

    def dispute_sample(self, sample_id, payload, headers):
        return self._request(
            "POST", f"/api/quality-samples/{sample_id}/dispute", payload, headers
        )

    # --- settlements ---
    def generate_settlement(self, payload, headers):
        return self._request("POST", "/api/settlements/generate", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/api/settlements/{settlement_id}", headers=headers)

    def list_customer_settlements(self, customer_id, headers):
        return self._request(
            "GET", f"/api/customers/{customer_id}/settlements", headers=headers
        )

    def list_settlement_lines(self, settlement_id, headers):
        return self._request(
            "GET", f"/api/settlements/{settlement_id}/lines", headers=headers
        )

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/api/settlements/{settlement_id}/finalize", {}, headers
        )

    def pay_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/api/settlements/{settlement_id}/pay", {}, headers
        )

    def void_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/api/settlements/{settlement_id}/void", payload, headers
        )

    # --- complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/api/complaints", payload, headers)

    def list_customer_complaints(self, customer_id, headers):
        return self._request(
            "GET", f"/api/customers/{customer_id}/complaints", headers=headers
        )

    def investigate_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/api/complaints/{complaint_id}/investigate", {}, headers
        )

    def escalate_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/api/complaints/{complaint_id}/escalate", payload, headers
        )

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/api/complaints/{complaint_id}/resolve", payload, headers
        )

    def reopen_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/api/complaints/{complaint_id}/reopen", payload, headers
        )

    # --- processing batches ---
    def create_processing_batch(self, payload, headers):
        return self._request("POST", "/api/processing-batches", payload, headers)

    def process_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/processing-batches/{batch_id}/process", payload, headers
        )

    def sell_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/processing-batches/{batch_id}/sell", payload, headers
        )

    # --- theft incidents ---
    def create_theft_incident(self, payload, headers):
        return self._request("POST", "/api/theft-incidents", payload, headers)

    def confirm_theft_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/api/theft-incidents/{incident_id}/confirm", {}, headers
        )

    def dismiss_theft_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/api/theft-incidents/{incident_id}/dismiss", payload, headers
        )

    def resolve_theft_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/api/theft-incidents/{incident_id}/resolve", payload, headers
        )


api_client = ApiClient()
