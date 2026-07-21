"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Carrier ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/subro/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/subro/carriers/{carrier_id}", headers=headers)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"/subro/carriers/{carrier_id}/suspend", {}, headers)

    # --- AdverseParty ---
    def create_adverse_party(self, payload, headers):
        return self._request("POST", "/subro/adverse-parties", payload, headers)

    def get_adverse_party(self, adverse_party_id, headers):
        return self._request("GET", f"/subro/adverse-parties/{adverse_party_id}", headers=headers)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/subro/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/subro/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/subro/claims", headers=headers, params=params)

    def assess_liability(self, claim_id, payload, headers):
        return self._request("POST", f"/subro/claims/{claim_id}/assess-liability", payload, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/subro/claims/{claim_id}/withdraw", {}, headers)

    def add_document(self, claim_id, payload, headers):
        return self._request("POST", f"/subro/claims/{claim_id}/documents", payload, headers)

    def list_documents(self, claim_id, headers, params=None):
        return self._request("GET", f"/subro/claims/{claim_id}/documents", headers=headers, params=params)

    # --- Demand ---
    def create_demand(self, claim_id, payload, headers):
        return self._request("POST", f"/subro/claims/{claim_id}/demands", payload, headers)

    def get_demand(self, demand_id, headers):
        return self._request("GET", f"/subro/demands/{demand_id}", headers=headers)

    def list_demands(self, headers, params=None):
        return self._request("GET", "/subro/demands", headers=headers, params=params)

    def record_response(self, demand_id, payload, headers):
        return self._request("POST", f"/subro/demands/{demand_id}/record-response", payload, headers)

    # --- Arbitration ---
    def create_arbitration(self, claim_id, payload, headers):
        return self._request("POST", f"/subro/claims/{claim_id}/arbitrations", payload, headers)

    def get_arbitration(self, arbitration_id, headers):
        return self._request("GET", f"/subro/arbitrations/{arbitration_id}", headers=headers)

    def list_arbitrations(self, headers, params=None):
        return self._request("GET", "/subro/arbitrations", headers=headers, params=params)

    def schedule_hearing(self, arbitration_id, payload, headers):
        return self._request("POST", f"/subro/arbitrations/{arbitration_id}/schedule-hearing", payload, headers)

    def file_round(self, arbitration_id, payload, headers):
        return self._request("POST", f"/subro/arbitrations/{arbitration_id}/rounds", payload, headers)

    def decide_arbitration(self, arbitration_id, payload, headers):
        return self._request("POST", f"/subro/arbitrations/{arbitration_id}/decide", payload, headers)

    # --- Settlement ---
    def propose_settlement(self, claim_id, payload, headers):
        return self._request("POST", f"/subro/claims/{claim_id}/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/subro/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/subro/settlements", headers=headers, params=params)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/subro/settlements/{settlement_id}/approve", {}, headers)

    def reject_settlement(self, settlement_id, headers):
        return self._request("POST", f"/subro/settlements/{settlement_id}/reject", {}, headers)

    def accept_settlement(self, settlement_id, headers):
        return self._request("POST", f"/subro/settlements/{settlement_id}/accept", {}, headers)

    # --- RecoveryPayment ---
    def create_recovery_payment(self, claim_id, payload, headers):
        return self._request("POST", f"/subro/claims/{claim_id}/recovery-payments", payload, headers)

    def get_recovery_payment(self, recovery_payment_id, headers):
        return self._request("GET", f"/subro/recovery-payments/{recovery_payment_id}", headers=headers)

    def list_recovery_payments(self, headers, params=None):
        return self._request("GET", "/subro/recovery-payments", headers=headers, params=params)

    def clear_payment(self, recovery_payment_id, headers):
        return self._request("POST", f"/subro/recovery-payments/{recovery_payment_id}/clear", {}, headers)

    def reverse_payment(self, recovery_payment_id, headers):
        return self._request("POST", f"/subro/recovery-payments/{recovery_payment_id}/reverse", {}, headers)

    # --- DeductibleReimbursement ---
    def get_deductible_reimbursement(self, deductible_reimbursement_id, headers):
        return self._request("GET", f"/subro/deductible-reimbursements/{deductible_reimbursement_id}", headers=headers)

    def list_deductible_reimbursements(self, headers, params=None):
        return self._request("GET", "/subro/deductible-reimbursements", headers=headers, params=params)

    def disburse_reimbursement(self, deductible_reimbursement_id, headers):
        return self._request("POST", f"/subro/deductible-reimbursements/{deductible_reimbursement_id}/disburse", {}, headers)

    # --- CommissionStatement ---
    def create_commission_statement(self, carrier_id, payload, headers):
        return self._request("POST", f"/subro/carriers/{carrier_id}/commission-statements", payload, headers)

    def get_commission_statement(self, commission_statement_id, headers):
        return self._request("GET", f"/subro/commission-statements/{commission_statement_id}", headers=headers)

    def list_commission_statements(self, headers, params=None):
        return self._request("GET", "/subro/commission-statements", headers=headers, params=params)

    def finalize_commission_statement(self, commission_statement_id, payload, headers):
        return self._request("POST", f"/subro/commission-statements/{commission_statement_id}/finalize", payload, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
