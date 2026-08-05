"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Parties ---
    def create_landlord(self, payload, headers):
        return self._request("POST", "/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/landlords/{landlord_id}", headers=headers)

    def create_leaseholder(self, payload, headers):
        return self._request("POST", "/leaseholders", payload, headers)

    def get_leaseholder(self, leaseholder_id, headers):
        return self._request("GET", f"/leaseholders/{leaseholder_id}", headers=headers)

    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # --- Leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def submit_lease_verification(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/submit-verification", {}, headers)

    def verify_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/verify", payload, headers)

    def amend_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/amend", payload, headers)

    # --- Listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def request_listing_approval(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/request-approval", {}, headers)

    def approve_listing(self, listing_id, headers, payload=None):
        return self._request("POST", f"/listings/{listing_id}/approve", payload or {}, headers)

    def decline_listing(self, listing_id, headers, payload=None):
        return self._request("POST", f"/listings/{listing_id}/decline", payload or {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/withdraw", {}, headers)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def start_screening(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/start-screening", {}, headers)

    def request_info(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/request-info", {}, headers)

    def resubmit_info(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/resubmit-info", {}, headers)

    def create_screening_report(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/screening-report", payload, headers)

    def list_screening_reports(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/screening-report", headers=headers, params=params)

    def match_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/match", {}, headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/decline", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    # --- Agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def send_for_signature(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/send-for-signature", {}, headers)

    def create_signature(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/signatures", payload, headers)

    def list_signatures(self, agreement_id, headers, params=None):
        return self._request("GET", f"/agreements/{agreement_id}/signatures", headers=headers, params=params)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/activate", {}, headers)

    def complete_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/complete", {}, headers)

    def void_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/void", {}, headers)

    # --- Settlements ---
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def fund_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/fund", payload, headers)

    def handoff_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/handoff", payload, headers)

    def release_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/release", {}, headers)

    # --- Handoff appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/handoff-appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/handoff-appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/handoff-appointments", headers=headers, params=params)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/handoff-appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/handoff-appointments/{appointment_id}/cancel", {}, headers)

    # --- Disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/review", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # --- Fees ---
    def create_fee(self, payload, headers):
        return self._request("POST", "/fees", payload, headers)

    def get_fee(self, fee_id, headers):
        return self._request("GET", f"/fees/{fee_id}", headers=headers)

    def list_fees(self, headers, params=None):
        return self._request("GET", "/fees", headers=headers, params=params)

    def charge_fee(self, fee_id, headers):
        return self._request("POST", f"/fees/{fee_id}/charge", {}, headers)

    def waive_fee(self, fee_id, headers):
        return self._request("POST", f"/fees/{fee_id}/waive", {}, headers)

    def refund_fee(self, fee_id, headers):
        return self._request("POST", f"/fees/{fee_id}/refund", {}, headers)


api_client = ApiClient()
