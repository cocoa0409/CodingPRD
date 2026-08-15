"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Loans ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/property-solutions/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/property-solutions/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/property-solutions/loans", headers=headers, params=params)

    # --- Borrowers ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/property-solutions/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/property-solutions/borrowers/{borrower_id}", headers=headers)

    # --- Properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/property-solutions/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/property-solutions/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/property-solutions/properties", headers=headers, params=params)

    # --- Workout cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/property-solutions/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/property-solutions/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/property-solutions/cases", headers=headers, params=params)

    def submit_case(self, case_id, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/submit", headers=headers)

    def evaluate_eligibility(self, case_id, payload, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/evaluate-eligibility", payload, headers)

    def grant_marketing_exception(self, case_id, payload, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/marketing-exception", payload, headers)

    def certify_marketing(self, case_id, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/certify-marketing", headers=headers)

    def certify_title(self, case_id, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/certify-title", headers=headers)

    def escalate_holdover(self, case_id, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/escalate-holdover", headers=headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/withdraw", headers=headers)

    # --- Case sub-resource reads ---
    def list_case_listings(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/listings", headers=headers, params=params)

    def list_case_title_commitments(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/title-commitments", headers=headers, params=params)

    def list_case_agreements(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/agreements", headers=headers, params=params)

    def list_case_inspection_appointments(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/inspection-appointments", headers=headers, params=params)

    def list_case_inspection_reports(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/inspection-reports", headers=headers, params=params)

    def list_case_disbursements(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/disbursements", headers=headers, params=params)

    def list_case_deficiency_waivers(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/deficiency-waivers", headers=headers, params=params)

    def list_case_deed_recordings(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/deed-recordings", headers=headers, params=params)

    def list_case_eviction_cases(self, case_id, headers, params=None):
        return self._request("GET", f"/property-solutions/cases/{case_id}/eviction-cases", headers=headers, params=params)

    # --- Marketing listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/property-solutions/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/property-solutions/listings/{listing_id}", headers=headers)

    def suspend_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/property-solutions/listings/{listing_id}/suspend", payload, headers)

    def resume_listing(self, listing_id, headers):
        return self._request("POST", f"/property-solutions/listings/{listing_id}/resume", headers=headers)

    def close_listing(self, listing_id, headers):
        return self._request("POST", f"/property-solutions/listings/{listing_id}/close", headers=headers)

    def list_listing_suspensions(self, listing_id, headers, params=None):
        return self._request("GET", f"/property-solutions/listings/{listing_id}/suspensions", headers=headers, params=params)

    # --- Title ---
    def create_title_commitment(self, payload, headers):
        return self._request("POST", "/property-solutions/title-commitments", payload, headers)

    def get_title_commitment(self, commitment_id, headers):
        return self._request("GET", f"/property-solutions/title-commitments/{commitment_id}", headers=headers)

    def receive_title_commitment(self, commitment_id, payload, headers):
        return self._request("POST", f"/property-solutions/title-commitments/{commitment_id}/receive", payload, headers)

    def add_lien(self, commitment_id, payload, headers):
        return self._request("POST", f"/property-solutions/title-commitments/{commitment_id}/liens", payload, headers)

    def list_liens(self, commitment_id, headers, params=None):
        return self._request("GET", f"/property-solutions/title-commitments/{commitment_id}/liens", headers=headers, params=params)

    def release_lien(self, commitment_id, payload, headers):
        return self._request("POST", f"/property-solutions/title-commitments/{commitment_id}/lien-releases", payload, headers)

    # --- Settlement agreements ---
    def create_agreement(self, case_id, payload, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/property-solutions/agreements/{agreement_id}", headers=headers)

    def offer_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/property-solutions/agreements/{agreement_id}/offer", payload, headers)

    def counter_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/property-solutions/agreements/{agreement_id}/counter", payload, headers)

    def reoffer_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/property-solutions/agreements/{agreement_id}/reoffer", payload, headers)

    def accept_agreement(self, agreement_id, headers):
        return self._request("POST", f"/property-solutions/agreements/{agreement_id}/accept", headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/property-solutions/agreements/{agreement_id}/terminate", headers=headers)

    def list_agreement_disbursements(self, agreement_id, headers, params=None):
        return self._request("GET", f"/property-solutions/agreements/{agreement_id}/disbursements", headers=headers, params=params)

    # --- Inspection appointments & reports ---
    def create_inspection_appointment(self, payload, headers):
        return self._request("POST", "/property-solutions/inspection-appointments", payload, headers)

    def get_inspection_appointment(self, appointment_id, headers):
        return self._request("GET", f"/property-solutions/inspection-appointments/{appointment_id}", headers=headers)

    def cancel_inspection_appointment(self, appointment_id, headers):
        return self._request("POST", f"/property-solutions/inspection-appointments/{appointment_id}/cancel", headers=headers)

    def no_access_inspection_appointment(self, appointment_id, headers):
        return self._request("POST", f"/property-solutions/inspection-appointments/{appointment_id}/no-access", headers=headers)

    def create_inspection_report(self, appointment_id, payload, headers):
        return self._request("POST", f"/property-solutions/inspection-appointments/{appointment_id}/reports", payload, headers)

    def list_appointment_reports(self, appointment_id, headers, params=None):
        return self._request("GET", f"/property-solutions/inspection-appointments/{appointment_id}/reports", headers=headers, params=params)

    def get_inspection_report(self, report_id, headers):
        return self._request("GET", f"/property-solutions/inspection-reports/{report_id}", headers=headers)

    def submit_inspection_report(self, report_id, headers):
        return self._request("POST", f"/property-solutions/inspection-reports/{report_id}/submit", headers=headers)

    # --- Disbursements ---
    def create_disbursement(self, case_id, payload, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/property-solutions/disbursements/{disbursement_id}", headers=headers)

    def approve_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/property-solutions/disbursements/{disbursement_id}/approve", headers=headers)

    def release_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/property-solutions/disbursements/{disbursement_id}/release", headers=headers)

    def void_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/property-solutions/disbursements/{disbursement_id}/void", headers=headers)

    def clawback_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/property-solutions/disbursements/{disbursement_id}/clawback", headers=headers)

    # --- Deficiency waivers ---
    def get_deficiency_waiver(self, waiver_id, headers):
        return self._request("GET", f"/property-solutions/deficiency-waivers/{waiver_id}", headers=headers)

    def document_deficiency_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/property-solutions/deficiency-waivers/{waiver_id}/document", payload, headers)

    def rescind_deficiency_waiver(self, waiver_id, headers):
        return self._request("POST", f"/property-solutions/deficiency-waivers/{waiver_id}/rescind", headers=headers)

    def list_loan_deficiency_waivers(self, loan_id, headers, params=None):
        return self._request("GET", f"/property-solutions/loans/{loan_id}/deficiency-waivers", headers=headers, params=params)

    # --- Deed recordings ---
    def create_deed_recording(self, case_id, payload, headers):
        return self._request("POST", f"/property-solutions/cases/{case_id}/deed-recordings", payload, headers)

    def get_deed_recording(self, recording_id, headers):
        return self._request("GET", f"/property-solutions/deed-recordings/{recording_id}", headers=headers)

    def submit_deed_recording(self, recording_id, headers):
        return self._request("POST", f"/property-solutions/deed-recordings/{recording_id}/submit", headers=headers)

    def confirm_deed_recording(self, recording_id, payload, headers):
        return self._request("POST", f"/property-solutions/deed-recordings/{recording_id}/confirm", payload, headers)

    def reject_deed_recording(self, recording_id, payload, headers):
        return self._request("POST", f"/property-solutions/deed-recordings/{recording_id}/reject", payload, headers)

    # --- Eviction cases ---
    def get_eviction_case(self, eviction_case_id, headers):
        return self._request("GET", f"/property-solutions/eviction-cases/{eviction_case_id}", headers=headers)

    def file_eviction(self, eviction_case_id, payload, headers):
        return self._request("POST", f"/property-solutions/eviction-cases/{eviction_case_id}/file", payload, headers)

    def issue_writ(self, eviction_case_id, headers):
        return self._request("POST", f"/property-solutions/eviction-cases/{eviction_case_id}/writ", headers=headers)

    def record_evicted(self, eviction_case_id, headers):
        return self._request("POST", f"/property-solutions/eviction-cases/{eviction_case_id}/evicted", headers=headers)

    def dismiss_eviction(self, eviction_case_id, payload, headers):
        return self._request("POST", f"/property-solutions/eviction-cases/{eviction_case_id}/dismiss", payload, headers)


api_client = ApiClient()
