"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        try:
            return super()._request(method, path, payload, headers, params)
        except requests.exceptions.ConnectionError:
            # The harness's per-test-server isolation SIGKILLs and reboots the
            # API server before every test; this module-level session's pooled
            # keep-alive connection to the killed process can then be reused
            # for the first request of the next test and severed mid-flight
            # (RemoteDisconnected). Drop the stale pool and retry once on a
            # fresh connection. If the server is genuinely down the retry
            # raises ConnectionError again, so no real failure is masked.
            self.session.close()
            self.session = requests.Session()
            return super()._request(method, path, payload, headers, params)
    # --- Clock / test-driving ---
    def advance_day(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/_clock/advance_day", payload, headers)

    # --- Tenant ---
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tid, headers):
        return self._request("GET", f"/tenants/{tid}", headers=headers)

    # --- JurisdictionRule ---
    def create_jurisdiction_rule(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/jurisdiction_rules", payload, headers)

    def list_jurisdiction_rules(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/jurisdiction_rules", headers=headers, params=params)

    def get_jurisdiction_rule(self, tid, rule_id, headers):
        return self._request("GET", f"/tenants/{tid}/jurisdiction_rules/{rule_id}", headers=headers)

    # --- ExemptionReason ---
    def create_exemption_reason(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/exemption_reasons", payload, headers)

    def list_exemption_reasons(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/exemption_reasons", headers=headers, params=params)

    # --- Customer ---
    def create_customer(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/customers", payload, headers)

    def list_customers(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/customers", headers=headers, params=params)

    def get_customer(self, tid, customer_id, headers):
        return self._request("GET", f"/tenants/{tid}/customers/{customer_id}", headers=headers)

    def complete_onboarding(self, tid, customer_id, headers):
        return self._request("POST", f"/tenants/{tid}/customers/{customer_id}/complete_onboarding", headers=headers)

    # --- ExemptionCertificate / CertificateVersion ---
    def create_certificate(self, tid, customer_id, payload, headers):
        return self._request("POST", f"/tenants/{tid}/customers/{customer_id}/certificates", payload, headers)

    def list_certificates(self, tid, customer_id, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/customers/{customer_id}/certificates", headers=headers, params=params)

    def get_certificate(self, tid, cert_id, headers):
        return self._request("GET", f"/tenants/{tid}/certificates/{cert_id}", headers=headers)

    def upload_certificate_version(self, tid, cert_id, payload, headers):
        return self._request("POST", f"/tenants/{tid}/certificates/{cert_id}/versions", payload, headers)

    def list_certificate_versions(self, tid, cert_id, headers):
        return self._request("GET", f"/tenants/{tid}/certificates/{cert_id}/versions", headers=headers)

    def submit_certificate(self, tid, cert_id, headers):
        return self._request("POST", f"/tenants/{tid}/certificates/{cert_id}/submit", headers=headers)

    def begin_review_certificate(self, tid, cert_id, headers):
        return self._request("POST", f"/tenants/{tid}/certificates/{cert_id}/begin_review", headers=headers)

    def approve_certificate(self, tid, cert_id, payload, headers):
        return self._request("POST", f"/tenants/{tid}/certificates/{cert_id}/approve", payload, headers)

    def reject_certificate(self, tid, cert_id, headers):
        return self._request("POST", f"/tenants/{tid}/certificates/{cert_id}/reject", headers=headers)

    def suspend_certificate(self, tid, cert_id, headers):
        return self._request("POST", f"/tenants/{tid}/certificates/{cert_id}/suspend", headers=headers)

    def reinstate_certificate(self, tid, cert_id, headers):
        return self._request("POST", f"/tenants/{tid}/certificates/{cert_id}/reinstate", headers=headers)

    def revoke_certificate(self, tid, cert_id, headers):
        return self._request("POST", f"/tenants/{tid}/certificates/{cert_id}/revoke", headers=headers)

    # --- Order / OrderLine ---
    def create_order(self, tid, customer_id, payload, headers):
        return self._request("POST", f"/tenants/{tid}/customers/{customer_id}/orders", payload, headers)

    def get_order(self, tid, order_id, headers):
        return self._request("GET", f"/tenants/{tid}/orders/{order_id}", headers=headers)

    def list_orders(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/orders", headers=headers, params=params)

    def add_order_line(self, tid, order_id, payload, headers):
        return self._request("POST", f"/tenants/{tid}/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, tid, order_id, headers):
        return self._request("GET", f"/tenants/{tid}/orders/{order_id}/lines", headers=headers)

    def submit_order(self, tid, order_id, headers):
        return self._request("POST", f"/tenants/{tid}/orders/{order_id}/submit", headers=headers)

    def ship_order(self, tid, order_id, headers):
        return self._request("POST", f"/tenants/{tid}/orders/{order_id}/ship", headers=headers)

    def invoice_order(self, tid, order_id, headers):
        return self._request("POST", f"/tenants/{tid}/orders/{order_id}/invoice", headers=headers)

    def cancel_order(self, tid, order_id, headers):
        return self._request("POST", f"/tenants/{tid}/orders/{order_id}/cancel", headers=headers)

    # --- DropShipLink ---
    def create_drop_ship_link(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/drop_ship_links", payload, headers)

    def get_drop_ship_link(self, tid, link_id, headers):
        return self._request("GET", f"/tenants/{tid}/drop_ship_links/{link_id}", headers=headers)

    def verify_drop_ship_link(self, tid, link_id, headers):
        return self._request("POST", f"/tenants/{tid}/drop_ship_links/{link_id}/verify", headers=headers)

    def reject_drop_ship_link(self, tid, link_id, headers):
        return self._request("POST", f"/tenants/{tid}/drop_ship_links/{link_id}/reject", headers=headers)

    # --- AuditCampaign / AuditSample ---
    def create_audit_campaign(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/audit_campaigns", payload, headers)

    def get_audit_campaign(self, tid, campaign_id, headers):
        return self._request("GET", f"/tenants/{tid}/audit_campaigns/{campaign_id}", headers=headers)

    def open_audit_campaign(self, tid, campaign_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_campaigns/{campaign_id}/open", headers=headers)

    def sample_audit_campaign(self, tid, campaign_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_campaigns/{campaign_id}/sample", headers=headers)

    def list_audit_samples(self, tid, campaign_id, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/audit_campaigns/{campaign_id}/samples", headers=headers, params=params)

    def resample_audit_campaign(self, tid, campaign_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_campaigns/{campaign_id}/resample", headers=headers)

    def begin_defense_assembly(self, tid, campaign_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_campaigns/{campaign_id}/begin_defense_assembly", headers=headers)

    def close_audit_campaign(self, tid, campaign_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_campaigns/{campaign_id}/close", headers=headers)

    def cancel_audit_campaign(self, tid, campaign_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_campaigns/{campaign_id}/cancel", headers=headers)

    def get_audit_sample(self, tid, sample_id, headers):
        return self._request("GET", f"/tenants/{tid}/audit_samples/{sample_id}", headers=headers)

    def request_docs(self, tid, sample_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_samples/{sample_id}/request_docs", headers=headers)

    def receive_docs(self, tid, sample_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_samples/{sample_id}/receive_docs", headers=headers)

    def request_rework(self, tid, sample_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_samples/{sample_id}/request_rework", headers=headers)

    def pass_sample(self, tid, sample_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_samples/{sample_id}/pass", headers=headers)

    def fail_sample(self, tid, sample_id, payload, headers):
        return self._request("POST", f"/tenants/{tid}/audit_samples/{sample_id}/fail", payload, headers)

    def waive_sample(self, tid, sample_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_samples/{sample_id}/waive", headers=headers)

    # --- RemediationAction ---
    def get_remediation_action(self, tid, action_id, headers):
        return self._request("GET", f"/tenants/{tid}/remediation_actions/{action_id}", headers=headers)

    def list_remediation_actions(self, tid, sample_id, headers):
        return self._request("GET", f"/tenants/{tid}/audit_samples/{sample_id}/remediation_actions", headers=headers)

    def create_remediation_action(self, tid, sample_id, payload, headers):
        return self._request("POST", f"/tenants/{tid}/audit_samples/{sample_id}/remediation_actions", payload, headers)

    def begin_remediation_action(self, tid, action_id, headers):
        return self._request("POST", f"/tenants/{tid}/remediation_actions/{action_id}/begin", headers=headers)

    def escalate_remediation_action(self, tid, action_id, headers):
        return self._request("POST", f"/tenants/{tid}/remediation_actions/{action_id}/escalate", headers=headers)

    def resolve_remediation_action(self, tid, action_id, payload, headers):
        return self._request("POST", f"/tenants/{tid}/remediation_actions/{action_id}/resolve", payload, headers)

    # --- OutreachCampaign / OutreachNotice ---
    def create_outreach_campaign(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/outreach_campaigns", payload, headers)

    def get_outreach_campaign(self, tid, campaign_id, headers):
        return self._request("GET", f"/tenants/{tid}/outreach_campaigns/{campaign_id}", headers=headers)

    def schedule_outreach_campaign(self, tid, campaign_id, headers):
        return self._request("POST", f"/tenants/{tid}/outreach_campaigns/{campaign_id}/schedule", headers=headers)

    def cancel_outreach_campaign(self, tid, campaign_id, headers):
        return self._request("POST", f"/tenants/{tid}/outreach_campaigns/{campaign_id}/cancel", headers=headers)

    def list_outreach_notices(self, tid, campaign_id, headers):
        return self._request("GET", f"/tenants/{tid}/outreach_campaigns/{campaign_id}/notices", headers=headers)

    # --- AuditDefensePacket ---
    def get_defense_packet(self, tid, campaign_id, headers):
        return self._request("GET", f"/tenants/{tid}/audit_campaigns/{campaign_id}/defense_packet", headers=headers)

    def assemble_defense_packet(self, tid, packet_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_defense_packets/{packet_id}/assemble", headers=headers)

    def deliver_defense_packet(self, tid, packet_id, headers):
        return self._request("POST", f"/tenants/{tid}/audit_defense_packets/{packet_id}/deliver", headers=headers)


api_client = ApiClient()
