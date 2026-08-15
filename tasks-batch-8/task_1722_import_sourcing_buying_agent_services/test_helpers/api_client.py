"""API client: one method per endpoint defined in the PRD.

All methods return the raw requests.Response so tests can assert on status
codes and envelopes via the framework validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Platform bootstrap ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/sourcing/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/sourcing/buyers/{buyer_id}", headers=headers)

    def create_agent(self, payload, headers):
        return self._request("POST", "/sourcing/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/sourcing/agents/{agent_id}", headers=headers)

    def create_inspector(self, payload, headers):
        return self._request("POST", "/sourcing/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/sourcing/inspectors/{inspector_id}", headers=headers)

    # --- Factory registry ---
    def create_factory(self, payload, headers):
        return self._request("POST", "/sourcing/factories", payload, headers)

    def get_factory(self, factory_id, headers):
        return self._request("GET", f"/sourcing/factories/{factory_id}", headers=headers)

    # --- Audits ---
    def create_audit(self, factory_id, payload, headers):
        return self._request("POST", f"/sourcing/factories/{factory_id}/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/sourcing/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/sourcing/audits/{audit_id}", headers=headers)

    def approve_audit(self, audit_id, headers):
        return self._request("POST", f"/sourcing/audits/{audit_id}/approve", {}, headers)

    def reject_audit(self, audit_id, headers):
        return self._request("POST", f"/sourcing/audits/{audit_id}/reject", {}, headers)

    # --- Compliance documents ---
    def create_compliance_document(self, factory_id, payload, headers):
        return self._request(
            "POST", f"/sourcing/factories/{factory_id}/compliance-documents", payload, headers
        )

    def list_compliance_documents(self, headers, params=None):
        return self._request("GET", "/sourcing/compliance-documents", headers=headers, params=params)

    def get_compliance_document(self, doc_id, headers):
        return self._request("GET", f"/sourcing/compliance-documents/{doc_id}", headers=headers)

    def verify_compliance_document(self, doc_id, headers):
        return self._request("POST", f"/sourcing/compliance-documents/{doc_id}/verify", {}, headers)

    def reject_compliance_document(self, doc_id, headers):
        return self._request("POST", f"/sourcing/compliance-documents/{doc_id}/reject", {}, headers)

    # --- Sourcing requests ---
    def create_sourcing_request(self, payload, headers):
        return self._request("POST", "/sourcing/sourcing-requests", payload, headers)

    def list_sourcing_requests(self, headers, params=None):
        return self._request("GET", "/sourcing/sourcing-requests", headers=headers, params=params)

    def get_sourcing_request(self, sr_id, headers):
        return self._request("GET", f"/sourcing/sourcing-requests/{sr_id}", headers=headers)

    def cancel_sourcing_request(self, sr_id, headers):
        return self._request("POST", f"/sourcing/sourcing-requests/{sr_id}/cancel", {}, headers)

    # --- Samples ---
    def create_sample(self, sr_id, payload, headers):
        return self._request("POST", f"/sourcing/sourcing-requests/{sr_id}/samples", payload, headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/sourcing/samples", headers=headers, params=params)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/sourcing/samples/{sample_id}", headers=headers)

    def review_sample(self, sample_id, payload, headers):
        return self._request("POST", f"/sourcing/samples/{sample_id}/review", payload, headers)

    def resubmit_sample(self, sample_id, payload, headers):
        return self._request("POST", f"/sourcing/samples/{sample_id}/resubmit", payload, headers)

    # --- Quotations ---
    def create_quotation(self, sr_id, payload, headers):
        return self._request("POST", f"/sourcing/sourcing-requests/{sr_id}/quotations", payload, headers)

    def list_quotations(self, headers, params=None):
        return self._request("GET", "/sourcing/quotations", headers=headers, params=params)

    def get_quotation(self, quotation_id, headers):
        return self._request("GET", f"/sourcing/quotations/{quotation_id}", headers=headers)

    def counter_quotation(self, quotation_id, payload, headers):
        return self._request("POST", f"/sourcing/quotations/{quotation_id}/counter", payload, headers)

    def accept_quotation(self, quotation_id, payload, headers):
        return self._request("POST", f"/sourcing/quotations/{quotation_id}/accept", payload, headers)

    def reject_quotation(self, quotation_id, headers):
        return self._request("POST", f"/sourcing/quotations/{quotation_id}/reject", {}, headers)

    # --- Purchase orders ---
    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/sourcing/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/sourcing/purchase-orders/{po_id}", headers=headers)

    def amend_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/sourcing/purchase-orders/{po_id}/amend", payload, headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/sourcing/purchase-orders/{po_id}/cancel", {}, headers)

    # --- Milestones ---
    def create_milestone(self, po_id, payload, headers):
        return self._request("POST", f"/sourcing/purchase-orders/{po_id}/milestones", payload, headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/sourcing/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/sourcing/milestones/{milestone_id}", headers=headers)

    def submit_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/sourcing/milestones/{milestone_id}/submit", payload, headers)

    def verify_milestone(self, milestone_id, headers):
        return self._request("POST", f"/sourcing/milestones/{milestone_id}/verify", {}, headers)

    def reject_milestone(self, milestone_id, headers):
        return self._request("POST", f"/sourcing/milestones/{milestone_id}/reject", {}, headers)

    # --- Inspections ---
    def create_inspection(self, po_id, payload, headers):
        return self._request("POST", f"/sourcing/purchase-orders/{po_id}/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/sourcing/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/sourcing/inspections/{inspection_id}", headers=headers)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/sourcing/inspections/{inspection_id}/record-result", payload, headers
        )

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/sourcing/inspections/{inspection_id}/cancel", {}, headers)

    # --- Shipments ---
    def create_shipment(self, po_id, payload, headers):
        return self._request("POST", f"/sourcing/purchase-orders/{po_id}/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/sourcing/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/sourcing/shipments/{shipment_id}", headers=headers)

    def handover_shipment_documents(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/sourcing/shipments/{shipment_id}/handover-documents", payload, headers
        )

    def confirm_shipment_receipt(self, shipment_id, headers):
        return self._request("POST", f"/sourcing/shipments/{shipment_id}/confirm-receipt", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/sourcing/shipments/{shipment_id}/cancel", {}, headers)

    # --- Quality claims ---
    def create_quality_claim(self, po_id, payload, headers):
        return self._request("POST", f"/sourcing/purchase-orders/{po_id}/quality-claims", payload, headers)

    def list_quality_claims(self, headers, params=None):
        return self._request("GET", "/sourcing/quality-claims", headers=headers, params=params)

    def get_quality_claim(self, claim_id, headers):
        return self._request("GET", f"/sourcing/quality-claims/{claim_id}", headers=headers)

    def approve_quality_claim(self, claim_id, headers):
        return self._request("POST", f"/sourcing/quality-claims/{claim_id}/approve", {}, headers)

    def reject_quality_claim(self, claim_id, headers):
        return self._request("POST", f"/sourcing/quality-claims/{claim_id}/reject", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/sourcing/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
