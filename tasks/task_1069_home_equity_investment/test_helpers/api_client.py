"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Fund ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/hei/funds", payload, headers)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/hei/funds/{fund_id}", headers=headers)

    # --- Homeowner ---
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/hei/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"/hei/homeowners/{homeowner_id}", headers=headers)

    # --- Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/hei/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/hei/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/hei/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/hei/applications/{application_id}/submit", {}, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/hei/applications/{application_id}/decision", payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/hei/applications/{application_id}/withdraw", {}, headers)

    # --- Valuation ---
    def create_valuation(self, application_id, payload, headers):
        return self._request("POST", f"/hei/applications/{application_id}/valuations", payload, headers)

    def get_valuation(self, valuation_id, headers):
        return self._request("GET", f"/hei/valuations/{valuation_id}", headers=headers)

    def list_valuations(self, headers, params=None):
        return self._request("GET", "/hei/valuations", headers=headers, params=params)

    # --- Appraiser ---
    def create_appraiser(self, payload, headers):
        return self._request("POST", "/hei/appraisers", payload, headers)

    def get_appraiser(self, appraiser_id, headers):
        return self._request("GET", f"/hei/appraisers/{appraiser_id}", headers=headers)

    # --- AppraisalAppointment ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/hei/appraisal-appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/hei/appraisal-appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/hei/appraisal-appointments", headers=headers, params=params)

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/hei/appraisal-appointments/{appointment_id}/complete", payload, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/hei/appraisal-appointments/{appointment_id}/cancel", {}, headers)

    # --- Offer ---
    def create_offer(self, application_id, payload, headers):
        return self._request("POST", f"/hei/applications/{application_id}/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/hei/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/hei/offers", headers=headers, params=params)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/hei/offers/{offer_id}/accept", {}, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/hei/offers/{offer_id}/decline", {}, headers)

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/hei/offers/{offer_id}/counter", payload, headers)

    def represent_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/hei/offers/{offer_id}/represent", payload, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/hei/offers/{offer_id}/withdraw", {}, headers)

    # --- Agreement ---
    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/hei/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/hei/agreements", headers=headers, params=params)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/hei/agreements/{agreement_id}/activate", {}, headers)

    def initiate_exit(self, agreement_id, headers):
        return self._request("POST", f"/hei/agreements/{agreement_id}/initiate-exit", {}, headers)

    def default_agreement(self, agreement_id, headers):
        return self._request("POST", f"/hei/agreements/{agreement_id}/default", {}, headers)

    # --- Lien ---
    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/hei/liens/{lien_id}", headers=headers)

    def list_liens(self, headers, params=None):
        return self._request("GET", "/hei/liens", headers=headers, params=params)

    def record_lien(self, lien_id, payload, headers):
        return self._request("POST", f"/hei/liens/{lien_id}/record", payload, headers)

    # --- Inspector ---
    def create_inspector(self, payload, headers):
        return self._request("POST", "/hei/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/hei/inspectors/{inspector_id}", headers=headers)

    # --- Inspection ---
    def create_inspection(self, agreement_id, payload, headers):
        return self._request("POST", f"/hei/agreements/{agreement_id}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/hei/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/hei/inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/hei/inspections/{inspection_id}/complete", payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/hei/inspections/{inspection_id}/cancel", {}, headers)

    # --- Settlement ---
    def create_settlement(self, agreement_id, payload, headers):
        return self._request("POST", f"/hei/agreements/{agreement_id}/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/hei/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/hei/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/hei/settlements/{settlement_id}/finalize", {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/hei/settlements/{settlement_id}/dispute", payload, headers)

    # --- Dispute ---
    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/hei/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/hei/disputes", headers=headers, params=params)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/hei/disputes/{dispute_id}/resolve", payload, headers)

    def reject_dispute(self, dispute_id, headers):
        return self._request("POST", f"/hei/disputes/{dispute_id}/reject", {}, headers)


api_client = ApiClient()
