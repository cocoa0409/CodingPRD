"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.6) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/sourcing/_clock/set_current_utc", payload, headers)

    # --- Ingredients ---
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/sourcing/ingredients", payload, headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/sourcing/ingredients", headers=headers, params=params)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/sourcing/ingredients/{ingredient_id}", headers=headers)

    def activate_ingredient(self, ingredient_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/activate", {}, headers)

    def discontinue_ingredient(self, ingredient_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/discontinue", {}, headers)

    # --- Specs ---
    def create_spec(self, ingredient_id, payload, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/specs", payload, headers)

    def list_specs(self, ingredient_id, headers, params=None):
        return self._request("GET", f"/sourcing/ingredients/{ingredient_id}/specs", headers=headers, params=params)

    def get_spec(self, ingredient_id, spec_id, headers):
        return self._request("GET", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}", headers=headers)

    def add_spec_parameter(self, ingredient_id, spec_id, payload, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}/parameters", payload, headers)

    def list_spec_parameters(self, ingredient_id, spec_id, headers, params=None):
        return self._request("GET", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}/parameters", headers=headers, params=params)

    def submit_spec(self, ingredient_id, spec_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}/submit", {}, headers)

    def approve_spec(self, ingredient_id, spec_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}/approve", {}, headers)

    def reject_spec(self, ingredient_id, spec_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}/reject", {}, headers)

    def revise_spec(self, ingredient_id, spec_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}/revise", {}, headers)

    def make_spec_effective(self, ingredient_id, spec_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}/make-effective", {}, headers)

    def retire_spec(self, ingredient_id, spec_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/specs/{spec_id}/retire", {}, headers)

    # --- Suppliers ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/sourcing/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/sourcing/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/sourcing/suppliers/{supplier_id}", headers=headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/suspend", {}, headers)

    def disqualify_supplier(self, supplier_id, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/disqualify", {}, headers)

    # --- Qualifications ---
    def create_qualification(self, supplier_id, payload, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/qualifications", payload, headers)

    def list_qualifications(self, supplier_id, headers, params=None):
        return self._request("GET", f"/sourcing/suppliers/{supplier_id}/qualifications", headers=headers, params=params)

    def evaluate_qualification(self, supplier_id, qualification_id, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/qualifications/{qualification_id}/evaluate", {}, headers)

    def decide_qualification(self, supplier_id, qualification_id, payload, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/qualifications/{qualification_id}/decide", payload, headers)

    # --- Approved sources (ASL) ---
    def create_approved_source(self, ingredient_id, payload, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/approved-sources", payload, headers)

    def list_approved_sources(self, ingredient_id, headers, params=None):
        return self._request("GET", f"/sourcing/ingredients/{ingredient_id}/approved-sources", headers=headers, params=params)

    def get_approved_source(self, source_id, headers):
        return self._request("GET", f"/sourcing/approved-sources/{source_id}", headers=headers)

    def activate_approved_source(self, ingredient_id, source_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/approved-sources/{source_id}/activate", {}, headers)

    def suspend_approved_source(self, ingredient_id, source_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/approved-sources/{source_id}/suspend", {}, headers)

    def reinstate_approved_source(self, ingredient_id, source_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/approved-sources/{source_id}/reinstate", {}, headers)

    def revoke_approved_source(self, ingredient_id, source_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/approved-sources/{source_id}/revoke", {}, headers)

    # --- Declarations ---
    def create_declaration(self, source_id, payload, headers):
        return self._request("POST", f"/sourcing/approved-sources/{source_id}/declarations", payload, headers)

    def list_declarations(self, source_id, headers, params=None):
        return self._request("GET", f"/sourcing/approved-sources/{source_id}/declarations", headers=headers, params=params)

    # --- Contracts ---
    def create_contract(self, source_id, payload, headers):
        return self._request("POST", f"/sourcing/approved-sources/{source_id}/contracts", payload, headers)

    def list_contracts(self, source_id, headers, params=None):
        return self._request("GET", f"/sourcing/approved-sources/{source_id}/contracts", headers=headers, params=params)

    def activate_contract(self, source_id, contract_id, headers):
        return self._request("POST", f"/sourcing/approved-sources/{source_id}/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, source_id, contract_id, headers):
        return self._request("POST", f"/sourcing/approved-sources/{source_id}/contracts/{contract_id}/terminate", {}, headers)

    def get_contract_rebate(self, source_id, contract_id, headers):
        return self._request("GET", f"/sourcing/approved-sources/{source_id}/contracts/{contract_id}/rebate", headers=headers)

    # --- Flat read aliases ---
    def list_all_specs(self, headers, params=None):
        return self._request("GET", "/sourcing/specs", headers=headers, params=params)

    def get_spec_flat(self, spec_id, headers):
        return self._request("GET", f"/sourcing/specs/{spec_id}", headers=headers)

    def list_spec_parameters_flat(self, spec_id, headers, params=None):
        return self._request("GET", f"/sourcing/specs/{spec_id}/parameters", headers=headers, params=params)

    def list_spec_approved_sources(self, spec_id, headers, params=None):
        return self._request("GET", f"/sourcing/specs/{spec_id}/approved-sources", headers=headers, params=params)

    def list_supplier_approved_sources(self, supplier_id, headers, params=None):
        return self._request("GET", f"/sourcing/suppliers/{supplier_id}/approved-sources", headers=headers, params=params)

    def get_contract_flat(self, contract_id, headers):
        return self._request("GET", f"/sourcing/contracts/{contract_id}", headers=headers)

    def list_contract_coas(self, contract_id, headers, params=None):
        return self._request("GET", f"/sourcing/contracts/{contract_id}/coas", headers=headers, params=params)

    def get_coa_flat(self, coa_id, headers):
        return self._request("GET", f"/sourcing/coas/{coa_id}", headers=headers)

    def list_coa_findings_flat(self, coa_id, headers, params=None):
        return self._request("GET", f"/sourcing/coas/{coa_id}/findings", headers=headers, params=params)

    def list_source_substitution_requests(self, source_id, headers, params=None):
        return self._request("GET", f"/sourcing/approved-sources/{source_id}/substitution-requests", headers=headers, params=params)

    def get_substitution_request_flat(self, request_id, headers):
        return self._request("GET", f"/sourcing/substitution-requests/{request_id}", headers=headers)

    def get_substitution_assessment_flat(self, request_id, headers):
        return self._request("GET", f"/sourcing/substitution-requests/{request_id}/assessment", headers=headers)

    def get_audit_flat(self, audit_id, headers):
        return self._request("GET", f"/sourcing/audits/{audit_id}", headers=headers)

    def list_audit_capas_flat(self, audit_id, headers, params=None):
        return self._request("GET", f"/sourcing/audits/{audit_id}/corrective-actions", headers=headers, params=params)

    # --- Price index observations ---
    def create_price_index_observation(self, payload, headers):
        return self._request("POST", "/sourcing/price-index-observations", payload, headers)

    def list_price_index_observations(self, headers, params=None):
        return self._request("GET", "/sourcing/price-index-observations", headers=headers, params=params)

    # --- CoAs ---
    def register_coa(self, source_id, payload, headers):
        return self._request("POST", f"/sourcing/approved-sources/{source_id}/coas", payload, headers)

    def list_coas(self, source_id, headers, params=None):
        return self._request("GET", f"/sourcing/approved-sources/{source_id}/coas", headers=headers, params=params)

    def get_coa(self, source_id, coa_id, headers):
        return self._request("GET", f"/sourcing/approved-sources/{source_id}/coas/{coa_id}", headers=headers)

    def start_coa_review(self, source_id, coa_id, headers):
        return self._request("POST", f"/sourcing/approved-sources/{source_id}/coas/{coa_id}/start-review", {}, headers)

    def list_coa_findings(self, source_id, coa_id, headers, params=None):
        return self._request("GET", f"/sourcing/approved-sources/{source_id}/coas/{coa_id}/findings", headers=headers, params=params)

    def disposition_finding(self, source_id, coa_id, finding_id, payload, headers):
        return self._request("POST", f"/sourcing/approved-sources/{source_id}/coas/{coa_id}/findings/{finding_id}/disposition", payload, headers)

    def close_coa_review(self, source_id, coa_id, payload, headers):
        return self._request("POST", f"/sourcing/approved-sources/{source_id}/coas/{coa_id}/close-review", payload, headers)

    # --- Substitution requests ---
    def create_substitution_request(self, ingredient_id, payload, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/substitution-requests", payload, headers)

    def list_substitution_requests(self, ingredient_id, headers, params=None):
        return self._request("GET", f"/sourcing/ingredients/{ingredient_id}/substitution-requests", headers=headers, params=params)

    def assess_substitution(self, ingredient_id, request_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/substitution-requests/{request_id}/assess", {}, headers)

    def get_assessment(self, ingredient_id, request_id, headers):
        return self._request("GET", f"/sourcing/ingredients/{ingredient_id}/substitution-requests/{request_id}/assessment", headers=headers)

    def route_regulatory(self, ingredient_id, request_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/substitution-requests/{request_id}/route-regulatory", {}, headers)

    def regulatory_signoff(self, ingredient_id, request_id, payload, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/substitution-requests/{request_id}/regulatory-signoff", payload, headers)

    def approve_substitution(self, ingredient_id, request_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/substitution-requests/{request_id}/approve", {}, headers)

    def reject_substitution(self, ingredient_id, request_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/substitution-requests/{request_id}/reject", {}, headers)

    def execute_substitution(self, ingredient_id, request_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/substitution-requests/{request_id}/execute", {}, headers)

    def cancel_substitution(self, ingredient_id, request_id, headers):
        return self._request("POST", f"/sourcing/ingredients/{ingredient_id}/substitution-requests/{request_id}/cancel", {}, headers)

    # --- Audits ---
    def schedule_audit(self, supplier_id, payload, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits", payload, headers)

    def list_audits(self, supplier_id, headers, params=None):
        return self._request("GET", f"/sourcing/suppliers/{supplier_id}/audits", headers=headers, params=params)

    def start_audit(self, supplier_id, audit_id, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/start", {}, headers)

    def issue_audit_report(self, supplier_id, audit_id, payload, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/issue-report", payload, headers)

    def close_audit(self, supplier_id, audit_id, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/close", {}, headers)

    def cancel_audit(self, supplier_id, audit_id, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/cancel", {}, headers)

    # --- Corrective actions ---
    def create_corrective_action(self, supplier_id, audit_id, payload, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/corrective-actions", payload, headers)

    def list_corrective_actions(self, supplier_id, audit_id, headers, params=None):
        return self._request("GET", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/corrective-actions", headers=headers, params=params)

    def submit_capa_response(self, supplier_id, audit_id, capa_id, payload, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/corrective-actions/{capa_id}/submit-response", payload, headers)

    def verify_capa(self, supplier_id, audit_id, capa_id, payload, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/corrective-actions/{capa_id}/verify", payload, headers)

    def reject_capa_response(self, supplier_id, audit_id, capa_id, payload, headers):
        return self._request("POST", f"/sourcing/suppliers/{supplier_id}/audits/{audit_id}/corrective-actions/{capa_id}/reject-response", payload, headers)


api_client = ApiClient()
