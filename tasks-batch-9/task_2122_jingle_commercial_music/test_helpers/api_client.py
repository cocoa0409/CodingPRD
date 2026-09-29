"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Clients -----------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    # --- Projects ----------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def hold_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/hold", payload, headers)

    def resume_project(self, project_id, headers, payload=None):
        return self._request("POST", f"/projects/{project_id}/resume", payload or {}, headers)

    def get_sourcing_comparison(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/sourcing-comparison", headers=headers, params=params)

    def get_afm_report(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/afm-report", headers=headers, params=params)

    # --- Creative briefs ---------------------------------------------------
    def create_brief(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/briefs", payload, headers)

    def list_project_briefs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/briefs", headers=headers, params=params)

    def approve_brief(self, brief_id, headers, payload=None):
        return self._request("POST", f"/briefs/{brief_id}/approve", payload or {}, headers)

    # --- Composers ---------------------------------------------------------
    def create_composer(self, payload, headers):
        return self._request("POST", "/composers", payload, headers)

    # --- Demos -------------------------------------------------------------
    def create_demo(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/demos", payload, headers)

    def get_demo(self, demo_id, headers):
        return self._request("GET", f"/demos/{demo_id}", headers=headers)

    def list_demos(self, headers, params=None):
        return self._request("GET", "/demos", headers=headers, params=params)

    def submit_demo(self, demo_id, headers, payload=None):
        return self._request("POST", f"/demos/{demo_id}/submit", payload or {}, headers)

    def request_demo_revision(self, demo_id, payload, headers):
        return self._request("POST", f"/demos/{demo_id}/request-revision", payload, headers)

    def shortlist_demo(self, demo_id, headers, payload=None):
        return self._request("POST", f"/demos/{demo_id}/shortlist", payload or {}, headers)

    def select_demo(self, demo_id, headers, payload=None):
        return self._request("POST", f"/demos/{demo_id}/select", payload or {}, headers)

    # --- Musicians ---------------------------------------------------------
    def create_musician(self, payload, headers):
        return self._request("POST", "/musicians", payload, headers)

    def set_afm_clearance(self, musician_id, payload, headers):
        return self._request("POST", f"/musicians/{musician_id}/afm-clearance", payload, headers)

    # --- Studio rooms ------------------------------------------------------
    def create_studio_room(self, payload, headers):
        return self._request("POST", "/studio-rooms", payload, headers)

    # --- Session calls -----------------------------------------------------
    def create_session_call(self, payload, headers):
        return self._request("POST", "/session-calls", payload, headers)

    def get_session_call(self, session_call_id, headers):
        return self._request("GET", f"/session-calls/{session_call_id}", headers=headers)

    def list_session_calls(self, headers, params=None):
        return self._request("GET", "/session-calls", headers=headers, params=params)

    def confirm_session_call(self, session_call_id, headers, payload=None):
        return self._request(
            "POST", f"/session-calls/{session_call_id}/confirm", payload or {}, headers)

    def cancel_session_call(self, session_call_id, payload, headers):
        return self._request("POST", f"/session-calls/{session_call_id}/cancel", payload, headers)

    def complete_session_call(self, session_call_id, payload, headers):
        return self._request("POST", f"/session-calls/{session_call_id}/complete", payload, headers)

    # --- Musician bookings -------------------------------------------------
    def create_booking(self, session_call_id, payload, headers):
        return self._request("POST", f"/session-calls/{session_call_id}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/musician-bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/musician-bookings", headers=headers, params=params)

    # --- Licence deals -----------------------------------------------------
    def create_license_deal(self, payload, headers):
        return self._request("POST", "/license-deals", payload, headers)

    def get_license_deal(self, license_deal_id, headers):
        return self._request("GET", f"/license-deals/{license_deal_id}", headers=headers)

    def list_license_deals(self, headers, params=None):
        return self._request("GET", "/license-deals", headers=headers, params=params)

    def propose_license_deal(self, license_deal_id, headers, payload=None):
        return self._request(
            "POST", f"/license-deals/{license_deal_id}/propose", payload or {}, headers)

    def counter_license_deal(self, license_deal_id, payload, headers):
        return self._request("POST", f"/license-deals/{license_deal_id}/counter", payload, headers)

    def accept_license_deal(self, license_deal_id, headers, payload=None):
        return self._request(
            "POST", f"/license-deals/{license_deal_id}/accept", payload or {}, headers)

    def activate_license_deal(self, license_deal_id, headers, payload=None):
        return self._request(
            "POST", f"/license-deals/{license_deal_id}/activate", payload or {}, headers)

    def renew_license_deal(self, license_deal_id, headers, payload=None):
        return self._request(
            "POST", f"/license-deals/{license_deal_id}/renew", payload or {}, headers)

    # --- Re-use extensions -------------------------------------------------
    def create_reuse_extension(self, license_deal_id, payload, headers):
        return self._request(
            "POST", f"/license-deals/{license_deal_id}/reuse-extensions", payload, headers)

    def list_reuse_extensions(self, license_deal_id, headers, params=None):
        return self._request(
            "GET", f"/license-deals/{license_deal_id}/reuse-extensions",
            headers=headers, params=params)

    # --- Delivery packages -------------------------------------------------
    def create_deliverable(self, license_deal_id, headers, payload=None):
        return self._request(
            "POST", f"/license-deals/{license_deal_id}/deliverables", payload or {}, headers)

    def list_deliverables(self, license_deal_id, headers, params=None):
        return self._request(
            "GET", f"/license-deals/{license_deal_id}/deliverables", headers=headers, params=params)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    def deliver_stems(self, deliverable_id, payload, headers):
        return self._request("POST", f"/deliverables/{deliverable_id}/stems", payload, headers)

    def approve_master(self, deliverable_id, headers, payload=None):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/approve-master", payload or {}, headers)

    def reject_master(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/reject-master", payload, headers)

    def file_cue_sheet(self, deliverable_id, headers, payload=None):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/file-cue-sheet", payload or {}, headers)

    def register_cue_sheet(self, deliverable_id, headers, payload=None):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/register-cue-sheet", payload or {}, headers)

    # --- Cue-sheet lines ---------------------------------------------------
    def create_cue_entry(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/cue-entries", payload, headers)

    def get_cue_entry(self, cue_entry_id, headers):
        return self._request("GET", f"/cue-entries/{cue_entry_id}", headers=headers)

    def list_cue_entries(self, headers, params=None):
        return self._request("GET", "/cue-entries", headers=headers, params=params)

    def void_cue_entry(self, cue_entry_id, headers, payload=None):
        return self._request("POST", f"/cue-entries/{cue_entry_id}/void", payload or {}, headers)

    # --- Library tracks ----------------------------------------------------
    def create_library_track(self, payload, headers):
        return self._request("POST", "/library-tracks", payload, headers)


api_client = ApiClient()
