"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock & daily ops cycle ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/pm/_clock/set_current_utc", payload, headers)

    def run_daily_cycle(self, headers, payload=None):
        return self._request("POST", "/pm/ops/run_daily_cycle", payload or {}, headers)

    # --- JurisdictionProfile ---
    def create_jurisdiction_profile(self, payload, headers):
        return self._request("POST", "/pm/jurisdiction-profiles", payload, headers)

    def get_jurisdiction_profile(self, profile_id, headers):
        return self._request("GET", f"/pm/jurisdiction-profiles/{profile_id}", headers=headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/pm/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/pm/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/pm/properties", headers=headers, params=params)

    # --- Unit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/pm/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/pm/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/pm/units", headers=headers, params=params)

    # --- Tenancy ---
    def create_tenancy(self, payload, headers):
        return self._request("POST", "/pm/tenancies", payload, headers)

    def get_tenancy(self, tenancy_id, headers):
        return self._request("GET", f"/pm/tenancies/{tenancy_id}", headers=headers)

    def list_tenancies(self, headers, params=None):
        return self._request("GET", "/pm/tenancies", headers=headers, params=params)

    def give_notice(self, tenancy_id, headers):
        return self._request("POST", f"/pm/tenancies/{tenancy_id}/give_notice", {}, headers)

    def record_key_return(self, tenancy_id, payload, headers):
        return self._request("POST", f"/pm/tenancies/{tenancy_id}/record_key_return", payload, headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/pm/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/pm/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/pm/inspections", headers=headers, params=params)

    def add_inspection_item(self, inspection_id, payload, headers):
        return self._request("POST", f"/pm/inspections/{inspection_id}/items", payload, headers)

    def complete_inspection(self, inspection_id, headers):
        return self._request("POST", f"/pm/inspections/{inspection_id}/complete", {}, headers)

    # --- InspectionItem ---
    def get_inspection_item(self, item_id, headers):
        return self._request("GET", f"/pm/inspection-items/{item_id}", headers=headers)

    def list_inspection_items(self, headers, params=None):
        return self._request("GET", "/pm/inspection-items", headers=headers, params=params)

    # --- DeductionItem ---
    def create_deduction(self, payload, headers):
        return self._request("POST", "/pm/deductions", payload, headers)

    def get_deduction(self, deduction_id, headers):
        return self._request("GET", f"/pm/deductions/{deduction_id}", headers=headers)

    def list_deductions(self, headers, params=None):
        return self._request("GET", "/pm/deductions", headers=headers, params=params)

    # --- DepositStatement ---
    def create_statement(self, payload, headers):
        return self._request("POST", "/pm/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/pm/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/pm/statements", headers=headers, params=params)

    def issue_statement(self, statement_id, headers):
        return self._request("POST", f"/pm/statements/{statement_id}/issue", {}, headers)

    def reopen_statement(self, statement_id, headers):
        return self._request("POST", f"/pm/statements/{statement_id}/reopen", {}, headers)

    # --- Dispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/pm/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/pm/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/pm/disputes", headers=headers, params=params)

    def counter_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/pm/disputes/{dispute_id}/counter", payload, headers)

    def close_agreed_dispute(self, dispute_id, headers):
        return self._request("POST", f"/pm/disputes/{dispute_id}/close_agreed", {}, headers)

    def escalate_dispute(self, dispute_id, headers):
        return self._request("POST", f"/pm/disputes/{dispute_id}/escalate", {}, headers)

    def resolve_court_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/pm/disputes/{dispute_id}/resolve_court", payload, headers)

    # --- Disbursement ---
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/pm/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/pm/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/pm/disbursements", headers=headers, params=params)

    def mark_cashed(self, disbursement_id, headers):
        return self._request("POST", f"/pm/disbursements/{disbursement_id}/mark_cashed", {}, headers)

    def reverse_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/pm/disbursements/{disbursement_id}/reverse", {}, headers)

    def escheat_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"/pm/disbursements/{disbursement_id}/escheat", payload, headers)


api_client = ApiClient()
