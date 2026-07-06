"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Logical clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- Studies -----
    def create_study(self, payload, headers):
        return self._request("POST", "/studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/studies/{study_id}", headers=headers)

    def launch_study(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/launch", {}, headers)

    def pause_study(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/pause", {}, headers)

    def resume_study(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/resume", {}, headers)

    def close_study(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/close", {}, headers)

    def deliver_study(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/deliver", {}, headers)

    # ----- Quota cells -----
    def create_quota_cell(self, study_id, payload, headers):
        return self._request("POST", f"/studies/{study_id}/quota-cells", payload, headers)

    def list_quota_cells(self, study_id, headers, params=None):
        return self._request("GET", f"/studies/{study_id}/quota-cells", headers=headers, params=params)

    def get_quota_cell(self, cell_id, headers):
        return self._request("GET", f"/quota-cells/{cell_id}", headers=headers)

    # ----- Panelists -----
    def create_panelist(self, payload, headers):
        return self._request("POST", "/panelists", payload, headers)

    def list_panelists(self, headers, params=None):
        return self._request("GET", "/panelists", headers=headers, params=params)

    def get_panelist(self, panelist_id, headers):
        return self._request("GET", f"/panelists/{panelist_id}", headers=headers)

    def get_panelist_health(self, panelist_id, headers):
        return self._request("GET", f"/panelists/{panelist_id}/health", headers=headers)

    def suspend_panelist(self, panelist_id, headers):
        return self._request("POST", f"/panelists/{panelist_id}/suspend", {}, headers)

    def reinstate_panelist(self, panelist_id, headers):
        return self._request("POST", f"/panelists/{panelist_id}/reinstate", {}, headers)

    def mark_churned_panelist(self, panelist_id, headers):
        return self._request("POST", f"/panelists/{panelist_id}/mark_churned", {}, headers)

    # ----- Consent -----
    def create_consent(self, payload, headers):
        return self._request("POST", "/consents", payload, headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/consents", headers=headers, params=params)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/consents/{consent_id}", headers=headers)

    # ----- Participations -----
    def create_participation(self, payload, headers):
        return self._request("POST", "/participations", payload, headers)

    def list_participations(self, headers, params=None):
        return self._request("GET", "/participations", headers=headers, params=params)

    def get_participation(self, participation_id, headers):
        return self._request("GET", f"/participations/{participation_id}", headers=headers)

    def screen_participation(self, participation_id, outcome, headers):
        return self._request("POST", f"/participations/{participation_id}/screen",
                             {"outcome": outcome}, headers)

    def rescreen_participation(self, participation_id, headers):
        return self._request("POST", f"/participations/{participation_id}/rescreen", {}, headers)

    def start_participation(self, participation_id, headers):
        return self._request("POST", f"/participations/{participation_id}/start", {}, headers)

    def submit_participation(self, participation_id, payload, headers):
        return self._request("POST", f"/participations/{participation_id}/submit", payload, headers)

    def abandon_participation(self, participation_id, headers):
        return self._request("POST", f"/participations/{participation_id}/abandon", {}, headers)

    # ----- Attention checks -----
    def create_attention_check(self, participation_id, payload, headers):
        return self._request("POST", f"/participations/{participation_id}/attention-checks",
                             payload, headers)

    def list_attention_checks(self, participation_id, headers, params=None):
        return self._request("GET", f"/participations/{participation_id}/attention-checks",
                             headers=headers, params=params)

    # ----- Incentive accruals -----
    def list_incentive_accruals(self, headers, params=None):
        return self._request("GET", "/incentive-accruals", headers=headers, params=params)

    def get_incentive_accrual(self, accrual_id, headers):
        return self._request("GET", f"/incentive-accruals/{accrual_id}", headers=headers)

    # ----- Payout requests -----
    def create_payout_request(self, payload, headers):
        return self._request("POST", "/payout-requests", payload, headers)

    def list_payout_requests(self, headers, params=None):
        return self._request("GET", "/payout-requests", headers=headers, params=params)

    def get_payout_request(self, request_id, headers):
        return self._request("GET", f"/payout-requests/{request_id}", headers=headers)

    def approve_payout_request(self, request_id, headers):
        return self._request("POST", f"/payout-requests/{request_id}/approve", {}, headers)

    def pay_payout_request(self, request_id, headers):
        return self._request("POST", f"/payout-requests/{request_id}/pay", {}, headers)

    def reject_payout_request(self, request_id, headers):
        return self._request("POST", f"/payout-requests/{request_id}/reject", {}, headers)

    def cancel_payout_request(self, request_id, headers):
        return self._request("POST", f"/payout-requests/{request_id}/cancel", {}, headers)

    # ----- Facilities -----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    # ----- Focus groups -----
    def create_focus_group(self, payload, headers):
        return self._request("POST", "/focus-groups", payload, headers)

    def list_focus_groups(self, headers, params=None):
        return self._request("GET", "/focus-groups", headers=headers, params=params)

    def get_focus_group(self, focus_group_id, headers):
        return self._request("GET", f"/focus-groups/{focus_group_id}", headers=headers)

    def cancel_focus_group(self, focus_group_id, headers):
        return self._request("POST", f"/focus-groups/{focus_group_id}/cancel", {}, headers)

    def complete_focus_group(self, focus_group_id, headers):
        return self._request("POST", f"/focus-groups/{focus_group_id}/complete", {}, headers)

    # ----- Focus group bookings -----
    def create_focus_group_booking(self, payload, headers):
        return self._request("POST", "/focus-group-bookings", payload, headers)

    def list_focus_group_bookings(self, headers, params=None):
        return self._request("GET", "/focus-group-bookings", headers=headers, params=params)

    def get_focus_group_booking(self, booking_id, headers):
        return self._request("GET", f"/focus-group-bookings/{booking_id}", headers=headers)

    def cancel_focus_group_booking(self, booking_id, headers):
        return self._request("POST", f"/focus-group-bookings/{booking_id}/cancel", {}, headers)

    def mark_attended_booking(self, booking_id, headers):
        return self._request("POST", f"/focus-group-bookings/{booking_id}/mark_attended", {}, headers)

    def mark_no_show_booking(self, booking_id, headers):
        return self._request("POST", f"/focus-group-bookings/{booking_id}/mark_no_show", {}, headers)

    # ----- Data deliveries -----
    def create_data_delivery(self, payload, headers):
        return self._request("POST", "/data-deliveries", payload, headers)

    def list_data_deliveries(self, headers, params=None):
        return self._request("GET", "/data-deliveries", headers=headers, params=params)

    def get_data_delivery(self, delivery_id, headers):
        return self._request("GET", f"/data-deliveries/{delivery_id}", headers=headers)

    def build_data_delivery(self, delivery_id, headers):
        return self._request("POST", f"/data-deliveries/{delivery_id}/build", {}, headers)

    def revoke_data_delivery(self, delivery_id, headers):
        return self._request("POST", f"/data-deliveries/{delivery_id}/revoke", {}, headers)


api_client = ApiClient()
