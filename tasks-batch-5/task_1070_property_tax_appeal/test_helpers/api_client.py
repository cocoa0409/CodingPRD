"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Analyst ----
    def create_analyst(self, payload, headers):
        return self._request("POST", "/api/analysts", payload, headers)

    def get_analyst(self, analyst_id, headers):
        return self._request("GET", f"/api/analysts/{analyst_id}", headers=headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/api/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}", headers=headers)

    # ---- Jurisdiction ----
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/api/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/api/jurisdictions/{jurisdiction_id}", headers=headers)

    # ---- FeeAgreement ----
    def create_fee_agreement(self, payload, headers):
        return self._request("POST", "/api/fee-agreements", payload, headers)

    def get_fee_agreement(self, fee_agreement_id, headers):
        return self._request("GET", f"/api/fee-agreements/{fee_agreement_id}", headers=headers)

    def list_fee_agreements(self, headers, params=None):
        return self._request("GET", "/api/fee-agreements", headers=headers, params=params)

    def accept_fee_agreement(self, fee_agreement_id, headers):
        return self._request("POST", f"/api/fee-agreements/{fee_agreement_id}/accept", headers=headers)

    # ---- Parcel ----
    def create_parcel(self, payload, headers):
        return self._request("POST", "/api/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/api/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/api/parcels", headers=headers, params=params)

    # ---- Assessment ----
    def create_assessment(self, payload, headers):
        return self._request("POST", "/api/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/api/assessments", headers=headers, params=params)

    # ---- ExemptionClaim ----
    def create_exemption_claim(self, payload, headers):
        return self._request("POST", "/api/exemption-claims", payload, headers)

    def get_exemption_claim(self, exemption_claim_id, headers):
        return self._request("GET", f"/api/exemption-claims/{exemption_claim_id}", headers=headers)

    def list_exemption_claims(self, headers, params=None):
        return self._request("GET", "/api/exemption-claims", headers=headers, params=params)

    def submit_exemption_claim(self, exemption_claim_id, headers):
        return self._request("POST", f"/api/exemption-claims/{exemption_claim_id}/submit", headers=headers)

    def decide_exemption_claim(self, exemption_claim_id, payload, headers):
        return self._request("POST", f"/api/exemption-claims/{exemption_claim_id}/decide", payload, headers)

    # ---- Appeal ----
    def create_appeal(self, payload, headers):
        return self._request("POST", "/api/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/api/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/api/appeals", headers=headers, params=params)

    def create_evidence(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/evidence", payload, headers)

    def list_evidence(self, appeal_id, headers, params=None):
        return self._request("GET", f"/api/appeals/{appeal_id}/evidence", headers=headers, params=params)

    def file_appeal(self, appeal_id, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/file", headers=headers)

    def request_informal_review(self, appeal_id, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/request-informal-review", headers=headers)

    def schedule_hearing(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/hearings", payload, headers)

    def record_decision(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/record-decision", payload, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/withdraw", headers=headers)

    # ---- SettlementOffer ----
    def create_settlement_offer(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/settlement-offers", payload, headers)

    def list_settlement_offers(self, appeal_id, headers, params=None):
        return self._request("GET", f"/api/appeals/{appeal_id}/settlement-offers", headers=headers, params=params)

    def get_settlement_offer(self, offer_id, headers):
        return self._request("GET", f"/api/settlement-offers/{offer_id}", headers=headers)

    def counter_settlement_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/api/settlement-offers/{offer_id}/counter", payload, headers)

    def accept_settlement_offer(self, offer_id, headers):
        return self._request("POST", f"/api/settlement-offers/{offer_id}/accept", headers=headers)

    def reject_settlement_offer(self, offer_id, headers):
        return self._request("POST", f"/api/settlement-offers/{offer_id}/reject", headers=headers)

    # ---- Hearing ----
    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/api/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/api/hearings", headers=headers, params=params)

    def hold_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/api/hearings/{hearing_id}/hold", payload, headers)

    def cancel_hearing(self, hearing_id, headers):
        return self._request("POST", f"/api/hearings/{hearing_id}/cancel", headers=headers)

    # ---- Invoice / Payment ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", headers=headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/payments", payload, headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/api/invoices/{invoice_id}/payments", headers=headers, params=params)


api_client = ApiClient()
