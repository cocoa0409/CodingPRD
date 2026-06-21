"""API client for the Contract Lifecycle Management API.

One method per endpoint defined in the PRD. Subclasses GenericApiClient so the
base _request() (URL construction, session, query-vs-body routing) is inherited.
"""
import time

from requests.exceptions import ConnectionError as RequestsConnectionError

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        """Override the base request to harden against per-test-server reboots.

        Under ``--isolation per-test-server`` the server is restarted before every
        test, so a keep-alive socket left in the client session's connection pool
        from a prior boot can fire a stale-connection ``BadStatusLine`` (surfaced as
        requests.exceptions.ConnectionError) on the first request of the next test.
        We (1) force ``Connection: close`` so the server never hands back a socket
        we would reuse across reboots, and (2) retry once on ConnectionError after a
        short pause to ride out the rare same-instant reboot race. This is purely an
        HTTP-transport hardening; it changes no request semantics.
        """
        merged_headers = dict(headers or {})
        merged_headers.setdefault("Connection", "close")
        try:
            return super()._request(method, path, payload, merged_headers, params)
        except RequestsConnectionError:
            time.sleep(0.25)
            return super()._request(method, path, payload, merged_headers, params)

    # ─── Organizations ────────────────────────────────────────────────
    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/organizations/{org_id}", headers=headers)

    # ─── Clause templates ─────────────────────────────────────────────
    def create_clause_template(self, payload, headers):
        return self._request("POST", "/clause-templates", payload, headers)

    def get_clause_template(self, clause_id, headers):
        return self._request("GET", f"/clause-templates/{clause_id}", headers=headers)

    def list_clause_templates(self, headers, params=None):
        return self._request("GET", "/clause-templates", headers=headers, params=params)

    def retire_clause_template(self, clause_id, headers):
        return self._request("POST", f"/clause-templates/{clause_id}/retire", headers=headers)

    # ─── Contract templates ───────────────────────────────────────────
    def create_contract_template(self, payload, headers):
        return self._request("POST", "/contract-templates", payload, headers)

    def get_contract_template(self, template_id, headers):
        return self._request("GET", f"/contract-templates/{template_id}", headers=headers)

    def list_contract_templates(self, headers, params=None):
        return self._request("GET", "/contract-templates", headers=headers, params=params)

    def retire_contract_template(self, template_id, headers):
        return self._request("POST", f"/contract-templates/{template_id}/retire", headers=headers)

    # ─── Contracts ────────────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def create_version(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/versions", payload, headers)

    def list_versions(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/versions", headers=headers, params=params)

    def get_version(self, version_id, headers):
        return self._request("GET", f"/contract-versions/{version_id}", headers=headers)

    def submit_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/submit", payload, headers)

    def send_for_signature(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/send-for-signature", payload, headers)

    def renew_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/renew", payload, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", payload, headers)

    def cancel_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/cancel", payload, headers)

    def get_cost_estimate(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/cost-estimate", headers=headers)

    # ─── Approval workflows / steps ───────────────────────────────────
    def list_contract_approval_workflows(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/approval-workflows", headers=headers, params=params)

    def get_approval_workflow(self, workflow_id, headers):
        return self._request("GET", f"/approval-workflows/{workflow_id}", headers=headers)

    def list_approval_workflows(self, headers, params=None):
        return self._request("GET", "/approval-workflows", headers=headers, params=params)

    def create_approval_step(self, workflow_id, payload, headers):
        return self._request("POST", f"/approval-workflows/{workflow_id}/steps", payload, headers)

    def list_approval_steps(self, workflow_id, headers, params=None):
        return self._request("GET", f"/approval-workflows/{workflow_id}/steps", headers=headers, params=params)

    # ─── Signature requests ───────────────────────────────────────────
    def list_signature_requests(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/signature-requests", headers=headers, params=params)

    def sign_signature_request(self, signature_request_id, headers):
        return self._request("POST", f"/signature-requests/{signature_request_id}/sign", headers=headers)

    def decline_signature_request(self, signature_request_id, headers):
        return self._request("POST", f"/signature-requests/{signature_request_id}/decline", headers=headers)

    # ─── Obligations ──────────────────────────────────────────────────
    def create_obligation(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/obligations", payload, headers)

    def list_obligations(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/obligations", headers=headers, params=params)

    def fulfill_obligation(self, obligation_id, headers):
        return self._request("POST", f"/obligations/{obligation_id}/fulfill", headers=headers)

    def waive_obligation(self, obligation_id, headers):
        return self._request("POST", f"/obligations/{obligation_id}/waive", headers=headers)

    # ─── Deviation approvals ──────────────────────────────────────────
    def create_deviation_approval(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/deviation-approvals", payload, headers)

    def list_contract_deviation_approvals(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/deviation-approvals", headers=headers, params=params)

    def decide_deviation_approval(self, deviation_approval_id, payload, headers):
        return self._request("POST", f"/deviation-approvals/{deviation_approval_id}/decide", payload, headers)

    def get_deviation_approval(self, deviation_approval_id, headers):
        return self._request("GET", f"/deviation-approvals/{deviation_approval_id}", headers=headers)

    def list_deviation_approvals(self, headers, params=None):
        return self._request("GET", "/deviation-approvals", headers=headers, params=params)

    # ─── Renewal alerts / audit events ────────────────────────────────
    def list_renewal_alerts(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/renewal-alerts", headers=headers, params=params)

    def list_audit_events(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/audit-events", headers=headers, params=params)

    # ─── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
