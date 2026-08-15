"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Payer ---
    def create_payer(self, payload, headers):
        return self._request("POST", "/api/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/api/payers/{payer_id}", headers=headers)

    def list_payers(self, headers, params=None):
        return self._request("GET", "/api/payers", headers=headers, params=params)

    def deactivate_payer(self, payer_id, headers):
        return self._request("POST", f"/api/payers/{payer_id}/deactivate", headers=headers)

    # --- PayerContract ---
    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/api/payer-contracts", payload, headers)

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/api/payer-contracts/{contract_id}", headers=headers)

    def list_payer_contracts(self, headers, params=None):
        return self._request("GET", "/api/payer-contracts", headers=headers, params=params)

    def activate_payer_contract(self, contract_id, headers):
        return self._request("POST", f"/api/payer-contracts/{contract_id}/activate", headers=headers)

    def suspend_payer_contract(self, contract_id, headers):
        return self._request("POST", f"/api/payer-contracts/{contract_id}/suspend", headers=headers)

    def resume_payer_contract(self, contract_id, headers):
        return self._request("POST", f"/api/payer-contracts/{contract_id}/resume", headers=headers)

    def terminate_payer_contract(self, contract_id, headers):
        return self._request("POST", f"/api/payer-contracts/{contract_id}/terminate", headers=headers)

    # --- ContractTerm ---
    def create_contract_term(self, payload, headers):
        return self._request("POST", "/api/contract-terms", payload, headers)

    def get_contract_term(self, term_id, headers):
        return self._request("GET", f"/api/contract-terms/{term_id}", headers=headers)

    def list_contract_terms(self, headers, params=None):
        return self._request("GET", "/api/contract-terms", headers=headers, params=params)

    # --- CarveOutProvision ---
    def create_carve_out_provision(self, payload, headers):
        return self._request("POST", "/api/carve-out-provisions", payload, headers)

    def get_carve_out_provision(self, provision_id, headers):
        return self._request("GET", f"/api/carve-out-provisions/{provision_id}", headers=headers)

    def list_carve_out_provisions(self, headers, params=None):
        return self._request("GET", "/api/carve-out-provisions", headers=headers, params=params)

    # --- StopLossProvision ---
    def create_stop_loss_provision(self, payload, headers):
        return self._request("POST", "/api/stop-loss-provisions", payload, headers)

    def get_stop_loss_provision(self, provision_id, headers):
        return self._request("GET", f"/api/stop-loss-provisions/{provision_id}", headers=headers)

    def list_stop_loss_provisions(self, headers, params=None):
        return self._request("GET", "/api/stop-loss-provisions", headers=headers, params=params)

    # --- RateEscalator ---
    def create_rate_escalator(self, payload, headers):
        return self._request("POST", "/api/rate-escalators", payload, headers)

    def get_rate_escalator(self, escalator_id, headers):
        return self._request("GET", f"/api/rate-escalators/{escalator_id}", headers=headers)

    def list_rate_escalators(self, headers, params=None):
        return self._request("GET", "/api/rate-escalators", headers=headers, params=params)

    def void_rate_escalator(self, escalator_id, headers):
        return self._request("POST", f"/api/rate-escalators/{escalator_id}/void", headers=headers)

    # --- RateAmendment ---
    def create_rate_amendment(self, payload, headers):
        return self._request("POST", "/api/rate-amendments", payload, headers)

    def get_rate_amendment(self, amendment_id, headers):
        return self._request("GET", f"/api/rate-amendments/{amendment_id}", headers=headers)

    def list_rate_amendments(self, headers, params=None):
        return self._request("GET", "/api/rate-amendments", headers=headers, params=params)

    def approve_rate_amendment(self, amendment_id, headers):
        return self._request("POST", f"/api/rate-amendments/{amendment_id}/approve", headers=headers)

    def void_rate_amendment(self, amendment_id, headers):
        return self._request("POST", f"/api/rate-amendments/{amendment_id}/void", headers=headers)

    # --- NetworkAgreement ---
    def create_network_agreement(self, payload, headers):
        return self._request("POST", "/api/network-agreements", payload, headers)

    def get_network_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/network-agreements/{agreement_id}", headers=headers)

    def list_network_agreements(self, headers, params=None):
        return self._request("GET", "/api/network-agreements", headers=headers, params=params)

    def verify_network_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/network-agreements/{agreement_id}/verify", headers=headers)

    def flag_suspect_network_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/network-agreements/{agreement_id}/flag_suspect", headers=headers)

    def retire_network_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/network-agreements/{agreement_id}/retire", headers=headers)

    # --- Claim / ClaimLine ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def add_claim_line(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/lines", payload, headers)

    def list_claim_lines(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}/lines", headers=headers)

    def price_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/price", headers=headers)

    def reprice_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/reprice", headers=headers)

    # --- Remittance ---
    def create_remittance(self, payload, headers):
        return self._request("POST", "/api/remittances", payload, headers)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/api/remittances/{remittance_id}", headers=headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/api/remittances", headers=headers, params=params)

    def reverse_remittance(self, remittance_id, headers):
        return self._request("POST", f"/api/remittances/{remittance_id}/reverse", headers=headers)

    # --- UnderpaymentCase ---
    def get_underpayment_case(self, case_id, headers):
        return self._request("GET", f"/api/underpayment-cases/{case_id}", headers=headers)

    def list_underpayment_cases(self, headers, params=None):
        return self._request("GET", "/api/underpayment-cases", headers=headers, params=params)

    def pick_up_underpayment_case(self, case_id, headers):
        return self._request("POST", f"/api/underpayment-cases/{case_id}/pick_up", headers=headers)

    def write_off_underpayment_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/underpayment-cases/{case_id}/write_off", payload, headers)

    def withdraw_underpayment_case(self, case_id, headers):
        return self._request("POST", f"/api/underpayment-cases/{case_id}/withdraw", headers=headers)

    # --- Appeal ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/api/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/api/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/api/appeals", headers=headers, params=params)

    def file_appeal(self, appeal_id, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/file", headers=headers)

    def record_appeal_outcome(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/record_outcome", payload, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/withdraw", headers=headers)

    # --- ContractProposal ---
    def create_contract_proposal(self, payload, headers):
        return self._request("POST", "/api/contract-proposals", payload, headers)

    def get_contract_proposal(self, proposal_id, headers):
        return self._request("GET", f"/api/contract-proposals/{proposal_id}", headers=headers)

    def list_contract_proposals(self, headers, params=None):
        return self._request("GET", "/api/contract-proposals", headers=headers, params=params)

    def run_proposal_model(self, proposal_id, headers):
        return self._request("POST", f"/api/contract-proposals/{proposal_id}/run_model", headers=headers)

    def submit_proposal(self, proposal_id, headers):
        return self._request("POST", f"/api/contract-proposals/{proposal_id}/submit", headers=headers)

    def record_proposal_counter(self, proposal_id, headers):
        return self._request("POST", f"/api/contract-proposals/{proposal_id}/record_counter", headers=headers)

    def accept_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/api/contract-proposals/{proposal_id}/accept", payload, headers)

    def reject_proposal(self, proposal_id, headers):
        return self._request("POST", f"/api/contract-proposals/{proposal_id}/reject", headers=headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST", f"/api/contract-proposals/{proposal_id}/withdraw", headers=headers)

    # --- ContractAlert ---
    def get_contract_alert(self, alert_id, headers):
        return self._request("GET", f"/api/contract-alerts/{alert_id}", headers=headers)

    def list_contract_alerts(self, headers, params=None):
        return self._request("GET", "/api/contract-alerts", headers=headers, params=params)

    def acknowledge_contract_alert(self, alert_id, headers):
        return self._request("POST", f"/api/contract-alerts/{alert_id}/acknowledge", headers=headers)

    def dismiss_contract_alert(self, alert_id, headers):
        return self._request("POST", f"/api/contract-alerts/{alert_id}/dismiss", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
