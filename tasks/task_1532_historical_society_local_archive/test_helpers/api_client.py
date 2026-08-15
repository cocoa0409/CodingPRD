"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- StorageZone ---
    def create_storage_zone(self, payload, headers):
        return self._request("POST", "/storage-zones", payload, headers)

    def list_storage_zones(self, headers, params=None):
        return self._request("GET", "/storage-zones", params or {}, headers)

    def get_storage_zone(self, zone_id, headers):
        return self._request("GET", f"/storage-zones/{zone_id}", headers=headers)

    def post_zone_reading(self, zone_id, payload, headers):
        return self._request("POST", f"/storage-zones/{zone_id}/readings",
                             payload, headers)

    # --- Collection ---
    def create_collection(self, payload, headers):
        return self._request("POST", "/collections", payload, headers)

    def list_collections(self, headers, params=None):
        return self._request("GET", "/collections", params or {}, headers)

    def get_collection(self, collection_id, headers):
        return self._request("GET", f"/collections/{collection_id}",
                             headers=headers)

    def patch_collection(self, collection_id, payload, headers):
        return self._request("PATCH", f"/collections/{collection_id}",
                             payload, headers)

    # --- Accession ---
    def create_accession(self, payload, headers):
        return self._request("POST", "/accessions", payload, headers)

    def list_accessions(self, headers, params=None):
        return self._request("GET", "/accessions", params or {}, headers)

    def get_accession(self, accession_id, headers):
        return self._request("GET", f"/accessions/{accession_id}",
                             headers=headers)

    def submit_accession(self, accession_id, headers):
        return self._request("POST", f"/accessions/{accession_id}/submit",
                             {}, headers)

    def amend_accession(self, accession_id, headers):
        return self._request("POST", f"/accessions/{accession_id}/amend",
                             {}, headers)

    def withdraw_accession(self, accession_id, headers):
        return self._request("POST", f"/accessions/{accession_id}/withdraw",
                             {}, headers)

    # --- DeedOfGift ---
    def create_deed(self, accession_id, payload, headers):
        return self._request("POST", f"/accessions/{accession_id}/deeds",
                             payload, headers)

    def list_deeds(self, accession_id, headers, params=None):
        return self._request("GET", f"/accessions/{accession_id}/deeds",
                             params or {}, headers)

    def execute_deed(self, deed_id, payload, headers):
        return self._request("POST", f"/deeds/{deed_id}/execute", payload,
                             headers)

    def void_deed(self, deed_id, headers):
        return self._request("POST", f"/deeds/{deed_id}/void", {}, headers)

    # --- Item ---
    def create_item(self, payload, headers):
        return self._request("POST", "/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/items", params or {}, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def catalog_item(self, item_id, payload, headers):
        return self._request("POST", f"/items/{item_id}/catalog", payload,
                             headers)

    def make_item_available(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/make-available", {},
                             headers)

    def flag_item_conservation(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/flag-conservation", {},
                             headers)

    def list_item_research_requests(self, item_id, headers, params=None):
        return self._request("GET", f"/items/{item_id}/research-requests",
                             params or {}, headers)

    def list_item_reproduction_orders(self, item_id, headers, params=None):
        return self._request("GET", f"/items/{item_id}/reproduction-orders",
                             params or {}, headers)

    def list_item_deaccession_proposals(self, item_id, headers, params=None):
        return self._request("GET", f"/items/{item_id}/deaccession-proposals",
                             params or {}, headers)

    # --- ConservationAssessment ---
    def create_conservation_assessment(self, item_id, payload, headers):
        return self._request("POST",
                             f"/items/{item_id}/conservation-assessments",
                             payload, headers)

    def list_conservation_assessments(self, item_id, headers, params=None):
        return self._request("GET",
                             f"/items/{item_id}/conservation-assessments",
                             params or {}, headers)

    def approve_assessment(self, assessment_id, headers):
        return self._request("POST",
                             f"/conservation-assessments/{assessment_id}/approve",
                             {}, headers)

    def begin_treatment(self, assessment_id, headers):
        return self._request(
            "POST",
            f"/conservation-assessments/{assessment_id}/begin-treatment",
            {}, headers)

    def complete_treatment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/conservation-assessments/{assessment_id}/complete-treatment",
            payload, headers)

    # --- FindingAid ---
    def create_finding_aid(self, payload, headers):
        return self._request("POST", "/finding-aids", payload, headers)

    def list_finding_aids(self, headers, params=None):
        return self._request("GET", "/finding-aids", params or {}, headers)

    def get_finding_aid(self, finding_aid_id, headers):
        return self._request("GET", f"/finding-aids/{finding_aid_id}",
                             headers=headers)

    def submit_finding_aid_review(self, finding_aid_id, headers):
        return self._request("POST",
                             f"/finding-aids/{finding_aid_id}/submit-review",
                             {}, headers)

    def publish_finding_aid(self, finding_aid_id, headers):
        return self._request("POST", f"/finding-aids/{finding_aid_id}/publish",
                             {}, headers)

    def return_finding_aid(self, finding_aid_id, headers):
        return self._request("POST", f"/finding-aids/{finding_aid_id}/return",
                             {}, headers)

    def open_finding_aid_revision(self, finding_aid_id, headers):
        return self._request("POST",
                             f"/finding-aids/{finding_aid_id}/open-revision",
                             {}, headers)

    # --- VolunteerProject ---
    def create_volunteer_project(self, payload, headers):
        return self._request("POST", "/volunteer-projects", payload, headers)

    def list_volunteer_projects(self, headers, params=None):
        return self._request("GET", "/volunteer-projects", params or {},
                             headers)

    def get_volunteer_project(self, project_id, headers):
        return self._request("GET", f"/volunteer-projects/{project_id}",
                             headers=headers)

    def activate_project(self, project_id, headers):
        return self._request("POST",
                             f"/volunteer-projects/{project_id}/activate",
                             {}, headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/volunteer-projects/{project_id}/close",
                             {}, headers)

    # --- DigitizationTicket ---
    def create_ticket(self, project_id, payload, headers):
        return self._request("POST",
                             f"/volunteer-projects/{project_id}/tickets",
                             payload, headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/digitization-tickets", params or {},
                             headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/digitization-tickets/{ticket_id}",
                             headers=headers)

    def claim_next_ticket(self, project_id, headers):
        return self._request("POST",
                             f"/volunteer-projects/{project_id}/tickets/claim-next",
                             {}, headers)

    def begin_capture(self, ticket_id, headers):
        return self._request("POST",
                             f"/digitization-tickets/{ticket_id}/begin-capture",
                             {}, headers)

    def submit_qc(self, ticket_id, headers):
        return self._request("POST",
                             f"/digitization-tickets/{ticket_id}/submit-qc",
                             {}, headers)

    def qc_pass(self, ticket_id, headers):
        return self._request("POST",
                             f"/digitization-tickets/{ticket_id}/qc-pass",
                             {}, headers)

    def qc_fail(self, ticket_id, headers):
        return self._request("POST",
                             f"/digitization-tickets/{ticket_id}/qc-fail",
                             {}, headers)

    def release_ticket(self, ticket_id, headers):
        return self._request("POST",
                             f"/digitization-tickets/{ticket_id}/release",
                             {}, headers)

    def log_hours(self, ticket_id, payload, headers):
        return self._request("POST",
                             f"/digitization-tickets/{ticket_id}/log-hours",
                             payload, headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST",
                             f"/digitization-tickets/{ticket_id}/cancel",
                             {}, headers)

    # --- Researcher ---
    def create_researcher(self, payload, headers):
        return self._request("POST", "/researchers", payload, headers)

    def list_researchers(self, headers, params=None):
        return self._request("GET", "/researchers", params or {}, headers)

    def get_researcher(self, researcher_id, headers):
        return self._request("GET", f"/researchers/{researcher_id}",
                             headers=headers)

    def reinstate_researcher(self, researcher_id, headers):
        return self._request("POST",
                             f"/researchers/{researcher_id}/reinstate",
                             {}, headers)

    # --- ResearchRequest ---
    def create_research_request(self, payload, headers):
        return self._request("POST", "/research-requests", payload, headers)

    def list_research_requests(self, headers, params=None):
        return self._request("GET", "/research-requests", params or {}, headers)

    def get_research_request(self, request_id, headers):
        return self._request("GET", f"/research-requests/{request_id}",
                             headers=headers)

    def begin_request_review(self, request_id, headers):
        return self._request("POST",
                             f"/research-requests/{request_id}/begin-review",
                             {}, headers)

    def approve_request(self, request_id, headers):
        return self._request("POST",
                             f"/research-requests/{request_id}/approve",
                             {}, headers)

    def deny_request(self, request_id, payload, headers):
        return self._request("POST", f"/research-requests/{request_id}/deny",
                             payload, headers)

    def cancel_request(self, request_id, headers):
        return self._request("POST", f"/research-requests/{request_id}/cancel",
                             {}, headers)

    # --- ReadingRoomAppointment ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/reading-room-appointments", payload,
                             headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/reading-room-appointments", params or {},
                             headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET",
                             f"/reading-room-appointments/{appointment_id}",
                             headers=headers)

    def check_in_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/reading-room-appointments/{appointment_id}/check-in",
            {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/reading-room-appointments/{appointment_id}/complete",
            {}, headers)

    def record_no_show(self, appointment_id, headers):
        return self._request(
            "POST",
            f"/reading-room-appointments/{appointment_id}/record-no-show",
            {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/reading-room-appointments/{appointment_id}/cancel",
            {}, headers)

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/reading-room-appointments/{appointment_id}/reschedule",
            payload, headers)

    # --- ReproductionOrder ---
    def create_reproduction_order(self, payload, headers):
        return self._request("POST", "/reproduction-orders", payload, headers)

    def list_reproduction_orders(self, headers, params=None):
        return self._request("GET", "/reproduction-orders", params or {},
                             headers)

    def get_reproduction_order(self, order_id, headers):
        return self._request("GET", f"/reproduction-orders/{order_id}",
                             headers=headers)

    def approve_quote(self, order_id, headers):
        return self._request("POST",
                             f"/reproduction-orders/{order_id}/approve-quote",
                             {}, headers)

    def invoice_order(self, order_id, payload, headers):
        return self._request("POST",
                             f"/reproduction-orders/{order_id}/invoice",
                             payload, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/reproduction-orders/{order_id}/pay",
                             payload, headers)

    def deliver_order(self, order_id, payload, headers):
        return self._request("POST",
                             f"/reproduction-orders/{order_id}/deliver",
                             payload, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST",
                             f"/reproduction-orders/{order_id}/refund",
                             {}, headers)

    # --- DeaccessionProposal ---
    def create_deaccession_proposal(self, payload, headers):
        return self._request("POST", "/deaccession-proposals", payload, headers)

    def list_deaccession_proposals(self, headers, params=None):
        return self._request("GET", "/deaccession-proposals", params or {},
                             headers)

    def get_deaccession_proposal(self, proposal_id, headers):
        return self._request("GET", f"/deaccession-proposals/{proposal_id}",
                             headers=headers)

    def submit_proposal(self, proposal_id, headers):
        return self._request("POST",
                             f"/deaccession-proposals/{proposal_id}/submit",
                             {}, headers)

    def send_proposal_to_board(self, proposal_id, headers):
        return self._request(
            "POST", f"/deaccession-proposals/{proposal_id}/send-to-board",
            {}, headers)

    def approve_proposal(self, proposal_id, headers):
        return self._request("POST",
                             f"/deaccession-proposals/{proposal_id}/approve",
                             {}, headers)

    def reject_proposal(self, proposal_id, headers):
        return self._request("POST",
                             f"/deaccession-proposals/{proposal_id}/reject",
                             {}, headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST",
                             f"/deaccession-proposals/{proposal_id}/withdraw",
                             {}, headers)

    def finalize_proposal(self, proposal_id, payload, headers):
        return self._request("POST",
                             f"/deaccession-proposals/{proposal_id}/finalize",
                             payload, headers)

    # --- OralHistoryRecording ---
    def create_oral_history(self, payload, headers):
        return self._request("POST", "/oral-histories", payload, headers)

    def list_oral_histories(self, headers, params=None):
        return self._request("GET", "/oral-histories", params or {}, headers)

    def get_oral_history(self, recording_id, headers):
        return self._request("GET", f"/oral-histories/{recording_id}",
                             headers=headers)

    def mark_recorded(self, recording_id, headers):
        return self._request("POST",
                             f"/oral-histories/{recording_id}/mark-recorded",
                             {}, headers)

    def submit_transcript(self, recording_id, headers):
        return self._request(
            "POST", f"/oral-histories/{recording_id}/submit-transcript",
            {}, headers)

    def send_recording_to_review(self, recording_id, headers):
        return self._request("POST",
                             f"/oral-histories/{recording_id}/send-to-review",
                             {}, headers)

    def return_to_transcription(self, recording_id, headers):
        return self._request(
            "POST",
            f"/oral-histories/{recording_id}/return-to-transcription",
            {}, headers)

    def sign_release(self, recording_id, payload, headers):
        return self._request("POST",
                             f"/oral-histories/{recording_id}/release-forms/sign",
                             payload, headers)

    def decline_release(self, recording_id, headers):
        return self._request(
            "POST",
            f"/oral-histories/{recording_id}/release-forms/decline",
            {}, headers)

    def publish_release(self, recording_id, headers):
        return self._request("POST",
                             f"/oral-histories/{recording_id}/publish-release",
                             {}, headers)

    def cancel_oral_history(self, recording_id, headers):
        return self._request("POST", f"/oral-histories/{recording_id}/cancel",
                             {}, headers)


api_client = ApiClient()
