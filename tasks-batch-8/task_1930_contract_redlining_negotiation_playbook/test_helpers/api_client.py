"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Playbook ---
    def create_playbook(self, payload, headers):
        return self._request("POST", "/playbooks", payload, headers)

    def list_playbooks(self, headers, params=None):
        return self._request("GET", "/playbooks", headers=headers, params=params)

    def get_playbook(self, playbook_id, headers):
        return self._request("GET", f"/playbooks/{playbook_id}", headers=headers)

    def publish_playbook(self, playbook_id, headers):
        return self._request("POST", f"/playbooks/{playbook_id}/publish", {}, headers)

    def deprecate_playbook(self, playbook_id, headers):
        return self._request("POST", f"/playbooks/{playbook_id}/deprecate", {}, headers)

    # --- ClauseTemplate (nested + flat) ---
    def create_clause(self, playbook_id, payload, headers):
        return self._request("POST", f"/playbooks/{playbook_id}/clauses", payload, headers)

    def list_clauses(self, playbook_id, headers, params=None):
        return self._request("GET", f"/playbooks/{playbook_id}/clauses", headers=headers, params=params)

    def get_clause(self, playbook_id, clause_id, headers):
        return self._request("GET", f"/playbooks/{playbook_id}/clauses/{clause_id}", headers=headers)

    def retire_clause(self, playbook_id, clause_id, headers):
        return self._request("POST", f"/playbooks/{playbook_id}/clauses/{clause_id}/retire", {}, headers)

    def list_clauses_flat(self, headers, params=None):
        return self._request("GET", "/clauses", headers=headers, params=params)

    def get_clause_flat(self, clause_id, headers):
        return self._request("GET", f"/clauses/{clause_id}", headers=headers)

    # --- ContractType ---
    def create_contract_type(self, payload, headers):
        return self._request("POST", "/contract-types", payload, headers)

    def list_contract_types(self, headers, params=None):
        return self._request("GET", "/contract-types", headers=headers, params=params)

    def get_contract_type(self, type_id, headers):
        return self._request("GET", f"/contract-types/{type_id}", headers=headers)

    def retire_contract_type(self, type_id, headers):
        return self._request("POST", f"/contract-types/{type_id}/retire", {}, headers)

    # --- Counterparty ---
    def create_counterparty(self, payload, headers):
        return self._request("POST", "/counterparties", payload, headers)

    def list_counterparties(self, headers, params=None):
        return self._request("GET", "/counterparties", headers=headers, params=params)

    def get_counterparty(self, counterparty_id, headers):
        return self._request("GET", f"/counterparties/{counterparty_id}", headers=headers)

    # --- User ---
    def create_user(self, payload, headers):
        return self._request("POST", "/users", payload, headers)

    def list_users(self, headers, params=None):
        return self._request("GET", "/users", headers=headers, params=params)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/users/{user_id}", headers=headers)

    # --- IntakeRequest ---
    def create_intake_request(self, payload, headers):
        return self._request("POST", "/intake-requests", payload, headers)

    def list_intake_requests(self, headers, params=None):
        return self._request("GET", "/intake-requests", headers=headers, params=params)

    def get_intake_request(self, intake_id, headers):
        return self._request("GET", f"/intake-requests/{intake_id}", headers=headers)

    def triage_intake_request(self, intake_id, payload, headers):
        return self._request("POST", f"/intake-requests/{intake_id}/triage", payload, headers)

    def list_triage_decisions(self, intake_id, headers, params=None):
        return self._request("GET", f"/intake-requests/{intake_id}/triage-decisions", headers=headers, params=params)

    def reject_intake_request(self, intake_id, payload, headers):
        return self._request("POST", f"/intake-requests/{intake_id}/reject", payload, headers)

    def cancel_intake_request(self, intake_id, headers):
        return self._request("POST", f"/intake-requests/{intake_id}/cancel", {}, headers)

    def open_negotiation(self, intake_id, payload, headers):
        return self._request("POST", f"/intake-requests/{intake_id}/open-negotiation", payload, headers)

    # --- Negotiation ---
    def list_negotiations(self, headers, params=None):
        return self._request("GET", "/negotiations", headers=headers, params=params)

    def get_negotiation(self, negotiation_id, headers):
        return self._request("GET", f"/negotiations/{negotiation_id}", headers=headers)

    def create_round(self, negotiation_id, payload, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/rounds", payload, headers)

    def list_rounds(self, negotiation_id, headers, params=None):
        return self._request("GET", f"/negotiations/{negotiation_id}/rounds", headers=headers, params=params)

    def get_round(self, negotiation_id, round_id, headers):
        return self._request("GET", f"/negotiations/{negotiation_id}/rounds/{round_id}", headers=headers)

    def close_round(self, negotiation_id, round_id, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/rounds/{round_id}/close", {}, headers)

    def finalize_redlining(self, negotiation_id, payload, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/finalize-redlining", payload, headers)

    def abort_negotiation(self, negotiation_id, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/abort", {}, headers)

    # --- Deviation ---
    def create_deviation(self, negotiation_id, payload, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/deviations", payload, headers)

    def list_deviations(self, negotiation_id, headers, params=None):
        return self._request("GET", f"/negotiations/{negotiation_id}/deviations", headers=headers, params=params)

    def get_deviation(self, negotiation_id, deviation_id, headers):
        return self._request("GET", f"/negotiations/{negotiation_id}/deviations/{deviation_id}", headers=headers)

    def begin_review(self, negotiation_id, deviation_id, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/deviations/{deviation_id}/begin-review", {}, headers)

    def decide_deviation(self, negotiation_id, deviation_id, payload, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/deviations/{deviation_id}/decide", payload, headers)

    def list_approval_decisions(self, negotiation_id, deviation_id, headers, params=None):
        return self._request("GET", f"/negotiations/{negotiation_id}/deviations/{deviation_id}/decisions", headers=headers, params=params)

    def withdraw_deviation(self, negotiation_id, deviation_id, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/deviations/{deviation_id}/withdraw", {}, headers)

    # --- Flat single-resource collections (PRD §4) ---
    def list_triage_decisions_flat(self, headers, params=None):
        return self._request("GET", "/triage-decisions", headers=headers, params=params)

    def get_triage_decision_flat(self, decision_id, headers):
        return self._request("GET", f"/triage-decisions/{decision_id}", headers=headers)

    def list_rounds_flat(self, headers, params=None):
        return self._request("GET", "/rounds", headers=headers, params=params)

    def get_round_flat(self, round_id, headers):
        return self._request("GET", f"/rounds/{round_id}", headers=headers)

    def list_deviations_flat(self, headers, params=None):
        return self._request("GET", "/deviations", headers=headers, params=params)

    def get_deviation_flat(self, deviation_id, headers):
        return self._request("GET", f"/deviations/{deviation_id}", headers=headers)

    def list_approval_decisions_flat(self, headers, params=None):
        return self._request("GET", "/approval-decisions", headers=headers, params=params)

    def get_approval_decision_flat(self, decision_id, headers):
        return self._request("GET", f"/approval-decisions/{decision_id}", headers=headers)

    # --- SignaturePacket ---
    def create_signature_packet(self, negotiation_id, payload, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/signature-packets", payload, headers)

    def list_signature_packets(self, negotiation_id, headers, params=None):
        return self._request("GET", f"/negotiations/{negotiation_id}/signature-packets", headers=headers, params=params)

    def get_signature_packet(self, negotiation_id, packet_id, headers):
        return self._request("GET", f"/negotiations/{negotiation_id}/signature-packets/{packet_id}", headers=headers)

    def sign_packet(self, negotiation_id, packet_id, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/signature-packets/{packet_id}/sign", {}, headers)

    def record_execution(self, negotiation_id, packet_id, payload, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/signature-packets/{packet_id}/record-execution", payload, headers)

    def void_packet(self, negotiation_id, packet_id, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/signature-packets/{packet_id}/void", {}, headers)

    def list_signature_packets_flat(self, headers, params=None):
        return self._request("GET", "/signature-packets", headers=headers, params=params)

    def get_signature_packet_flat(self, packet_id, headers):
        return self._request("GET", f"/signature-packets/{packet_id}", headers=headers)

    # --- Obligation ---
    def list_obligations(self, negotiation_id, headers, params=None):
        return self._request("GET", f"/negotiations/{negotiation_id}/obligations", headers=headers, params=params)

    def list_obligations_flat(self, headers, params=None):
        return self._request("GET", "/obligations", headers=headers, params=params)

    def get_obligation(self, obligation_id, headers):
        return self._request("GET", f"/obligations/{obligation_id}", headers=headers)

    # --- Analytics ---
    def get_cycle_time_analytics(self, headers, params=None):
        return self._request("GET", "/analytics/cycle-time", headers=headers, params=params)

    def get_bottleneck_analytics(self, headers, params=None):
        return self._request("GET", "/analytics/bottlenecks", headers=headers, params=params)


api_client = ApiClient()
