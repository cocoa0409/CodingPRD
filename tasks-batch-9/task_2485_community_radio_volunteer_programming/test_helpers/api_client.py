"""API client: one method per endpoint defined in the PRD (§4).

Every collection is a peer at the URL root — there is no version or namespace
prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers=None):
        """Set the station's logical clock. Exempt from the role-header check."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers or {}
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers or {})

    # ------------------------------------------------------------ operations
    def run_daily_sweep(self, headers):
        return self._request("POST", "/operations/daily-sweep", {}, headers)

    # ------------------------------------------------------------ volunteers
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    def update_volunteer(self, volunteer_id, payload, headers):
        return self._request("PATCH", f"/volunteers/{volunteer_id}", payload, headers)

    # -------------------------------------------------------- certifications
    def create_certification(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/certifications", payload, headers
        )

    def list_volunteer_certifications(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/certifications", headers=headers, params=params
        )

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def grade_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"/certifications/{certification_id}/exam-results", payload, headers
        )

    def retake_certification(self, certification_id, headers, payload=None):
        return self._request(
            "POST", f"/certifications/{certification_id}/retake", payload or {}, headers
        )

    def revoke_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"/certifications/{certification_id}/revoke", payload, headers
        )

    # ------------------------------------------------------ program proposals
    def create_proposal(self, payload, headers):
        return self._request("POST", "/program-proposals", payload, headers)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/program-proposals/{proposal_id}", headers=headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/program-proposals", headers=headers, params=params)

    def update_proposal(self, proposal_id, payload, headers):
        return self._request("PATCH", f"/program-proposals/{proposal_id}", payload, headers)

    def submit_proposal(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"/program-proposals/{proposal_id}/submit", payload or {}, headers
        )

    def withdraw_proposal(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"/program-proposals/{proposal_id}/withdraw", payload or {}, headers
        )

    def open_proposal_review(self, proposal_id, headers, payload=None):
        return self._request(
            "POST", f"/program-proposals/{proposal_id}/open-review", payload or {}, headers
        )

    def cast_vote(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/program-proposals/{proposal_id}/votes", payload, headers
        )

    def decide_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/program-proposals/{proposal_id}/decide", payload, headers
        )

    # -------------------------------------------------------- committee votes
    def get_committee_vote(self, vote_id, headers):
        return self._request("GET", f"/committee-votes/{vote_id}", headers=headers)

    def list_committee_votes(self, headers, params=None):
        return self._request("GET", "/committee-votes", headers=headers, params=params)

    # -------------------------------------------------------------- programs
    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def create_performance_review(self, program_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/performance-reviews", payload, headers
        )

    def cancel_program(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/cancel", payload, headers)

    # -------------------------------------------------------- schedule grids
    def create_schedule_grid(self, payload, headers):
        return self._request("POST", "/schedule-grids", payload, headers)

    def get_schedule_grid(self, grid_id, headers):
        return self._request("GET", f"/schedule-grids/{grid_id}", headers=headers)

    def list_schedule_grids(self, headers, params=None):
        return self._request("GET", "/schedule-grids", headers=headers, params=params)

    def create_slot_assignment(self, grid_id, payload, headers):
        return self._request(
            "POST", f"/schedule-grids/{grid_id}/slot-assignments", payload, headers
        )

    def publish_schedule_grid(self, grid_id, payload, headers):
        return self._request("POST", f"/schedule-grids/{grid_id}/publish", payload, headers)

    # ------------------------------------------------------ slot assignments
    def get_slot_assignment(self, assignment_id, headers):
        return self._request("GET", f"/slot-assignments/{assignment_id}", headers=headers)

    def list_slot_assignments(self, headers, params=None):
        return self._request("GET", "/slot-assignments", headers=headers, params=params)

    def confirm_slot_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/slot-assignments/{assignment_id}/confirm", payload or {}, headers
        )

    def release_slot_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/slot-assignments/{assignment_id}/release", payload, headers
        )

    def reinstate_slot_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/slot-assignments/{assignment_id}/reinstate", payload or {}, headers
        )

    # -------------------------------------------------------------- episodes
    def create_episode(self, payload, headers):
        return self._request("POST", "/episodes", payload, headers)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}", headers=headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/episodes", headers=headers, params=params)

    def record_air_result(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/air-result", payload, headers)

    def create_playlist_entry(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/playlist-entries", payload, headers
        )

    def submit_playlist_log(self, episode_id, headers, payload=None):
        return self._request(
            "POST", f"/episodes/{episode_id}/submit-log", payload or {}, headers
        )

    def decide_playlist_log(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/log-decision", payload, headers)

    # ------------------------------------------------------- playlist entries
    def get_playlist_entry(self, entry_id, headers):
        return self._request("GET", f"/playlist-entries/{entry_id}", headers=headers)

    def list_playlist_entries(self, headers, params=None):
        return self._request("GET", "/playlist-entries", headers=headers, params=params)

    # ----------------------------------------------------- underwriting spots
    def create_underwriting_spot(self, payload, headers):
        return self._request("POST", "/underwriting-spots", payload, headers)

    def get_underwriting_spot(self, spot_id, headers):
        return self._request("GET", f"/underwriting-spots/{spot_id}", headers=headers)

    def list_underwriting_spots(self, headers, params=None):
        return self._request("GET", "/underwriting-spots", headers=headers, params=params)

    def update_underwriting_spot(self, spot_id, payload, headers):
        return self._request("PATCH", f"/underwriting-spots/{spot_id}", payload, headers)

    def submit_spot_for_review(self, spot_id, headers, payload=None):
        return self._request(
            "POST", f"/underwriting-spots/{spot_id}/submit-for-review", payload or {}, headers
        )

    def review_underwriting_spot(self, spot_id, payload, headers):
        return self._request("POST", f"/underwriting-spots/{spot_id}/review", payload, headers)

    def post_public_file(self, spot_id, payload, headers):
        return self._request(
            "POST", f"/underwriting-spots/{spot_id}/public-file-posting", payload, headers
        )

    # --------------------------------------------------- compliance incidents
    def create_compliance_incident(self, payload, headers):
        return self._request("POST", "/compliance-incidents", payload, headers)

    def get_compliance_incident(self, incident_id, headers):
        return self._request("GET", f"/compliance-incidents/{incident_id}", headers=headers)

    def list_compliance_incidents(self, headers, params=None):
        return self._request("GET", "/compliance-incidents", headers=headers, params=params)

    def adjudicate_compliance_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/compliance-incidents/{incident_id}/adjudicate", payload, headers
        )

    def remediate_compliance_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/compliance-incidents/{incident_id}/remediate", payload, headers
        )

    # ------------------------------------------------------ membership drives
    def create_membership_drive(self, payload, headers):
        return self._request("POST", "/membership-drives", payload, headers)

    def get_membership_drive(self, drive_id, headers):
        return self._request("GET", f"/membership-drives/{drive_id}", headers=headers)

    def list_membership_drives(self, headers, params=None):
        return self._request("GET", "/membership-drives", headers=headers, params=params)

    def activate_membership_drive(self, drive_id, headers, payload=None):
        return self._request(
            "POST", f"/membership-drives/{drive_id}/activate", payload or {}, headers
        )

    def close_membership_drive(self, drive_id, headers, payload=None):
        return self._request(
            "POST", f"/membership-drives/{drive_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------ phone bank shifts
    def create_phone_bank_shift(self, payload, headers):
        return self._request("POST", "/phone-bank-shifts", payload, headers)

    def get_phone_bank_shift(self, shift_id, headers):
        return self._request("GET", f"/phone-bank-shifts/{shift_id}", headers=headers)

    def list_phone_bank_shifts(self, headers, params=None):
        return self._request("GET", "/phone-bank-shifts", headers=headers, params=params)

    def close_phone_bank_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/phone-bank-shifts/{shift_id}/close", payload, headers)

    # ---------------------------------------------------------- premium items
    def create_premium_item(self, payload, headers):
        return self._request("POST", "/premium-items", payload, headers)

    def get_premium_item(self, premium_item_id, headers):
        return self._request("GET", f"/premium-items/{premium_item_id}", headers=headers)

    def list_premium_items(self, headers, params=None):
        return self._request("GET", "/premium-items", headers=headers, params=params)

    def receive_premium_units(self, premium_item_id, payload, headers):
        return self._request(
            "POST", f"/premium-items/{premium_item_id}/receipts", payload, headers
        )

    # ---------------------------------------------------------------- pledges
    def create_pledge(self, payload, headers):
        return self._request("POST", "/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/pledges", headers=headers, params=params)

    def settle_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/pledges/{pledge_id}/payment", payload, headers)

    def refund_pledge(self, pledge_id, headers, payload=None):
        return self._request("POST", f"/pledges/{pledge_id}/refund", payload or {}, headers)

    def fulfill_pledge_premium(self, pledge_id, payload, headers):
        return self._request(
            "POST", f"/pledges/{pledge_id}/premium-fulfillment", payload, headers
        )


api_client = ApiClient()
