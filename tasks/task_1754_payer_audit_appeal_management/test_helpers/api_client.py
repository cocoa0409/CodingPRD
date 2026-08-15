"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Payers
    # ------------------------------------------------------------------
    def create_payer(self, payload, headers):
        return self._request("POST", "/payers", payload, headers)

    def list_payers(self, headers, params=None):
        return self._request("GET", "/payers", headers=headers, params=params)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    def suspend_payer(self, payer_id, headers):
        return self._request("POST", f"/payers/{payer_id}/suspend", {}, headers)

    def reactivate_payer(self, payer_id, headers):
        return self._request("POST", f"/payers/{payer_id}/reactivate", {}, headers)

    # ------------------------------------------------------------------
    # Issue codes
    # ------------------------------------------------------------------
    def create_issue_code(self, payload, headers):
        return self._request("POST", "/issue-codes", payload, headers)

    def list_issue_codes(self, headers, params=None):
        return self._request("GET", "/issue-codes", headers=headers, params=params)

    def get_issue_code(self, issue_code_id, headers):
        return self._request("GET", f"/issue-codes/{issue_code_id}", headers=headers)

    # ------------------------------------------------------------------
    # Audit cases and claim lines
    # ------------------------------------------------------------------
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/audit-cases", payload, headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", "/audit-cases", headers=headers, params=params)

    def get_audit_case(self, case_id, headers):
        return self._request("GET", f"/audit-cases/{case_id}", headers=headers)

    def add_claim_line(self, case_id, payload, headers):
        return self._request("POST", f"/audit-cases/{case_id}/claim-lines",
                             payload, headers)

    def list_case_claim_lines(self, case_id, headers, params=None):
        return self._request("GET", f"/audit-cases/{case_id}/claim-lines",
                             headers=headers, params=params)

    def get_claim_line(self, line_id, headers):
        return self._request("GET", f"/claim-lines/{line_id}", headers=headers)

    def list_claim_lines(self, headers, params=None):
        return self._request("GET", "/claim-lines", headers=headers, params=params)

    def submit_records(self, case_id, payload, headers):
        return self._request("POST", f"/audit-cases/{case_id}/records-submissions",
                             payload, headers)

    def begin_payer_review(self, case_id, headers):
        return self._request("POST", f"/audit-cases/{case_id}/begin-payer-review",
                             {}, headers)

    def post_determination(self, case_id, payload, headers):
        return self._request("POST", f"/audit-cases/{case_id}/determination",
                             payload, headers)

    def close_audit_case(self, case_id, headers):
        return self._request("POST", f"/audit-cases/{case_id}/close", {}, headers)

    def list_case_events(self, case_id, headers, params=None):
        return self._request("GET", f"/audit-cases/{case_id}/events",
                             headers=headers, params=params)

    def get_exposure(self, case_id, headers):
        return self._request("GET", f"/audit-cases/{case_id}/exposure",
                             headers=headers)

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------
    def create_appeal(self, line_id, payload, headers):
        return self._request("POST", f"/claim-lines/{line_id}/appeals",
                             payload, headers)

    def list_line_appeals(self, line_id, headers, params=None):
        return self._request("GET", f"/claim-lines/{line_id}/appeals",
                             headers=headers, params=params)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def file_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/file", {}, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/withdraw", {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decision",
                             payload, headers)

    # ------------------------------------------------------------------
    # Evidence packets and items
    # ------------------------------------------------------------------
    def create_evidence_packet(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/evidence-packet",
                             {}, headers)

    def get_appeal_evidence_packet(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}/evidence-packet",
                             headers=headers)

    def get_evidence_packet(self, packet_id, headers):
        return self._request("GET", f"/evidence-packets/{packet_id}",
                             headers=headers)

    def add_packet_item(self, packet_id, payload, headers):
        return self._request("POST", f"/evidence-packets/{packet_id}/items",
                             payload, headers)

    def list_packet_items(self, packet_id, headers, params=None):
        return self._request("GET", f"/evidence-packets/{packet_id}/items",
                             headers=headers, params=params)

    def attach_packet_item(self, packet_id, item_id, payload, headers):
        return self._request(
            "POST",
            f"/evidence-packets/{packet_id}/items/{item_id}/attach",
            payload, headers)

    def waive_packet_item(self, packet_id, item_id, headers):
        return self._request(
            "POST",
            f"/evidence-packets/{packet_id}/items/{item_id}/waive",
            {}, headers)

    def detach_packet_item(self, packet_id, item_id, headers):
        return self._request(
            "POST",
            f"/evidence-packets/{packet_id}/items/{item_id}/detach",
            {}, headers)

    def submit_evidence_packet(self, packet_id, headers):
        return self._request("POST", f"/evidence-packets/{packet_id}/submit",
                             {}, headers)

    # ------------------------------------------------------------------
    # Recoupment demands
    # ------------------------------------------------------------------
    def create_recoupment_demand(self, case_id, payload, headers):
        return self._request("POST", f"/audit-cases/{case_id}/recoupment-demands",
                             payload, headers)

    def list_case_demands(self, case_id, headers, params=None):
        return self._request("GET", f"/audit-cases/{case_id}/recoupment-demands",
                             headers=headers, params=params)

    def list_recoupment_demands(self, headers, params=None):
        return self._request("GET", "/recoupment-demands",
                             headers=headers, params=params)

    def get_recoupment_demand(self, demand_id, headers):
        return self._request("GET", f"/recoupment-demands/{demand_id}",
                             headers=headers)

    def adjust_recoupment_demand(self, demand_id, payload, headers):
        return self._request("POST",
                             f"/recoupment-demands/{demand_id}/adjustments",
                             payload, headers)

    def write_off_demand(self, demand_id, headers):
        return self._request("POST", f"/recoupment-demands/{demand_id}/write-off",
                             {}, headers)

    def create_manual_offset(self, demand_id, payload, headers):
        return self._request("POST", f"/recoupment-demands/{demand_id}/offsets",
                             payload, headers)

    # ------------------------------------------------------------------
    # Remittances and offsets
    # ------------------------------------------------------------------
    def create_remittance(self, payload, headers):
        return self._request("POST", "/remittances", payload, headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/remittances", headers=headers, params=params)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/remittances/{remittance_id}",
                             headers=headers)

    def allocate_remittance(self, remittance_id, headers):
        return self._request("POST", f"/remittances/{remittance_id}/allocate",
                             {}, headers)

    def list_remittance_offsets(self, remittance_id, headers, params=None):
        return self._request("GET",
                             f"/remittances/{remittance_id}/offset-transactions",
                             headers=headers, params=params)

    def list_demand_offsets(self, demand_id, headers, params=None):
        return self._request(
            "GET", f"/recoupment-demands/{demand_id}/offset-transactions",
            headers=headers, params=params)

    def reverse_offset(self, offset_id, headers):
        return self._request("POST", f"/offset-transactions/{offset_id}/reverse",
                             {}, headers)

    # ------------------------------------------------------------------
    # Corrective action plans
    # ------------------------------------------------------------------
    def create_corrective_action_plan(self, payload, headers):
        return self._request("POST", "/corrective-action-plans", payload, headers)

    def list_corrective_action_plans(self, headers, params=None):
        return self._request("GET", "/corrective-action-plans",
                             headers=headers, params=params)

    def get_corrective_action_plan(self, cap_id, headers):
        return self._request("GET", f"/corrective-action-plans/{cap_id}",
                             headers=headers)

    def activate_plan(self, cap_id, headers):
        return self._request("POST",
                             f"/corrective-action-plans/{cap_id}/activate",
                             {}, headers)

    def begin_effectiveness_check(self, cap_id, headers):
        return self._request(
            "POST",
            f"/corrective-action-plans/{cap_id}/begin-effectiveness-check",
            {}, headers)

    def verify_plan(self, cap_id, headers):
        return self._request("POST",
                             f"/corrective-action-plans/{cap_id}/verify",
                             {}, headers)

    def mark_plan_ineffective(self, cap_id, headers):
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/mark-ineffective",
            {}, headers)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    def get_success_rates(self, headers, params=None):
        return self._request("GET", "/analytics/success-rates",
                             headers=headers, params=params)


api_client = ApiClient()
