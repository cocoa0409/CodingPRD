"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock --------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Client --------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def list_client_sites(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/sites", headers=headers, params=params)

    # --- Site ----------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_site_contract_sites(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/contract-sites", headers=headers, params=params)

    # --- Contract ------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/suspend", {}, headers)

    def resume_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/resume", {}, headers)

    def expire_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/expire", {}, headers)

    def renew_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/renew", payload, headers)

    def get_billing_preview(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/billing-preview", headers=headers)

    def get_true_up_preview(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/true-up-preview", headers=headers)

    # --- ContractSite ----------------------------------------------------------
    def create_contract_site(self, payload, headers):
        return self._request("POST", "/contract-sites", payload, headers)

    def get_contract_site(self, contract_site_id, headers):
        return self._request("GET", f"/contract-sites/{contract_site_id}", headers=headers)

    def list_contract_contract_sites(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/contract-sites", headers=headers, params=params)

    # --- ContractAmendment -----------------------------------------------------
    def create_amendment(self, payload, headers):
        return self._request("POST", "/amendments", payload, headers)

    def list_contract_amendments(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/amendments", headers=headers, params=params)

    def approve_amendment(self, amendment_id, headers):
        return self._request("POST", f"/amendments/{amendment_id}/approve", {}, headers)

    def reject_amendment(self, amendment_id, headers):
        return self._request("POST", f"/amendments/{amendment_id}/reject", {}, headers)

    # --- StormEvent ------------------------------------------------------------
    def create_storm_event(self, payload, headers):
        return self._request("POST", "/storm-events", payload, headers)

    def get_storm_event(self, event_id, headers):
        return self._request("GET", f"/storm-events/{event_id}", headers=headers)

    def list_storm_events(self, headers, params=None):
        return self._request("GET", "/storm-events", headers=headers, params=params)

    def verify_storm_event(self, event_id, headers):
        return self._request("POST", f"/storm-events/{event_id}/verify", {}, headers)

    def challenge_storm_event(self, event_id, payload, headers):
        return self._request("POST", f"/storm-events/{event_id}/challenge", payload, headers)

    def void_storm_event(self, event_id, headers):
        return self._request("POST", f"/storm-events/{event_id}/void", {}, headers)

    def close_sweep_storm_event(self, event_id, headers):
        return self._request("POST", f"/storm-events/{event_id}/close-sweep", {}, headers)

    def get_route_plan(self, event_id, headers, params=None):
        return self._request("GET", f"/storm-events/{event_id}/route-plan", headers=headers, params=params)

    # --- WeatherObservation ----------------------------------------------------
    def create_observation(self, payload, headers):
        return self._request("POST", "/observations", payload, headers)

    def list_event_observations(self, event_id, headers, params=None):
        return self._request("GET", f"/storm-events/{event_id}/observations", headers=headers, params=params)

    # --- ServiceVisit ----------------------------------------------------------
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/start", {}, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def void_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/void", {}, headers)

    def reassign_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/reassign", payload, headers)

    # --- MaterialApplication ---------------------------------------------------
    def create_material(self, payload, headers):
        return self._request("POST", "/materials", payload, headers)

    def list_visit_materials(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/materials", headers=headers, params=params)

    def void_material(self, material_id, headers):
        return self._request("POST", f"/materials/{material_id}/void", {}, headers)

    # --- ServicePhoto ----------------------------------------------------------
    def create_photo(self, payload, headers):
        return self._request("POST", "/photos", payload, headers)

    def list_visit_photos(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/photos", headers=headers, params=params)

    def accept_photo(self, photo_id, headers):
        return self._request("POST", f"/photos/{photo_id}/accept", {}, headers)

    def reject_photo(self, photo_id, headers):
        return self._request("POST", f"/photos/{photo_id}/reject", {}, headers)

    # --- Invoice ---------------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    # --- Dispute ---------------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def submit_dispute_evidence(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/submit-evidence", payload, headers)

    def request_dispute_evidence(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/request-evidence", payload, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # --- SlipFallClaim ---------------------------------------------------------
    def create_slip_fall_claim(self, payload, headers):
        return self._request("POST", "/slip-fall-claims", payload, headers)

    def get_slip_fall_claim(self, claim_id, headers):
        return self._request("GET", f"/slip-fall-claims/{claim_id}", headers=headers)

    def list_slip_fall_claims(self, headers, params=None):
        return self._request("GET", "/slip-fall-claims", headers=headers, params=params)

    def get_documentation_bundle(self, claim_id, headers):
        return self._request("GET", f"/slip-fall-claims/{claim_id}/documentation-bundle", headers=headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/slip-fall-claims/{claim_id}/review", {}, headers)

    def document_claim(self, claim_id, headers):
        return self._request("POST", f"/slip-fall-claims/{claim_id}/document", {}, headers)

    def close_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/slip-fall-claims/{claim_id}/close", payload, headers)

    # --- Subcontractor ---------------------------------------------------------
    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/subcontractors", payload, headers)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request("GET", f"/subcontractors/{subcontractor_id}", headers=headers)

    def list_subcontractors(self, headers, params=None):
        return self._request("GET", "/subcontractors", headers=headers, params=params)

    def approve_subcontractor(self, subcontractor_id, headers):
        return self._request("POST", f"/subcontractors/{subcontractor_id}/approve", {}, headers)

    def suspend_subcontractor(self, subcontractor_id, headers):
        return self._request("POST", f"/subcontractors/{subcontractor_id}/suspend", {}, headers)

    # --- CoverageAssignment ----------------------------------------------------
    def create_coverage_assignment(self, payload, headers):
        return self._request("POST", "/coverage-assignments", payload, headers)

    def get_coverage_assignment(self, assignment_id, headers):
        return self._request("GET", f"/coverage-assignments/{assignment_id}", headers=headers)

    def list_coverage_assignments(self, headers, params=None):
        return self._request("GET", "/coverage-assignments", headers=headers, params=params)

    def activate_coverage_assignment(self, assignment_id, headers):
        return self._request("POST", f"/coverage-assignments/{assignment_id}/activate", {}, headers)

    def fail_coverage_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/coverage-assignments/{assignment_id}/fail", payload, headers)

    def release_coverage_assignment(self, assignment_id, headers):
        return self._request("POST", f"/coverage-assignments/{assignment_id}/release", {}, headers)

    # --- SeasonalTrueUp --------------------------------------------------------
    def create_true_up(self, payload, headers):
        return self._request("POST", "/true-ups", payload, headers)

    def get_true_up(self, true_up_id, headers):
        return self._request("GET", f"/true-ups/{true_up_id}", headers=headers)

    def list_true_ups(self, headers, params=None):
        return self._request("GET", "/true-ups", headers=headers, params=params)

    def issue_true_up(self, true_up_id, headers):
        return self._request("POST", f"/true-ups/{true_up_id}/issue", {}, headers)

    def settle_true_up(self, true_up_id, payload, headers):
        return self._request("POST", f"/true-ups/{true_up_id}/settle", payload, headers)


api_client = ApiClient()
